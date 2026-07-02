from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def write_json_pretty(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, indent=2, default=_json_default)
    path.write_text(f"{raw}\n", encoding="utf-8")


@dataclass
class SeenMarkets:
    markets: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> "SeenMarkets":
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls()
        except OSError as error:
            raise RuntimeError(f"failed to read {path}") from error

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"failed to parse {path}") from error

        markets = parsed.get("markets") if isinstance(parsed, dict) else None
        if not isinstance(markets, list) or not all(isinstance(item, str) for item in markets):
            raise RuntimeError(f"failed to parse {path}: markets must be a list of strings")

        return cls(set(markets))

    def save(self, path: Path) -> None:
        write_json_pretty(path, {"markets": sorted(self.markets)})

    def mark_new(self, market_key: str) -> bool:
        before = len(self.markets)
        self.markets.add(market_key)
        return len(self.markets) != before


@dataclass(frozen=True)
class PauseState:
    reason: str
    created_at_unix_secs: int

    @classmethod
    def load(cls, path: Path) -> "PauseState | None":
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as error:
            raise RuntimeError(f"failed to read {path}") from error

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"failed to parse {path}") from error

        if not isinstance(parsed, dict):
            raise RuntimeError(f"failed to parse {path}: pause state must be an object")
        reason = parsed.get("reason")
        created_at = parsed.get("created_at_unix_secs")
        if not isinstance(reason, str) or not isinstance(created_at, int):
            raise RuntimeError(
                f"failed to parse {path}: reason must be a string and created_at_unix_secs must be an integer"
            )
        return cls(reason=reason, created_at_unix_secs=created_at)

    @classmethod
    def save_reason(cls, path: Path, reason: str) -> "PauseState":
        pause = cls(reason=reason, created_at_unix_secs=int(time.time()))
        pause.save(path)
        return pause

    @staticmethod
    def clear(path: Path) -> bool:
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except OSError as error:
            raise RuntimeError(f"failed to remove {path}") from error
        return True

    def save(self, path: Path) -> None:
        write_json_pretty(
            path,
            {
                "reason": self.reason,
                "created_at_unix_secs": self.created_at_unix_secs,
            },
        )


@dataclass(frozen=True)
class FillRecord:
    id: str
    token_id: str
    market: str
    side: str
    size: Decimal
    price: Decimal
    status: str
    matched_at_unix_secs: int

    @classmethod
    def from_json(cls, value: object, path: Path) -> "FillRecord":
        if not isinstance(value, dict):
            raise RuntimeError(f"failed to parse {path}: fill record must be an object")
        try:
            record_id = _required_str(value, "id")
            return cls(
                id=record_id,
                token_id=_required_str(value, "token_id"),
                market=_required_str(value, "market"),
                side=_required_str(value, "side"),
                size=_decimal(value.get("size")),
                price=_decimal(value.get("price")),
                status=_required_str(value, "status"),
                matched_at_unix_secs=_required_int(value, "matched_at_unix_secs"),
            )
        except (InvalidOperation, TypeError, ValueError) as error:
            raise RuntimeError(f"failed to parse {path}: invalid fill record") from error

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "token_id": self.token_id,
            "market": self.market,
            "side": self.side,
            "size": self.size,
            "price": self.price,
            "status": self.status,
            "matched_at_unix_secs": self.matched_at_unix_secs,
        }


@dataclass
class FillLedger:
    trades: dict[str, FillRecord] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "FillLedger":
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls()
        except OSError as error:
            raise RuntimeError(f"failed to read {path}") from error

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"failed to parse {path}") from error

        trades = parsed.get("trades") if isinstance(parsed, dict) else None
        if not isinstance(trades, dict):
            raise RuntimeError(f"failed to parse {path}: trades must be an object")
        records = {}
        for record_id, raw_record in trades.items():
            record = FillRecord.from_json(raw_record, path)
            record_key = str(record_id)
            if record_key != record.id:
                raise RuntimeError(f"failed to parse {path}: fill record key must match id")
            records[record_key] = record
        return cls(records)

    def save(self, path: Path) -> None:
        write_json_pretty(
            path,
            {
                "trades": {
                    record_id: record.to_json()
                    for record_id, record in sorted(self.trades.items())
                }
            },
        )

    def upsert(self, record: FillRecord) -> bool:
        changed = self.trades.get(record.id) != record
        if changed:
            self.trades[record.id] = record
        return changed

    def records_for_token(self, token_id: str) -> list[FillRecord]:
        records = [
            record
            for record in self.trades.values()
            if record.token_id == token_id
        ]
        records.sort(key=lambda record: (record.matched_at_unix_secs, record.id))
        return records

    def latest_matched_at_unix_secs(self, token_id: str) -> int | None:
        return max(
            (
                record.matched_at_unix_secs
                for record in self.trades.values()
                if record.token_id == token_id
            ),
            default=None,
        )

    def prune_to_max_records(self, max_records: int) -> bool:
        if len(self.trades) <= max_records:
            return False

        records = sorted(
            (record.matched_at_unix_secs, record.id)
            for record in self.trades.values()
        )
        for _, record_id in records[: len(self.trades) - max_records]:
            self.trades.pop(record_id, None)
        return True


def _required_str(value: dict[str, object], key: str) -> str:
    field_value = value.get(key)
    if not isinstance(field_value, str):
        raise TypeError(key)
    return field_value


def _required_int(value: dict[str, object], key: str) -> int:
    field_value = value.get(key)
    if type(field_value) is not int:
        raise TypeError(key)
    return field_value


def _decimal(value: object) -> Decimal:
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError("decimal must be finite")
    return parsed
