# 📦 Cy-TH

> [!NOTE]
> - **\[09/12/2026\]** Original document created to serve as loose outline for project's architecture.
> - **\[09/13/2026\]** Document updated to reflect changes in project's architecture relating to agentic workflow concepts.

Cy-TH (Cylitix-Takehome; very well-thought-out name, I know) is a natural-language intelligence layer for Department of Defense contract data.

It uses USASpending as its authoritative source and maintains a compact local representation of contract activity, entities, relationships, and semantic search material.

**The system is designed to answer questions that can require:**

- Direct award or transaction lookup
- Filtering and aggregation over contract activity
- Traversal across related recipients, agencies, offices, IDVs, locations, and classifications
- Semantic discovery from contract descriptions and classifications
- Combinations of structured, relational, and semantic reasoning

## Architecture

Cy-TH treats question answering as a **bounded evidence-acquisition workflow:**

```text
User Question
    ↓
Procurement Agent
    ├── interpret goal + constraints
    ├── choose tools
    ├── inspect acquired evidence
    ├── expand / refine search when needed
    ├── stop when evidence sufficient
    ▼
Grounded Answer + Evidence + Citations/Links/Card-objects/etc. (for human-facing UX)
```

**The agent will operate through typed tools over deterministic data services:**

```text
                       Procurement Agent
                              ↓
                         typed tools
       ┌──────────────────────┼──────────────────────┐
       ▼                      ▼                      ▼
Semantic Search /      Structured Query        Relationship
   Embeddings           + Aggregation           Traversal
       │                      │                      │
       └──────────────────────┼──────────────────────┘
                              ▼
                       DuckDB + Parquet
                              ↓
                       USASpending Data
                       + Lazy Enrichment
```

Wherein our model decides *what evidence to grab and when/if to continue searching.*

**Deterministic systems will remain responsible for:**

- Filtering + aggregation
- Any analytical calculations (math, ranking, monetary, etc.)
- Relationship traversal
- Similarity search
- Identity + deduplication
- Provenance, citations, data objects to be sent to any UI, etc.

## Design Principles

Evidence is accumulated across tool-calls so the agent can refine ambiguous concepts, compare retrievals, and combine/collate results before answering.

The local data layer will remain compact, while wider USASpending detail will be retrieved on-demand through source identifiers.

**The core design priorities are:**

1. **Correctness:** Preserve procurement semantics and avoid unsupported conclusions
2. **Provenance:** Keep answers traceable to authoritative source facts
3. **Efficacy:** Use the most effective chain of tools/retrievals/computations to answer the question accurately and fully
4. **Compactness:** Retain useful local structure without mirroring the full USASpending dataset
5. **Extensibility:** Keep data acquisition, reasoning, storage, and model-provider choices loosely coupled