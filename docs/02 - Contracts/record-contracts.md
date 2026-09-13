# 📚 Record Contracts

This document defines the **canonical local records** for Cy-TH and the rules that bind them.

Executable definitions live in `src/cy_th/schema/`. This note records the locked semantics so extraction and normalization can proceed without more data-model research.

It *does not select a storage engine, Parquet layout, graph store, or query runtime.*

## 1. Contract Statement

The local dataset is a **compact procurement relationship index** backed by transaction facts.

**It must:**

- Keep transactions as the activity grain
- Keep Award topology and observed Award money distinct from activity
- Preserve stable USASpending identities
- Keep relationship roles explicit
- Represent referenced objects outside the primary activity population
- Prefer an explicit unknown over an unsupported value

## 2. Record Inventory

| Record              | Module           | Role                                          |
| :------------------ | :--------------- | :-------------------------------------------- |
| `TransactionFact`   | `transaction.py` | Activity truth                                |
| `AwardRecord`       | `award.py`       | Identity, topology, semantics, optional money |
| `RecipientRef`      | `references.py`  | Recipient (+ parent UEI)                      |
| `AgencyRef`         | `references.py`  | Toptier / subtier agency                      |
| `OfficeRef`         | `references.py`  | Office under subtier                          |
| `IDVRef`            | `references.py`  | Parent vehicle stub                           |
| `ClassificationRef` | `references.py`  | NAICS or PSC                                  |
| `LocationRef`       | `references.py`  | Geo value-object                              |
| Download projection | `projection.py`  | `TRANSACTION_DOWNLOAD_COLUMNS`                |
| Snapshot helper     | `snapshot.py`    | Topology + money rules                        |

The ingestion manifest remains a control-plane object (see [Ingestion Contract](ingestion-contract.md)). Its schema lands with the ingest path.

## 3. Logical Types

Column contracts use **storage / logical types,** not library dtypes.

| Kind           | Meaning                                    |
| :------------- | :----------------------------------------- |
| `string`       | IDs, codes, names, text                    |
| `int64`        | Signed 64-bit integer                      |
| `decimal(p,s)` | Exact decimal; money uses `decimal(20, 2)` |
| `date`         | Calendar date                              |
| `bool`         | Boolean                                    |
| `enum`         | Constrained string; catalog in `enums.py`  |

Nullability is orthogonal (each column sets `nullable` explicitly).

Physical binding to DuckDB, Polars, etc. is deferred until the transform code we stand up requires it.

## 4. Identity and Deduplication

| Record              | Primary key         | Rule                                                                  |
| :------------------ | :------------------ | :-------------------------------------------------------------------- |
| `TransactionFact`   | `transaction_id`    | `contract_transaction_unique_key`; dedupe authority across shards     |
| `AwardRecord`       | `award_id`          | `contract_award_unique_key`                                           |
| `RecipientRef`      | `uei`               | `recipient_uei`                                                       |
| `AgencyRef`         | `agency_id`         | `{tier}:{code}` from `*_agency_code`                                  |
| `OfficeRef`         | `office_id`         | `{sub_agency_code}:{office_code}`; **no row** if office code is blank |
| `IDVRef`            | `idv_id`            | `CONT_IDV_{piid}_{award_key_agency_id}`                               |
| `ClassificationRef` | `classification_id` | `NAICS:{code}` or `PSC:{code}`                                        |
| `LocationRef`       | `location_id`       | SHA-256 of canonical geo tuple                                        |

Helpers live in `keys.py`.

### 4.1 Agency Namespaces

**We keep these namespaces separate:**

| Namespace           | Example | Use                                                |
| :------------------ | :------ | :------------------------------------------------- |
| Agency code         | `097`   | `AgencyRef.code` / `agency_id`                     |
| Award-key agency ID | `9700`  | Award / IDV generated keys (`award_key_agency_id`) |

**And will not substitute one for the other.**

### 4.2 Location Identity

Location identity is a **weak deterministic value-object:**

```text
(country_code, state_code, county_fips, normalized_city_name, zip)
```

- Prefer codes; city is a normalized label fallback (`strip` + `casefold`)
- Exclude congressional district from identity
- Store `granularity` from `location_granularity()`

## 5. Relationships

Relationships are **role-typed FKs** on `AwardRecord`, not a generic edge table.

```text
AwardRecord
├── recipient_id
├── awarding_agency_id / awarding_sub_agency_id / awarding_office_id
├── funding_agency_id  / funding_sub_agency_id  / funding_office_id
├── parent_idv_id
├── naics_id / psc_id
├── recipient_location_id
└── place_of_performance_id
```

Awarding and funding roles *must stay distinct even when they point at the same agency.*

Recipient parentage lives on `RecipientRef.parent_uei` (not on every Award row).

## 6. Award Projection Rules

Recompute each `AwardRecord` from the **union** of local `TransactionFact` rows for that `award_id` after cross-shard dedupe.

Sharding is an acquisition detail and must not change Award meaning (**meaning we avoid last-shard-wins**).

Topology/semantics and money use **separate selection rules** (see `snapshot.py`).

### 6.1 Topology and Semantics

**Among all local transactions for the Award:**

1. Take `MAX(action_date)`
2. Break ties with the minimum `transaction_id`

Store that row as `projection_transaction_id`.

**Don't filter on `transaction_number` for topology and don't order by `modification_number`.**

### 6.2 Money Snapshot

**Eligible rows:**

```text
transaction_number ∈ {0, "", null}
```

**Then:**

1. `latest_date = MAX(action_date)` among eligible rows
2. Candidates = eligible rows on `latest_date`
3. Compare:
   - `total_dollars_obligated`
   - `current_total_value_of_award`
   - `potential_total_value_of_award`

| Outcome                                        | `snapshot_status`     | `snapshot_source` | Money fields                                      |
| :--------------------------------------------- | :-------------------- | :---------------- | :------------------------------------------------ |
| All three non-null and equal across candidates | `defensible`          | `transaction`     | Populated; `snapshot_transaction_id` = min txn ID |
| All three null                                 | `not_observed`        | `transaction`     | Null                                              |
| No eligible rows, conflict, or partial nulls   | `requires_enrichment` | `none`            | Null                                              |

Observed money describes *the latest defensible state in the local population* (not necessarily the current USASpending state).

We'll reserve `date_signed` on `AwardRecord` as nullable (transaction-only materialization leaves it null).

## 7. Source Projection

`TRANSACTION_DOWNLOAD_COLUMNS` in `projection.py` is the exact `/download/transactions/` `columns=` allowlist.

**We retain a field when it:**

1. Establishes identity
2. Establishes an important relationship
3. Supports activity aggregation
4. Supplies useful semantic text
5. Carries high-value observed Award state
6. Supports citation / provenance

`COLUMN_PURPOSE` tags each column while `DEFERRED_DOWNLOAD_COLUMNS` notes known omissions (see `projection.py`).

**Out-of-projection (for now):**

- Competition, pricing, set-aside, business-type flags
- `period_of_performance_potential_end_date`
- Congressional district in location identity
- `date_signed` / `award_base_action_date` (absent from txn export)

## 8. Lazy Enrichment

USASpending remains authoritative for detail that is not local.

**Typical enrichment targets are:**

- `date_signed`
- Full IDV hydration (`IDVRef.hydration_status`: `stub` → `hydrated`)
- Ambiguous Award money (`requires_enrichment`)
- Competition / pricing / set-aside characteristics

Enrichment cache is *separate from the canonical activity dataset and may be evicted.*

## 9. Correctness Invariants

1. `TransactionFact` is the activity grain; window obligation is `SUM(federal_action_obligation)`
2. Observed Award money is never inferred from window activity
3. Role-typed FKs preserve awarding vs. funding and recipient location vs. place of performance
4. Agency code (`097`) and award-key agency ID (`9700`) stay separate
5. Cross-shard Award recompute uses the deduped txn union
6. Uncertain money stays null with an explicit `snapshot_status`
7. Source facts stay distinguishable from derived facts
8. Executable schemas and `TRANSACTION_DOWNLOAD_COLUMNS` are the implementation contract (which is what this document's about)

## 10. Code Map

```text
src/cy_th/schema/
├── enums.py         # Snapshot*, AgencyTier, ClassificationKind, HydrationStatus
├── types.py         # LogicalType, ColumnSpec, MONEY
├── keys.py          # Deterministic ID helpers
├── references.py    # *Ref schemas
├── transaction.py   # TransactionFact
├── award.py         # AwardRecord
├── projection.py    # Download allowlist + purposes
└── snapshot.py      # project_award_from_transactions()
```
