from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


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
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps({"markets": sorted(self.markets)}, indent=2)
        path.write_text(f"{raw}\n", encoding="utf-8")

    def mark_new(self, market_key: str) -> bool:
        before = len(self.markets)
        self.markets.add(market_key)
        return len(self.markets) != before
