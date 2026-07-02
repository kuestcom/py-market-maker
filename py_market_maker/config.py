from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Sequence

POLYGON = 137
AMOY = 80002


class DiscoveryMode(str, Enum):
    AUTO = "auto"
    SAMPLING = "sampling"
    SITE = "site"


class QuoteSides(str, Enum):
    BUY = "buy"
    SELL = "sell"
    BOTH = "both"

    def includes_buy(self) -> bool:
        return self in (QuoteSides.BUY, QuoteSides.BOTH)

    def includes_sell(self) -> bool:
        return self in (QuoteSides.SELL, QuoteSides.BOTH)


@dataclass(frozen=True)
class Config:
    clob_host: str
    live: bool
    private_key: str | None
    deposit_wallet: str | None
    chain_id: int | None
    discovery: DiscoveryMode
    max_markets: int
    max_pages: int
    order_size: Decimal
    edge_ticks: int
    min_spread_ticks: int
    max_loss_per_market: Decimal
    max_book_spread_ticks: int
    min_top_depth: Decimal
    quote_sides: QuoteSides
    allow_single_sided: bool
    respect_reward_min_size: bool
    cancel_before_quote: bool
    post_only: bool
    require_two_sided_live: bool
    discover_only: bool
    cycles: int
    refresh_secs: int
    state_path: Path
    event_slug: str | None = None


def parse_args(argv: Sequence[str] | None = None) -> Config:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = Config(
        clob_host=args.clob_host,
        live=args.live,
        private_key=args.private_key,
        deposit_wallet=args.deposit_wallet,
        chain_id=args.chain_id,
        discovery=DiscoveryMode(args.discovery),
        event_slug=args.event_slug,
        max_markets=args.max_markets,
        max_pages=args.max_pages,
        order_size=args.order_size,
        edge_ticks=args.edge_ticks,
        min_spread_ticks=args.min_spread_ticks,
        max_loss_per_market=args.max_loss_per_market,
        max_book_spread_ticks=args.max_book_spread_ticks,
        min_top_depth=args.min_top_depth,
        quote_sides=QuoteSides(args.quote_sides),
        allow_single_sided=args.allow_single_sided,
        respect_reward_min_size=args.respect_reward_min_size,
        cancel_before_quote=args.cancel_before_quote,
        post_only=args.post_only,
        require_two_sided_live=args.require_two_sided_live,
        discover_only=args.discover_only,
        cycles=args.cycles,
        refresh_secs=args.refresh_secs,
        state_path=args.state_path,
    )
    validate_config(config, parser)
    return config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="py-market-maker",
        description="Simple Python market maker example for Kuest based prediction markets",
    )
    parser.add_argument(
        "--clob-host",
        default=_env_str("KUEST_CLOB_HOST", "https://clob.kuest.com"),
    )
    parser.add_argument(
        "--live",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("MARKET_MAKER_LIVE", False),
    )
    parser.add_argument("--private-key", default=_env_optional_str("KUEST_PRIVATE_KEY"))
    parser.add_argument(
        "--deposit-wallet",
        default=_env_optional_str("KUEST_DEPOSIT_WALLET"),
    )
    parser.add_argument("--chain-id", type=int, default=_env_optional_int("KUEST_CHAIN_ID"))
    parser.add_argument(
        "--discovery",
        choices=[mode.value for mode in DiscoveryMode],
        default=_env_choice(
            "MARKET_MAKER_DISCOVERY",
            DiscoveryMode.AUTO.value,
            [mode.value for mode in DiscoveryMode],
        ),
    )
    parser.add_argument("--event-slug", default=_env_optional_str("MARKET_MAKER_EVENT_SLUG"))
    parser.add_argument(
        "--max-markets",
        type=int,
        default=_env_int("MARKET_MAKER_MAX_MARKETS", 3),
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=_env_int("MARKET_MAKER_MAX_PAGES", 5),
    )
    parser.add_argument(
        "--order-size",
        type=_parse_decimal,
        default=_env_decimal("MARKET_MAKER_ORDER_SIZE", Decimal("5")),
    )
    parser.add_argument(
        "--edge-ticks",
        type=int,
        default=_env_int("MARKET_MAKER_EDGE_TICKS", 1),
    )
    parser.add_argument(
        "--min-spread-ticks",
        type=int,
        default=_env_int("MARKET_MAKER_MIN_SPREAD_TICKS", 2),
    )
    parser.add_argument(
        "--max-loss-per-market",
        type=_parse_decimal,
        default=_env_decimal("MARKET_MAKER_MAX_LOSS_PER_MARKET", Decimal("25")),
    )
    parser.add_argument(
        "--max-book-spread-ticks",
        type=int,
        default=_env_int("MARKET_MAKER_MAX_BOOK_SPREAD_TICKS", 20),
    )
    parser.add_argument(
        "--min-top-depth",
        type=_parse_decimal,
        default=_env_decimal("MARKET_MAKER_MIN_TOP_DEPTH", Decimal("5")),
    )
    parser.add_argument(
        "--quote-sides",
        choices=[side.value for side in QuoteSides],
        default=_env_choice(
            "MARKET_MAKER_QUOTE_SIDES",
            QuoteSides.BUY.value,
            [side.value for side in QuoteSides],
        ),
    )
    parser.add_argument(
        "--allow-single-sided",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("MARKET_MAKER_ALLOW_SINGLE_SIDED", True),
    )
    parser.add_argument(
        "--respect-reward-min-size",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("MARKET_MAKER_RESPECT_REWARD_MIN_SIZE", False),
    )
    parser.add_argument(
        "--cancel-before-quote",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("MARKET_MAKER_CANCEL_BEFORE_QUOTE", True),
    )
    parser.add_argument(
        "--post-only",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("MARKET_MAKER_POST_ONLY", True),
    )
    parser.add_argument(
        "--require-two-sided-live",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("MARKET_MAKER_REQUIRE_TWO_SIDED_LIVE", True),
    )
    parser.add_argument(
        "--discover-only",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("MARKET_MAKER_DISCOVER_ONLY", False),
    )
    parser.add_argument("--cycles", type=int, default=_env_int("MARKET_MAKER_CYCLES", 1))
    parser.add_argument(
        "--refresh-secs",
        type=int,
        default=_env_int("MARKET_MAKER_REFRESH_SECS", 30),
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=Path(_env_str("MARKET_MAKER_STATE_PATH", "state/seen-markets.json")),
    )
    return parser


def validate_config(config: Config, parser: argparse.ArgumentParser) -> None:
    if config.max_markets <= 0:
        parser.error("MARKET_MAKER_MAX_MARKETS must be greater than zero")
    if config.max_pages <= 0:
        parser.error("MARKET_MAKER_MAX_PAGES must be greater than zero")
    if config.order_size <= Decimal("0"):
        parser.error("MARKET_MAKER_ORDER_SIZE must be greater than zero")
    if config.edge_ticks <= 0:
        parser.error("MARKET_MAKER_EDGE_TICKS must be greater than zero")
    if config.min_spread_ticks <= 0:
        parser.error("MARKET_MAKER_MIN_SPREAD_TICKS must be greater than zero")
    if config.max_loss_per_market <= Decimal("0"):
        parser.error("MARKET_MAKER_MAX_LOSS_PER_MARKET must be greater than zero")
    if config.max_book_spread_ticks <= 0:
        parser.error("MARKET_MAKER_MAX_BOOK_SPREAD_TICKS must be greater than zero")
    if config.min_top_depth < Decimal("0"):
        parser.error("MARKET_MAKER_MIN_TOP_DEPTH cannot be negative")
    if config.event_slug is not None and not config.event_slug.strip():
        parser.error("MARKET_MAKER_EVENT_SLUG cannot be empty")
    if config.cycles <= 0:
        parser.error("MARKET_MAKER_CYCLES must be greater than zero")
    if config.live:
        if not config.private_key:
            parser.error("--live requires KUEST_PRIVATE_KEY or --private-key")
        if not config.deposit_wallet:
            parser.error("--live requires KUEST_DEPOSIT_WALLET or --deposit-wallet")
        if config.chain_id is None:
            parser.error("--live requires KUEST_CHAIN_ID or --chain-id; use 137 for Polygon or 80002 for Amoy")
        if config.chain_id not in (POLYGON, AMOY):
            parser.error(f"unsupported chain id {config.chain_id}; SDK supports {POLYGON} and {AMOY}")


def _env_optional_str(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_str(name: str, default: str) -> str:
    return _env_optional_str(name) or default


def _env_optional_int(name: str) -> int | None:
    value = _env_optional_str(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error


def _env_int(name: str, default: int) -> int:
    value = _env_optional_int(name)
    return default if value is None else value


def _env_decimal(name: str, default: Decimal) -> Decimal:
    value = _env_optional_str(name)
    if value is None:
        return default
    return _parse_decimal(value)


def _env_bool(name: str, default: bool) -> bool:
    value = _env_optional_str(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in ("1", "true", "yes", "y", "on"):
        return True
    if normalized in ("0", "false", "no", "n", "off"):
        return False
    raise ValueError(f"{name} must be true or false")


def _env_choice(name: str, default: str, choices: list[str]) -> str:
    value = _env_optional_str(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(choices)}")
    return normalized


def _parse_decimal(value: str) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError(f"{value} is not a decimal") from error
