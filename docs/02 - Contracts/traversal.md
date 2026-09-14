# 🖇️ Relationship Traversal Contract

This document defines **how Cy-TH expands a session-valid Award selection into related canonical entities** (recipients, agencies, offices, IDVs, locations, classifications).

Canonical Parquet is authoritative ([Materialization](materialization.md), [Record Contracts](records.md)). Award filtering and aggregation stay in the [Query Contract](query.md). Fuzzy discovery stays in the [Semantic Search Contract](semantic.md). Model-facing composition lives in the [Evidence Tooling Contract](evidence.md).

## 1. Contract Statement

**Relationship traversal is a deterministic one-hop relational primitive over projected Award topology:**

```text
AwardSelection
    → traverse_relationships(selection, include=...)
    → TraversalResult(entities)
    → (caller) AwardFilters / resolve_awards(...)
    → related AwardSelection
```

**It must:**

- Start from a session-valid `AwardSelection`
- Join only published Award FKs → reference tables (no inferred edges)
- Preserve relationship roles (never collapse awarding w/ funding, recipient location w/ PoP, etc.)
- Skip null / absent FKs rather than synthesizing entities
- Expose stable canonical entity IDs plus minimal display metadata
- Deduplicate and order results deterministically
- Compose with existing structured filters for later Award resolution

**It must not:**

- Provide a path / multi-hop query language (callers compose hops)
- Compute money, obligations, or other analytical facts
- Require a graph database or generic graph framework

## 2. API

```text
dataset.traverse_relationships(selection, include=None) → TraversalResult
```

| Argument    | Semantics                                                                                          |
| :---------- | :------------------------------------------------------------------------------------------------- |
| `selection` | Session-scoped `AwardSelection` (stale / cross-session → `StaleSelectionError`)                    |
| `include`   | Optional collection of `EntityKind`. `None` = all supported kinds; empty collection = empty result |

`TraversalResult` is a flat ordered tuple of `RelatedEntity` (no per-kind bundles).

**Usage:**

```python
with ProcurementDataset.open(".data") as ds:
    seed = ds.select_awards(award_ids)  # Or resolve_awards(...)
    related = ds.traverse_relationships(seed)

    recipient_ids = [
        e.entity_id for e in related.entities if e.kind is EntityKind.RECIPIENT
    ]
    expanded = ds.resolve_awards(AwardFilters(recipient_ids=recipient_ids))

    pop_ids = [
        e.entity_id
        for e in related.entities
        if e.kind is EntityKind.LOCATION
        and e.role is RelationRole.PLACE_OF_PERFORMANCE
    ]
    pop_awards = ds.resolve_awards(
        AwardFilters(
            location=LocationFilter(
                role=RelationRole.PLACE_OF_PERFORMANCE,
                location_ids=pop_ids,
            )
        )
    )
```

## 3. Enums and Result Model

### 3.1 `EntityKind` (Declaration Order)

1. `RECIPIENT`
2. `AGENCY`
3. `OFFICE`
4. `IDV`
5. `LOCATION`
6. `CLASSIFICATION`

Declaration order is the primary sort key.

### 3.2 `RelationRole` (Declaration Order)

1. `AWARDING`
2. `FUNDING`
3. `RECIPIENT`
4. `PLACE_OF_PERFORMANCE`

Used only when the Award edge has a meaningful procurement role. For recipient, IDV, and classification edges, `role` is `None` (we don't invent placeholder roles).

`LocationFilter.role` uses the same `RelationRole` enum (only `RECIPIENT` / `PLACE_OF_PERFORMANCE` are valid there).

We reuse existing schema enums for agency tier and classification discriminator: `AgencyTier` (`toptier` / `subtier`) and `ClassificationKind` (`NAICS` / `PSC`).

### 3.3 `RelatedEntity`

| Field                  | When Set                                  |
| :--------------------- | :---------------------------------------- |
| `kind`                 | Always                                    |
| `role`                 | Agency/office/location edges; else `None` |
| `entity_id`            | Always (canonical ID)                     |
| `label`                | Best available display string (see §5)    |
| `agency_tier`          | Agencies only                             |
| `idv_agency_id`        | IDVs only (`award_key_agency_id`)         |
| `classification_kind`  | Classifications only                      |
| `code`                 | Classifications only                      |
| `description`          | Classifications only (nullable)           |
| `country_code` … geo   | Locations only (nullable components)      |
| `granularity`          | Locations only when available             |

No money fields, transaction facts, or enrichment payloads.

## 4. One-Hop Edges

Traversal reads **projected Award topology** (same surface as structured Award/ref filters). Each non-null FK yields at most one candidate edge per Award; results are then deduped across the selection.

| Kind           | Award FK(s)                                         | Role                                 | Tier / Discriminator               |
| :------------- | :-------------------------------------------------- | :----------------------------------- | :--------------------------------- |
| Recipient      | `recipient_id`                                      | `None`                               | -                                  |
| Agency         | `awarding_agency_id`, `awarding_sub_agency_id`      | `AWARDING`                           | `TOPTIER` / `SUBTIER`              |
| Agency         | `funding_agency_id`, `funding_sub_agency_id`        | `FUNDING`                            | `TOPTIER` / `SUBTIER`              |
| Office         | `awarding_office_id` / `funding_office_id`          | `AWARDING` / `FUNDING`               | -                                  |
| IDV            | `parent_idv_id`                                     | `None`                               | -                                  |
| Location       | `recipient_location_id` / `place_of_performance_id` | `RECIPIENT` / `PLACE_OF_PERFORMANCE` | -                                  |
| Classification | `naics_id` / `psc_id`                               | `None`                               | `ClassificationKind` on the entity |

Join to the corresponding reference table for labels / geo / classification fields. Never invent entity IDs. A non-null Award FK that does not join to a ref row is omitted (should not occur on integrity-checked published sets).

## 5. Labels

| Kind           | `label`                                | Other Fields                                                              |
| :------------- | :------------------------------------- | :------------------------------------------------------------------------ |
| Recipient      | recipient name                         | -                                                                         |
| Agency/Office  | agency/office name                     | `agency_tier` on agencies                                                 |
| IDV            | PIID                                   | `idv_agency_id` = `award_key_agency_id`                                   |
| Classification | `description` if present, else `code`  | keep `code` (+ `description`, `classification_kind`) separate for handoff |
| Location       | may be null (geo fields carry display) | country / state / county / city / zip + `granularity` as available        |

We'll avoid manufacturing composite strings such as `"{code}: {description}"` for classification labels.

## 6. Dedup and Ordering

**Dedup key:** `(kind, role, entity_id)`

- Never merge distinct roles (same agency awarding and funding → two entities)
- `agency_tier` is not part of the dedup key (canonical agency IDs already identify one tier)

**Stable sort:**

```text
1. kind         - EntityKind declaration order
2. role         - None first, then RelationRole declaration order
3. agency_tier  - None first, then AgencyTier declaration order (toptier, then subtier)
4. entity_id    - ascending string order
```

## 7. Session, Empty, and Include Semantics

- Stale / cross-session / closed-session selections fail with the same `StaleSelectionError` rules as aggregation
- Empty `AwardSelection` → empty `entities`
- Awards whose optional FKs are null contribute nothing for those edges
- `include=None` → all `EntityKind` values
- `include=()` → empty result (same "empty means none" convention as Award filter lists)
- Unknown kinds in `include` are a caller error (reject clearly)

## 8. Structured-Query Handoff

Returned `entity_id` values are intended for existing `AwardFilters` / `LocationFilter` fields:

| Related Entity                  | Filter Field(s)                                        |
| :------------------------------ | :----------------------------------------------------- |
| Recipient                       | `recipient_ids`                                        |
| Agency + `AWARDING` + `TOPTIER` | `awarding_agency_ids`                                  |
| Agency + `AWARDING` + `SUBTIER` | `awarding_sub_agency_ids`                              |
| Agency + `FUNDING` + `TOPTIER`  | `funding_agency_ids`                                   |
| Agency + `FUNDING` + `SUBTIER`  | `funding_sub_agency_ids`                               |
| Office + `AWARDING` / `FUNDING` | `awarding_office_ids` / `funding_office_ids`           |
| Location + role                 | `LocationFilter(role=entity.role, location_ids=[...])` |
| Classification `NAICS` / `PSC`  | `naics_ids` / `psc_ids`                                |
| IDV                             | `parent_idv_ids`                                       |

Multi-hop questions (e.g. "other agencies that awarded to these recipients") are **caller composition:** traverse → filter IDs → `resolve_awards` → traverse again. Traversal itself stays one-hop.
