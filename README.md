# 📦 Cy-TH

Natural-language Q&A over Department of Defense contract awards from [USASpending](https://www.usaspending.gov/).

Cy-TH ingests a date window of prime DoD contract transactions, materializes a compact local Parquet dataset, builds a semantic index, and answers questions through a bounded tool-using agent grounded in that data (with USASpending citations).

Architecture and contracts live under [`docs/`](docs/overview.md). This README is the **setup-and-use path.**

## Requirements

- Python **3.12.10+**
- [`uv`](https://docs.astral.sh/uv/)
- Network access to USASpending (for `ingest`)
- Optional: NVIDIA GPU + CUDA 13.0 for fast embeddings
- Optional: OpenAI API key for `cyth ask` (default provider; protocol can be extended to other providers)

## Install

**Clone the repo and sync w/ extras:**

```sh
git clone <repo-url> cy-th
cd cy-th
uv sync --extra openai --extra semantic
```

| Extra      | What it Adds                                                                                  |
| ---------- | --------------------------------------------------------------------------------------------- |
| `openai`   | `cyth ask` via Responses API                                                                  |
| `semantic` | `cyth semantic build` + semantic tool search (`torch` from CUDA 13.0 wheels on Windows/Linux) |

**Confirm CUDA torch (recommended for embeddings):**

```sh
uv run python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

Note that you'll want a `+cu130` build and `True`. If you get a CPU wheel, re-sync after pulling the latest `pyproject.toml` (Torch should be pinned to `https://download.pytorch.org/whl/cu130`).

## Quickstart

`--from` / `--to` are inclusive `action_date` bounds. Adjust the window if you like; the commands below use a rolling ~2-year range.

### 1. Ingest

```sh
uv run cyth ingest --from 2024-09-14 --to 2026-09-14
```

This downloads projected prime DoD transactions, writes shard manifests, materializes Parquet, and flips `CURRENT`.

Expect USASpending export waits (sometimes quite a while) and possible count 504s on large ranges (which will cause ingest to retry and bisect until shards fit under the 500k-row download cap). A full 2-year pull is large (~millions of transactions); resume is safe if interrupted (same job ID skips completed shards).

### 2. Generate Embeddings

```sh
uv run cyth semantic build --batch-size 1024
```

Builds the BGE semantic index for the pinned `CURRENT` set. Use a CUDA torch build for speed; raise `--batch-size` if VRAM allows.

### 3. Ask

```sh
# PowerShell
$env:OPENAI_API_KEY = "sk-..."
uv run cyth ask --data-root .data "Which recipient had the highest total obligation in the local window?"
```

```sh
# bash
export OPENAI_API_KEY="sk-..."
uv run cyth ask --data-root .data "Which recipient had the highest total obligation in the local window?"
```

**Optional model override:** `--model <model slug>` (or set `CYTH_MODEL`).

## Environment

| Variable         | Purpose                                   |
| ---------------- | ----------------------------------------- |
| `OPENAI_API_KEY` | Required for default `cyth ask` provider  |
| `CYTH_MODEL`     | OpenAI model id (default: `gpt-5.6-luna`) |
| `CYTH_PROVIDER`  | Model provider name (default: `openai`)   |

## CLI

```text
uv run cyth <command> ...
```

### `ingest`

```sh
uv run cyth ingest --from YYYY-MM-DD --to YYYY-MM-DD [--out .data] [--no-materialize]
```

**Population (locked):** prime contracts, types A–D, awarding toptier Department of Defense.

### `semantic build`

```sh
uv run cyth semantic build [--data-root .data] [--force] [--batch-size 1024] [--offline]
```

### `ask`

```sh
uv run cyth ask [--data-root .data] [--provider openai] [--model gpt-4.1] "Your question"
```

### Other

```sh
uv run cyth materialize --in path/to.csv [--out .data]
uv run cyth clear-test-cache
```

## Data layout

```text
.data/
├── ingest/<from>_<to>_<hash>/     # download job + shard CSVs/manifests
├── sets/<run-id>/                 # immutable Parquet set
├── CURRENT                        # pointer to active run-id
├── derived/<run-id>/semantic/     # embeddings + documents
└── enrichment/                    # optional lazy award/IDV detail cache
```

`.data/` is gitignored. **Remember to point every command at the same `--out` / `--data-root`.**

## Development

```sh
uv sync --extra openai --extra semantic
uv run pytest
```

- Package code: `src/cy_th/`
- Contracts: `docs/02 - Contracts/`
- Source-domain notes: `docs/01 - Source Docs/`

## Notes

- **Ingest latency** is dominated by USASpending's async export queue, not local materialize.
- **Embeddings** are much faster on CUDA; CPU works but is slow on multi-year sets.
- **Enrichment** (`cy_th.enrichment`) is cache-only and does not rewrite `CURRENT`.
- Model providers are pluggable via `cy_th.agent.providers.resolve`; only OpenAI is registered currently.
