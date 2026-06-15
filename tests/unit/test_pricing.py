from decimal import Decimal

from py_market_maker.pricing import fair_price, quote_prices


def test_quotes_inside_wide_book_without_crossing_fair_edge():
    buy, sell = quote_prices(
        Decimal("0.50"),
        Decimal("0.40"),
        Decimal("0.60"),
        Decimal("0.01"),
        1,
        2,
    )

    assert buy == Decimal("0.41")
    assert sell == Decimal("0.59")


def test_quotes_keep_configured_edge_on_tight_book():
    buy, sell = quote_prices(
        Decimal("0.50"),
        Decimal("0.49"),
        Decimal("0.51"),
        Decimal("0.01"),
        2,
        2,
    )

    assert buy == Decimal("0.48")
    assert sell == Decimal("0.52")


def test_quotes_refuse_prices_outside_tradeable_bounds():
    buy, sell = quote_prices(Decimal("0.99"), None, None, Decimal("0.01"), 1, 2)

    assert buy == Decimal("0.97")
    assert sell is None


def test_midpoint_is_preferred_when_book_is_two_sided():
    fair = fair_price(
        Decimal("0.44"),
        Decimal("0.56"),
        Decimal("0.10"),
        Decimal("0.20"),
    )

    assert fair == Decimal("0.50")
