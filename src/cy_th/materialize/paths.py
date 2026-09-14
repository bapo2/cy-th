# cy_th/materialize/paths.py

"""On-disk layout helpers for materialization sets, CURRENT, and staging."""

# === Imports ===

from __future__ import annotations
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Final


# === Constants ===

DEFAULT_DATA_ROOT: Final[Path] = Path(".data")
"""Default data root (cwd-relative); overridden with `--out`."""

CURRENT_NAME: Final[str] = "CURRENT"
"""Filename of the published run-ID pointer (plain text)."""

SETS_DIRNAME: Final[str] = "sets"
STAGING_DIRNAME: Final[str] = ".staging"
REFS_DIRNAME: Final[str] = "refs"

_RUN_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{8}T\d{6}Z_[0-9a-f]{6}$"
)
"""Regex for run-ID form (`YYYYMMDDTHHMMSSZ_<6 hex chars>`)."""


# === Run IDs ===

def new_run_id(*, when: datetime | None = None, suffix: str | None = None) -> str:
    """Allocate a new materialization run ID.

    #### Form:
        `YYYYMMDDTHHMMSSZ_<6-char>` (UTC timestamp + hex suffix)

    `suffix` must be exactly 6 lowercase hex digits when provided (tests / deterministic fixtures), else random 6-char suffix is used.
    """

    ts = when if when is not None else datetime.now(timezone.utc)
    if ts.tzinfo is None:
        raise ValueError("when must be timezone-aware (use UTC)")
    utc = ts.astimezone(timezone.utc)
    stamp = utc.strftime("%Y%m%dT%H%M%SZ")

    if suffix is None:
        tail = secrets.token_hex(3)  # Random 6-char suffix
    else:
        if not re.fullmatch(r"[0-9a-f]{6}", suffix):  # Check for valid hex suffix
            raise ValueError("suffix must be 6 lowercase hex digits")
        tail = suffix

    return f"{stamp}_{tail}"

def is_run_id(value: str) -> bool:
    """Return whether `value` matches the run-ID form."""

    return _RUN_ID_RE.fullmatch(value) is not None


# === Roots ===

def resolve_data_root(path: Path | str | None = None) -> Path:
    """Resolve the data root (default `.data/`); doesn't create directories."""

    root = DEFAULT_DATA_ROOT if path is None else Path(path)
    return root.expanduser()

def sets_dir(root: Path) -> Path:
    """Resolve the sets directory (`<root>/sets/`)."""

    return root / SETS_DIRNAME

def staging_dir(root: Path) -> Path:
    """Resolve the staging directory (`<root>/.staging/`)."""

    return root / STAGING_DIRNAME

def current_path(root: Path) -> Path:
    """Resolve the current pointer file (`<root>/CURRENT`)."""

    return root / CURRENT_NAME


# === Set / Staging Paths ===

def set_dir(root: Path, run_id: str) -> Path:
    """Resolve the directory for a given set/run (`<root>/sets/<run-id>/`)."""

    if not is_run_id(run_id):
        raise ValueError(f"invalid run_id: {run_id!r}")
    return sets_dir(root) / run_id

def refs_dir(set_path: Path) -> Path:
    """Resolve the refs directory (`<set>/refs/`)."""

    return set_path / REFS_DIRNAME

def staging_db_path(root: Path, run_id: str) -> Path:
    """Resolve the staging database file (`<root>/.staging/<run-id>.duckdb`)."""

    if not is_run_id(run_id):
        raise ValueError(f"invalid run_id: {run_id!r}")
    return staging_dir(root) / f"{run_id}.duckdb"


# === CURRENT Pointer ===

def read_current(root: Path) -> str | None:
    """Read the published run-ID from `CURRENT`, or `None` if missing/blank."""

    path = current_path(root)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None

def write_current_atomic(root: Path, run_id: str) -> None:
    """Atomically publish `CURRENT` to `run_id` via temp file + `replace`.

    Creates `root` if needed. Doesn't validate that `sets/<run-id>/` exists (callers run integrity checks before flipping pointer).
    """

    if not is_run_id(run_id):
        raise ValueError(f"invalid run_id: {run_id!r}")

    root.mkdir(parents=True, exist_ok=True)
    target = current_path(root)
    tmp = target.with_name(f"{CURRENT_NAME}.tmp")
    tmp.write_text(f"{run_id}\n", encoding="utf-8")
    tmp.replace(target)
