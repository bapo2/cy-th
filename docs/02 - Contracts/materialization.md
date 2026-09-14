# 🧱 Materialization Contract

This document defines **how projected USASpending CSVs become the durable local Parquet surface.**

Record semantics stay in [Record Contracts](record-contracts.md) and acquisition intent in [Ingestion Contract](ingestion-contract.md) while this covers the materialize path that we've implemented.

Executable code lives under `src/cy_th/materialize/`.

## 1. Contract Statement

Materialization turns N ≥ 1 projected prime-transaction CSVs **into one versioned, queryable dataset:**

```text
CSV_1, CSV_2, ..., CSV_N
    → union → validate + dedupe
    → TransactionFact + Refs + AwardRecord
    → Parquet set under .data/
    → optional CURRENT pointer
```

**It must:**

- Accept multiple shard files without last-shard-wins Award semantics
- Use DuckDB for production transforms (`snapshot.py` for money/topology oracle)
- Publish immutable versioned sets
- Flip `CURRENT` only after integrity checks pass (strict by default, i.e. no rejects)
- Keep rejects explicit when present

## 2. Inputs

Each `--in` file is a **projected** USASpending prime-transaction CSV.

**Header rules:**

- `TRANSACTION_DOWNLOAD_COLUMNS ⊆ header`
- Duplicate header names fail
- Extra columns are ignored

**Row rules:**

- Blank → NULL
- Blank required ID / `action_date` → reject (`missing_required:*`)
- Malformed money / date → reject (`malformed:*`)
- Exact projected payload dups (content hash within `transaction_id`) → keep one
- Same ID, disagreeing hash → reject all (`identity_collision`)

## 3. Derived Tables

**From the deduped valid rows:**

| Output            | Rule                                                                           |
| :---------------- | :----------------------------------------------------------------------------- |
| `TransactionFact` | Rename / project activity columns                                              |
| Refs              | Distinct identities; latest non-empty descriptor by `action_date`, then txn ID |
| `AwardRecord`     | Topology row ≠ money snapshot; `date_signed` null on txn-only materialize      |

Parent recipient UEIs that never appear as recipients become stubs. Empty geo tuples do not create `LocationRef` rows.

## 4. On-Disk Layout

Default root is `.data/` (which is gitignore'd). Overridden with `--out`.

```text
<data-root>/
├── sets/
│   └── <run-id>/                     # e.g. 20260914T021530Z_a1b2c3
│       ├── transactions.parquet
│       ├── awards.parquet
│       ├── rejects.parquet           # only if reject_count > 0
│       └── refs/
│           ├── recipients.parquet
│           ├── agencies.parquet
│           ├── offices.parquet
│           ├── idvs.parquet
│           ├── classifications.parquet
│           └── locations.parquet
├── CURRENT                           # plain run-ID string
└── .staging/
    └── <run-id>.duckdb
```

Staging is **deleted on success** unless `--keep-staging` is used, while staging is **retained on failure** by default to help debug failed runs.

**Run-ID form:** `YYYYMMDDTHHMMSSZ_<6 hex chars>` (uses UTC for tz).

Sets are **immutable.** Each set is assembled under `.tmp-<run-id>/` and renamed into `sets/<run-id>/` only after every Parquet write succeeds, so a mid-write failure never leaves a partial set directory. Reusing a run-ID that already exists fails. GC of old sets is manual for now.

## 5. Rejects and CURRENT

| Mode                         | Set written | `CURRENT` flipped                        |
| :--------------------------- | :---------- | :--------------------------------------- |
| No rejects                   | Yes         | Yes                                      |
| Rejects + default (strict)   | Yes         | No                                       |
| Rejects + `--allow-rejects`  | Yes         | Yes (degraded set; rejects.parquet kept) |

Integrity failures (PK/FK) abort before the set is written and never flip `CURRENT`.

## 6. Integrity Checks

**Before publish:**

- Primary keys unique and non-null on txn / award / ref tables
- `TransactionFact.award_id` → `AwardRecord`
- Non-null Award role FKs → matching ref tables
- `projection_transaction_id` and non-null `snapshot_transaction_id` → `TransactionFact`

## 7. CLI

```text
uv run cyth materialize --in a.csv [--in b.csv] [--out .data] [--allow-rejects] [--keep-staging]
```

**Exit codes for `materialize`:**

| Code | Meaning                                           |
| :--- | :------------------------------------------------ |
| `0`  | Set written and `CURRENT` published               |
| `2`  | Set written; `CURRENT` skipped (strict + rejects) |
| `1`  | Hard failure (bad input, integrity, etc.)         |

## 8. Code Map

```text
src/cy_th/materialize/
├── pipeline.py      # end-to-end orchestration
├── load.py          # CSV → staging_raw
├── validate.py      # casts, rejects, dedupe
├── transactions.py  # TransactionFact
├── references.py    # ref_* tables
├── awards.py        # AwardRecord reduce
├── publish.py       # Parquet + integrity + CURRENT
└── paths.py         # data-root / run-id / CURRENT helpers
```

Logical column contracts and the download allowlist are under `src/cy_th/schema/` (see [Record Contracts](record-contracts.md)).
