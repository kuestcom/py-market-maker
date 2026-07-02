from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

BUY = "BUY"
SELL = "SELL"


@dataclass(frozen=True)
class ProposedOrder:
    token_id: str
    side: str
    price: Decimal
    size: Decimal


@dataclass
class OutcomeExposure:
    token_id: str
    position: Decimal
    cost: Decimal
    proceeds: Decimal = Decimal("0")


@dataclass
class MarketExposure:
    outcomes: list[OutcomeExposure]

    def apply_order(self, order: ProposedOrder) -> None:
        validate_order(order)
        outcome = self._outcome(order.token_id)
        if order.side == BUY:
            outcome.position += order.size
            outcome.cost += order.size * order.price
            return
        if order.side == SELL:
            outcome.position -= order.size
            outcome.proceeds += order.size * order.price
            return

    def worst_loss(self) -> Decimal:
        cost = sum((outcome.cost for outcome in self.outcomes), Decimal("0"))
        proceeds = sum((outcome.proceeds for outcome in self.outcomes), Decimal("0"))
        worst_resolution_payout = Decimal("0")
        if len(self.outcomes) > 1:
            worst_resolution_payout = min(
                (outcome.position for outcome in self.outcomes),
                default=Decimal("0"),
            )
        return max(cost - proceeds - worst_resolution_payout, Decimal("0"))

    def projected_loss(self, order: ProposedOrder) -> Decimal:
        exposure = MarketExposure(
            outcomes=[
                OutcomeExposure(
                    token_id=outcome.token_id,
                    position=outcome.position,
                    cost=outcome.cost,
                    proceeds=outcome.proceeds,
                )
                for outcome in self.outcomes
            ]
        )
        exposure.apply_order(order)
        return exposure.worst_loss()

    def _outcome(self, token_id: str) -> OutcomeExposure:
        for outcome in self.outcomes:
            if outcome.token_id == token_id:
                return outcome
        raise RuntimeError(f"missing exposure state for token {token_id}")


def validate_order(order: ProposedOrder) -> None:
    if order.side not in (BUY, SELL):
        raise ValueError(f"unsupported order side {order.side}")
    if order.price <= Decimal("0"):
        raise ValueError(f"order price must be greater than zero: {order.price}")
    if order.size <= Decimal("0"):
        raise ValueError(f"order size must be greater than zero: {order.size}")
