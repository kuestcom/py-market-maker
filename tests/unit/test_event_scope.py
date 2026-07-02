import json

import pytest

from py_market_maker.event_scope import (
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
                    {"condition_id": "0x02"},
                    {"conditionId": "0x03"},
                    {"condition_id": ""},
                    {},
                ],
            },
        ]

    assert condition_ids_from_site_config("target-event", 5, path, get_json) == {"0x02", "0x03"}


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
