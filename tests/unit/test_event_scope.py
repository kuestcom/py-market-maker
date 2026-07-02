import json

import pytest

from py_market_maker.event_scope import (
    condition_id_from_market,
    condition_ids_from_site_config,
    fetch_site_events,
    site_url_from_config,
)


def test_site_url_from_config_requires_local_site_config(tmp_path):
    with pytest.raises(RuntimeError, match="failed to read"):
        site_url_from_config(tmp_path / ".sdk" / "site-config.json")


def test_site_url_from_config_normalizes_missing_scheme(tmp_path):
    path = tmp_path / ".sdk" / "site-config.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"site_url": "example.com"}), encoding="utf-8")

    assert site_url_from_config(path) == "https://example.com"


def test_condition_ids_from_site_config_uses_matching_event(tmp_path):
    path = tmp_path / ".sdk" / "site-config.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"site_url": "https://kuest.example"}), encoding="utf-8")

    def get_json(url):
        assert url.startswith("https://kuest.example/api/events?")
        return [
            {"slug": "other-event", "markets": [{"condition_id": "0x01"}]},
            {
                "slug": "target-event",
                "markets": [
                    {"condition_id": "0x02", "outcomes": [{"token_id": "100"}]},
                    {"conditionId": "0x03", "clob_token_ids": ["101"]},
                    {"condition_id": ""},
                    {},
                ],
            },
        ]

    assert condition_ids_from_site_config("target-event", 5, path, get_json) == {"0x02", "0x03"}


def test_condition_ids_from_site_config_ignores_non_clob_event_markets(tmp_path):
    path = tmp_path / ".sdk" / "site-config.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"site_url": "https://kuest.example"}), encoding="utf-8")

    def get_json(url):
        return [
            {
                "slug": "target-event",
                "markets": [
                    {"condition_id": "0xlegacy"},
                    {"condition_id": "0xclob-a", "outcomes": [{"token_id": "100"}]},
                    {"condition_id": "0xclob-b", "enable_order_book": True},
                ],
            },
        ]

    assert condition_ids_from_site_config("target-event", 1, path, get_json) == {
        "0xclob-a",
        "0xclob-b",
    }


def test_condition_id_from_market_supports_all_known_keys():
    assert condition_id_from_market({"condition_id": "0x01"}) == "0x01"
    assert condition_id_from_market({"conditionId": "0x02"}) == "0x02"
    assert condition_id_from_market({"conditionID": "0x03"}) == "0x03"
    assert condition_id_from_market({"c": "0x04"}) == "0x04"


def test_fetch_site_events_paginates_until_short_page():
    first_page = [{"slug": f"event-{index}"} for index in range(100)]
    second_page = [{"slug": "last-event"}]
    calls = []

    def get_json(url):
        calls.append(url)
        return first_page if len(calls) == 1 else second_page

    events = fetch_site_events("https://kuest.example", 5, get_json)

    assert len(events) == 101
    assert events[-1] == {"slug": "last-event"}
    assert "offset=0" in calls[0]
    assert "offset=100" in calls[1]
