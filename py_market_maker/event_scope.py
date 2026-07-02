from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import urlopen

SITE_CONFIG_PATH = Path(".sdk/site-config.json")
SITE_EVENTS_LIMIT = 100

JsonGetter = Callable[[str], Any]
CONDITION_ID_KEYS = ("condition_id", "conditionId", "conditionID", "c")
TOKEN_ID_KEYS = ("token_id", "tokenId", "asset_id", "assetId", "t")
CLOB_TOKEN_LIST_KEYS = ("clob_token_ids", "clobTokenIds", "outcome_assets", "outcomeAssets")
NESTED_MARKET_KEYS = ("markets", "outcomes", "tokens")


def condition_ids_from_site_config(
    event_slug: str,
    max_pages: int,
    config_path: Path = SITE_CONFIG_PATH,
    get_json: JsonGetter | None = None,
) -> set[str]:
    site_url = site_url_from_config(config_path)
    events = fetch_site_events(site_url, max_pages, get_json)

    for event in events:
        if event.get("slug") != event_slug:
            continue
        markets = event.get("markets")
        if not isinstance(markets, list):
            return set()
        return {
            condition_id
            for market in markets
            if isinstance(market, dict)
            if is_clob_market_entry(market)
            for condition_id in [condition_id_from_market(market)]
            if condition_id
        }

    return set()


def site_url_from_config(path: Path = SITE_CONFIG_PATH) -> str:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RuntimeError(f"failed to read {path}") from error

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"failed to parse {path}") from error

    if not isinstance(parsed, dict):
        raise RuntimeError(f"failed to parse {path}: expected a JSON object")

    site_url = parsed.get("site_url")
    if not isinstance(site_url, str):
        raise RuntimeError(f"{path}.site_url must be a string")

    site_url = site_url.strip()
    if not site_url:
        raise RuntimeError(f"{path}.site_url must not be empty")
    if site_url.startswith(("http://", "https://")):
        return site_url
    return f"https://{site_url}"


def fetch_site_events(
    site_url: str,
    max_pages: int,
    get_json: JsonGetter | None = None,
) -> list[dict[str, Any]]:
    get_json = get_json or _get_json
    events: list[dict[str, Any]] = []

    for page in range(max(max_pages, 1)):
        url = _site_events_url(site_url, page)
        page_events = get_json(url)
        if not isinstance(page_events, list):
            raise RuntimeError("site-scoped market discovery expected /api/events to return an array")

        events.extend(event for event in page_events if isinstance(event, dict))
        if len(page_events) < SITE_EVENTS_LIMIT:
            break

    return events


def _site_events_url(site_url: str, page: int) -> str:
    query = urlencode(
        {
            "status": "active",
            "includeBookmarkState": "false",
            "limit": str(SITE_EVENTS_LIMIT),
            "offset": str(page * SITE_EVENTS_LIMIT),
        }
    )
    base = site_url if site_url.endswith("/") else f"{site_url}/"
    return f"{urljoin(base, 'api/events')}?{query}"


def _get_json(url: str) -> Any:
    try:
        with urlopen(url, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"site events request failed for {url}: HTTP {error.code}") from error
    except URLError as error:
        raise RuntimeError(f"failed to fetch site events from {url}: {error.reason}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"failed to parse site events from {url}") from error


def condition_id_from_market(market: dict[str, Any]) -> str | None:
    for key in CONDITION_ID_KEYS:
        value = market.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return None


def is_clob_market_entry(market: dict[str, Any]) -> bool:
    if condition_id_from_market(market) is None:
        return False
    if _bool_field(market, "enable_order_book"):
        return True
    return _has_token_evidence(market)


def _has_token_evidence(value: Any) -> bool:
    if isinstance(value, dict):
        if any(_token_id(value.get(key)) for key in TOKEN_ID_KEYS):
            return True
        for key in CLOB_TOKEN_LIST_KEYS:
            if _has_token_evidence(value.get(key)):
                return True
        for key in NESTED_MARKET_KEYS:
            if _has_token_evidence(value.get(key)):
                return True
        return False

    if isinstance(value, list):
        return any(_has_token_evidence(item) for item in value)

    return _token_id(value) is not None


def _token_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool_field(source: dict[str, Any], name: str) -> bool:
    value = source.get(name)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(value)
