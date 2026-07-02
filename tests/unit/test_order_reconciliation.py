from decimal import Decimal

from py_clob_client.clob_types import OrderBookSummary, OrderSummary

from py_market_maker import bot
from py_market_maker.bot import (
    InventoryBuyRoom,
    LiveMarketState,
    LiveTokenState,
    PreflightRiskAuditResult,
    QuoteBand,
    QuotePlan,
    TokenQuote,
    post_quote_plan,
    inventory_adjusted_buy_size,
    preflight_risk_audit,
    preflight_stale_data_reason,
    stale_input_reason,
)
from py_market_maker.config import parse_args
from py_market_maker.market_loss import BUY, SELL, ProposedOrder
from py_market_maker.state import PauseState


def test_cancel_refreshes_open_orders_before_posting_replacement():
    stale_order = _open_order("stale", BUY, "0.46", "5")
    market_state = _market_state(open_orders=[stale_order])
    client = FakeClient(
        open_order_pages={"yes": [[]]},
        post_responses=[_post_response(True, "replacement")],
    )

    post_quote_plan(client, _plan(buy_band=_buy_band()), parse_args([]), market_state)

    assert client.cancel_batches == [["stale"]]
    assert client.get_order_tokens == ["yes"]
    assert len(client.posted_orders) == 1
    assert market_state.open_orders("yes") == []
    assert market_state.pending_orders == [
        ProposedOrder("yes", BUY, Decimal("0.49"), Decimal("10"))
    ]


def test_cancel_refresh_skips_post_when_canceled_order_is_still_open():
    stale_order = _open_order("stale", BUY, "0.46", "5")
    market_state = _market_state(open_orders=[stale_order])
    client = FakeClient(
        open_order_pages={"yes": [[stale_order]]},
        post_responses=[_post_response(True, "replacement")],
    )

    post_quote_plan(client, _plan(buy_band=_buy_band()), parse_args([]), market_state)

    assert client.cancel_batches == [["stale"]]
    assert client.get_order_tokens == ["yes"]
    assert client.posted_orders == []
    assert market_state.open_orders("yes") == [stale_order]
    assert market_state.pending_orders == []


def test_rejected_post_does_not_record_pending_order_and_refreshes_state():
    market_state = _market_state()
    client = FakeClient(
        open_order_pages={"yes": [[]]},
        post_responses=[_post_response(False, "rejected")],
    )

    post_quote_plan(client, _plan(buy_band=_buy_band()), parse_args([]), market_state)

    assert len(client.posted_orders) == 1
    assert client.get_order_tokens == ["yes"]
    assert market_state.pending_orders == []
    assert market_state.open_orders("yes") == []


def test_failed_batch_response_dedupes_partially_filled_pending_order_now_open():
    market_state = _market_state(balance=Decimal("10"))
    posted_buy = _open_order("posted-buy", BUY, "0.49", "3")
    client = FakeClient(
        open_order_pages={"yes": [[posted_buy]]},
        post_responses=[
            _post_response(True, "posted-buy"),
            _post_response(False, "rejected-sell"),
        ],
    )

    post_quote_plan(
        client,
        _plan(
            buy_band=_buy_band(avg_size=Decimal("5")),
            sell_band=_sell_band(avg_size=Decimal("5")),
        ),
        parse_args(["--quote-sides", "both"]),
        market_state,
    )

    assert [order["side"] for order in client.created_orders] == [BUY, SELL]
    assert market_state.pending_orders == []
    assert market_state.open_orders("yes") == [posted_buy]


def test_stale_book_skips_live_post(monkeypatch):
    now = 100.0
    monkeypatch.setattr(bot.time, "monotonic", lambda: now)
    stale_order = _open_order("stale", BUY, "0.46", "5")
    market_state = _market_state(open_orders=[stale_order], now=now)
    client = FakeClient(post_responses=[_post_response(True, "posted")])

    post_quote_plan(
        client,
        _plan(buy_band=_buy_band(), book_fetched_at=now - 11),
        parse_args(["--max-data-age-secs", "10"]),
        market_state,
    )

    assert client.cancel_batches == []
    assert client.created_orders == []
    assert client.posted_orders == []
    assert market_state.open_orders("yes") == [stale_order]
    assert market_state.pending_orders == []


def test_stale_book_after_cancel_refresh_skips_replacement_post(monkeypatch):
    times = iter([109.0, 109.5, 111.0])
    monkeypatch.setattr(bot.time, "monotonic", lambda: next(times))
    stale_order = _open_order("stale", BUY, "0.46", "5")
    market_state = _market_state(open_orders=[stale_order], now=100.0)
    client = FakeClient(
        open_order_pages={"yes": [[]]},
        post_responses=[_post_response(True, "posted")],
    )

    post_quote_plan(
        client,
        _plan(buy_band=_buy_band(), book_fetched_at=100.0),
        parse_args(["--max-data-age-secs", "10"]),
        market_state,
    )

    assert client.cancel_batches == [["stale"]]
    assert client.get_order_tokens == ["yes"]
    assert client.created_orders == []
    assert client.posted_orders == []
    assert market_state.open_orders("yes") == []
    assert market_state.pending_orders == []


def test_stale_input_reason_flags_data_older_than_threshold():
    reason = stale_input_reason("order book", 100.0, 111.0, 10.0)

    assert reason is not None
    assert "order book" in reason


def test_stale_input_reason_accepts_fresh_data():
    assert stale_input_reason("order book", 100.0, 109.0, 10.0) is None


def test_preflight_stale_data_reason_flags_stale_token_inputs():
    now = 100.0
    token_quotes = [
        TokenQuote(
            token_id="yes",
            outcome="Yes",
            fair_price=Decimal("0.50"),
            book_fetched_at=now,
            plan=None,
            skip_reason=None,
        )
    ]
    market_state = _market_state(now=now)
    market_state.token_state("yes").open_orders_fetched_at = now - 11

    reason = preflight_stale_data_reason(
        token_quotes,
        market_state,
        now,
        parse_args(["--max-data-age-secs", "10"]),
    )

    assert reason is not None
    assert "token yes open orders" in reason


def test_inventory_adjusted_buy_size_caps_to_remaining_room():
    assert inventory_adjusted_buy_size(Decimal("5"), Decimal("1"), Decimal("3")) == Decimal("3")


def test_inventory_adjusted_buy_size_skips_when_room_is_below_minimum():
    assert inventory_adjusted_buy_size(Decimal("5"), Decimal("1"), Decimal("0.5")) is None


def test_inventory_buy_room_counts_balance_and_open_buys():
    open_buy = _open_order("open-buy", BUY, "0.40", "5")
    market_state = _market_state(open_orders=[open_buy], balance=Decimal("10"))

    room = market_state.inventory_buy_room(
        "yes",
        [],
        parse_args(["--max-inventory-per-token", "20", "--max-inventory-per-market", "50"]),
    )

    assert room == InventoryBuyRoom(
        token_position=Decimal("15"),
        market_inventory=Decimal("15"),
        room=Decimal("5"),
    )


def test_inventory_buy_room_ignores_open_sells():
    open_sell = _open_order("open-sell", SELL, "0.60", "5")
    market_state = _market_state(open_orders=[open_sell], balance=Decimal("20"))

    room = market_state.inventory_buy_room(
        "yes",
        [],
        parse_args(["--max-inventory-per-token", "25", "--max-inventory-per-market", "50"]),
    )

    assert room == InventoryBuyRoom(
        token_position=Decimal("20"),
        market_inventory=Decimal("20"),
        room=Decimal("5"),
    )


def test_buy_size_is_capped_by_token_inventory_room():
    market_state = _market_state(balance=Decimal("22"))
    client = FakeClient(post_responses=[_post_response(True, "posted")])

    post_quote_plan(
        client,
        _plan(buy_band=_buy_band()),
        parse_args(["--max-inventory-per-token", "25", "--max-inventory-per-market", "50"]),
        market_state,
    )

    assert len(client.created_orders) == 1
    assert Decimal(client.created_orders[0]["size"]) == Decimal("3.0")
    assert market_state.pending_orders == [
        ProposedOrder("yes", BUY, Decimal("0.49"), Decimal("3"))
    ]


def test_buy_is_skipped_when_inventory_room_is_below_minimum():
    market_state = _market_state(balance=Decimal("24.5"))
    client = FakeClient(post_responses=[_post_response(True, "posted")])

    post_quote_plan(
        client,
        _plan(buy_band=_buy_band()),
        parse_args(["--max-inventory-per-token", "25", "--max-inventory-per-market", "50"]),
        market_state,
    )

    assert client.created_orders == []
    assert client.posted_orders == []
    assert market_state.pending_orders == []


def test_risk_breaches_detect_token_inventory_over_limit():
    market_state = _market_state(balance=Decimal("11"))
    breaches = market_state.risk_breaches(parse_args(["--max-inventory-per-token", "10"]))

    assert any(
        breach.kind == "token_inventory"
        and breach.token_id == "yes"
        and breach.value == Decimal("11")
        and breach.limit == Decimal("10")
        for breach in breaches
    )


def test_risk_breaches_detect_market_inventory_over_limit():
    market_state = _market_state(balance=Decimal("8"), no_balance=Decimal("8"))
    breaches = market_state.risk_breaches(parse_args(["--max-inventory-per-market", "15"]))

    assert any(
        breach.kind == "market_inventory"
        and breach.value == Decimal("16")
        and breach.limit == Decimal("15")
        for breach in breaches
    )


def test_risk_breaches_detect_market_loss_over_limit():
    market_state = _market_state(balance=Decimal("5"))
    breaches = market_state.risk_breaches(parse_args(["--max-loss-per-market", "2"]))

    assert any(
        breach.kind == "market_loss"
        and breach.value == Decimal("2.50")
        and breach.limit == Decimal("2")
        for breach in breaches
    )


def test_risk_breach_skips_new_quotes_without_canceling_by_default():
    open_buy = _open_order("open-buy", BUY, "0.49", "5")
    market_state = _market_state(open_orders=[open_buy], balance=Decimal("11"))
    client = FakeClient(post_responses=[_post_response(True, "posted")])

    post_quote_plan(
        client,
        _plan(buy_band=_buy_band()),
        parse_args(["--max-inventory-per-token", "10"]),
        market_state,
    )

    assert client.cancel_batches == []
    assert client.created_orders == []
    assert client.posted_orders == []
    assert market_state.open_orders("yes") == [open_buy]


def test_cancel_on_risk_breach_cancels_open_buys_and_refreshes_state():
    open_buy = _open_order("open-buy", BUY, "0.49", "5")
    open_sell = _open_order("open-sell", SELL, "0.51", "5")
    market_state = _market_state(open_orders=[open_buy, open_sell], balance=Decimal("11"))
    client = FakeClient(open_order_pages={"yes": [[open_sell]]})

    post_quote_plan(
        client,
        _plan(buy_band=_buy_band(), sell_band=_sell_band()),
        parse_args([
            "--live",
            "--private-key",
            "0xabc",
            "--deposit-wallet",
            "0xdef",
            "--chain-id",
            "137",
            "--cancel-on-risk-breach",
            "--max-inventory-per-token",
            "10",
        ]),
        market_state,
    )

    assert client.cancel_batches == [["open-buy"]]
    assert client.get_order_tokens == ["yes"]
    assert client.created_orders == []
    assert client.posted_orders == []
    assert market_state.open_orders("yes") == [open_sell]


def test_cancel_on_risk_breach_does_not_cancel_unrelated_token_buys():
    open_buy = _open_order("open-buy", BUY, "0.49", "5")
    market_state = _market_state(open_orders=[open_buy], no_balance=Decimal("11"))
    client = FakeClient(post_responses=[_post_response(True, "posted")])

    post_quote_plan(
        client,
        _plan(buy_band=_buy_band()),
        parse_args([
            "--live",
            "--private-key",
            "0xabc",
            "--deposit-wallet",
            "0xdef",
            "--chain-id",
            "137",
            "--cancel-on-risk-breach",
            "--max-inventory-per-token",
            "10",
        ]),
        market_state,
    )

    assert client.cancel_batches == []
    assert client.get_order_tokens == []
    assert client.created_orders == []
    assert client.posted_orders == []
    assert market_state.open_orders("yes") == [open_buy]


def test_pause_on_risk_breach_writes_pause_file_and_skips_new_quotes(tmp_path):
    pause_path = tmp_path / "paused.json"
    market_state = _market_state(balance=Decimal("11"))
    client = FakeClient(post_responses=[_post_response(True, "posted")])

    post_quote_plan(
        client,
        _plan(buy_band=_buy_band()),
        parse_args([
            "--live",
            "--private-key",
            "0xabc",
            "--deposit-wallet",
            "0xdef",
            "--chain-id",
            "137",
            "--pause-on-risk-breach",
            "--pause-path",
            str(pause_path),
            "--max-inventory-per-token",
            "10",
        ]),
        market_state,
    )

    pause = PauseState.load(pause_path)
    assert pause is not None
    assert pause.reason == "risk breach market Yes: token yes inventory 11 exceeds limit 10"
    assert client.created_orders == []
    assert client.posted_orders == []


def test_active_pause_skips_stale_order_cancel(tmp_path):
    pause_path = tmp_path / "paused.json"
    PauseState.save_reason(pause_path, "manual stop")
    stale_order = _open_order("stale", BUY, "0.46", "5")
    market_state = _market_state(open_orders=[stale_order])
    client = FakeClient(open_order_pages={"yes": [[]]})

    post_quote_plan(
        client,
        _plan(buy_band=_buy_band()),
        parse_args(["--pause-path", str(pause_path)]),
        market_state,
    )

    assert client.cancel_batches == []
    assert client.get_order_tokens == []
    assert market_state.open_orders("yes") == [stale_order]


def test_active_pause_skips_posting_orders(tmp_path):
    pause_path = tmp_path / "paused.json"
    PauseState.save_reason(pause_path, "manual stop")
    market_state = _market_state()
    client = FakeClient(post_responses=[_post_response(True, "posted")])

    post_quote_plan(
        client,
        _plan(buy_band=_buy_band()),
        parse_args(["--pause-path", str(pause_path)]),
        market_state,
    )

    assert len(client.created_orders) == 1
    assert client.posted_orders == []
    assert market_state.pending_orders == []


def test_preflight_risk_audit_cancels_and_pauses_on_market_breach(tmp_path):
    pause_path = tmp_path / "paused.json"
    open_buy = _open_order("open-buy", BUY, "0.49", "5")
    client = FakeClient(
        books={"yes": _book()},
        balances={"yes": Decimal("11")},
        open_order_pages={"yes": [[open_buy]]},
    )

    result = preflight_risk_audit(
        client,
        client,
        [_market()],
        parse_args([
            "--live",
            "--private-key",
            "0xabc",
            "--deposit-wallet",
            "0xdef",
            "--chain-id",
            "137",
            "--cancel-on-risk-breach",
            "--pause-on-risk-breach",
            "--pause-path",
            str(pause_path),
            "--max-inventory-per-token",
            "10",
        ]),
    )

    pause = PauseState.load(pause_path)
    assert result == PreflightRiskAuditResult.STOP
    assert client.cancel_batches == [["open-buy"]]
    assert pause is not None
    assert pause.reason == "preflight risk breach market: token yes inventory 16 exceeds limit 10"


class FakeClient:
    def __init__(self, open_order_pages=None, post_responses=None, books=None, balances=None):
        self.open_order_pages = {
            token_id: list(pages)
            for token_id, pages in (open_order_pages or {}).items()
        }
        self.post_responses = list(post_responses or [])
        self.books = dict(books or {})
        self.balances = dict(balances or {})
        self.cancel_batches = []
        self.created_orders = []
        self.posted_orders = []
        self.get_order_tokens = []

    def get_order_book(self, token_id):
        return self.books[token_id]

    def get_balance_allowance(self, params):
        balance = self.balances.get(params.token_id, Decimal("0"))
        return {"balance": str(balance * bot.CONDITIONAL_TOKEN_BASE_UNITS)}

    def cancel_orders(self, order_ids):
        self.cancel_batches.append(list(order_ids))
        return {"canceled": list(order_ids), "not_canceled": []}

    def get_orders(self, params):
        self.get_order_tokens.append(params.asset_id)
        pages = self.open_order_pages.get(params.asset_id, [])
        return list(pages.pop(0)) if pages else []

    def create_order(self, order_args):
        order = {
            "token_id": order_args.token_id,
            "price": str(order_args.price),
            "size": str(order_args.size),
            "side": order_args.side,
        }
        self.created_orders.append(order)
        return order

    def post_order(self, order, orderType=None, post_only=True):
        self.posted_orders.append((order, orderType, post_only))
        return self.post_responses.pop(0)


def _market_state(open_orders=None, balance=Decimal("0"), no_balance=Decimal("0"), now=None):
    now = bot.time.monotonic() if now is None else now
    return LiveMarketState(
        tokens=[
            LiveTokenState(
                token_id="yes",
                fair_price=Decimal("0.50"),
                balance=balance,
                balance_fetched_at=now,
                open_orders=list(open_orders or []),
                open_orders_fetched_at=now,
            ),
            LiveTokenState("no", Decimal("0.50"), no_balance, now, [], now),
        ],
        pending_orders=[],
    )


def _plan(buy_band=None, sell_band=None, book_fetched_at=None):
    book_fetched_at = bot.time.monotonic() if book_fetched_at is None else book_fetched_at
    return QuotePlan(
        market_key="market",
        market_slug="market",
        question="Question?",
        token_id="yes",
        outcome="Yes",
        fair_price=Decimal("0.50"),
        best_bid=Decimal("0.49"),
        best_ask=Decimal("0.51"),
        book_fetched_at=book_fetched_at,
        buy_band=buy_band,
        sell_band=sell_band,
    )


def _buy_band(avg_size=Decimal("10")):
    return QuoteBand(
        side=BUY,
        price=Decimal("0.49"),
        min_price=Decimal("0.47"),
        max_price=Decimal("0.49"),
        minimum_size=Decimal("1"),
        min_size=Decimal("5"),
        avg_size=avg_size,
        max_size=Decimal("15"),
    )


def _sell_band(avg_size=Decimal("10")):
    return QuoteBand(
        side=SELL,
        price=Decimal("0.51"),
        min_price=Decimal("0.51"),
        max_price=Decimal("0.53"),
        minimum_size=Decimal("1"),
        min_size=Decimal("5"),
        avg_size=avg_size,
        max_size=Decimal("15"),
    )


def _open_order(order_id, side, price, size):
    return {
        "id": order_id,
        "asset_id": "yes",
        "side": side,
        "price": price,
        "original_size": size,
        "size_matched": "0",
    }


def _post_response(success, order_id):
    return {
        "success": success,
        "orderID": order_id,
        "status": "live" if success else "rejected",
    }


def _market():
    return {
        "slug": "market",
        "question": "Question?",
        "enable_order_book": True,
        "active": True,
        "closed": False,
        "archived": False,
        "accepting_orders": True,
        "tokens": [{"token_id": "yes", "outcome": "Yes", "price": "0.50"}],
    }


def _book():
    return OrderBookSummary(
        bids=[OrderSummary(price="0.49", size="10")],
        asks=[OrderSummary(price="0.51", size="10")],
        tick_size="0.01",
    )
