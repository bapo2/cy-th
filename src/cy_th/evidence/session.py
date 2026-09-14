# cy_th/evidence/session.py

"""Question-scoped evidence session over deterministic procurement primitives."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import secrets
from types import TracebackType
from typing import Collection, Self, Sequence

from cy_th.evidence.errors import (
    ClosedEvidenceSessionError,
    InvalidSelectionRefError,
    SemanticUnavailableError,
)
from cy_th.evidence.types import (
    DEFAULT_AGGREGATE_LIMIT,
    DEFAULT_AWARD_CARD_LIMIT,
    DEFAULT_SEMANTIC_TOP_K,
    DEFAULT_TRAVERSAL_LIMIT,
    AggregateEvidence,
    AggregateResultView,
    AwardCard,
    AwardEvidenceView,
    ResolveResultView,
    SearchResultView,
    SelectionRef,
    SemanticHitEvidence,
    TraversalEvidence,
    TraversalResultView,
)
from cy_th.evidence import tools
from cy_th.query.dataset import ProcurementDataset
from cy_th.query.types import (
    ActivityWindow,
    AwardFilters,
    AwardSelection,
    EntityKind,
    GroupBy,
)
from cy_th.semantic.errors import (
    IncompatibleSemanticIndexError,
    MissingEmbeddingDepsError,
    MissingSemanticIndexError,
    SemanticError,
)
from cy_th.semantic.index import SemanticIndex


# === Registry Entries ===

@dataclass(frozen=True, slots=True)
class _SelectionEntry:
    """Internal selection + light provenance for a minted `SelectionRef`."""

    selection: AwardSelection
    source: str
    detail: str


# === Session ===

@dataclass(slots=True)
class EvidenceSession:
    """Model-facing evidence session over one published procurement dataset.

    Opens structured query resources only. Semantic index / embedder load lazily on the first `search_contract_work` call.
    """

    _dataset: ProcurementDataset
    _closed: bool = False
    _session_token: str = field(
        default_factory=lambda: secrets.token_hex(6),
        init=False,
        repr=False,
    )
    _selection_seq: int = field(default=0, init=False, repr=False)
    _selections: dict[str, _SelectionEntry] = field(
        default_factory=dict, init=False, repr=False
    )
    _award_cards: dict[str, AwardCard] = field(
        default_factory=dict, init=False, repr=False
    )
    _semantic_hits: list[SemanticHitEvidence] = field(
        default_factory=list, init=False, repr=False
    )
    _aggregates: list[AggregateEvidence] = field(
        default_factory=list, init=False, repr=False
    )
    _traversals: list[TraversalEvidence] = field(
        default_factory=list, init=False, repr=False
    )
    _semantic: SemanticIndex | None = field(default=None, init=False, repr=False)

    @classmethod
    def open(cls, data_root: Path | str | None = None) -> Self:
        """Open a session over the active published dataset (semantic deferred)."""

        return cls(_dataset=ProcurementDataset.open(data_root))

    @property
    def dataset(self) -> ProcurementDataset:
        """Underlying structured query session (not for model-facing use)."""

        self._ensure_open()
        return self._dataset

    @property
    def data_root(self) -> Path:
        return self.dataset.data_root

    @property
    def run_id(self) -> str:
        return self.dataset.run_id

    # --- Tool surface ---

    def search_contract_work(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_SEMANTIC_TOP_K,
        min_score: float | None = None,
        candidates: SelectionRef | None = None,
    ) -> SearchResultView:
        """Semantic discovery → mint `SelectionRef` from hit Award IDs."""

        self._ensure_open()
        return tools.search_contract_work(
            self,
            query,
            top_k=top_k,
            min_score=min_score,
            candidates=candidates,
        )

    def resolve_awards(
        self,
        filters: AwardFilters | None = None,
        *,
        preview_limit: int = DEFAULT_AWARD_CARD_LIMIT,
    ) -> ResolveResultView:
        """Structured filters → mint `SelectionRef` + bounded Award card preview."""

        self._ensure_open()
        return tools.resolve_awards(self, filters, preview_limit=preview_limit)

    def aggregate_activity(
        self,
        selection: SelectionRef,
        window: ActivityWindow,
        *,
        group_by: GroupBy = GroupBy.AWARD,
        limit: int = DEFAULT_AGGREGATE_LIMIT,
    ) -> AggregateResultView:
        """Deterministic obligation aggregation over a selection ref."""

        self._ensure_open()
        return tools.aggregate_activity(
            self,
            selection,
            window,
            group_by=group_by,
            limit=limit,
        )

    def traverse_relationships(
        self,
        selection: SelectionRef,
        *,
        include: Collection[EntityKind] | None = None,
        limit: int = DEFAULT_TRAVERSAL_LIMIT,
    ) -> TraversalResultView:
        """One-hop related entities over a selection ref."""

        self._ensure_open()
        return tools.traverse_relationships(
            self,
            selection,
            include=include,
            limit=limit,
        )

    def get_award_evidence(
        self,
        *,
        selection: SelectionRef | None = None,
        award_ids: Sequence[str] | None = None,
        limit: int = DEFAULT_AWARD_CARD_LIMIT,
    ) -> AwardEvidenceView:
        """Bounded Award citation cards from a selection or explicit IDs."""

        self._ensure_open()
        return tools.get_award_evidence(
            self,
            selection=selection,
            award_ids=award_ids,
            limit=limit,
        )

    # --- Lifecycle ---

    def close(self) -> None:
        """Release semantic (if any) + dataset; invalidate refs and registry."""

        if self._closed:
            return
        self._closed = True
        semantic = self._semantic
        self._semantic = None
        if semantic is not None:
            try:
                semantic.close()
            except Exception:
                pass
        try:
            self._dataset.close()
        finally:
            self._selections.clear()
            self._award_cards.clear()
            self._semantic_hits.clear()
            self._aggregates.clear()
            self._traversals.clear()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # --- Registry (tools / tests) ---

    def _mint_selection(
        self,
        selection: AwardSelection,
        *,
        source: str,
        detail: str,
    ) -> SelectionRef:
        self._ensure_open()
        self._selection_seq += 1
        ref = SelectionRef(
            id=f"sel_{self._session_token}_{self._selection_seq:04d}"
        )
        self._selections[ref.id] = _SelectionEntry(
            selection=selection,
            source=source,
            detail=detail,
        )
        return ref

    def _require_selection(self, ref: SelectionRef) -> AwardSelection:
        self._ensure_open()
        entry = self._selections.get(ref.id)
        if entry is None:
            raise InvalidSelectionRefError(
                ref_id=ref.id,
                detail="unknown or stale SelectionRef for this session",
            )
        return entry.selection

    def _upsert_award_cards(self, cards: Sequence[AwardCard]) -> None:
        for card in cards:
            self._award_cards[card.award_id] = card

    def _retain_semantic_hit(self, hit: SemanticHitEvidence) -> None:
        self._semantic_hits.append(hit)

    def _retain_aggregate(self, evidence: AggregateEvidence) -> None:
        self._aggregates.append(evidence)

    def _retain_traversal(self, evidence: TraversalEvidence) -> None:
        self._traversals.append(evidence)

    def _ensure_semantic(self) -> SemanticIndex:
        """Lazily open embedder + published semantic index for this dataset."""

        self._ensure_open()
        if self._semantic is not None:
            return self._semantic

        try:
            from cy_th.semantic.embed import SentenceTransformerEmbedder

            embedder = SentenceTransformerEmbedder()
            self._semantic = SemanticIndex.open(self._dataset, embedder)
        except (
            MissingEmbeddingDepsError,
            MissingSemanticIndexError,
            IncompatibleSemanticIndexError,
        ) as exc:
            raise SemanticUnavailableError(str(exc)) from exc
        except SemanticError as exc:
            raise SemanticUnavailableError(str(exc)) from exc

        return self._semantic

    def _ensure_open(self) -> None:
        if self._closed:
            raise ClosedEvidenceSessionError()
