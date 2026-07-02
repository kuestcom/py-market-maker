import pytest

from py_market_maker.config import parse_args


def test_event_slug_is_configurable():
    config = parse_args(["--event-slug", "nba-finals"])

    assert config.event_slug == "nba-finals"
    assert config.max_loss_per_market > 0


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
