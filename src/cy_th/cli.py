# cy_th/cli.py

"""`cyth` command-line dispatcher (`cyth <subcommand> --kwargs`)."""

# === Imports ===

from __future__ import annotations
import argparse
import shutil
import sys
from pathlib import Path
from typing import Sequence

from cy_th.materialize.pipeline import materialize
from cy_th.materialize.publish import IntegrityError


# === Entrypoint ===

def main(argv: Sequence[str] | None = None) -> None:
    """Parse argv and dispatch.

    Raises `SystemExit` with a process exit code.
    """

    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    raise SystemExit(args.handler(args))


# === Parser ===

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cyth",
        description="Cy-TH CLI dispatcher",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Materialize subcommand
    mat = sub.add_parser(
        "materialize",
        help="materialize projected CSVs into a Parquet set",
    )
    mat.add_argument(
        "--in",
        dest="inputs",
        action="append",
        required=True,
        metavar="CSV",
        help="projected prime-transaction CSV (repeatable; N >= 1)",
    )
    mat.add_argument(
        "--out",
        default=".data",
        metavar="DIR",
        help="data root for sets/CURRENT/staging (default: .data/)",
    )
    mat.add_argument(
        "--allow-rejects",
        action="store_true",
        help="publish CURRENT even when reject-rows exist (degraded set)",
    )
    mat.add_argument(
        "--keep-staging",
        action="store_true",
        help="retain .staging/<run-id>.duckdb after the run",
    )
    mat.set_defaults(handler=_cmd_materialize)

    # Test-cache clear subcommand
    clear = sub.add_parser(
        "clear-test-cache",
        help="delete tests/.cache/ (USASpending test extracts)",
    )
    clear.set_defaults(handler=_cmd_clear_test_cache)

    # Ingest subcommand
    # TODO: Not yet implemented, for now this is just reserved
    ingest = sub.add_parser(
        "ingest",
        help="not yet implemented!",
    )
    ingest.set_defaults(handler=_cmd_ingest)

    return parser


# === Commands ===

def _cmd_materialize(args: argparse.Namespace) -> int:
    """Run materialize and print a verbose summary."""

    inputs = [Path(p) for p in args.inputs]
    try:
        result = materialize(
            inputs,
            out=args.out,
            allow_rejects=args.allow_rejects,
            keep_staging=args.keep_staging,
        )
    except IntegrityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    v = result.validate
    refs = result.refs
    pub = result.publish

    print("materialize complete")
    print(f"  run_id:          {result.run_id}")
    print(f"  out:             {result.data_root}")
    print(f"  set:             {pub.set_path}")
    print(f"  inputs:          {result.load.input_files}")
    print(f"  rows_in:         {v.rows_in}")
    print(f"  rows_valid:      {v.rows_valid}")
    print(f"  collapsed_dupes: {v.rows_collapsed_dupes}")
    print(f"  rejects:         {pub.reject_count}")
    if v.rows_rejected_invalid or v.rows_rejected_collision:
        print(f"    invalid:       {v.rows_rejected_invalid}")
        print(f"    collisions:    {v.rows_rejected_collision}")
    print(f"  transactions:    {result.transactions}")
    print(f"  awards:          {result.awards}")
    print(
        "  refs:            ["
        f"agencies={refs.agencies} offices={refs.offices} "
        f"recipients={refs.recipients} classifications={refs.classifications} "
        f"idvs={refs.idvs} locations={refs.locations}]"
    )
    print(f"  rejects_file:    {pub.wrote_rejects}")
    print(f"  staging_kept:    {result.staging_kept}")
    if pub.published:
        print(f"  CURRENT:         {result.run_id}")
        return 0

    print("  CURRENT:         (not updated; rejects present; pass --allow-rejects)")
    return 2

def _cmd_clear_test_cache(_args: argparse.Namespace) -> int:
    """Delete `tests/.cache/` under the repository root."""

    cache_dir = _repo_root() / "tests" / ".cache"
    if not cache_dir.exists():
        print(f"no test cache at {cache_dir}")
        return 0

    shutil.rmtree(cache_dir)
    print(f"removed {cache_dir}")
    return 0

def _cmd_ingest(_args: argparse.Namespace) -> int:
    print(
        "error: `cyth ingest` is not implemented yet!",
        file=sys.stderr,
    )
    return 1


# === Paths ===

def _repo_root() -> Path:
    """Return the repository root (parent of `src/`)."""

    return Path(__file__).resolve().parents[2]


# === __name__ Handler ===

if __name__ == "__main__":
    main()
