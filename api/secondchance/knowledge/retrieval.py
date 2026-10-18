"""Hybrid retrieval and grounded answers (ADR-004, ADR-015, FR-042..045).

Security before retrieval: every query runs in the caller's tenant transaction, so RLS has
already removed spaces the caller's network or role may not read. Lexical (Postgres FTS in
the query's language) and dense (pgvector cosine) candidates are fused with RRF in SQL.
"""

import os
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from secondchance.knowledge.embeddings import as_pgvector, provider
from secondchance.llm import guardrail, model, prompt
from secondchance.observability import meter

RRF_K = 60
CANDIDATES = 50
# Cosine distance beyond which a neighbour is not relevant; tune per embedding model on the
# golden set (FR-042). The hash embedding of local runs is lexical, so the cut is strict.
MAX_DENSE_DISTANCE = float(os.environ.get("SECONDCHANCE_MAX_DENSE_DISTANCE", "0.75"))

answers_counter = meter.create_counter("secondchance.knowledge.answers", description="Answers by mode and outcome")


@dataclass(frozen=True)
class Hit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    version: int
    section_path: list[str]
    page_start: int
    page_end: int
    language: str
    content: str
    score: float
    lexical_rank: int | None
    dense_distance: float | None


_SEARCH = text(
    """
    -- OR between terms: natural questions rarely contain every word of the answer;
    -- ts_rank_cd still ranks chunks matching more terms first.
    -- Without a declared language, the query is stemmed for it, en and da at once, plus the
    -- unstemmed words that match Polish ('simple') chunks: short queries cannot be
    -- language-detected reliably, and chunks keep their own dictionary.
    WITH q AS (SELECT CASE WHEN CAST(:lang AS text) IS NULL THEN
                   replace(plainto_tsquery('pg_catalog.italian', :query)::text, ' & ', ' | ')::tsquery
                   || replace(plainto_tsquery('pg_catalog.english', :query)::text, ' & ', ' | ')::tsquery
                   || replace(plainto_tsquery('pg_catalog.danish', :query)::text, ' & ', ' | ')::tsquery
                   || replace(plainto_tsquery('pg_catalog.simple', :query)::text, ' & ', ' | ')::tsquery
               ELSE replace(plainto_tsquery(fts_config(:lang), :query)::text, ' & ', ' | ')::tsquery END AS tsq,
               -- Polish has no stemmer: word prefixes stand in for one, on Polish chunks only.
               CASE WHEN CAST(:pl_prefixes AS text) IS NOT NULL THEN to_tsquery('pg_catalog.simple', :pl_prefixes) END AS plq),
    scoped AS (
        SELECT c.* FROM knowledge_chunk c
        JOIN document d ON d.id = c.document_id AND d.deleted_at IS NULL
        WHERE c.active
          AND (CAST(:spaces AS uuid[]) IS NULL OR c.space_id = ANY(CAST(:spaces AS uuid[])))
          AND (CAST(:territory AS text) IS NULL OR d.territory IS NULL OR d.territory = :territory)
    ),
    lexical AS (
        SELECT s.id, row_number() OVER (
                   ORDER BY ts_rank_cd(s.tsv, CASE WHEN s.language = 'pl' AND q.plq IS NOT NULL THEN q.tsq || q.plq ELSE q.tsq END) DESC, s.id
               ) AS rank
        FROM scoped s, q WHERE s.tsv @@ q.tsq OR (s.language = 'pl' AND s.tsv @@ q.plq)
        ORDER BY rank LIMIT :candidates
    ),
    dense AS (
        SELECT s.id, s.embedding <=> CAST(:vector AS vector) AS distance,
               row_number() OVER (ORDER BY s.embedding <=> CAST(:vector AS vector), s.id) AS rank
        FROM scoped s WHERE s.embedding_model = :model
          AND s.embedding <=> CAST(:vector AS vector) <= :max_distance
        ORDER BY distance LIMIT :candidates
    ),
    fused AS (
        SELECT coalesce(l.id, d.id) AS id,
               -- float8 as Hit.score declares; numeric would reach Python as Decimal
               (coalesce(1.0 / (:k + l.rank), 0) + coalesce(1.0 / (:k + d.rank), 0))::float8 AS score,
               l.rank AS lexical_rank, d.distance AS dense_distance
        FROM lexical l FULL OUTER JOIN dense d ON d.id = l.id
    )
    SELECT c.id AS chunk_id, c.document_id, doc.title, doc.active_version AS version, c.section_path,
           c.page_start, c.page_end, c.language, c.content, f.score, f.lexical_rank, f.dense_distance
    FROM fused f JOIN knowledge_chunk c ON c.id = f.id JOIN document doc ON doc.id = c.document_id
    ORDER BY f.score DESC, c.id LIMIT :top_k
    """
)


_WORD = re.compile(r"[^\W\d_]+")


def polish_prefixes(query: str) -> str | None:
    """`żywności chłodzonej` -> `żywno:* | chłodzo:*`: Polish inflects mostly in the last
    letters. Letters only, so the result is always a valid tsquery.
    ponytail: a crude stemmer; a Polish ispell dictionary replaces it if recall needs it (ADR-019)."""
    words = [w for w in _WORD.findall(query.lower()) if len(w) >= 5]
    return " | ".join(f"{w[:max(4, len(w) - 3)]}:*" for w in words) or None


def search(
    session: Session,
    query: str,
    *,
    space_ids: list[uuid.UUID] | None = None,
    language: str | None = None,
    territory: str | None = None,
    top_k: int = 8,
) -> list[Hit]:
    embedder = provider()
    rows = session.execute(
        _SEARCH,
        {"query": query, "lang": language, "spaces": space_ids, "territory": territory,
         "pl_prefixes": polish_prefixes(query) if language in (None, "pl") else None,
         "vector": as_pgvector(embedder.embed([query])[0]), "model": embedder.model,
         "candidates": CANDIDATES, "k": RRF_K, "top_k": top_k, "max_distance": MAX_DENSE_DISTANCE},
    ).mappings()
    return [Hit(**row) for row in rows]


def _is_evidence(hit: Hit) -> bool:
    return hit.lexical_rank is not None or (hit.dense_distance is not None and hit.dense_distance <= MAX_DENSE_DISTANCE)


@dataclass(frozen=True)
class Answer:
    text: str | None
    abstained: bool
    reason: str | None
    mode: str
    sources: list[Hit]  # numbered from 1, as cited in the text
    cited: list[int]
    model_id: str | None = None
    prompt_sha256: str | None = None


def answer(session: Session, question: str, **filters) -> Answer:
    """Abstains without calling a model when the evidence is not there (FR-045)."""
    evidence = [h for h in search(session, question, top_k=6, **filters) if _is_evidence(h)]
    if not evidence:
        answers_counter.add(1, {"mode": "none", "outcome": "abstained"})
        return Answer(None, True, "insufficient_evidence", "none", [], [])

    llm, guard = model(), guardrail()
    if llm is None:
        # Extractive fallback: the best sections, verbatim and cited; nothing generated.
        cited = evidence[:3]
        body = "\n\n".join(f"[{i}] {h.content[:500]}" for i, h in enumerate(cited, start=1))
        answers_counter.add(1, {"mode": "extractive", "outcome": "answered"})
        return Answer(body, False, None, "extractive", cited, list(range(1, len(cited) + 1)))

    if guard is not None and guard.blocks_question(question):
        answers_counter.add(1, {"mode": "generated", "outcome": "blocked_input"})
        return Answer(None, True, "guardrail_input", "generated", [], [], llm.model_id)

    system, sha = prompt("knowledge_answer.v1")
    sources = "\n\n".join(
        f"<source id=\"{i}\" title=\"{h.title}\" version=\"{h.version}\" pages=\"{h.page_start}-{h.page_end}\">\n{h.content}\n</source>"
        for i, h in enumerate(evidence, start=1)
    )
    completion = llm.complete(system, f"{sources}\n\nQuestion: {question}")
    cited_ids = {int(n) for n in re.findall(r"\[(\d+)\]", completion.text) if 0 < int(n) <= len(evidence)}
    grounded = (
        not completion.refused
        and completion.text.strip() != "ABSTAIN"
        and cited_ids
        and not (guard is not None and guard.blocks_answer(question, [h.content for h in evidence], completion.text))
    )
    if not grounded:
        answers_counter.add(1, {"mode": "generated", "outcome": "abstained"})
        return Answer(None, True, "not_grounded", "generated", [], [], llm.model_id, sha)
    answers_counter.add(1, {"mode": "generated", "outcome": "answered"})
    return Answer(completion.text, False, None, "generated", evidence, sorted(cited_ids), llm.model_id, sha)
