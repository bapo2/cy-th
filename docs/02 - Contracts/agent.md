# 🧠 Procurement Agent Contract

This document defines **how Cy-TH runs a bounded model-driven loop over the evidence tool surface** to answer natural-language procurement questions with grounded citations.

Canonical Parquet is authoritative ([Materialization](materialization.md), [Record Contracts](records.md)). Deterministic primitives stay in the [Query Contract](query.md), [Semantic Search Contract](semantic.md), and [Relationship Traversal Contract](traversal.md). Model-facing evidence tools stay in the [Evidence Tooling Contract](evidence.md).

*This layer will not reimplement existing services.*

## 1. Contract Statement

**The procurement agent is the orchestration boundary that calls evidence tools:**

```text
User Question
	→ ProcurementAgent (one EvidenceSession per question)
	→ ModelClient (OpenAI Responses, or injected FakeModelClient)
	→ tool calls: five evidence ops + submit_answer
	→ AgentAnswer (text, validated citations, trace, termination)
```

The model decides **what evidence to acquire.** Deterministic services remain responsible for filtering, aggregation, ranking, similarity, traversal, identity, and provenance.

The agent terminates only by calling `submit_answer`. *Prose alone is not a valid final act.*

**It must:**

- Open one `EvidenceSession` per `answer(question)` and reuse it across all tool rounds
- Interact with procurement data only through the evidence tool surface (plus the orchestration tool `submit_answer`)
- Expose the same five conceptual tools as evidence (`search_contract_work`, `resolve_awards`, `aggregate_activity`, `traverse_relationships`, `get_award_evidence`)
- Bound tool-use by configurable round and procurement tool-call budgets
- Retain acquired evidence across rounds (including semantic refinement)
- Return tool failures as bounded observations without inventing evidence
- Require `submit_answer` with `answer` + `citation_award_ids`
- Machine-validate citation IDs against Award cards actually acquired in the session
- Return a structured `AgentAnswer` including always-populated `tool_trace`

**It must not:**

- Access DuckDB, Parquet paths, semantic-index internals, or raw `AwardSelection` values
- Add Anthropic or untested "OpenAI-compatible" providers until we verify one model provider is working stably
- Treat free-text model output as the terminal answer (no regex extraction of citations)
- Fail the whole answer solely because some citation IDs were unknown

## 2. Lifecycle

```text
ProcurementAgent.open(data_root, model_client=...) → owns EvidenceSession
    ↓
answer(question) → bounded loop → AgentAnswer
    ↓
ProcurementAgent.close() → close EvidenceSession
```

- Context-manager form is supported
- Semantic resources remain lazy inside `EvidenceSession`
- `ModelClient` may be injected (tests); otherwise an OpenAI Responses client is constructed when needed

## 3. Loop Protocol

```text
LLM
 ├─ procurement tool → execute → observation → LLM again
 ├─ procurement tool → execute → observation → LLM again
 └─ submit_answer(answer, citation_award_ids)
    ↓
validate citation IDs against acquired AwardCards
    ↓
AgentAnswer
```

### 3.1 Tools Exposed to the Model

| Tool                     | Owner            | Purpose                                  |
| :----------------------- | :--------------- | :--------------------------------------- |
| `search_contract_work`   | EvidenceSession  | Semantic discovery → `SelectionRef`      |
| `resolve_awards`         | EvidenceSession  | Structured filters → `SelectionRef`      |
| `aggregate_activity`     | EvidenceSession  | Deterministic obligation aggregation     |
| `traverse_relationships` | EvidenceSession  | One-hop related entities                 |
| `get_award_evidence`     | EvidenceSession  | Bounded Award citation cards             |
| `submit_answer`          | Agent only       | Terminal act: prose + citation Award IDs |

JSON/schema parsing and dataclass conversion live in the agent adapter. `EvidenceSession` remains the authority for domain validation, opaque refs, bounds, and execution.

### 3.2 `submit_answer`

```json
{
  "answer": "...",
  "citation_award_ids": ["A1", "A7"]
}
```

- Required terminal tool for a successful run
- Normal rounds expose procurement tools **and** `submit_answer`
- On budget exhaustion: one final turn exposing **only** `submit_answer` (`tool_choice` required)

### 3.3 Parallel Tool Calls

If a model turn requests multiple procurement tools, execute them **sequentially** in response order. Each counts toward the tool-call budget. If the budget is exhausted mid-turn, do not dispatch further procurement calls; proceed to the forced `submit_answer` turn when applicable.

## 4. Budgets

| Budget                 | Default | Hard Max |
| :--------------------- | ------: | -------: |
| Model rounds           |       6 |       10 |
| Procurement tool calls |      12 |       24 |

- Requested limits above the hard max are clamped; values `≤ 0` are rejected
- A **round** is one processed model response
- A **tool call** is one dispatched procurement tool (success or handled failure). `submit_answer` *does not consume the tool-call budget*
- The model may call `submit_answer` at any point before the budget is exhausted

**On exhaustion (rounds or tool calls hit while more procurement work was requested / incomplete):**

1. Run one final tools-disabled turn with only `submit_answer` required
2. Return `termination_reason=BUDGET_EXHAUSTED` (not an exception)
3. State uncertainty / insufficient evidence rather than fabricate what a missing call would have established (prompt policy)

## 5. `AgentAnswer`

```text
AgentAnswer
  text: str
  citations: AwardCard[]                 # validated only
  dropped_citation_ids: str[]            # unknown IDs; normally empty
  termination_reason: TerminationReason
  rounds: int
  tool_calls: int
  tool_trace: ToolTraceEntry[]           # always populated; bounded by tool budget
```

### 5.1 `TerminationReason`

```text
ANSWERED
BUDGET_EXHAUSTED
ERROR
```

- Ordinary "couldn't establish X from available evidence" is still `ANSWERED`
- `ERROR` is for provider/transport (or equivalent) failures that abort the run; don't invent tool evidence

### 5.2 Citation Membership

1. Collect `citation_award_ids` from `submit_answer`
2. Keep IDs that exist in the session's acquired `AwardCard` registry (cards from resolve preview / `get_award_evidence`)
3. Drop unknown IDs into `dropped_citation_ids`
4. **Never fail the answer solely due to dropped IDs**

Prompt grounding covers broader factual discipline; citation membership is enforced exactly.

### 5.3 `tool_trace`

Always retained on the result for debugging and tests. Do not dump the full trace into answer prose by default.

## 6. Provider

- **One implementation (to start):** OpenAI Responses API function tools
- Config: `OPENAI_API_KEY`; `CYTH_MODEL` optional (default `gpt-5.6-sol`)
- Thin `ModelClient` protocol for test injection (`FakeModelClient`)

## 7. Prompt / Policy

- Prompt text lives in code (`prompts.py`); this contract documents the rules
- **Hard-enforce:** Budgets, schemas, opaque refs, tool dispatch, citation membership
- **Prompt-enforce:** Do not compute obligation totals / rankings / counts by model arithmetic when aggregation exists; prefer `SelectionRef` composition; cite only acquired Awards; on forced final turn, acknowledge gaps rather than invent results

## 8. Serialization

- Frozen `@dataclass(slots=True)` models
- No Pydantic in this layer
- Outward `AgentAnswer` / trace entries expose stable `to_dict()` where useful for smoke / adapters

## 9. Errors

**Typed failures (non-exhaustive):**

- Closed agent
- Invalid budgets / requests
- Missing API key when constructing the live OpenAI client
- Underlying evidence errors surfaced as **tool observations** when recoverable inside the loop

Provider failures that abort the run yield `termination_reason=ERROR` rather than fabricated evidence.

## 11. Code Map

🚧 TBD after implementation. 🚧
