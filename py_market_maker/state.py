from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


def write_json_pretty(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, indent=2)
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
