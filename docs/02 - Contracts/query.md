# 🔍 Query Contract

This document defines **how the procurement query runtime reads the published canonical dataset.**

Record semantics stay in [Record Contracts](record-contracts.md) and physical layout in [Materialization Contract](materialization.md). Executable code lives under `src/cy_th/query/`.

## 1. Contract Statement

The query runtime turns the active published Parquet set into a **read-only, deterministic query surface:**

```text
.data/CURRENT
    → resolve <run-id>
    → .data/sets/<run-id>/
    → read-only DuckDB views (session-pinned)
    → resolve_awards(filters) → AwardSelection (temp relation)
    → aggregate_activity(selection, window, group_by) → ranked rows
```

**It must:**

- Treat canonical Parquet as the source of truth
- Resolve `CURRENT` once per session and keep the dataset stable for the session lifetime
- Separate Award/ref filtering from transaction activity filtering
- Keep resolved Award IDs inside DuckDB (no Python ID round-trip)
- Compute window obligations from `TransactionFact.federal_action_obligation`
- Preserve canonical identities needed for provenance and citations

## 2. Session and Open Validation

On `ProcurementDataset.open(data_root)`:

1. Read `CURRENT`; fail clearly if missing, blank, or not a valid run-ID
2. Verify the referenced `sets/<run-id>/` exists with required Parquet files
3. Register DuckDB views over absolute pinned paths
4. Probe that expected relations/columns are readable

**We avoid re-running full PK/FK integrity checks at open time.** Materialization already certified the immutable set.

If `CURRENT` changes on disk while a session is open, *the open session continues using its pinned run-ID.*

**`AwardSelection` is session-scoped.** Each open `ProcurementDataset` has an opaque `session_id`, and every selection it produces carries that ID. Using a selection on another session, or after `close()`, raises `StaleSelectionError`. Temp relations live only on that session's DuckDB connection.

## 3. Query API

Two explicit operations compose the deterministic runtime:

| Step                                                             | Purpose                                                                            |
| :--------------------------------------------------------------- | :--------------------------------------------------------------------------------- |
| `resolve_awards(AwardFilters)`                                   | Materialize qualifying `award_id`s into a session temp relation (`AwardSelection`) |
| `select_awards(award_ids)`                                       | Same abstraction from an explicit ID collection (tests / semantic candidates)      |
| `aggregate_activity(selection, ActivityWindow, group_by, limit)` | JOIN the selection and sum obligations                                             |

```text
selection = dataset.resolve_awards(filters)
rows = dataset.aggregate_activity(selection, window, group_by=...)
```

`AwardSelection` carries `relation_name`, `count`, and `session_id`. Aggregation JOINs that relation; IDs are not shipped through Python between stages.

Semantic retrieval builds the same `AwardSelection` from hit IDs via `select_awards`. Fuzzy discovery lives in the [Semantic Search Contract](semantic.md). Relationship expansion from a selection lives in the [Relationship Traversal Contract](traversal.md).

## 4. Filter Semantics

### 4.1 Award / Ref Predicates

Award and reference predicates select Awards. **Each active filter is AND'd.**

| Field                     | Matches                               |
| :------------------------ | :------------------------------------ |
| `award_ids`               | `award_record.award_id`               |
| `recipient_ids`           | `award_record.recipient_id` (UEI)     |
| `awarding_agency_ids`     | `award_record.awarding_agency_id`     |
| `awarding_sub_agency_ids` | `award_record.awarding_sub_agency_id` |
| `awarding_office_ids`     | `award_record.awarding_office_id`     |
| `funding_agency_ids`      | `award_record.funding_agency_id`      |
| `funding_sub_agency_ids`  | `award_record.funding_sub_agency_id`  |
| `funding_office_ids`      | `award_record.funding_office_id`      |
| `naics_ids`               | `award_record.naics_id`               |
| `psc_ids`                 | `award_record.psc_id`                 |
| `location`                | role-specific location FK (see below) |

**List semantics:**

- `None` → unconstrained
- Empty iterable → zero matches **(don't interpret as "all")**

We'll opt to use canonical IDs everywhere (`toptier:097`, `NAICS:541330`, `location_id` digest, etc.).

### 4.2 Location Filter

**`LocationFilter.role` is required and explicit:**

- `recipient` → `award_record.recipient_location_id`
- `place_of_performance` → `award_record.place_of_performance_id`

We don't silently OR recipient and place-of-performance roles.

**Match either:**

- Exact `location_ids`
- Exact structured fields on `LocationRef` (`country_code`, `state_code`, `county_fips`, normalized `city_name`, `zip_code`)

When multiple structured fields are set, they are AND'd. *No substring city matching.*

### 4.3 Activity Window

`ActivityWindow` uses inclusive bounds `[from_date, to_date]` on `transaction_fact.action_date`.

### 4.4 Topology Projection

Recipient, agency, office, classification, and location filters use **projected Award topology** from `AwardRecord` (latest `action_date` projection row).

Date filters remain transaction-exact.

**Example:**

> "Virginia obligations in 2025"

Means obligations in 2025 for Awards whose locally projected place-of-performance is Virginia, not necessarily each transaction's PoP at action time.

## 5. Aggregation Semantics

**Given a qualifying `award_id` set and activity window:**

```text
qualifying awards
    → qualifying TransactionFact rows (date window)
    → SUM(federal_action_obligation)
    → group / rank
```

**Money rules:**

- Sum `transaction_fact.federal_action_obligation` only
- SQL null obligations are ignored inside `SUM` (not coerced to zero)
- Groups whose total obligation is null are excluded from ranked monetary results

*We don't infer window totals from `AwardRecord.observed_*` money fields.*

## 6. Result Shape and Ranking

### Group-by-Award

| Field                   | Source                               |
| :---------------------- | :----------------------------------- |
| `award_id`              | `award_record.award_id`              |
| `total_obligation`      | aggregated sum                       |
| `transaction_count`     | qualifying txn count                 |
| `recipient_id`          | `award_record.recipient_id`          |
| `piid`                  | `award_record.piid`                  |
| `usaspending_permalink` | `award_record.usaspending_permalink` |

### Group-by-Recipient

| Field               | Source                            |
| :------------------ | :-------------------------------- |
| `recipient_id`      | `award_record.recipient_id` (UEI) |
| `name`              | `RecipientRef.name`               |
| `total_obligation`  | aggregated sum                    |
| `transaction_count` | qualifying txn count              |

**Ranking:**

- `ORDER BY total_obligation DESC`
- Stable secondary key (`award_id ASC` or `recipient_id ASC`)
- Optional `limit`

## 7. Code Map

```text
src/cy_th/query/
├── types.py      # Filter/result models
├── errors.py     # Open/query failures
├── open.py       # CURRENT resolution + view registration
├── resolve.py    # resolve_awards
├── aggregate.py  # aggregate_activity
└── dataset.py    # ProcurementDataset
```
