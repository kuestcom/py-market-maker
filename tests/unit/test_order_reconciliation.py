from decimal import Decimal

from py_market_maker import bot
from py_market_maker.bot import (
    LiveMarketState,
    LiveTokenState,
    QuoteBand,
    QuotePlan,
    post_quote_plan,
    stale_input_reason,
)
from py_market_maker.config import parse_args
from py_market_maker.market_loss import BUY, SELL, ProposedOrder


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
    market_state = _market_state(now=now)
    client = FakeClient(post_responses=[_post_response(True, "posted")])

    post_quote_plan(
        client,
        _plan(buy_band=_buy_band(), book_fetched_at=now - 11),
        parse_args(["--max-data-age-secs", "10"]),
        market_state,
    )

    assert client.created_orders == []
    assert client.posted_orders == []
    assert market_state.pending_orders == []


def test_stale_input_reason_flags_data_older_than_threshold():
    reason = stale_input_reason("order book", 100.0, 111.0, 10.0)

    assert reason is not None
    assert "order book" in reason


def test_stale_input_reason_accepts_fresh_data():
    assert stale_input_reason("order book", 100.0, 109.0, 10.0) is None


class FakeClient:
    def __init__(self, open_order_pages=None, post_responses=None):
        self.open_order_pages = {
            token_id: list(pages)
            for token_id, pages in (open_order_pages or {}).items()
        }
        self.post_responses = list(post_responses or [])
        self.cancel_batches = []
        self.created_orders = []
        self.posted_orders = []
        self.get_order_tokens = []

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


def _market_state(open_orders=None, balance=Decimal("0"), now=None):
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
            LiveTokenState("no", Decimal("0.50"), Decimal("0"), now, [], now),
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
