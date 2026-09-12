# 📦 Cy-TH

Cy-TH (Cylitix-Takehome; very well-thought-out name, I know) is a natural-language intelligence layer for Department of Defense contract data.

It uses USASpending as its authoritative source and maintains a compact local representation of contract activity, important entities, and their relationships.

**The system is designed to answer questions that can require:**

- Direct award or transaction lookup
- Filtering and aggregation over contract activity
- Traversal across related recipients, agencies, offices, IDVs, locations, and classifications
- Semantic discovery from contract descriptions and classifications
- Combinations of structured, relational, and semantic reasoning

Cy-TH does not treat an LLM, vector index, or knowledge graph as the source of truth.

**Instead:**

```text
USASpending
    ↓
authoritative procurement facts
    ↓
compact local relationship + activity model
    ↓
query planning and retrieval
    ↓
grounded answer + provenance
```

The local dataset contains the information required for common questions and relationship discovery. Wider USASpending detail can be retrieved on demand through stable source identifiers.

**The core design priorities are:**

1. **Correctness:** Preserve procurement semantics and avoid unsupported conclusions
2. **Provenance:** Keep answers traceable to authoritative source facts
3. **Effective Retrieval:** Use the retrieval or computation method best suited to each question
4. **Compactness:** Retain useful local structure without mirroring the full USASpending dataset
5. **Extensibility:** Keep data acquisition, reasoning, storage, and model-provider choices loosely coupled
