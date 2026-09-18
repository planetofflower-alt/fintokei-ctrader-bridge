"""Entry point: python -m ctrader_bridge"""

import asyncio
import sys

from .config import load_config
from .server import CTraderMCPServer


def main() -> None:
    config = load_config()
    if not config.credentials_present:
        print(
            "Warning: cTrader credentials not set. Read tools will fail until "
            "CTRADER_CLIENT_ID / CTRADER_CLIENT_SECRET / CTRADER_ACCESS_TOKEN / "
            "CTRADER_ACCOUNT_ID are configured.",
            file=sys.stderr,
        )
    server = CTraderMCPServer(config)
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
