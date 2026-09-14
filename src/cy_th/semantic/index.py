# cy_th/semantic/index.py

"""Session-scoped semantic index open / search / close."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Iterator, Self
import duckdb
import numpy as np
import numpy.typing as npt

from cy_th.query.dataset import ProcurementDataset
from cy_th.query.types import AwardSelection
from cy_th.schema.db_types import quote_ident
from cy_th.semantic.build import _close_memmap, validate_semantic_artifacts
from cy_th.semantic.embed import Embedder, l2_normalize_rows
from cy_th.semantic.errors import (
    ClosedSemanticIndexError,
    IncompatibleSemanticIndexError,
    InvalidSemanticQueryError,
)
from cy_th.semantic.paths import (
    DEFAULT_SEARCH_CHUNK_SIZE,
    documents_path,
    embeddings_path,
    semantic_dir,
)
from cy_th.semantic.search import IdChunk, top_k_from_id_chunks
from cy_th.semantic.types import (
    SearchDiagnostics,
    SearchResult,
    SemanticHit,
    SemanticMetadata,
)


# === Constants ===

_QUERY_NORM_EPS: float = 1e-8


# === Index ===

@dataclass(slots=True)
class SemanticIndex:
    """Read-only semantic search session bound to one `ProcurementDataset` open.

    Query encoding uses the injected `Embedder` (must match index model/dim). Search streams `(row_index, award_id)` chunks from Parquet and retains only a top-k heap (corpus identity not loaded into memory at open).
    """

    _dataset: ProcurementDataset
    _session_id: str
    _run_id: str
    _semantic_path: Path
    _embedder: Embedder
    _meta: SemanticMetadata
    _matrix: npt.NDArray[np.float32]
    _docs_view: str
    _lookup_conn: duckdb.DuckDBPyConnection
    _chunk_size: int = DEFAULT_SEARCH_CHUNK_SIZE
    _closed: bool = False

    @classmethod
    def open(
        cls,
        dataset: ProcurementDataset,
        embedder: Embedder,
        *,
        chunk_size: int = DEFAULT_SEARCH_CHUNK_SIZE,
    ) -> Self:
        """Open the published semantic index for `dataset.run_id`.

        #### Raises:
            - `MissingSemanticIndexError` / `IncompatibleSemanticIndexError` on artifact problems
            - `IncompatibleSemanticIndexError` when `embedder` model/dim doesn't match metadata
        """

        if chunk_size <= 0:
            raise ValueError("chunk_size must be > 0")

        run_id = dataset.run_id
        data_root = dataset.data_root
        session_id = dataset.session_id
        semantic_path = semantic_dir(data_root, run_id)
        meta = validate_semantic_artifacts(semantic_path, expected_run_id=run_id)

        if embedder.model_id != meta.model_id:
            raise IncompatibleSemanticIndexError(
                run_id=run_id,
                detail=(
                    f"embedder model_id {embedder.model_id!r} != index {meta.model_id!r}"
                ),
            )
        if embedder.embedding_dim != meta.embedding_dim:
            raise IncompatibleSemanticIndexError(
                run_id=run_id,
                detail=(
                    f"embedder dim {embedder.embedding_dim} != index {meta.embedding_dim}"
                ),
            )

        matrix = np.load(embeddings_path(semantic_path), mmap_mode="r")
        lookup = duckdb.connect()
        docs_view = f"semantic_documents_{session_id}"
        try:
            _register_docs_view(lookup, "documents", semantic_path, temporary=False)
            _register_docs_view(dataset.conn, docs_view, semantic_path, temporary=True)
        except Exception:
            _close_memmap(matrix)  # Needed so we don't get in-use errors
            lookup.close()
            raise

        return cls(
            _dataset=dataset,
            _session_id=session_id,
            _run_id=run_id,
            _semantic_path=semantic_path,
            _embedder=embedder,
            _meta=meta,
            _matrix=matrix,
            _docs_view=docs_view,
            _lookup_conn=lookup,
            _chunk_size=chunk_size,
        )

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def semantic_path(self) -> Path:
        return self._semantic_path

    @property
    def metadata(self) -> SemanticMetadata:
        return self._meta

    @property
    def document_count(self) -> int:
        return self._meta.document_count

    def search(
        self,
        query: str,
        *,
        candidates: AwardSelection | None = None,
        top_k: int = 50,
        min_score: float | None = None,
    ) -> SearchResult:
        """Rank Awards by cosine similarity to `query`."""

        self._ensure_usable()
        if top_k <= 0:
            raise ValueError("top_k must be > 0")
        if not query.strip():
            raise InvalidSemanticQueryError("blank query")

        query_vec = self._embed_query(query)

        if candidates is None:
            scored = top_k_from_id_chunks(
                self._matrix,
                query_vec,
                self._iter_corpus_id_chunks(),
                top_k=top_k,
                min_score=min_score,
            )
            diagnostics = SearchDiagnostics()
        else:
            self._dataset._require_selection(candidates)
            indexed_candidate_count = 0

            def candidate_chunks() -> Iterator[IdChunk]:
                nonlocal indexed_candidate_count
                for chunk in self._iter_candidate_id_chunks(candidates):
                    indexed_candidate_count += int(chunk.row_indices.shape[0])
                    yield chunk

            scored = top_k_from_id_chunks(
                self._matrix,
                query_vec,
                candidate_chunks(),
                top_k=top_k,
                min_score=min_score,
            )
            diagnostics = SearchDiagnostics(
                candidate_count=candidates.count,
                indexed_candidate_count=indexed_candidate_count,
            )

        details = self._hit_details([row.row_index for row in scored])
        hits = tuple(
            SemanticHit(
                award_id=row.award_id,
                document_id=details[row.row_index][0],
                score=row.score,
                text=details[row.row_index][1],
            )
            for row in scored
        )
        return SearchResult(hits=hits, diagnostics=diagnostics)

    def close(self) -> None:
        """Release memmap / DuckDB handles and invalidate this index."""

        if self._closed:
            return
        self._closed = True
        try:
            _close_memmap(self._matrix)
        finally:
            try:
                self._lookup_conn.close()
            finally:
                try:
                    self._dataset.conn.execute(
                        f"DROP VIEW IF EXISTS {quote_ident(self._docs_view)}"
                    )
                except Exception:
                    pass

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _ensure_usable(self) -> None:
        if self._closed:
            raise ClosedSemanticIndexError()
        if self._dataset._closed or self._dataset.session_id != self._session_id:
            raise ClosedSemanticIndexError(
                "owning ProcurementDataset session is closed or changed"
            )

    def _embed_query(self, query: str) -> npt.NDArray[np.float32]:
        vectors = self._embedder.embed([query])
        if vectors.shape != (1, self._meta.embedding_dim):
            raise InvalidSemanticQueryError(
                f"embedder returned shape {vectors.shape}, "
                f"expected (1, {self._meta.embedding_dim})"
            )
        vec = l2_normalize_rows(vectors)[0]
        if not np.isfinite(vec).all():
            raise InvalidSemanticQueryError("query embedding contains non-finite values")
        norm = float(np.linalg.norm(vec))
        if norm < _QUERY_NORM_EPS:
            raise InvalidSemanticQueryError("query embedding is a zero vector")
        return vec

    def _iter_corpus_id_chunks(self) -> Iterator[IdChunk]:
        result = self._lookup_conn.execute(
            f"""
            SELECT {quote_ident('row_index')}, {quote_ident('award_id')}
            FROM documents
            ORDER BY {quote_ident('row_index')} ASC
            """
        )
        yield from _fetch_id_chunks(result, self._chunk_size)

    def _iter_candidate_id_chunks(
        self,
        selection: AwardSelection,
    ) -> Iterator[IdChunk]:
        qdocs = quote_ident(self._docs_view)
        qsel = quote_ident(selection.relation_name)
        result = self._dataset.conn.execute(
            f"""
            SELECT d.{quote_ident('row_index')}, d.{quote_ident('award_id')}
            FROM {qdocs} AS d
            INNER JOIN {qsel} AS s
              ON s.{quote_ident('award_id')} = d.{quote_ident('award_id')}
            ORDER BY d.{quote_ident('row_index')} ASC
            """
        )
        yield from _fetch_id_chunks(result, self._chunk_size)

    def _hit_details(
        self,
        row_indices: list[int],
    ) -> dict[int, tuple[str, str]]:
        """Load `(document_id, text)` for the small top-k winner set only."""

        if not row_indices:
            return {}
        rows = self._lookup_conn.execute(
            f"""
            SELECT
              {quote_ident('row_index')},
              {quote_ident('document_id')},
              {quote_ident('text')}
            FROM documents
            WHERE {quote_ident('row_index')} IN (SELECT UNNEST(?))
            """,
            [row_indices],
        ).fetchall()
        return {int(row[0]): (str(row[1]), str(row[2])) for row in rows}


# === Helpers ===

def _register_docs_view(
    conn: duckdb.DuckDBPyConnection,
    view_name: str,
    semantic_path: Path,
    *,
    temporary: bool,
) -> None:
    """Register a view over the semantic documents parquet file."""

    parquet_sql = documents_path(semantic_path).resolve().as_posix().replace("'", "''")
    qname = quote_ident(view_name)
    conn.execute(f"DROP VIEW IF EXISTS {qname}")
    kind = "TEMP VIEW" if temporary else "VIEW"
    conn.execute(
        f"CREATE {kind} {qname} AS SELECT * FROM read_parquet('{parquet_sql}')"
    )

def _fetch_id_chunks(
    result: object,
    chunk_size: int,
) -> Iterator[IdChunk]:
    """Yield bounded `(row_index, award_id)` chunks from an executed DuckDB result."""

    fetchmany = getattr(result, "fetchmany")
    while True:
        rows = fetchmany(chunk_size)
        if not rows:
            break
        indices = np.asarray([int(row[0]) for row in rows], dtype=np.int64)
        award_ids = tuple(str(row[1]) for row in rows)
        yield IdChunk(row_indices=indices, award_ids=award_ids)
