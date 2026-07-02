from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderBookSummary, OrderSummary, OrderType
from py_clob_client.constants import END_CURSOR
from py_clob_client.order_builder.constants import BUY, SELL

from .config import Config, DiscoveryMode
from .event_scope import condition_id_from_market, condition_ids_from_site_config
from .pricing import fair_price, quote_prices
from .state import SeenMarkets

INITIAL_CURSOR = "MA=="


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
    buy_price: Decimal | None
    sell_price: Decimal | None
    size: Decimal


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
    for token in _market_tokens(market):
        token_id = _token_id(token)
        if not token_id:
            continue

        book = public_client.get_order_book(token_id)
        plan = build_quote_plan(market, token, book, config)
        if plan is None:
            print(f"skip {_market_slug(market)} {_token_outcome(token)}: no safe quote at configured edge/sides")
            continue

        print_plan(plan, config.live)
        if live_client is not None:
            post_quote_plan(live_client, plan, config)


def build_quote_plan(
    market: dict[str, Any],
    token: dict[str, Any],
    book: OrderBookSummary,
    config: Config,
) -> QuotePlan | None:
    best_bid_price = best_bid(book.bids or [])
    best_ask_price = best_ask(book.asks or [])
    fair = fair_price(
        best_bid_price,
        best_ask_price,
        _decimal(_field(token, "price", "p"), Decimal("0")),
        _decimal_or_none(book.last_trade_price),
    )
    tick = _decimal(book.tick_size, Decimal("0.01"))
    buy_price, sell_price = quote_prices(
        fair,
        best_bid_price,
        best_ask_price,
        tick,
        config.edge_ticks,
        config.min_spread_ticks,
    )

    if not config.quote_sides.includes_buy():
        buy_price = None
    if not config.quote_sides.includes_sell():
        sell_price = None

    if not config.allow_single_sided and (buy_price is None or sell_price is None):
        return None

    if buy_price is not None and sell_price is not None and buy_price >= sell_price:
        buy_price = None
        sell_price = None

    if buy_price is None and sell_price is None:
        return None

    return QuotePlan(
        market_key=market_key(market),
        market_slug=_market_slug(market),
        question=_market_question(market),
        token_id=_token_id(token),
        outcome=_token_outcome(token),
        fair_price=fair,
        best_bid=best_bid_price,
        best_ask=best_ask_price,
        buy_price=buy_price,
        sell_price=sell_price,
        size=order_size(market, config),
    )


def order_size(market: dict[str, Any], config: Config) -> Decimal:
    size = max(config.order_size, _decimal(_field(market, "minimum_order_size"), Decimal("0")))
    if config.respect_reward_min_size:
        size = max(size, _decimal(_dict_field(market, "rewards").get("min_size"), Decimal("0")))
    return size


def print_plan(plan: QuotePlan, live: bool) -> None:
    mode = "live" if live else "dry-run"
    print(
        f"{mode}: {plan.market_key} :: {plan.market_slug} :: {plan.question} :: "
        f"{plan.outcome} ({plan.token_id}) fair={plan.fair_price} "
        f"bid={plan.best_bid} ask={plan.best_ask} buy={plan.buy_price} "
        f"sell={plan.sell_price} size={plan.size}"
    )


def post_quote_plan(client: ClobClient, plan: QuotePlan, config: Config) -> None:
    if config.cancel_before_quote:
        response = client.cancel_market_orders(asset_id=plan.token_id)
        canceled = _response_list(response, "canceled")
        not_canceled = _response_list(response, "not_canceled")
        if canceled or not_canceled:
            print(
                f"canceled stale orders for {plan.token_id}: "
                f"canceled={len(canceled)} not_canceled={len(not_canceled)}"
            )

    responses = []
    if plan.buy_price is not None:
        order = client.create_order(
            OrderArgs(
                token_id=plan.token_id,
                price=float(plan.buy_price),
                size=float(plan.size),
                side=BUY,
            )
        )
        responses.append((BUY, client.post_order(order, orderType=OrderType.GTC, post_only=config.post_only)))

    if plan.sell_price is not None:
        order = client.create_order(
            OrderArgs(
                token_id=plan.token_id,
                price=float(plan.sell_price),
                size=float(plan.size),
                side=SELL,
            )
        )
        responses.append((SELL, client.post_order(order, orderType=OrderType.GTC, post_only=config.post_only)))

    print_post_responses(plan, responses)


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
