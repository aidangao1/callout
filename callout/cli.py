"""Command line: python -m callout <command>. Run with --help to list the commands."""

from __future__ import annotations

import argparse
import asyncio
import sys

from .config import ConfigError
from .console.common import out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="callout", description="Voice-command order entry for IBKR futures.")
    p.add_argument("--config", default="config.toml", help="path to config file (default: config.toml)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("app", help="open the Callout window (what start.bat runs)")
    s.add_argument("--sim", action="store_true", help="simulated broker, no TWS needed")

    s = sub.add_parser("run", help="start trading in this console window (no app window)")
    s.add_argument("--sim", action="store_true", help="simulated broker, no TWS needed")
    s.add_argument("--text", action="store_true", help="type commands instead of speaking")
    s.add_argument("--live", action="store_true", help="required (with trading_mode = 'live') for real money")
    s.add_argument("--mute", action="store_true", help="no spoken readback")
    s.add_argument("--ignore-market-hours", action="store_true", help="paper/sim only: skip the hours check")

    s = sub.add_parser("init", help="write a starter config.toml")
    s.add_argument("--force", action="store_true")

    s = sub.add_parser("check", help="connect to the broker, show contracts and positions, then exit")
    s.add_argument("--sim", action="store_true")
    s.add_argument("--live", action="store_true")

    sub.add_parser("devices", help="list microphones")
    sub.add_parser("tts-test", help="speak a test sentence")
    s = sub.add_parser("mic-scan", help="record a moment from every mic and show which one hears you")
    s.add_argument("--all", action="store_true", help="include WDM-KS entries")
    sub.add_parser("mic-test", help="speak commands and see what's recognised; never trades")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "app":
            from .app.window import run_app

            return run_app(args.config, use_sim=args.sim)
        if args.command == "run":
            from .console.trade import run

            return asyncio.run(run(args))

        from .console import tools

        handler = {
            "init": tools.init,
            "check": tools.check,
            "devices": tools.devices,
            "tts-test": tools.tts_test,
            "mic-scan": tools.mic_scan,
            "mic-test": tools.mic_test,
        }[args.command]
        result = handler(args)
        return asyncio.run(result) if asyncio.iscoroutine(result) else result
    except ConfigError as e:
        out(f"Config error: {e}")
        return 2
    except KeyboardInterrupt:
        out("Stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
