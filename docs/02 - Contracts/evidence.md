# 💼 Evidence Tooling Contract

This document defines **how Cy-TH exposes deterministic procurement capabilities through a model-facing evidence session,** retaining acquired evidence across one question-answering session while returning only bounded views into model context.

Canonical Parquet is authoritative ([Materialization](materialization.md), [Record Contracts](records.md)). Underlying primitives stay in the [Query Contract](query.md), [Semantic Search Contract](semantic.md), and [Relationship Traversal Contract](traversal.md). *This layer will not attempt to reimplement those services.*

## 1. Contract Statement

**The evidence tool layer is the stable boundary the [procurement agent](agent.md) calls:**

```text
EvidenceSession
    → typed tools (search / resolve / aggregate / traverse / get_award_evidence)
    → session registry (opaque SelectionRef → internal AwardSelection + retained evidence)
    → Query + Semantic Search + Relationship Traversal
    → published canonical dataset (+ optional published semantic index)
```

*Tool operations **both acquire/retain session evidence and return bounded model-visible views** over that retained state.*

*Opaque refs **represent potentially large internal evidence sets;** model-visible payloads are **bounded views** over those sets.*

**It must:**

- Own a question-scoped session over the published procurement dataset (and lazily over semantic resources)
- Expose typed operations for semantic search, structured Award resolution, aggregation, one-hop traversal, and Award citation evidence
- Keep DuckDB relation names, connections, Parquet paths, and `AwardSelection` internals hidden from callers
- Compose primarily via opaque `SelectionRef` values
- Retain and deduplicate acquired evidence for reuse within the session
- Bound only what crosses into model-visible payloads (never cap the cardinality of an internal selection used for aggregation)
- Fail clearly on stale/unknown refs and unavailable semantic resources

**It must not:**

- Duplicate query / semantic / traversal logic
- Expose storage-engine or DuckDB session internals to the model
- Ship unbounded Award ID lists through tool results as the default composition mechanism
- Implement the agent loop, LLM provider adapters, or answer synthesis (see [Procurement Agent Contract](agent.md))

## 2. Session Lifecycle

```text
EvidenceSession.open(data_root) → structured dataset only
    ↓
tool-calls...
    ↓
EvidenceSession.close() → release semantic (if any) + dataset; invalidate refs
```

- Open succeeds with a published set even when no semantic index / embedding deps exist
- Closing invalidates all `SelectionRef` values and retained registry state for that session
- Context-manager form is supported

## 3. Dual-Purpose Tools

Every tool call:

1. Runs the corresponding deterministic primitive
2. Updates the session registry (selections and/or evidence)
3. Returns a bounded `*View` DTO suitable for model context

### 3.1 Operations

| Operation                                  | Purpose                                                     |
| :----------------------------------------- | :---------------------------------------------------------- |
| `search_contract_work(query, …)`           | Semantic discovery → mint `SelectionRef` from hit Award IDs |
| `resolve_awards(filters, …)`               | Structured filters → mint `SelectionRef`                    |
| `aggregate_activity(selection, window, …)` | Deterministic obligation aggregation over a ref             |
| `traverse_relationships(selection, …)`     | One-hop related entities over a ref                         |
| `get_award_evidence(…)`                    | Bounded Award citation cards                                |

### 3.2 Return Views

| View                  | Contents                                                                                                                   |
| :-------------------- | :------------------------------------------------------------------------------------------------------------------------- |
| `SearchResultView`    | `selection: SelectionRef`, `count`, `hits: SemanticHitEvidence[]`                                                          |
| `ResolveResultView`   | `selection: SelectionRef`, `count`, `preview: AwardCard[]`                                                                 |
| `AggregateResultView` | `derived_from: SelectionRef`, bounded aggregate rows (+ retained `AggregateEvidence`)                                      |
| `TraversalResultView` | `derived_from: SelectionRef`, bounded `RelatedEntity[]`, `truncated` when the view is shorter than the full one-hop result |
| `AwardEvidenceView`   | bounded `AwardCard[]`                                                                                                      |

**Semantic `count`:** Number of retained semantic hits / Awards represented by that search result (the minted selection's size), *not corpus document count*

**Resolve `count`:** `AwardSelection.count` for the minted ref (may be huge); `preview` is the only Award-card payload returned from resolve

### 3.3 Composition

**Primary:** Pass `SelectionRef` between tools

Bounded raw `award_ids` are allowed where naturally useful (especially `get_award_evidence`). Explicit ID sets for selection minting remain available via `resolve_awards(AwardFilters(award_ids=…))`.

## 4. Opaque Selection Refs

```text
SelectionRef("sel_<session>_<n>") → (internal) AwardSelection + provenance
```

- Public surface is an opaque id string only (no relation name / dataset session id)
- IDs include a per-session token (`sel_<token>_<n>`) so refs cannot collide across sessions
- Unknown, foreign-session, or post-close refs fail with a typed evidence error
- Internal selections may represent arbitrarily large Award sets and remain valid inputs to aggregation / traversal

## 5. Registry Contents

Separate **canonical** Award evidence from **query-specific** retrieval evidence:

| Retained item                                | Dedup / keying                                                                                                             |
| :------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------- |
| `SelectionRef → AwardSelection + provenance` | unique ref id                                                                                                              |
| `AwardCard`                                  | dedupe by `award_id`                                                                                                       |
| `SemanticHitEvidence`                        | retained **separately** per search (score/query/text are retrieval-specific; same Award may appear under multiple queries) |
| `AggregateEvidence`                          | retained with `derived_from: SelectionRef`                                                                                 |
| `TraversalEvidence`                          | retained with `derived_from: SelectionRef`                                                                                 |

**Do not fold semantic score/text into `AwardCard`.**

## 6. Award Citation Card (`get_award_evidence`)

**Award-level citation only:**

- `award_id`, `piid`, `award_type_code`
- `recipient_id` / recipient name
- `base_description`
- Awarding agency / sub-agency / office identities + labels
- NAICS / PSC identities + labels
- Place-of-performance summary (available geo fields)
- `usaspending_permalink`

**Inputs (exactly one source):**

- `selection: SelectionRef` → first `limit` Awards by `award_id ASC`
- `award_ids: …` → bounded explicit ids (first-occurrence dedupe, then order preserved; reject when unique count exceeds award-card max)

*Never expand an entire large selection into model context.*

## 7. Bounds

Bounds apply to **model-visible payloads** only.

| Surface                     | Default | Max |
| :-------------------------- | ------: | --: |
| Semantic `top_k`            | 10      | 50  |
| Aggregate rows returned     | 10      | 100 |
| Award cards returned        | 10      | 50  |
| Traversal entities returned | 50      | 200 |

- Requested limits are clamped to the max; values `≤ 0` are rejected
- If a traversal **view** is truncated, set `truncated=true`. Callers that need exhaustive related sets for further computation must refine the selection first rather than treating the preview as complete
- Internal `SelectionRef` cardinality is **not** capped

## 8. Semantic Dependency (Lazy + Optional)

- `EvidenceSession.open` does **not** load Torch / sentence-transformers / BGE
- Only `search_contract_work` initializes semantic resources (embedder + published index)
- Missing optional deps, missing published index, or incompatible index → clear `SemanticUnavailableError` (or chained semantic errors); structured tools remain usable

## 9. Serialization

- Frozen `@dataclass(slots=True)` models
- No Pydantic in this layer
- Outward views/cards expose stable `to_dict()` for later tool/JSON adapters
- `from_dict()` only where structured tool input is actually deserialized (not required on every internal type)

## 10. Errors

**Typed failures (non-exhaustive):**
- Closed session
- Unknown/stale `SelectionRef`
- Invalid limits
- Semantic unavailable
- Underlying query/semantic/traversal errors surfaced without inventing results

## 11. Code Map

```text
src/cy_th/evidence/
├── types.py      # SelectionRef, AwardCard, retained evidence, *View DTOs, bounds
├── errors.py     # closed session / invalid ref / invalid request / semantic unavailable
├── tools.py      # dual-purpose ops + AwardCard hydration SQL
└── session.py    # EvidenceSession open/close, registry, lazy semantic
```

**Public entry:** `EvidenceSession` (methods delegate to `tools.py`)