"""Embedding providers behind one interface (ADR-015). All produce 1024-dimensional vectors.

- hash    (local default): deterministic feature hashing, offline, no model; lexical, not
           semantic and not cross-lingual. For tests and demos only.
- bedrock (AWS): Amazon Titan Text Embeddings V2, 1024 dimensions, normalised.
- ollama  (local, optional): any 1024-dimension model, e.g. bge-m3 (multilingual).
"""

import hashlib
import json
import math
import os
import re
import urllib.request
from functools import lru_cache
from typing import Protocol

DIMENSIONS = 1024


class EmbeddingProvider(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedding:
    model = "hash-1024-v1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    @staticmethod
    def _one(text: str) -> list[float]:
        vector = [0.0] * DIMENSIONS
        words = re.findall(r"\w+", text.lower())
        for feature in words + [a + " " + b for a, b in zip(words, words[1:])]:
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % DIMENSIONS
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]


class BedrockTitanEmbedding:
    model = "amazon.titan-embed-text-v2:0"

    def __init__(self) -> None:
        import boto3

        self.client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "eu-central-1"))

    def embed(self, texts: list[str]) -> list[list[float]]:
        # ponytail: one call per text; Bedrock batch inference when ingestion volume grows.
        vectors = []
        for text in texts:
            body = json.dumps({"inputText": text[:8000], "dimensions": DIMENSIONS, "normalize": True})
            response = self.client.invoke_model(modelId=self.model, body=body)
            vectors.append(json.loads(response["body"].read())["embedding"])
        return vectors


class OllamaEmbedding:
    def __init__(self, base_url: str, model: str) -> None:
        self.url = base_url.rstrip("/") + "/api/embed"
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        request = urllib.request.Request(
            self.url, data=json.dumps({"model": self.model, "input": texts}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            vectors = json.load(response)["embeddings"]
        if any(len(v) != DIMENSIONS for v in vectors):
            raise ValueError(f"{self.model} does not produce {DIMENSIONS}-dimensional vectors")
        return vectors


@lru_cache
def provider() -> EmbeddingProvider:
    kind = os.environ.get("SECONDCHANCE_EMBEDDINGS", "hash")
    if kind == "bedrock":
        return BedrockTitanEmbedding()
    if kind == "ollama":
        return OllamaEmbedding(os.environ["SECONDCHANCE_OLLAMA_URL"], os.environ.get("SECONDCHANCE_OLLAMA_EMBED_MODEL", "bge-m3"))
    return HashEmbedding()


def as_pgvector(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
