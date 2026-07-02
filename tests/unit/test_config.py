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


def test_zero_max_book_spread_is_rejected(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--max-book-spread-ticks", "0"])

    captured = capsys.readouterr()
    assert "MARKET_MAKER_MAX_BOOK_SPREAD_TICKS must be greater than zero" in captured.err


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
