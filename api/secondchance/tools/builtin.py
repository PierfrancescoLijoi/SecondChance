"""Built-in read-only tools. All data access inherits the caller's tenant transaction."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from secondchance.agents.planning import load_catalog
from secondchance.knowledge.retrieval import answer, search
from secondchance.tools.gateway import ToolContext, ToolGateway, ToolSpec

# mcp_client is the external MCP surface; specialists get a tool only by declaring it in the catalog.
_CATALOG = load_catalog()


class KnowledgeSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=500)
    space_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    language: Literal["en", "da", "pl", "it"] | None = None
    territory: str | None = Field(default=None, max_length=20)
    top_k: int = Field(default=6, ge=1, le=10)


class KnowledgeAnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=1000)
    space_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    language: Literal["en", "da", "pl", "it"] | None = None
    territory: str | None = Field(default=None, max_length=20)


def _knowledge_search(context: ToolContext, body: KnowledgeSearchInput) -> dict:
    hits = search(
        context.session,
        body.query,
        space_ids=body.space_ids,
        language=body.language,
        territory=body.territory,
        top_k=body.top_k,
    )
    return {
        "hits": [
            {
                "chunk_id": str(hit.chunk_id),
                "document_id": str(hit.document_id),
                "title": hit.title,
                "version": hit.version,
                "pages": [hit.page_start, hit.page_end],
                "language": hit.language,
                "content": hit.content[:1200],
                "score": hit.score,
            }
            for hit in hits
        ]
    }


def _knowledge_answer(context: ToolContext, body: KnowledgeAnswerInput) -> dict:
    result = answer(
        context.session,
        body.question,
        space_ids=body.space_ids,
        language=body.language,
        territory=body.territory,
    )
    return {
        "answer": result.text,
        "abstained": result.abstained,
        "reason": result.reason,
        "mode": result.mode,
        "model_id": result.model_id,
        "cited": result.cited,
        "sources": [
            {
                "chunk_id": str(hit.chunk_id), "document_id": str(hit.document_id),
                "title": hit.title, "version": hit.version,
                "pages": [hit.page_start, hit.page_end], "language": hit.language,
            }
            for hit in result.sources
        ],
    }


GATEWAY = ToolGateway()
GATEWAY.register(ToolSpec(
    name="knowledge_search",
    description="Hybrid RAG search over knowledge visible to the caller; returns sources, never a generated claim.",
    input_model=KnowledgeSearchInput,
    roles=frozenset({"coordinator", "org_admin", "volunteer", "center_staff", "platform_admin"}),
    agents=frozenset({"mcp_client"}) | _CATALOG.tool_callers("knowledge_search"),
    resource="knowledge_index",
    timeout_ms=8000,
    handler=_knowledge_search,
))
GATEWAY.register(ToolSpec(
    name="knowledge_answer",
    description="Grounded RAG answer with citations and explicit abstention when authorised evidence is insufficient.",
    input_model=KnowledgeAnswerInput,
    roles=frozenset({"coordinator", "org_admin", "volunteer", "center_staff", "platform_admin"}),
    agents=frozenset({"mcp_client"}),
    resource="knowledge_index",
    timeout_ms=25000,
    handler=_knowledge_answer,
))
