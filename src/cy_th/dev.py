# cy_th/dev.py

"""Developer utility commands (exposed as `uv run ...` entrypoints)."""

# === Imports ===

from __future__ import annotations
import shutil
from pathlib import Path


# === Paths ===

def _repo_root() -> Path:
    """Return the repository root (parent of `src/`)."""

    return Path(__file__).resolve().parents[2]

def _test_cache_dir() -> Path:
    return _repo_root() / "tests" / ".cache"


# === Commands ===

def clear_test_cache() -> int:
    """Delete `tests/.cache/` (USASpending extracts and related test artifacts).

    #### Returns:
        Process exit code (`0` on success)
    """

    cache_dir = _test_cache_dir()
    if not cache_dir.exists():
        print(f"no test cache at {cache_dir}")
        return 0

    shutil.rmtree(cache_dir)
    print(f"removed {cache_dir}")
    return 0


# === Entrypoints ===

def main_clear_test_cache() -> None:
    """CLI entry for `uv run clear-test-cache`."""

    raise SystemExit(clear_test_cache())

if __name__ == "__main__":
    # Allow `uv run python -m cy_th.dev` while we only expose one command
    # TODO: Remove this once we expose more commands
    raise SystemExit(clear_test_cache())
