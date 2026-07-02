from decimal import Decimal

from py_market_maker.bot import (
    QuoteBand,
    band_missing_size,
    cancellable_orders,
)
from py_market_maker.market_loss import BUY


def test_quote_band_contains_configured_price_range():
    band = QuoteBand(
        side=BUY,
        price=Decimal("0.49"),
        min_price=Decimal("0.47"),
        max_price=Decimal("0.49"),
        min_size=Decimal("5"),
        avg_size=Decimal("10"),
        max_size=Decimal("15"),
    )

    assert band.contains_price(Decimal("0.47"))
    assert band.contains_price(Decimal("0.48"))
    assert band.contains_price(Decimal("0.49"))
    assert not band.contains_price(Decimal("0.46"))
    assert not band.contains_price(Decimal("0.50"))


def test_band_missing_size_targets_average_only_below_minimum():
    band = QuoteBand(
        side=BUY,
        price=Decimal("0.49"),
        min_price=Decimal("0.47"),
        max_price=Decimal("0.49"),
        min_size=Decimal("5"),
        avg_size=Decimal("10"),
        max_size=Decimal("15"),
    )

    assert band_missing_size(band, Decimal("4")) == Decimal("6")
    assert band_missing_size(band, Decimal("5")) is None
    assert band_missing_size(band, Decimal("9")) is None


def test_cancellable_orders_removes_outside_band_and_excess_size():
    band = QuoteBand(
        side=BUY,
        price=Decimal("0.49"),
        min_price=Decimal("0.47"),
        max_price=Decimal("0.49"),
        min_size=Decimal("5"),
        avg_size=Decimal("10"),
        max_size=Decimal("12"),
    )
    plan = _plan(band)
    orders = [
        _order("outside", BUY, "0.46", "2", "2026-01-01T00:00:00+00:00"),
        _order("far", BUY, "0.47", "5", "2026-01-01T00:00:01+00:00"),
        _order("near", BUY, "0.49", "5", "2026-01-01T00:00:02+00:00"),
        _order("mid", BUY, "0.48", "5", "2026-01-01T00:00:03+00:00"),
    ]

    canceled = cancellable_orders(orders, plan)

    assert [order["id"] for order in canceled] == ["outside", "near"]


def _plan(band):
    from py_market_maker.bot import QuotePlan

    return QuotePlan(
        market_key="market",
        market_slug="market",
        question="Question?",
        token_id="yes",
        outcome="Yes",
        fair_price=Decimal("0.50"),
        best_bid=Decimal("0.49"),
        best_ask=Decimal("0.51"),
        buy_band=band,
        sell_band=None,
    )


def _order(order_id, side, price, size, created_at):
    return {
        "id": order_id,
        "side": side,
        "price": price,
        "original_size": size,
        "size_matched": "0",
        "created_at": created_at,
    }
