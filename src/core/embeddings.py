"""Core embeddings abstractions — Protocol, shared types, and errors.

Kept in src/core so both the embedding adapters (src/stages/s10_embeddings.py)
and the vector store (src/stages/s11_vector_store.py) can import from here
without creating a circular dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class DimensionMismatchError(ValueError):
    """Raised when a vector's dimensionality doesn't match the collection's configured size."""


@dataclass
class SparseVector:
    """Sparse embedding represented as parallel index/value arrays (Qdrant format)."""

    indices: list[int] = field(default_factory=list)
    values: list[float] = field(default_factory=list)

    def is_empty(self) -> bool:
        return len(self.indices) == 0


@runtime_checkable
class EmbeddingAdapter(Protocol):
    """Protocol for embedding backend adapters — implement to add a new provider.

    Each adapter declares the model it wraps and the output dimensionality.
    EmbeddingService uses these to enforce the ARCH-4 invariant: a fallback
    adapter whose vector_dim differs from the primary is never used.
    """

    model_id: str
    vector_dim: int
    supports_sparse: bool

    async def embed(
        self,
        texts: list[str],
        task: str = "retrieval.passage",
    ) -> tuple[list[list[float]], list[SparseVector]]:
        """Embed a batch of texts. Returns (dense_vectors, sparse_vectors).

        sparse_vectors must always have len == len(texts). Adapters that
        don't support sparse must return a list of empty SparseVectors.
        """
        ...
