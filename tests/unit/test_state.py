import json

import pytest

from py_market_maker.state import SeenMarkets


def test_missing_state_file_loads_empty(tmp_path):
    seen = SeenMarkets.load(tmp_path / "state" / "seen-markets.json")

    assert seen.markets == set()


def test_seen_markets_save_and_load_round_trip(tmp_path):
    path = tmp_path / "state" / "seen-markets.json"
    seen = SeenMarkets({"condition-b", "condition-a"})

    seen.save(path)

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "markets": ["condition-a", "condition-b"]
    }
    assert SeenMarkets.load(path).markets == {"condition-a", "condition-b"}


def test_seen_markets_rejects_invalid_shape(tmp_path):
    path = tmp_path / "state" / "seen-markets.json"
    path.parent.mkdir()
    path.write_text('{"markets": "condition-a"}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="markets must be a list of strings"):
        SeenMarkets.load(path)
