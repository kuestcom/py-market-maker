from py_market_maker.bot import (
    CANCEL_ORDER_BATCH_SIZE,
    cancel_open_orders_for_markets,
    managed_token_ids,
)


def test_managed_token_ids_are_deduped_in_scope_order():
    markets = [
        _market("market-a", ["yes", "no"]),
        _market("market-b", ["yes", "maybe"]),
    ]

    assert managed_token_ids(markets) == ["yes", "no", "maybe"]


def test_cancel_open_orders_for_markets_batches_and_verifies():
    order_count = CANCEL_ORDER_BATCH_SIZE + 1
    client = FakeClient(
        {
            "yes": [_order(f"yes-{index}") for index in range(order_count)],
            "no": [],
        }
    )

    summary = cancel_open_orders_for_markets(client, [_market("market", ["yes", "no", "yes"])])

    assert summary.markets_checked == 1
    assert summary.tokens_checked == 2
    assert summary.orders_found == order_count
    assert summary.canceled == order_count
    assert summary.not_canceled == 0
    assert summary.remaining_open == 0
    assert client.cancel_batches == [
        [f"yes-{index}" for index in range(CANCEL_ORDER_BATCH_SIZE)],
        [f"yes-{CANCEL_ORDER_BATCH_SIZE}"],
    ]


class FakeClient:
    def __init__(self, orders_by_token):
        self.orders_by_token = {
            token_id: list(orders)
            for token_id, orders in orders_by_token.items()
        }
        self.cancel_batches = []

    def get_orders(self, params):
        return list(self.orders_by_token.get(params.asset_id, []))

    def cancel_orders(self, order_ids):
        self.cancel_batches.append(list(order_ids))
        canceled = []
        order_id_set = set(order_ids)
        for token_id, orders in self.orders_by_token.items():
            remaining = []
            for order in orders:
                if order["id"] in order_id_set:
                    canceled.append(order["id"])
                else:
                    remaining.append(order)
            self.orders_by_token[token_id] = remaining
        return {"canceled": canceled, "not_canceled": []}


def _market(slug, token_ids):
    return {
        "slug": slug,
        "enable_order_book": True,
        "active": True,
        "closed": False,
        "archived": False,
        "accepting_orders": True,
        "tokens": [{"token_id": token_id} for token_id in token_ids],
    }


def _order(order_id):
    return {"id": order_id}
