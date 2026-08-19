"""Text chunking and vector retrieval over SQLite-stored embeddings."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import numpy as np
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeDocument
from app.services.llm import get_llm

logger = logging.getLogger(__name__)


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 80) -> list[str]:
    """Split text into overlapping character-based chunks, preferring sentence boundaries."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:].strip())
            break
        # Prefer break at punctuation / space
        window = text[start:end]
        break_at = max(
            window.rfind("。"),
            window.rfind("！"),
            window.rfind("？"),
            window.rfind("\n"),
            window.rfind(". "),
            window.rfind("; "),
            window.rfind("，"),
            window.rfind(" "),
        )
        if break_at > chunk_size // 3:
            end = start + break_at + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = max(end - overlap, start + 1)
    return chunks


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


async def index_document(
    db: Session,
    document: KnowledgeDocument,
) -> int:
    """Chunk document content, embed, and persist KnowledgeChunk rows."""
    # Clear existing chunks
    db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document.id).delete()
    db.flush()

    chunks = chunk_text(document.content)
    if not chunks:
        document.chunk_count = 0
        db.commit()
        return 0

    llm = get_llm()
    try:
        embeddings = await llm.embed(chunks)
    except Exception as exc:
        logger.warning("Embedding failed, storing chunks without vectors: %s", exc)
        embeddings = [None] * len(chunks)  # type: ignore[list-item]

    for i, (content, emb) in enumerate(zip(chunks, embeddings)):
        db.add(
            KnowledgeChunk(
                document_id=document.id,
                chunk_index=i,
                content=content,
                embedding=emb,
            )
        )
    document.chunk_count = len(chunks)
    db.commit()
    return len(chunks)


async def retrieve_context(
    db: Session,
    query: str,
    *,
    product_id: Optional[int] = None,
    brand_name: str = "",
    tenant_id: str = "default",
    top_k: int = 5,
) -> str:
    """Retrieve top-k relevant knowledge chunks as a context string."""
    result = await retrieve_context_with_hits(
        db,
        query,
        product_id=product_id,
        brand_name=brand_name,
        tenant_id=tenant_id,
        top_k=top_k,
    )
    return result["context"]


async def retrieve_context_with_hits(
    db: Session,
    query: str,
    *,
    product_id: Optional[int] = None,
    brand_name: str = "",
    tenant_id: str = "default",
    top_k: int = 5,
) -> dict[str, Any]:
    """Retrieve context plus auditable document/chunk hit metadata."""
    q = db.query(KnowledgeChunk).join(KnowledgeDocument).filter(
        KnowledgeDocument.tenant_id == tenant_id
    )
    if product_id is not None:
        q = q.filter(
            (KnowledgeDocument.product_id == product_id)
            | (
                KnowledgeDocument.product_id.is_(None)
                & (
                    (KnowledgeDocument.brand_name == "")
                    | (KnowledgeDocument.brand_name == brand_name)
                )
            )
        )
    chunks: list[KnowledgeChunk] = q.all()
    if not chunks:
        return {"context": "", "hits": [], "method": "none"}

    # Prefer vector search; fall back to keyword overlap
    with_emb = [c for c in chunks if c.embedding]
    scored_selected: list[tuple[Optional[float], KnowledgeChunk]] = []
    method = "keyword"
    if with_emb:
        try:
            llm = get_llm()
            query_emb = (await llm.embed([query]))[0]
            qvec = np.array(query_emb, dtype=np.float32)
            scored = []
            for c in with_emb:
                score = cosine_similarity(qvec, np.array(c.embedding, dtype=np.float32))
                scored.append((score, c))
            scored.sort(key=lambda x: x[0], reverse=True)
            scored_selected = [(score, chunk) for score, chunk in scored[:top_k]]
            method = "vector"
        except Exception as exc:
            logger.warning("Vector retrieval failed, using keyword fallback: %s", exc)
            selected = _keyword_retrieve(query, chunks, top_k)
            scored_selected = [(None, chunk) for chunk in selected]
    else:
        selected = _keyword_retrieve(query, chunks, top_k)
        scored_selected = [(None, chunk) for chunk in selected]

    if not scored_selected:
        return {"context": "", "hits": [], "method": method}

    parts = []
    hits = []
    for i, (score, c) in enumerate(scored_selected, 1):
        parts.append(f"[参考资料 {i}]\n{c.content}")
        document = c.document
        hits.append({
            "document_id": document.id,
            "document_title": document.title,
            "doc_type": document.doc_type,
            "scope": "product" if document.product_id else ("brand" if document.brand_name else "global"),
            "brand_name": document.brand_name,
            "chunk_id": c.id,
            "chunk_index": c.chunk_index,
            "score": round(score, 4) if score is not None else None,
            "excerpt": c.content[:220],
        })
    return {"context": "\n\n".join(parts), "hits": hits, "method": method}


def _keyword_retrieve(query: str, chunks: list[KnowledgeChunk], top_k: int) -> list[KnowledgeChunk]:
    tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", query.lower()))
    if not tokens:
        return chunks[:top_k]

    scored = []
    for c in chunks:
        content_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", c.content.lower()))
        overlap = len(tokens & content_tokens)
        if overlap > 0:
            scored.append((overlap, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]] or chunks[:top_k]
