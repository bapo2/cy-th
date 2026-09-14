# 📑 Semantic Search Contract

This document defines **how Cy-TH builds and queries a derived semantic index over the published canonical dataset.**

Canonical Parquet is authoritative ([Materialization](materialization.md), [Record Contracts](record-contracts.md)). Structured filtering and aggregation stay in the [Query Contract](query.md).

Code lives under `src/cy_th/semantic/`.

## 1. Contract Statement

Semantic search is a **rebuildable derived retrieval surface:**

```text
pinned canonical set (run-ID)
    → deterministic Award semantic documents
    → batched embeddings (BAAI/bge-small-en-v1.5)
    → disk-backed index under .data/derived/<run-id>/semantic/
    → chunked exact cosine search
    → SemanticHit[] → ProcurementDataset.select_awards(...)
```

**It must:**

- Keep one semantic document per indexable Award (`document_id = award:{award_id}`)
- Persist embeddings outside the immutable Parquet set
- Bind artifacts strictly to the pinned dataset `run_id`
- Support full-corpus search without loading the full embedding matrix into RAM
- Produce candidate evidence only (no obligations / monetary facts from similarity)
- Compose with session-scoped `AwardSelection` from the query runtime

## 2. Embedding Configuration

| Field     | Value                                                              |
| :-------- | :----------------------------------------------------------------- |
| Library   | `sentence-transformers` (optional install group `cy-th[semantic]`) |
| Model     | `BAAI/bge-small-en-v1.5`                                           |
| Dimension | `384`                                                              |
| Dtype     | `float32`                                                          |
| Normalize | `true` (document and query vectors)                                |
| Metric    | cosine ≡ dot product on L2-normalized vectors                      |

Query embeddings **must use the same model and configuration as the indexed documents.**

**Dependencies:**

- **Build** requires `cy-th[semantic]` (`sentence-transformers` + transitive Torch). Missing deps fail immediately with an install hint.
- **Search** over a published index requires only core deps (`numpy` + existing DuckDB/query stack). It must not import Torch / sentence-transformers.
- Tests use a deterministic fake embedder. `--offline` means cached weights only (any CI shouldn't require downloading model weights).

## 3. On-Disk Layout

```text
.data/
├── CURRENT
├── sets/<run-id>/...
└── derived/<run-id>/
    ├── .tmp-semantic/           # build staging (not opened by search)
    └── semantic/                # published index (search opens this)
        ├── documents.parquet
        ├── embeddings.npy
        └── metadata.json
```

**Published files:**

| Artifact            | Contents                                                      |
| :------------------ | :------------------------------------------------------------ |
| `documents.parquet` | `row_index`, `award_id`, `document_id`, `text`                |
| `embeddings.npy`    | shape `(N, 384)`, `float32`, C-contiguous, L2-normalized rows |
| `metadata.json`     | run + model fingerprint (see below)                           |

**Row alignment:**

- Documents sorted by `award_id ASC`
- `row_index = 0 .. N-1` in that order
- Embedding row `i` corresponds to document `row_index == i`
- `documents.parquet.row_index` is the row map (no sidecars)

**`metadata.json` records at least:**

- `run_id`
- `model_id`
- `model_revision` (resolved revision/hash when available, else null)
- `embedding_dim`
- `normalize`
- `metric` (`cosine`)
- `document_count`
- `text_budget` (`1800`)
- `sentence_transformers_version`
- Build timestamp (in UTC)

## 4. Build / Publish

**Our write path:** `cyth semantic build [--data-root .data] [--force]`.

1. Resolve `CURRENT` / open the pinned set
2. If `derived/<run-id>/semantic/` already exists → **refuse** unless `--force` (one published index per run-ID, regardless of model/config)
3. Build into sibling staging `derived/<run-id>/.tmp-semantic/`
4. Validate all artifacts (counts, shapes, metadata consistency, non-empty where required)
5. First build renames staging → `semantic/`; `--force` renames `semantic/` → `semantic.bak`, then staging → `semantic/`, restores the backup if that second rename fails, and deletes the backup after success

Search opens **only** the final published directory, never staging.

Mid-build crash may leave staging garbage; delete and rebuild. Never mutate a published index in-place.

## 5. Document Projection

### 5.1 Work-Bearing vs. Labels

**Work-bearing sources (any one makes an Award indexable):**

- Nonblank Award `base_description`
- Nonblank transaction `transaction_description` values
- Nonblank PSC classification `description`
- Nonblank NAICS classification `description`

**Supporting labels:** recipient name; awarding toptier name; awarding subtier name

**Labels alone don't make an Award indexable.** Bare PSC/NAICS codes with null/blank descriptions are *not work-bearing* and those lines are *omitted entirely.*

### 5.2 Text Normalization

| Use                | Rule                                           |
| :----------------- | :--------------------------------------------- |
| Readable body text | `collapse_whitespace(strip(s))`, preserve case |
| Txn dedupe key     | `casefold(collapse_whitespace(strip(s)))`      |

`collapse_whitespace` = split on Unicode whitespace and re-join with a single ASCII space.

### 5.3 Assembly Order

**We'll emit sections in this order, stopping when the 1800 Unicode codepoint budget is exhausted:**

1. Award description (if present)
2. PSC line (only if description present)
3. NAICS line (only if description present)
4. Unique transaction descriptions, *newest first* (`action_date DESC`, then `transaction_id ASC`); keep the newest when deduping; append while budget remains
5. Supporting labels last if budget remains (recipient, then awarding toptier, then awarding subtier)

**Budget:** `len(final_document) <= 1800` after assembly. Everything emitted counts (labels, separators, newlines). Truncate the last segment at a codepoint boundary so the final string never exceeds the cap.

**Section templates:**

```text
Award description: {text}
PSC: {code}; {description}
NAICS: {code}; {description}
Transaction work descriptions:
- {text}
- {text}
- ...
Recipient: {name}
Awarding agency: {toptier_name}
Awarding sub-agency: {subtier_name}
```

**Omit any section whose required fields are absent.** If no transaction lines survive, omit the `Transaction work descriptions:` header entirely.

`document_id` is always `award:{award_id}` (namespaced).

## 6. Search API

**Pattern:**

```python
with ProcurementDataset.open(".data") as ds:
    with SemanticIndex.open(ds, embedder) as index:
        hits = index.search(
            "detection systems",
            candidates=selection,  # Optional
            top_k=50,
            min_score=None,
        )
    semantic_selection = ds.select_awards([h.award_id for h in hits])
```

`SemanticIndex.open` takes an `Embedder` whose `model_id` / dimension must match the published index (search doesn't import sentence-transformers itself).

**Open:**

- Bind to dataset `run_id` and `session_id`
- Reject missing or incompatible published artifacts (run-ID / dim / normalize / metric / shape mismatch)
- Own memmap / file handles; support `close()` + context manager
- Closing the dataset invalidates the index; subsequent search fails clearly

**Query:**

- Blank / whitespace-only query → error
- Zero / near-zero / non-finite query embedding → error
- `min_score: float | None = None` → when set, drop hits below threshold; when absent, return best `top_k` (even if weak)

**Ranking:** `score DESC`, then `award_id ASC`. Deterministic for a given index + query + `top_k` / `min_score`

**Candidates:**

- `candidates=None` → sequential chunked full-corpus scan
- `AwardSelection` supplied → must match session (else `StaleSelectionError`); resolve `row_index` values, sort, score rows (in bounded chunks)
- Awards in the selection with no semantic row are **silently skipped** (expected w/ non-indexable Awards). Diagnostics can report `candidate_count` / `indexed_candidate_count` (we don't treat this as an error)

**Hits** include at least `award_id`, similarity `score`, inspectable `text` (and `document_id`). Semantic hit ID sets may be materialized through Python into `select_awards` (bounded `top_k`).

## 7. CLI

```text
cyth semantic build [--data-root .data] [--force] [--batch-size N] [--offline]
```

**Exit codes for `semantic build`:**

| Code | Meaning                                                                                                 |
| :--- | :------------------------------------------------------------------------------------------------------ |
| `0`  | Index built and published successfully                                                                  |
| `1`  | Failure (missing deps, missing/incompatible dataset/index, empty indexable set, validation error, etc.) |

## 8. Code Map

```text
src/cy_th/semantic/
├── paths.py      # derived / semantic / staging paths + locked constants
├── types.py      # SemanticDocument, SemanticHit, metadata, build/search results
├── errors.py     # missing/incompatible/build/query failures
├── documents.py  # projection + assembly (budget, dedupe, omit rules)
├── embed.py      # Embedder protocol + FakeEmbedder + SentenceTransformerEmbedder
├── metadata.py   # metadata.json serialize / load
├── build.py      # atomic build/publish + artifact validation
├── search.py     # chunked exact cosine top-k scoring
└── index.py      # SemanticIndex open / search / close
```
