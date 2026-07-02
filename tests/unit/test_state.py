import json

import pytest
from decimal import Decimal

from py_market_maker.state import FillLedger, FillRecord, PauseState, SeenMarkets


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


def test_pause_state_round_trips_and_clears(tmp_path):
    path = tmp_path / "state" / "paused.json"

    saved = PauseState.save_reason(path, "risk breach test")
    loaded = PauseState.load(path)

    assert loaded == saved
    assert loaded.reason == "risk breach test"
    assert PauseState.clear(path) is True
    assert PauseState.clear(path) is False
    assert PauseState.load(path) is None


def test_fill_ledger_round_trips_and_filters_by_token(tmp_path):
    path = tmp_path / "state" / "fills.json"
    expected = FillRecord(
        id="trade-a",
        token_id="1",
        market="market-a",
        side="BUY",
        size=Decimal("5"),
        price=Decimal("0.40"),
        status="Matched",
        matched_at_unix_secs=2,
    )
    ledger = FillLedger()

    assert ledger.upsert(expected)
    assert ledger.upsert(
        FillRecord(
            id="trade-b",
            token_id="2",
            market="market-a",
            side="BUY",
            size=Decimal("1"),
            price=Decimal("0.50"),
            status="Matched",
            matched_at_unix_secs=1,
        )
    )
    ledger.save(path)

    loaded = FillLedger.load(path)
    token_records = loaded.records_for_token("1")

    assert token_records == [expected]
    assert loaded.latest_matched_at_unix_secs("1") == 2
    assert loaded.latest_matched_at_unix_secs("missing") is None


def test_fill_ledger_prunes_oldest_records():
    ledger = FillLedger()
    for record_id, matched_at_unix_secs in [("trade-a", 1), ("trade-b", 3), ("trade-c", 2)]:
        assert ledger.upsert(
            FillRecord(
                id=record_id,
                token_id="1",
                market="market-a",
                side="BUY",
                size=Decimal("1"),
                price=Decimal("0.50"),
                status="Matched",
                matched_at_unix_secs=matched_at_unix_secs,
            )
        )

    assert ledger.prune_to_max_records(2)

    assert set(ledger.trades) == {"trade-b", "trade-c"}
    assert not ledger.prune_to_max_records(2)
