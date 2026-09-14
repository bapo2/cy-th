# cy_th/semantic/build.py

"""Build and atomically publish a derived semantic index."""

# === Imports ===

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import shutil
import duckdb
import numpy as np
import numpy.typing as npt

from cy_th.query.dataset import ProcurementDataset
from cy_th.schema.db_types import quote_ident
from cy_th.semantic.documents import write_documents_parquet
from cy_th.semantic.embed import Embedder, prepare_document_embeddings
from cy_th.semantic.errors import (
    IncompatibleSemanticIndexError,
    MissingSemanticIndexError,
    SemanticError,
    SemanticIndexExistsError,
)
from cy_th.semantic.metadata import read_metadata, write_metadata
from cy_th.semantic.paths import (
    DEFAULT_EMBED_BATCH_SIZE,
    DOCUMENTS_PARQUET,
    EMBEDDING_DIM,
    EMBEDDINGS_NPY,
    METADATA_JSON,
    METRIC_COSINE,
    QUERY_PREFIX,
    TEXT_BUDGET,
    documents_path,
    embeddings_path,
    metadata_path,
    semantic_dir,
    semantic_staging_dir,
)
from cy_th.semantic.types import SemanticBuildResult, SemanticMetadata


# === Public API ===

def build_semantic_index(
    dataset: ProcurementDataset,
    embedder: Embedder,
    *,
    force: bool = False,
    batch_size: int = DEFAULT_EMBED_BATCH_SIZE,
    text_budget: int = TEXT_BUDGET,
) -> SemanticBuildResult:
    """Project documents, embed, validate in staging, then publish under `derived/<run-id>/semantic/`.

    Streams Award documents to Parquet, then fills `embeddings.npy` via memmap in batches so the full document list + the full embedding matrix isn't held in memory.

    #### Raises:
        - `SemanticIndexExistsError` when published index exists and `force` is `False`
        - `SemanticError` when no Awards are indexable
        - `IncompatibleSemanticIndexError` when staging validation fails
    """

    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")

    data_root = dataset.data_root
    run_id = dataset.run_id
    published = semantic_dir(data_root, run_id)
    staging = semantic_staging_dir(data_root, run_id)

    if published.exists() and not force:
        raise SemanticIndexExistsError(run_id=run_id, semantic_path=published)

    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=False)

    try:
        document_count = write_documents_parquet(
            dataset.conn,
            documents_path(staging),
            text_budget=text_budget,
        )
        if document_count == 0:
            raise SemanticError(
                f"no indexable Awards for run {run_id}; can't publish an empty semantic index"
            )

        _embed_documents_memmap(
            staging,
            embedder,
            document_count=document_count,
            batch_size=batch_size,
        )
        meta = SemanticMetadata(
            run_id=run_id,
            model_id=embedder.model_id,
            model_revision=embedder.model_revision,
            embedding_dim=embedder.embedding_dim,
            normalize=True,
            metric=METRIC_COSINE,
            query_prefix=QUERY_PREFIX,
            document_count=document_count,
            text_budget=text_budget,
            sentence_transformers_version=embedder.sentence_transformers_version,
            built_at=datetime.now(timezone.utc),
        )
        write_metadata(staging, meta)
        validate_semantic_artifacts(staging, expected_run_id=run_id)
        _publish_semantic_dir(staging=staging, published=published)
    except Exception:
        # Staging left for inspection when publish did not succeed
        raise

    return SemanticBuildResult(
        run_id=run_id,
        data_root=data_root,
        semantic_path=published,
        document_count=document_count,
        model_id=embedder.model_id,
        forced=force,
    )

def validate_semantic_artifacts(
    semantic_root: Path,
    *,
    expected_run_id: str | None = None,
) -> SemanticMetadata:
    """Validate documents / embeddings / metadata coherence under `semantic_root`."""

    docs = documents_path(semantic_root)
    emb = embeddings_path(semantic_root)
    meta_file = metadata_path(semantic_root)
    missing: list[str] = []
    if not docs.is_file():
        missing.append(DOCUMENTS_PARQUET)
    if not emb.is_file():
        missing.append(EMBEDDINGS_NPY)
    if not meta_file.is_file():
        missing.append(METADATA_JSON)
    if missing:
        raise MissingSemanticIndexError(
            run_id=expected_run_id or "unknown",
            semantic_path=semantic_root,
            detail=f"missing {', '.join(missing)}",
        )

    try:
        meta = read_metadata(semantic_root)
    except (OSError, ValueError, TypeError) as exc:
        raise IncompatibleSemanticIndexError(
            run_id=expected_run_id or "unknown",
            detail=f"unreadable metadata.json: {exc}",
        ) from exc

    run_id = expected_run_id or meta.run_id
    if expected_run_id is not None and meta.run_id != expected_run_id:
        raise IncompatibleSemanticIndexError(
            run_id=run_id,
            detail=f"metadata run_id {meta.run_id!r} != expected {expected_run_id!r}",
        )
    if meta.metric != METRIC_COSINE:
        raise IncompatibleSemanticIndexError(
            run_id=run_id, detail=f"metric must be {METRIC_COSINE!r}, got {meta.metric!r}"
        )
    if meta.query_prefix != QUERY_PREFIX:
        raise IncompatibleSemanticIndexError(
            run_id=run_id,
            detail=(
                f"query_prefix {meta.query_prefix!r} != locked {QUERY_PREFIX!r}"
            ),
        )
    if not meta.normalize:
        raise IncompatibleSemanticIndexError(
            run_id=run_id, detail="normalize must be true"
        )
    if meta.embedding_dim != EMBEDDING_DIM:
        raise IncompatibleSemanticIndexError(
            run_id=run_id,
            detail=f"embedding_dim must be {EMBEDDING_DIM}, got {meta.embedding_dim}",
        )
    if meta.document_count <= 0:
        raise IncompatibleSemanticIndexError(
            run_id=run_id, detail="document_count must be > 0"
        )

    matrix = np.load(emb, mmap_mode="r")
    try:
        if matrix.dtype != np.float32:
            raise IncompatibleSemanticIndexError(
                run_id=run_id,
                detail=f"embeddings dtype must be float32, got {matrix.dtype}",
            )
        if matrix.ndim != 2 or matrix.shape != (meta.document_count, meta.embedding_dim):
            raise IncompatibleSemanticIndexError(
                run_id=run_id,
                detail=(
                    f"embeddings shape {matrix.shape} != "
                    f"({meta.document_count}, {meta.embedding_dim})"
                ),
            )
    finally:
        _close_memmap(matrix)  # Needed so we don't get in-use errors

    conn = duckdb.connect()
    try:
        qdocs = quote_ident("documents")
        parquet_sql = docs.resolve().as_posix().replace("'", "''")
        conn.execute(
            f"CREATE VIEW {qdocs} AS SELECT * FROM read_parquet('{parquet_sql}')"
        )
        count_row = conn.execute(f"SELECT COUNT(*) FROM {qdocs}").fetchone()
        assert count_row is not None
        n = int(count_row[0])
        if n != meta.document_count:
            raise IncompatibleSemanticIndexError(
                run_id=run_id,
                detail=f"documents.parquet rows {n} != metadata.document_count {meta.document_count}",
            )

        bad = conn.execute(
            f"""
            SELECT COUNT(*) FROM (
              SELECT
                {quote_ident('row_index')},
                {quote_ident('award_id')},
                ROW_NUMBER() OVER (ORDER BY {quote_ident('award_id')} ASC) - 1 AS expected_idx
              FROM {qdocs}
            ) AS t
            WHERE {quote_ident('row_index')} IS DISTINCT FROM expected_idx
            """
        ).fetchone()
        assert bad is not None
        if int(bad[0]) != 0:
            raise IncompatibleSemanticIndexError(
                run_id=run_id,
                detail="documents.parquet row_index must be 0..N-1 in award_id ASC order",
            )

        nulls = conn.execute(
            f"""
            SELECT COUNT(*) FROM {qdocs}
            WHERE {quote_ident('award_id')} IS NULL
              OR {quote_ident('document_id')} IS NULL
              OR {quote_ident('text')} IS NULL
            """
        ).fetchone()
        assert nulls is not None
        if int(nulls[0]) != 0:
            raise IncompatibleSemanticIndexError(
                run_id=run_id, detail="documents.parquet has null award_id/document_id/text"
            )
    finally:
        conn.close()

    return meta


# === Helpers ===

def _publish_semantic_dir(*, staging: Path, published: Path) -> None:
    """Publish staging into `published` without deleting a known-good index first.

    #### Workflow:
        1. First publish: `staging` → `published`.
        2. Replace `published` → `published.bak`, then `staging` → `published`
        3. Restore backup if the second rename fails; delete backup only after success
    """

    published.parent.mkdir(parents=True, exist_ok=True)
    if not published.exists():
        staging.rename(published)
        return

    backup = published.with_name(f"{published.name}.bak")
    if backup.exists():
        shutil.rmtree(backup)

    published.rename(backup)
    try:
        staging.rename(published)
    except Exception:
        if not published.exists() and backup.exists():
            backup.rename(published)
        raise

    shutil.rmtree(backup)

def _close_memmap(array: npt.NDArray[np.generic]) -> None:
    """Release numpy memmap file handles (sometimes needed before rmtree/rename)."""

    mmap = getattr(array, "_mmap", None)
    if mmap is not None:
        mmap.close()
    base = getattr(array, "base", None)
    if base is not None and base is not array:
        nested = getattr(base, "_mmap", None)
        if nested is not None:
            nested.close()

def _embed_documents_memmap(
    semantic_root: Path,
    embedder: Embedder,
    *,
    document_count: int,
    batch_size: int,
) -> None:
    """Embed documents from Parquet into a memmapped `embeddings.npy` in batches."""

    dim = embedder.embedding_dim
    emb_path = embeddings_path(semantic_root)
    docs_path = documents_path(semantic_root)
    matrix = np.lib.format.open_memmap(
        emb_path,
        mode="w+",
        dtype=np.float32,
        shape=(document_count, dim),
    )
    lookup = duckdb.connect()
    try:
        parquet_sql = docs_path.resolve().as_posix().replace("'", "''")
        lookup.execute(
            f"CREATE VIEW documents AS SELECT * FROM read_parquet('{parquet_sql}')"
        )
        for start in range(0, document_count, batch_size):
            stop = min(start + batch_size, document_count)
            rows = lookup.execute(
                f"""
                SELECT {quote_ident('text')}
                FROM documents
                WHERE {quote_ident('row_index')} >= ?
                  AND {quote_ident('row_index')} < ?
                ORDER BY {quote_ident('row_index')} ASC
                """,
                [start, stop],
            ).fetchall()
            if len(rows) != stop - start:
                raise RuntimeError(
                    f"expected {stop - start} document texts for rows [{start}, {stop}), "
                    f"got {len(rows)}"
                )
            vectors = embedder.embed([str(row[0]) for row in rows])
            matrix[start:stop] = prepare_document_embeddings(
                vectors,
                expected_rows=len(rows),
                expected_dim=dim,
            )
        matrix.flush()
    finally:
        lookup.close()
        _close_memmap(matrix)  # Needed so we don't get in-use errors
