from decimal import Decimal

from py_market_maker.bot import (
    LiveMarketState,
    LiveTokenState,
    open_order_remaining_size,
    proposed_order_from_open_order,
)
from py_market_maker.market_loss import BUY, ProposedOrder


def test_open_order_remaining_size_uses_unmatched_size():
    order = {
        "original_size": "10",
        "size_matched": "2.5",
    }

    assert open_order_remaining_size(order) == Decimal("7.5")


def test_unknown_open_order_side_is_ignored():
    order = {
        "asset_id": "yes",
        "side": "HOLD",
        "price": "0.40",
        "original_size": "5",
        "size_matched": "0",
    }

    assert proposed_order_from_open_order(order, "yes") is None


def test_live_market_state_removes_canceled_open_orders_from_exposure():
    market_state = LiveMarketState(
        tokens=[
            LiveTokenState(
                token_id="yes",
                fair_price=Decimal("0.50"),
                balance=Decimal("0"),
                open_orders=[
                    {
                        "id": "stale",
                        "asset_id": "yes",
                        "side": BUY,
                        "price": "0.40",
                        "original_size": "5",
                        "size_matched": "0",
                    }
                ],
            ),
            LiveTokenState("no", Decimal("0.50"), Decimal("0"), []),
        ],
        pending_orders=[],
    )

    assert market_state.exposure().worst_loss() == Decimal("2.00")

    market_state.remove_open_orders("yes", {"stale"})
    market_state.record_pending_order(ProposedOrder("no", BUY, Decimal("0.40"), Decimal("5")))

    assert market_state.exposure().worst_loss() == Decimal("2.00")
