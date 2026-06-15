from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR


def fair_price(
    best_bid: Decimal | None,
    best_ask: Decimal | None,
    token_price: Decimal,
    last_trade_price: Decimal | None,
) -> Decimal:
    if best_bid is not None and best_ask is not None and best_bid > Decimal("0") and best_ask > best_bid:
        return (best_bid + best_ask) / Decimal("2")

    if is_valid_probability(token_price):
        return token_price

    if last_trade_price is not None and is_valid_probability(last_trade_price):
        return last_trade_price

    return Decimal("0.5")


def quote_prices(
    fair: Decimal,
    best_bid: Decimal | None,
    best_ask: Decimal | None,
    tick: Decimal,
    edge_ticks: int,
    min_spread_ticks: int,
) -> tuple[Decimal | None, Decimal | None]:
    fair = clamp_probability(fair, tick)
    edge = tick * Decimal(edge_ticks)
    min_spread = tick * Decimal(min_spread_ticks)

    buy_cap = fair - edge
    sell_floor = fair + edge
    passive_buy = best_bid + tick if best_bid is not None else fair - min_spread
    passive_sell = best_ask - tick if best_ask is not None else fair + min_spread

    buy = floor_to_tick(min(passive_buy, buy_cap), tick)
    sell = ceil_to_tick(max(passive_sell, sell_floor), tick)

    buy_price = buy if valid_buy(buy, best_ask, tick) else None
    sell_price = sell if valid_sell(sell, best_bid, tick) else None

    if buy_price is not None and sell_price is not None and sell_price - buy_price < min_spread:
        return None, None

    return buy_price, sell_price


def valid_buy(price: Decimal, best_ask: Decimal | None, tick: Decimal) -> bool:
    return is_tradeable_price(price, tick) and (best_ask is None or price < best_ask)


def valid_sell(price: Decimal, best_bid: Decimal | None, tick: Decimal) -> bool:
    return is_tradeable_price(price, tick) and (best_bid is None or price > best_bid)


def is_tradeable_price(price: Decimal, tick: Decimal) -> bool:
    return tick <= price <= Decimal("1") - tick


def is_valid_probability(price: Decimal) -> bool:
    return Decimal("0") < price < Decimal("1")


def clamp_probability(price: Decimal, tick: Decimal) -> Decimal:
    return max(tick, min(Decimal("1") - tick, price))


def floor_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    return (price / tick).to_integral_value(rounding=ROUND_FLOOR) * tick


def ceil_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    return (price / tick).to_integral_value(rounding=ROUND_CEILING) * tick
