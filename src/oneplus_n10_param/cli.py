"""Command-line interface for offline-only param inspection and generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .core import (
    ParamValidationError,
    atomic_write,
    build_trigger,
    ensure_distinct_paths,
    inspect_param,
    read_param_file,
)


def _serial(value: str) -> int:
    try:
        serial = int(value, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "SoC serial must be decimal or 0x-prefixed hexadecimal"
        ) from error
    if not 0 <= serial <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("SoC serial must fit in 32 unsigned bits")
    return serial


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", type=Path, help="offline 1 MiB param backup")
    parser.add_argument(
        "--soc-serial",
        required=True,
        type=_serial,
        help="device SoC serial (decimal or 0x-prefixed hex); never stored in output",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")


def _add_patch(parser: argparse.ArgumentParser) -> None:
    _add_common(parser)
    parser.add_argument(
        "--output",
        type=Path,
        help="atomically write this offline image; omit for a verified dry-run",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="explicitly permit replacing an existing output (never the input)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oneplus-n10-param",
        description=(
            "Strict offline inspector and trigger-image generator for a BE2025 "
            "1 MiB param backup. It never talks to a phone or block device."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subcommands.add_parser(
        "inspect",
        help="validate and inspect only (default safe operation)",
    )
    _add_common(inspect_parser)

    global_parser = subcommands.add_parser(
        "patch-global",
        help="build the Global 20886 RPMB trigger; dry-run unless --output is supplied",
    )
    _add_patch(global_parser)

    rollback_parser = subcommands.add_parser(
        "rollback-trigger",
        help="build the Metro rollback RPMB trigger; dry-run unless --output is supplied",
    )
    _add_patch(rollback_parser)
    return parser


def _print_report(report: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    for key, value in report.items():
        if key == "records":
            for record in value:  # type: ignore[union-attr]
                print(
                    "record="
                    f"{record['offset']} state={record['state']} "
                    f"swid={record['swid']} proc={record['proc']} "
                    f"counter={record['counter']} hv={record['header_version']} "
                    f"cv={record['crypto_version']}"
                )
        else:
            print(f"{key}={value}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        data = read_param_file(args.input)
        if args.command == "inspect":
            inspection = inspect_param(data, args.soc_serial)
            _print_report(inspection.public_dict(), args.json)
            return 0

        if args.overwrite and args.output is None:
            raise ParamValidationError("--overwrite requires --output")

        kind = "global" if args.command == "patch-global" else "rollback"
        result = build_trigger(data, args.soc_serial, kind)
        wrote_output = args.output is not None
        if wrote_output:
            ensure_distinct_paths(args.input, args.output)
            atomic_write(args.output, result.data, overwrite=args.overwrite)
        _print_report(
            result.public_dict(wrote_output=wrote_output, output=args.output),
            args.json,
        )
        return 0
    except (ParamValidationError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
