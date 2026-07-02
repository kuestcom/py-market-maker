from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Callable

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    AssetType,
    BalanceAllowanceParams,
    OpenOrderParams,
    OrderArgs,
    OrderBookSummary,
    OrderSummary,
    OrderType,
)
from py_clob_client.constants import END_CURSOR
from py_clob_client.order_builder.constants import BUY, SELL

from .config import Config, DiscoveryMode, band_margin_ticks, band_sizes
from .event_scope import condition_id_from_market, condition_ids_from_site_config
from .market_loss import MarketExposure, OutcomeExposure, ProposedOrder
from .pricing import ceil_to_tick, fair_price, floor_to_tick, is_tradeable_price
from .state import SeenMarkets

INITIAL_CURSOR = "MA=="
CONDITIONAL_TOKEN_BASE_UNITS = Decimal("1000000")


@dataclass(frozen=True)
class MarketCandidate:
    market: dict[str, Any]
    is_new: bool


@dataclass(frozen=True)
class QuotePlan:
    market_key: str
    market_slug: str
    question: str
    token_id: str
    outcome: str
    fair_price: Decimal
    best_bid: Decimal | None
    best_ask: Decimal | None
    buy_band: QuoteBand | None
    sell_band: QuoteBand | None

    def bands(self) -> list["QuoteBand"]:
        return [band for band in (self.buy_band, self.sell_band) if band is not None]


@dataclass(frozen=True)
class QuoteBand:
    side: str
    price: Decimal
    min_price: Decimal
    max_price: Decimal
    min_size: Decimal
    avg_size: Decimal
    max_size: Decimal

    def contains_price(self, price: Decimal) -> bool:
        return self.min_price <= price <= self.max_price

    def includes_order(self, order: Any) -> bool:
        side = _response_field(order, "side")
        price = _decimal_or_none(_response_field(order, "price"))
        return side == self.side and price is not None and self.contains_price(price)

    def cancel_priority(self, order: Any) -> Decimal:
        price = _decimal(_response_field(order, "price"), Decimal("0"))
        if self.side == BUY:
            return max(self.max_price - price, Decimal("0"))
        if self.side == SELL:
            return max(price - self.min_price, Decimal("0"))
        return Decimal("0")


@dataclass(frozen=True)
class TokenQuote:
    token_id: str
    fair_price: Decimal
    plan: QuotePlan | None
    skip_reason: str | None


@dataclass(frozen=True)
class QuoteInputs:
    fair_price: Decimal
    best_bid: Decimal | None
    best_ask: Decimal | None


class LiquidityRejectKind(str, Enum):
    MISSING_TWO_SIDED_BOOK = "missing_two_sided_book"
    INVALID_TICK = "invalid_tick"
    SPREAD_TOO_WIDE = "spread_too_wide"
    BID_DEPTH_TOO_LOW = "bid_depth_too_low"
    ASK_DEPTH_TOO_LOW = "ask_depth_too_low"


@dataclass(frozen=True)
class LiquidityRejectReason:
    kind: LiquidityRejectKind
    spread_ticks: Decimal | None = None
    max_spread_ticks: int | None = None
    depth: Decimal | None = None
    min_depth: Decimal | None = None

    def message(self) -> str:
        if self.kind == LiquidityRejectKind.MISSING_TWO_SIDED_BOOK:
            return "missing a valid two-sided book"
        if self.kind == LiquidityRejectKind.INVALID_TICK:
            return "book tick size is invalid"
        if self.kind == LiquidityRejectKind.SPREAD_TOO_WIDE:
            return f"spread is {self.spread_ticks} ticks above max {self.max_spread_ticks}"
        if self.kind == LiquidityRejectKind.BID_DEPTH_TOO_LOW:
            return f"best bid depth {self.depth} below minimum {self.min_depth}"
        if self.kind == LiquidityRejectKind.ASK_DEPTH_TOO_LOW:
            return f"best ask depth {self.depth} below minimum {self.min_depth}"
        return self.kind.value


@dataclass
class LiveTokenState:
    token_id: str
    fair_price: Decimal
    balance: Decimal
    open_orders: list[Any]


@dataclass
class LiveMarketState:
    tokens: list[LiveTokenState]
    pending_orders: list[ProposedOrder]

    @classmethod
    def load(cls, client: ClobClient, token_quotes: list[TokenQuote]) -> "LiveMarketState":
        return cls(
            tokens=[
                LiveTokenState(
                    token_id=token_quote.token_id,
                    fair_price=token_quote.fair_price,
                    balance=conditional_balance(client, token_quote.token_id),
                    open_orders=open_orders_for_token(client, token_quote.token_id),
                )
                for token_quote in token_quotes
            ],
            pending_orders=[],
        )

    def exposure(self) -> MarketExposure:
        exposure = MarketExposure(
            outcomes=[
                OutcomeExposure(
                    token_id=token.token_id,
                    position=token.balance,
                    cost=token.balance * token.fair_price,
                )
                for token in self.tokens
            ]
        )
        for token in self.tokens:
            for order in token.open_orders:
                proposed = proposed_order_from_open_order(order, token.token_id)
                if proposed is not None:
                    exposure.apply_order(proposed)
        for order in self.pending_orders:
            exposure.apply_order(order)
        return exposure

    def record_pending_order(self, order: ProposedOrder) -> None:
        self.pending_orders.append(order)

    def open_orders(self, token_id: str) -> list[Any]:
        for token in self.tokens:
            if token.token_id == token_id:
                return list(token.open_orders)
        return []

    def remove_open_orders(self, token_id: str, order_ids: set[str]) -> None:
        if not order_ids:
            return
        for token in self.tokens:
            if token.token_id == token_id:
                token.open_orders = [
                    order for order in token.open_orders if open_order_id(order) not in order_ids
                ]
                return


def run(config: Config) -> None:
    public_client = ClobClient(config.clob_host)
    live_client = authenticate(config) if config.live else None
    seen = SeenMarkets.load(config.state_path)

    for cycle in range(1, config.cycles + 1):
        event_slug = config.event_slug.strip() if config.event_slug else None
        if event_slug:
            print(f"cycle {cycle}/{config.cycles}: discovering markets for event {event_slug}")
            markets = discover_event_markets(public_client, event_slug, config.max_pages)
            candidates = select_event_candidates(markets, config.max_markets)
        else:
            print(f"cycle {cycle}/{config.cycles}: discovering markets")
            markets = discover_markets(public_client, config.discovery, config.max_pages)
            candidates = select_candidates(markets, seen, config.max_markets)
            seen.save(config.state_path)

        new_count = sum(1 for candidate in candidates if candidate.is_new)
        if event_slug:
            print(f"event {event_slug}: found {len(candidates)} tradable markets")
        else:
            print(f"found {len(candidates)} tradable fork-scoped markets ({new_count} new)")

        for candidate in candidates:
            marker = "new" if candidate.is_new else "seen"
            print(f"- [{marker}] {market_key(candidate.market)} :: {_market_question(candidate.market)}")

        if config.discover_only:
            continue

        for candidate in candidates:
            quote_market(public_client, live_client, candidate.market, config)

        if cycle < config.cycles:
            time.sleep(config.refresh_secs)


def authenticate(config: Config) -> ClobClient:
    client = ClobClient(
        config.clob_host,
        chain_id=config.chain_id,
        key=config.private_key,
        signature_type=3,
        funder=config.deposit_wallet,
    )
    client.set_api_creds(client.create_or_derive_api_creds())
    return client


def discover_markets(client: ClobClient, mode: DiscoveryMode, max_pages: int) -> list[dict[str, Any]]:
    if mode == DiscoveryMode.AUTO:
        sampling = fetch_market_pages(client, DiscoveryMode.SAMPLING, max_pages)
        return sampling if sampling else fetch_market_pages(client, DiscoveryMode.SITE, max_pages)

    return fetch_market_pages(client, mode, max_pages)


def discover_event_markets(client: ClobClient, event_slug: str, max_pages: int) -> list[dict[str, Any]]:
    condition_ids = condition_ids_from_site_config(event_slug, max_pages)
    markets: list[dict[str, Any]] = []
    for condition_id in sorted(condition_ids):
        market = client.get_market(condition_id)
        if isinstance(market, dict):
            markets.append(market)
    return markets


def fetch_market_pages(client: ClobClient, mode: DiscoveryMode, max_pages: int) -> list[dict[str, Any]]:
    cursor = INITIAL_CURSOR
    markets: list[dict[str, Any]] = []

    for _ in range(max_pages):
        previous_cursor = cursor
        page = (
            client.get_sampling_markets(cursor)
            if mode == DiscoveryMode.SAMPLING
            else client.get_markets(cursor)
        )
        if not isinstance(page, dict):
            break

        data = page.get("data")
        if isinstance(data, list):
            markets.extend(market for market in data if isinstance(market, dict))

        next_cursor = str(page.get("next_cursor") or END_CURSOR)
        if next_cursor == END_CURSOR or next_cursor == previous_cursor:
            break
        cursor = next_cursor

    return markets


def select_candidates(
    markets: list[dict[str, Any]],
    seen: SeenMarkets,
    max_markets: int,
) -> list[MarketCandidate]:
    return _select_candidates(
        markets,
        max_markets,
        is_new=lambda market: seen.mark_new(market_key(market)),
    )


def select_event_candidates(
    markets: list[dict[str, Any]],
    max_markets: int,
) -> list[MarketCandidate]:
    return _select_candidates(markets, max_markets, is_new=lambda _: False)


def _select_candidates(
    markets: list[dict[str, Any]],
    max_markets: int,
    is_new: Callable[[dict[str, Any]], bool],
) -> list[MarketCandidate]:
    candidates = [
        MarketCandidate(market=market, is_new=is_new(market))
        for market in markets
        if is_tradable_market(market)
    ]
    candidates.sort(
        key=lambda candidate: (
            not candidate.is_new,
            not has_rewards(candidate.market),
            -_timestamp_sort_value(_field(candidate.market, "accepting_order_timestamp")),
            _market_slug(candidate.market),
        )
    )
    return candidates[:max_markets]


def is_tradable_market(market: dict[str, Any]) -> bool:
    return (
        _bool_field(market, "enable_order_book")
        and _bool_field(market, "active")
        and not _bool_field(market, "closed")
        and not _bool_field(market, "archived")
        and _bool_field(market, "accepting_orders")
        and bool(_market_tokens(market))
    )


def has_rewards(market: dict[str, Any]) -> bool:
    rewards = _dict_field(market, "rewards")
    rates = rewards.get("rates")
    min_size = _decimal(rewards.get("min_size"), Decimal("0"))
    return (isinstance(rates, list) and bool(rates)) or min_size > Decimal("0")


def market_key(market: dict[str, Any]) -> str:
    condition_id = condition_id_from_market(market)
    if condition_id:
        return condition_id
    return _market_slug(market)


def quote_market(
    public_client: ClobClient,
    live_client: ClobClient | None,
    market: dict[str, Any],
    config: Config,
) -> None:
    token_quotes: list[TokenQuote] = []
    for token in _market_tokens(market):
        token_id = _token_id(token)
        if not token_id:
            continue

        book = public_client.get_order_book(token_id)
        token_quote = build_token_quote(market, token, book, config)
        token_quotes.append(token_quote)
        if token_quote.plan is None:
            reason = token_quote.skip_reason or "no safe quote at configured edge/sides"
            print(f"skip {_market_slug(market)} {_token_outcome(token)}: {reason}")
            continue

        print_plan(token_quote.plan, config.live)

    if live_client is None:
        return

    market_state = LiveMarketState.load(live_client, token_quotes)
    for token_quote in token_quotes:
        if token_quote.plan is not None:
            post_quote_plan(live_client, token_quote.plan, config, market_state)


def build_token_quote(
    market: dict[str, Any],
    token: dict[str, Any],
    book: OrderBookSummary,
    config: Config,
) -> TokenQuote:
    quote_inputs = build_quote_inputs(token, book)
    liquidity_skip = None
    if should_enforce_liquidity_quality(config):
        reject_reason = liquidity_quality_reject_reason(book, config)
        if reject_reason is not None:
            liquidity_skip = f"liquidity quality check failed: {reject_reason.message()}"
    plan = None if liquidity_skip else build_quote_plan(market, token, book, quote_inputs, config)
    return TokenQuote(
        token_id=_token_id(token),
        fair_price=quote_inputs.fair_price,
        plan=plan,
        skip_reason=liquidity_skip if plan is None else None,
    )


def build_quote_inputs(token: dict[str, Any], book: OrderBookSummary) -> QuoteInputs:
    best_bid_price = best_bid(book.bids or [])
    best_ask_price = best_ask(book.asks or [])
    return QuoteInputs(
        fair_price=fair_price(
            best_bid_price,
            best_ask_price,
            _decimal(_field(token, "price", "p"), Decimal("0")),
            _decimal_or_none(book.last_trade_price),
        ),
        best_bid=best_bid_price,
        best_ask=best_ask_price,
    )


def build_quote_plan(
    market: dict[str, Any],
    token: dict[str, Any],
    book: OrderBookSummary,
    quote_inputs: QuoteInputs,
    config: Config,
) -> QuotePlan | None:
    tick = _decimal(book.tick_size, Decimal("0.01"))
    buy_band = build_quote_band(market, BUY, quote_inputs, tick, config) if config.quote_sides.includes_buy() else None
    sell_band = build_quote_band(market, SELL, quote_inputs, tick, config) if config.quote_sides.includes_sell() else None

    if not config.allow_single_sided and (buy_band is None or sell_band is None):
        return None

    if buy_band is not None and sell_band is not None:
        tick_spread = tick * Decimal(config.min_spread_ticks)
        if sell_band.price - buy_band.price < tick_spread:
            buy_band = None
            sell_band = None

    if buy_band is None and sell_band is None:
        return None

    return QuotePlan(
        market_key=market_key(market),
        market_slug=_market_slug(market),
        question=_market_question(market),
        token_id=_token_id(token),
        outcome=_token_outcome(token),
        fair_price=quote_inputs.fair_price,
        best_bid=quote_inputs.best_bid,
        best_ask=quote_inputs.best_ask,
        buy_band=buy_band,
        sell_band=sell_band,
    )


def build_quote_band(
    market: dict[str, Any],
    side: str,
    quote_inputs: QuoteInputs,
    tick: Decimal,
    config: Config,
) -> QuoteBand | None:
    if tick <= Decimal("0"):
        return None

    min_margin_ticks, avg_margin_ticks, max_margin_ticks = band_margin_ticks(config)
    min_size, avg_size, max_size = band_sizes(config)
    min_margin = tick * Decimal(min_margin_ticks)
    avg_margin = tick * Decimal(avg_margin_ticks)
    max_margin = tick * Decimal(max_margin_ticks)

    if side == BUY:
        price = floor_to_tick(quote_inputs.fair_price - avg_margin, tick)
        min_price = floor_to_tick(quote_inputs.fair_price - max_margin, tick)
        max_price = floor_to_tick(quote_inputs.fair_price - min_margin, tick)
        if quote_inputs.best_ask is not None and price >= quote_inputs.best_ask:
            return None
    elif side == SELL:
        price = ceil_to_tick(quote_inputs.fair_price + avg_margin, tick)
        min_price = ceil_to_tick(quote_inputs.fair_price + min_margin, tick)
        max_price = ceil_to_tick(quote_inputs.fair_price + max_margin, tick)
        if quote_inputs.best_bid is not None and price <= quote_inputs.best_bid:
            return None
    else:
        return None

    min_price = max(min_price, tick)
    max_price = min(max_price, Decimal("1") - tick)
    if not is_tradeable_price(price, tick) or min_price > max_price:
        return None

    return QuoteBand(
        side=side,
        price=price,
        min_price=min_price,
        max_price=max_price,
        min_size=order_size(market, min_size, config),
        avg_size=order_size(market, avg_size, config),
        max_size=order_size(market, max_size, config),
    )


def order_size(market: dict[str, Any], requested_size: Decimal, config: Config) -> Decimal:
    size = max(requested_size, _decimal(_field(market, "minimum_order_size"), Decimal("0")))
    if config.respect_reward_min_size:
        size = max(size, _decimal(_dict_field(market, "rewards").get("min_size"), Decimal("0")))
    return size


def should_enforce_liquidity_quality(config: Config) -> bool:
    return config.live and config.require_two_sided_live


def liquidity_quality_reject_reason(
    book: OrderBookSummary,
    config: Config,
) -> LiquidityRejectReason | None:
    return liquidity_reject_reason(
        book.bids or [],
        book.asks or [],
        _decimal(book.tick_size, Decimal("0")),
        config.max_book_spread_ticks,
        config.min_top_depth,
    )


def liquidity_reject_reason(
    bids: list[OrderSummary],
    asks: list[OrderSummary],
    tick: Decimal,
    max_spread_ticks: int,
    min_top_depth: Decimal,
) -> LiquidityRejectReason | None:
    if tick <= Decimal("0"):
        return LiquidityRejectReason(LiquidityRejectKind.INVALID_TICK)

    bid = best_bid(bids)
    ask = best_ask(asks)
    if bid is None or ask is None or bid <= Decimal("0") or ask <= bid:
        return LiquidityRejectReason(LiquidityRejectKind.MISSING_TWO_SIDED_BOOK)

    spread_ticks = (ask - bid) / tick
    if spread_ticks > Decimal(max_spread_ticks):
        return LiquidityRejectReason(
            LiquidityRejectKind.SPREAD_TOO_WIDE,
            spread_ticks=spread_ticks,
            max_spread_ticks=max_spread_ticks,
        )

    bid_depth = top_depth(bids, bid)
    if bid_depth < min_top_depth:
        return LiquidityRejectReason(
            LiquidityRejectKind.BID_DEPTH_TOO_LOW,
            depth=bid_depth,
            min_depth=min_top_depth,
        )

    ask_depth = top_depth(asks, ask)
    if ask_depth < min_top_depth:
        return LiquidityRejectReason(
            LiquidityRejectKind.ASK_DEPTH_TOO_LOW,
            depth=ask_depth,
            min_depth=min_top_depth,
        )

    return None


def top_depth(levels: list[OrderSummary], price: Decimal) -> Decimal:
    return sum(
        (
            _decimal(level.size, Decimal("0"))
            for level in levels
            if _decimal_or_none(level.price) == price
        ),
        Decimal("0"),
    )


def print_plan(plan: QuotePlan, live: bool) -> None:
    mode = "live" if live else "dry-run"
    print(
        f"{mode}: {plan.market_key} :: {plan.market_slug} :: {plan.question} :: "
        f"{plan.outcome} ({plan.token_id}) fair={plan.fair_price} "
        f"bid={plan.best_bid} ask={plan.best_ask} buy={format_band(plan.buy_band)} "
        f"sell={format_band(plan.sell_band)}"
    )


def format_band(band: QuoteBand | None) -> str:
    if band is None:
        return "none"
    return (
        f"price={band.price} band=[{band.min_price}, {band.max_price}] "
        f"size={band.min_size}/{band.avg_size}/{band.max_size}"
    )


def post_quote_plan(
    client: ClobClient,
    plan: QuotePlan,
    config: Config,
    market_state: LiveMarketState,
) -> None:
    open_orders = market_state.open_orders(plan.token_id)
    if config.cancel_before_quote:
        orders_to_cancel = cancellable_orders(open_orders, plan)
        order_ids = [open_order_id(order) for order in orders_to_cancel if open_order_id(order)]
        response = client.cancel_orders(order_ids) if order_ids else {}
        canceled = _response_list(response, "canceled")
        not_canceled = _response_list(response, "not_canceled")
        if order_ids or not_canceled:
            print(
                f"canceled band orders for {plan.token_id}: "
                f"requested={len(order_ids)} canceled={len(canceled)} not_canceled={len(not_canceled)}"
            )
        market_state.remove_open_orders(
            plan.token_id,
            {order_id for item in canceled for order_id in [response_item_id(item)] if order_id},
        )
        if canceled:
            open_orders = market_state.open_orders(plan.token_id)

    responses = []
    for band in plan.bands():
        open_size = band_open_size(open_orders, band)
        missing_size = band_missing_size(band, open_size)
        if missing_size is None:
            continue

        proposed = ProposedOrder(
            token_id=plan.token_id,
            side=band.side,
            price=band.price,
            size=missing_size,
        )
        if market_loss_exceeds_cap(plan, proposed, market_state, config):
            continue
        order = client.create_order(
            OrderArgs(
                token_id=plan.token_id,
                price=float(band.price),
                size=float(missing_size),
                side=band.side,
            )
        )
        market_state.record_pending_order(proposed)
        responses.append((band.side, client.post_order(order, orderType=OrderType.GTC, post_only=config.post_only)))

    print_post_responses(plan, responses)


def cancellable_orders(open_orders: list[Any], plan: QuotePlan) -> list[Any]:
    cancellable: list[Any] = []
    cancellable_ids: set[str] = set()

    for order in open_orders:
        if order_should_cancel(order, plan):
            order_id = open_order_id(order)
            if order_id and order_id not in cancellable_ids:
                cancellable_ids.add(order_id)
                cancellable.append(order)

    for band in plan.bands():
        matching_orders = [
            order
            for order in open_orders
            if open_order_id(order) not in cancellable_ids and band.includes_order(order)
        ]
        matching_size = sum((open_order_remaining_size(order) for order in matching_orders), Decimal("0"))
        if matching_size <= band.max_size:
            continue

        band_amount = matching_size
        matching_orders.sort(key=lambda order: (-band.cancel_priority(order), open_order_created_at(order)))
        for order in matching_orders:
            if band_amount <= band.avg_size:
                break
            order_id = open_order_id(order)
            if not order_id or order_id in cancellable_ids:
                continue
            cancellable_ids.add(order_id)
            cancellable.append(order)
            band_amount = max(band_amount - open_order_remaining_size(order), Decimal("0"))

    return cancellable


def order_should_cancel(order: Any, plan: QuotePlan) -> bool:
    side = _response_field(order, "side")
    if side == BUY:
        return plan.buy_band is None or not plan.buy_band.includes_order(order)
    if side == SELL:
        return plan.sell_band is None or not plan.sell_band.includes_order(order)
    return True


def band_open_size(open_orders: list[Any], band: QuoteBand) -> Decimal:
    return sum(
        (open_order_remaining_size(order) for order in open_orders if band.includes_order(order)),
        Decimal("0"),
    )


def band_missing_size(band: QuoteBand, open_size: Decimal) -> Decimal | None:
    if open_size >= band.min_size:
        return None
    return max(band.avg_size - open_size, Decimal("0"))


def market_loss_exceeds_cap(
    plan: QuotePlan,
    proposed_order: ProposedOrder,
    market_state: LiveMarketState,
    config: Config,
) -> bool:
    projected_loss = market_state.exposure().projected_loss(proposed_order)
    if projected_loss <= config.max_loss_per_market:
        return False

    print(
        f"skip {plan.market_slug} {plan.outcome} {proposed_order.side}: "
        f"projected market loss {projected_loss} exceeds cap {config.max_loss_per_market}"
    )
    return True


def open_orders_for_token(client: ClobClient, token_id: str) -> list[Any]:
    orders = client.get_orders(OpenOrderParams(asset_id=token_id))
    return orders if isinstance(orders, list) else []


def conditional_balance(client: ClobClient, token_id: str) -> Decimal:
    response = client.get_balance_allowance(
        BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=token_id)
    )
    balance = _decimal(_response_field(response, "balance"), Decimal("0"))
    return balance / CONDITIONAL_TOKEN_BASE_UNITS


def proposed_order_from_open_order(order: Any, default_token_id: str) -> ProposedOrder | None:
    side = _response_field(order, "side")
    if side not in (BUY, SELL):
        return None

    price = _decimal_or_none(_response_field(order, "price"))
    if price is None:
        return None

    size = open_order_remaining_size(order)
    if size <= Decimal("0"):
        return None

    token_id = str(_response_field(order, "asset_id", "token_id", "tokenId") or default_token_id)
    return ProposedOrder(token_id=token_id, side=side, price=price, size=size)


def open_order_remaining_size(order: Any) -> Decimal:
    original_size = _decimal(
        _response_field(order, "original_size", "originalSize", "size"),
        Decimal("0"),
    )
    size_matched = _decimal(
        _response_field(order, "size_matched", "sizeMatched"),
        Decimal("0"),
    )
    return max(original_size - size_matched, Decimal("0"))


def open_order_id(order: Any) -> str:
    value = _response_field(order, "id", "order_id", "orderID")
    return str(value) if value is not None else ""


def response_item_id(item: Any) -> str:
    if isinstance(item, str):
        return item
    value = _response_field(item, "id", "order_id", "orderID")
    return str(value) if value is not None else ""


def open_order_created_at(order: Any) -> float:
    return _timestamp_sort_value(_response_field(order, "created_at", "createdAt"))


def print_post_responses(plan: QuotePlan, responses: list[tuple[str, Any]]) -> None:
    for side, response in responses:
        print(
            f"posted {plan.market_slug} {plan.outcome} side={side} "
            f"order_id={_response_field(response, 'orderID', 'order_id', 'id')} "
            f"success={_response_field(response, 'success')} "
            f"status={_response_field(response, 'status')} "
            f"error={_response_field(response, 'errorMsg', 'error_msg', 'error')}"
        )


def best_bid(levels: list[OrderSummary]) -> Decimal | None:
    prices = [_decimal_or_none(level.price) for level in levels]
    prices = [price for price in prices if price is not None]
    return max(prices) if prices else None


def best_ask(levels: list[OrderSummary]) -> Decimal | None:
    prices = [_decimal_or_none(level.price) for level in levels]
    prices = [price for price in prices if price is not None]
    return min(prices) if prices else None


def _market_slug(market: dict[str, Any]) -> str:
    return str(_field(market, "market_slug", "slug") or "unknown")


def _market_question(market: dict[str, Any]) -> str:
    return str(_field(market, "question", "title") or "")


def _market_tokens(market: dict[str, Any]) -> list[dict[str, Any]]:
    tokens = _field(market, "tokens", "outcomes")
    if not isinstance(tokens, list):
        return []
    return [token for token in tokens if isinstance(token, dict)]


def _token_id(token: dict[str, Any]) -> str:
    value = _field(token, "token_id", "tokenId", "asset_id", "assetId", "t")
    return str(value) if value is not None else ""


def _token_outcome(token: dict[str, Any]) -> str:
    return str(_field(token, "outcome", "name", "label") or "")


def _field(source: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = source.get(name)
        if value is not None:
            return value
    return None


def _dict_field(source: dict[str, Any], name: str) -> dict[str, Any]:
    value = source.get(name)
    return value if isinstance(value, dict) else {}


def _bool_field(source: dict[str, Any], name: str) -> bool:
    value = source.get(name)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(value)


def _decimal(value: Any, default: Decimal) -> Decimal:
    parsed = _decimal_or_none(value)
    return default if parsed is None else parsed


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _response_field(response: Any, *names: str) -> Any:
    for name in names:
        if isinstance(response, dict) and name in response:
            return response.get(name)
        if hasattr(response, name):
            return getattr(response, name)
    return None


def _response_list(response: Any, name: str) -> list[Any]:
    value = _response_field(response, name)
    return value if isinstance(value, list) else []


def _timestamp_sort_value(value: Any) -> float:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0
    if text.isdigit():
        return float(text)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0
