from decimal import Decimal

from py_market_maker.market_loss import (
    BUY,
    SELL,
    MarketExposure,
    OutcomeExposure,
    ProposedOrder,
)


def test_complete_set_is_hedged():
    exposure = MarketExposure(
        [
            OutcomeExposure("yes", Decimal("5"), Decimal("2.5")),
            OutcomeExposure("no", Decimal("5"), Decimal("2.5")),
        ]
    )

    assert exposure.worst_loss() == Decimal("0")


def test_projected_buy_loss_uses_worst_resolution():
    exposure = MarketExposure(
        [
            OutcomeExposure("yes", Decimal("0"), Decimal("0")),
            OutcomeExposure("no", Decimal("0"), Decimal("0")),
        ]
    )

    loss = exposure.projected_loss(
        ProposedOrder("yes", BUY, Decimal("0.40"), Decimal("5"))
    )

    assert loss == Decimal("2.00")


def test_projected_cross_outcome_buys_can_reduce_loss():
    exposure = MarketExposure(
        [
            OutcomeExposure("yes", Decimal("0"), Decimal("0")),
            OutcomeExposure("no", Decimal("0"), Decimal("0")),
        ]
    )
    exposure.apply_order(ProposedOrder("yes", BUY, Decimal("0.40"), Decimal("5")))

    loss = exposure.projected_loss(
        ProposedOrder("no", BUY, Decimal("0.40"), Decimal("5"))
    )

    assert loss == Decimal("0")


def test_projected_sell_proceeds_offset_loss():
    exposure = MarketExposure(
        [
            OutcomeExposure("yes", Decimal("5"), Decimal("2.5")),
            OutcomeExposure("no", Decimal("0"), Decimal("0")),
        ]
    )

    loss = exposure.projected_loss(
        ProposedOrder("yes", SELL, Decimal("0.60"), Decimal("2"))
    )

    assert loss == Decimal("1.3")
