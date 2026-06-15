from __future__ import annotations

from dotenv import load_dotenv

from .config import parse_args


def main() -> int:
    load_dotenv()
    config = parse_args()
    from .bot import run

    run(config)
    return 0
