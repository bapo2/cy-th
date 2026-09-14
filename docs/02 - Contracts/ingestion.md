# 📜 Ingestion Contract

This document defines **how we'll acquire, interpret, and retain USASpending contract data.**

It describes the ingestion operating model and its invariants without prescribing the final storage engine, graph representation, or query architecture (which will be determined by the later implementation).

## 1. Contract Statement

We'll ingest prime Department of Defense contract **transactions** whose `action_date` is inside a requested interval.

**The local dataset preserves enough information to:**

- Identify each transaction and Award
- Reconstruct important procurement relationships
- Answer common analytical and semantic questions
- Trace local facts back to USASpending
- Retrieve additional authoritative detail when required

The project does not attempt to persist every USASpending field locally.

## 2. Primary Population

**The primary ingestion population is:**

- Prime contracts only
- Award types `A`, `B`, `C`, and `D`
- Department of Defense as the **awarding top-tier agency**
- Transactions whose `action_date` is in the requested interval

**Subawards are outside the initial scope.**

IDVs aren't members of the primary activity population. *Referenced IDVs are retained as related objects.*

## 3. Time Semantics

An ingestion interval applies to transaction `action_date`.

**For example:**

```text
--from 2024-09-11 --to 2026-09-11
```

Means:

> Ingest contract transactions whose activity occurred from 2024-09-11 through 2026-09-11.

Rather than:

> Ingest only Awards that began during this interval.

An Award can therefore **predate the requested interval** and still belong to the local dataset *if it has activity inside the interval.*

Recent source data can be incomplete because of USASpending reporting lag, thus we *must not represent a recent extraction as a final or complete government snapshot.*

## 4. Canonical Grain

A **Transaction** is the canonical grain for ingested contract activity.

Each local transaction **must preserve at least:**

- Stable transaction identity
- Parent Award identity
- Action date
- Transaction obligation
- Modification and transaction identity where available
- Enough text to describe or semantically search the action

Award-level information can be derived or projected from these transactions, but **Award state must remain distinct from transaction activity.**

## 5. Local Data Surface

The durable local surface contains **four logical classes of data.**

### 5.1 Transaction Facts

Transaction facts preserve procurement activity.

**At minimum they provide:**

```text
Transaction
├── transaction identity
├── Award identity
├── action date
├── federal action obligation
├── modification / transaction identity
└── useful transaction text
```

**Transaction facts are the authoritative local basis** for time-bounded activity calculations.

### 5.2 Core Award

Core Award records provide continuity and relationship topology.

They preserve enough information to identify and connect an Award **to concepts such as:**

- Recipient
- Parent Recipient
- Awarding and funding organizations
- Offices
- Parent IDV
- NAICS
- PSC
- Recipient location
- Place of performance

They also retain query-critical Award text and the USASpending permalink.

High-value observed Award-state values can be retained when their source and quality are known.

### 5.3 Reference Objects

The project retains compact reference information for entities needed to interpret Award relationships.

**Examples include:**

- Recipients
- Agencies
- Offices
- IDVs
- NAICS classifications
- PSC classifications
- Locations

Reference objects *should contain stable identity and enough descriptive information for local querying.*

They don't require complete USASpending detail.

### 5.4 Ingestion Manifests

Every acquired shard must have an ingestion manifest.

A manifest records enough information to identify and reproduce the extraction, including:

- Source
- Endpoint
- Filters
- Requested date range
- Field projection
- Retrieval time
- Row count
- Source file identity where applicable
- Checksum where applicable
- Ingestion/schema version

## 6. Relationship Closure

The local dataset must preserve the important relationships defined by the procurement model.

If a relationship target is outside the primary ingestion population, the project must still preserve a stable reference to that target.

**For example:**

```text
Delivery Order ── issued under ──> IDV
```

The parent IDV can predate the requested activity window.

The project can therefore create a local IDV reference from the child Award *without first downloading the complete IDV record.*

The same principle applies to other external relationship targets *where a stable source identity is available.*

This requirement provides **topological closure without requiring full hydration**.

## 7. Monetary Semantics

Transaction activity and Award state **must remain separate.**

### Activity

**For a selected interval:**

```text
window obligation =
    SUM(federal_action_obligation)
```

Over the matching transactions.

This is the canonical local measure of obligation activity during that interval.

### Award State

**Fields such as:**

- Lifetime obligation
- Current Award value
- Potential Award value

**Describe observed Award state.**

They *must not be inferred* from window activity.

Rolled-up state observed on transaction rows **must not be treated as authoritative** *unless the selected snapshot satisfies the applicable quality rule.*

If a trustworthy state cannot be established, the value *should remain unknown or require enrichment.*

**The project must prefer an explicit unknown value over an unsupported value.**

## 8. Source Identity

Stable USASpending identifiers must remain available throughout the pipeline.

The project must not use display names as primary identity.

**Important source identities include:**

- Transaction generated key
- Award generated key
- Recipient UEI
- Organizational identifiers
- Parent IDV identity
- Classification codes

Source identifiers must survive normalization so records can be reconciled with USASpending later.

## 9. Extraction and Partitioning

USASpending limits normal transaction-download jobs to a bounded number of rows.

The project can partition a requested interval into smaller shards.

**A typical planner can:**

```text
requested interval
    ↓
split into candidate periods
    ↓
count each period
    ↓
period exceeds source limit?
    ├── no  → download
    └── yes → subdivide and repeat
```

Partitioning is an operational detail and *must not change the semantic meaning of the requested dataset.*

**Therefore:**

```text
ingest(A → C)
```

Must represent **the same transaction population** regardless of whether it was downloaded as one shard or many shards.

## 10. Idempotence and Resumability

Ingestion must be safe to resume.

Completed shards should have deterministic identity based on their extraction parameters.

**A rerun must be able to:**

- Detect completed shards
- Skip valid completed work
- Retry failed or incomplete shards
- Avoid duplicate canonical transactions

**Transaction identity is the final deduplication authority.**

Network or source failures *must not require restarting a complete multi-shard ingestion.*

## 11. Source Projection

The project should request only fields that serve a known local purpose.

**A field should normally be retained when it:**

1. Establishes identity
2. Establishes an important relationship
3. Supports common filtering or aggregation
4. Provides useful semantic text
5. Carries high-value Award state
6. Supports citation or provenance

Wide source attributes that don't satisfy these conditions *can be retrieved later.*

The source projection can evolve without changing the conceptual procurement model.

## 12. Lazy Enrichment

USASpending remains the authoritative source for detail that's not present locally.

When the local dataset is insufficient, the project can retrieve additional information using stable source identity.

**Examples include:**

- Award signing date
- Complete Award detail
- Detailed IDV information
- Competition characteristics
- Pricing information
- Set-aside information
- Classification hierarchies
- Unusual Award-state validation

**The operating pattern is:**

```text
local query
    ↓
sufficient information?
    ├── yes → continue
    └── no
        ↓
    fetch authoritative detail
        ↓
    validate
        ↓
    optionally cache
        ↓
    continue
```

Lazy enrichment *must not silently replace source-derived facts with inferred values.*

## 13. Enrichment Cache

Fetched enrichment can be cached locally.

Cached enrichment is *separate from the canonical activity dataset.*

**A cached record should preserve:**

- Resource type
- Stable source identity
- Source endpoint
- Retrieval time
- Source payload or selected result

The cache can be *evicted and rebuilt.*

The correctness of the core dataset *must not depend on permanent cache retention.*

## 14. Semantic Surface

The local dataset must preserve enough text for useful semantic retrieval.

At minimum, **useful sources include:**

- Award base description
- Transaction description
- PSC code and description
- NAICS code and description
- Recipient and organization names

Inferred semantic labels are derived information and *must remain distinguishable from source text.*

## 15. Provenance

Every canonical source fact must remain traceable to USASpending.

At minimum, **provenance must allow the project to identify:**

```text
local fact
    ↓
source Transaction / Award
    ↓
ingestion shard
    ↓
source extraction parameters
```

Derived facts must also retain their derivation semantics.

**For example:**

```text
FY2025 obligation = $X
```

**Must be attributable to:**

```text
SUM(federal_action_obligation)
WHERE action_date ∈ FY2025
AND ...
```

User-facing citations can use USASpending permalinks where appropriate with *internal provenance not depending only on those links.*

## 16. Source Artifact Retention

Downloaded source files are acquisition artifacts, not the primary query surface.

**Two retention modes are valid.**

### Compact

```text
download
    ↓
validate
    ↓
materialize canonical local data
    ↓
record manifest
    ↓
discard source archive
```

**This minimizes local storage** (this is likely the one we'll go with provided we don't run into drawbacks).

### Archival

The source archive is retained with its manifest and checksum.

This provides stronger byte-level reproducibility at higher storage cost.

The retention mode must not change the semantic contents of the canonical dataset.

## 17. Correctness Invariants

The following rules must remain true throughout ingestion and normalization:

1. **Transaction identity is preserved**
2. **Award identity is preserved**
3. **Transaction activity remains distinct from Award state**
4. **`--from` and `--to` apply to `action_date`**
5. **Window obligation is derived from transaction-level obligation**
6. **Relationship roles remain explicit**
7. **References outside the primary population remain representable**
8. **Partition boundaries don't change dataset meaning**
9. **Repeated ingestion does not create duplicate canonical transactions**
10. **Uncertain Award state is not silently treated as authoritative**
11. **Source facts remain distinguishable from derived facts**
12. **Canonical facts remain traceable to source identity and extraction provenance**
13. **Lazy enrichment can add information but must not change the meaning of existing source facts without explicit reconciliation**
14. **Subaward data does not enter the prime-contract dataset unless scope is explicitly expanded**

## 18. Operating Model

**The resulting operating model is:**

```text
USASpending
    ↓
Extraction Planner
    ├── count / partition
    ├── submit downloads
    ├── retry / resume
    ├── validate
    ▼
Projected Source Data
    ↓
Normalization
    ├── Transaction Facts
    ├── Core Award
    ├── Reference Objects
    ├── Provenance
    ▼
Canonical Local Dataset
    ├───────────────┐
    ▼               ▼
Local Query     Lazy Enrichment
                    ↓
                USASpending APIs
                    ↓
                Enrichment Cache
```

The canonical local dataset is therefore a **compact procurement relationship index backed by transaction facts.**

USASpending remains the authoritative source for detail *that does not need to be carried in the local working set.*

## 19. CLI

```text
uv run cyth ingest --from YYYY-MM-DD --to YYYY-MM-DD [--out .data] [--no-materialize]
```

`--from` / `--to` are inclusive `action_date` bounds. Default publishes a Parquet set and flips `CURRENT` via existing materialize. `--no-materialize` stops after shards + manifests.

### 19.1 On-disk layout

```text
<data-root>/
├── ingest/
│   └── <from>_<to>_<12-hex>/
│       ├── job.json
│       └── shards/
│           ├── <start>_<end>.csv
│           └── <start>_<end>.json
├── sets/<run-id>/
└── CURRENT
```

Job-ID is deterministic from population + interval + projection + ingest version (reruns resume the same job). Per-shard JSON is the ingestion manifest (checksum, filters, row count). Completed shards are skipped.

### 19.2 Partitioning

`POST /download/count/` then bisect the date window until each shard is ≤ 500k rows (USASpending download cap). A single day still over the cap fails clearly. Transient count failures (HTTP 502/503/504 after retries) on multi-day windows are treated as "too large to count" and bisected the same way.

### 19.3 Code map

```text
src/cy_th/ingest/
├── pipeline.py    # plan / resume / download / optional materialize
├── planner.py     # date bisection
├── client.py      # live USASpending HTTP
├── fake.py        # offline DownloadClient
├── manifest.py    # job.json + per-shard manifests
├── filters.py     # locked DoD prime population
├── paths.py       # ingest/<job-id>/shards
└── types.py
```

## 20. Lazy Enrichment

Enrichment fetches USASpending award detail on demand and caches it under the data root. **It does not rewrite `CURRENT` / Parquet.**

```text
uv run python -c "from cy_th.enrichment.service import enrich_award; ..."
```

**Library entrypoints:** `enrich_award(dataset, award_id)`, `enrich_idv(dataset, idv_id)` in `cy_th.enrichment.service`

### 20.1 On-disk layout

```text
<data-root>/
├── enrichment/
│   ├── awards/<urlsafe-award-id>.json
│   └── idvs/<urlsafe-idv-id>.json
├── ingest/...
├── sets/<run-id>/
└── CURRENT
```

Each cache record preserves `resource_type`, `source_id`, `endpoint`, `retrieved_at`, `selected` (parsed fields), and full `payload`. Evict by deleting the file; the core dataset must not depend on cache retention.

### 20.2 Overlay rules

- Endpoint: `GET /api/v2/awards/{generated_unique_award_id}/` (works for Awards and IDVs)
- Always expose `date_signed` on the Award overlay when present on detail
- Apply detail money **only when local `snapshot_status` is `requires_enrichment`** → overlay may set `snapshot_source=award_detail`
- IDV overlay reports `hydration_status=hydrated` with type code/label from detail; local stub rows stay `stub`

### 20.3 Provenance chain

```text
local fact → source Award / Transaction id
           → ingest job + shard manifest (acquisition)
           → enrichment cache record (detail endpoint + retrieval time) when overlay fields are used
```

### 20.4 Code map

```text
src/cy_th/enrichment/
├── service.py     # enrich_award / enrich_idv / evict
├── reconcile.py   # selected fields + money gate
├── cache.py       # JSON cache IO
├── client.py      # live award-detail HTTP
├── fake.py        # offline DetailClient
├── paths.py
└── types.py
```
