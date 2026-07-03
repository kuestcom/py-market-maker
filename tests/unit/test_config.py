from decimal import Decimal

import pytest

from py_market_maker.config import parse_args


def test_event_slug_is_configurable():
    config = parse_args(["--event-slug", "nba-finals"])

    assert config.event_slug == "nba-finals"
    assert config.max_loss_per_market > 0
    assert config.require_two_sided_live is True


def test_empty_event_slug_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--event-slug", "  "])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_EVENT_SLUG cannot be empty" in captured.err


def test_zero_market_loss_limit_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--max-loss-per-market", "0"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_MAX_LOSS_PER_MARKET must be greater than zero" in captured.err


def test_rust_parity_risk_defaults_are_configurable():
    config = parse_args([
        "--min-price",
        "0.10",
        "--max-price",
        "0.90",
        "--max-collateral-per-market",
        "11",
        "--max-total-collateral",
        "22",
        "--min-free-collateral",
        "3",
        "--max-open-orders-per-token",
        "4",
    ])

    assert config.min_price == Decimal("0.10")
    assert config.max_price == Decimal("0.90")
    assert config.max_collateral_per_market == Decimal("11")
    assert config.max_total_collateral == Decimal("22")
    assert config.min_free_collateral == Decimal("3")
    assert config.max_open_orders_per_token == 4


def test_invalid_configured_price_range_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--min-price", "0", "--max-price", "0.95"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_MIN_PRICE must be between 0 and 1" in captured.err

    with pytest.raises(SystemExit):
        parse_args(["--min-price", "0.95", "--max-price", "0.95"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_MIN_PRICE must be less than MARKET_MAKER_MAX_PRICE" in captured.err


def test_invalid_collateral_and_open_order_limits_are_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--max-collateral-per-market", "0"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_MAX_COLLATERAL_PER_MARKET must be greater than zero" in captured.err

    with pytest.raises(SystemExit):
        parse_args(["--max-total-collateral", "0"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_MAX_TOTAL_COLLATERAL must be greater than zero" in captured.err

    with pytest.raises(SystemExit):
        parse_args(["--min-free-collateral", "-1"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_MIN_FREE_COLLATERAL cannot be negative" in captured.err

    with pytest.raises(SystemExit):
        parse_args(["--max-open-orders-per-token", "0"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_MAX_OPEN_ORDERS_PER_TOKEN must be greater than zero" in captured.err


def test_zero_token_inventory_limit_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--max-inventory-per-token", "0"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_MAX_INVENTORY_PER_TOKEN must be greater than zero" in captured.err


def test_zero_market_inventory_limit_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--max-inventory-per-market", "0"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_MAX_INVENTORY_PER_MARKET must be greater than zero" in captured.err


def test_zero_max_book_spread_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--max-book-spread-ticks", "0"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_MAX_BOOK_SPREAD_TICKS must be greater than zero" in captured.err


def test_zero_pre_post_move_limit_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--max-pre-post-move-ticks", "0"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_MAX_PRE_POST_MOVE_TICKS must be greater than zero" in captured.err


def test_negative_top_depth_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--min-top-depth", "-1"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_MIN_TOP_DEPTH cannot be negative" in captured.err


def test_non_finite_top_depth_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--min-top-depth", "NaN"])

    captured = capsys.readouterr()
    assert "NaN must be a finite decimal" in captured.err


def test_invalid_band_margins_are_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args([
            "--band-min-margin-ticks",
            "4",
            "--band-avg-margin-ticks",
            "3",
            "--band-max-margin-ticks",
            "5",
        ])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_BAND_*_MARGIN_TICKS" in captured.err


def test_zero_band_margin_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--band-min-margin-ticks", "0"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_BAND_*_MARGIN_TICKS must be greater than zero" in captured.err


def test_invalid_band_sizes_are_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--band-min-size", "10", "--band-avg-size", "5", "--band-max-size", "10"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_BAND_*_SIZE" in captured.err


def test_cancel_all_requires_live(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--cancel-all"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_CANCEL_ALL and MARKET_MAKER_CANCEL_ALL_ON_EXIT require --live" in captured.err


def test_cancel_all_on_exit_requires_live(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--cancel-all-on-exit"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_CANCEL_ALL and MARKET_MAKER_CANCEL_ALL_ON_EXIT require --live" in captured.err


def test_cancel_on_risk_breach_requires_live(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--cancel-on-risk-breach"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_CANCEL_ON_RISK_BREACH requires --live" in captured.err


def test_pause_on_risk_breach_requires_live(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--pause-on-risk-breach"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_PAUSE_ON_RISK_BREACH requires --live" in captured.err


def test_clear_pause_skips_trading_validation():
    config = parse_args(["--clear-pause", "--live", "--order-size", "0"])

    assert config.clear_pause is True
    assert config.live is True
    assert config.order_size == 0


def test_clear_pause_rejects_cancel_all_actions(capsys):
    with pytest.raises(SystemExit):
        parse_args([*_live_args(), "--clear-pause", "--cancel-all"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_CLEAR_PAUSE cannot be combined with cancel-all actions" in captured.err

    with pytest.raises(SystemExit):
        parse_args([*_live_args(), "--clear-pause", "--cancel-all-on-exit"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_CLEAR_PAUSE cannot be combined with cancel-all actions" in captured.err


def test_empty_pause_path_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--pause-path", ""])

    captured = capsys.readouterr()
    assert "path cannot be empty" in captured.err


def test_cancel_modes_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit):
        parse_args([*_live_args(), "--cancel-all", "--cancel-all-on-exit"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_CANCEL_ALL and MARKET_MAKER_CANCEL_ALL_ON_EXIT are mutually exclusive" in captured.err


def test_zero_max_data_age_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--max-data-age-secs", "0"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_MAX_DATA_AGE_SECS must be greater than zero" in captured.err


def test_zero_fill_max_records_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--fill-max-records", "0"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_FILL_MAX_RECORDS must be greater than zero" in captured.err


def test_negative_position_reconcile_tolerance_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--position-reconcile-tolerance", "-0.000001"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_POSITION_RECONCILE_TOLERANCE cannot be negative" in captured.err


def test_clear_pause_skips_fill_max_records_validation():
    config = parse_args(["--clear-pause", "--fill-max-records", "0"])

    assert config.clear_pause is True
    assert config.fill_max_records == 0


def _live_args():
    return [
        "--live",
        "--private-key",
        "0xabc",
        "--deposit-wallet",
        "0xdef",
        "--chain-id",
        "137",
    ]
