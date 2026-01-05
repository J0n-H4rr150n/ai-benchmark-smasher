from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import List, Optional

from ..config import settings

logger = logging.getLogger(__name__)

class EmbeddingService:
    """Service to generate embeddings for pgvector similarity search.

    Preferred: Vertex AI text embeddings (768-dim).
    Fallback: deterministic hash-based embedding (768-dim) for offline reliability.
    """
    
    def __init__(self):
        self._vertex_model = None
        self._vertex_init_attempted = False

        self._kaggle_preprocessor = None
        self._kaggle_encoder = None
        self._kaggle_init_attempted = False
        self._kaggle_last_error: Optional[str] = None

        # When EMBEDDING_PROVIDER=auto we pick one provider once and stick to it
        # for the lifetime of this process, to avoid mixing embedding spaces.
        self._active_provider: Optional[str] = None

    def _embedding_provider(self) -> str:
        provider = (getattr(settings, "embedding_provider", "auto") or "auto").strip().lower()
        if provider in {"kaggle", "tfhub", "kaggle-tfhub"}:
            return "kaggle_tfhub"
        if provider in {"vertex", "vertex_ai", "vertexai"}:
            return "vertexai"
        if provider in {"hash", "local"}:
            return "hash"
        if provider in {"auto", ""}:
            # Sticky auto: decide once, then reuse.
            if self._active_provider:
                return self._active_provider

            # Prefer Kaggle TF-Hub, then Vertex, then hash.
            self._ensure_kaggle_tfhub_model()
            if self._kaggle_preprocessor is not None and self._kaggle_encoder is not None:
                self._active_provider = "kaggle_tfhub"
            else:
                self._ensure_vertex_model()
                if self._vertex_model is not None:
                    self._active_provider = "vertexai"
                else:
                    self._active_provider = "hash"

            try:
                logger.info(f"[EMBEDDINGS] Using provider={self._active_provider} (selected via auto)")
            except Exception:
                pass

            return self._active_provider
        # Unknown provider -> treat as auto to avoid hard failures from typos
        return "auto"
    
    def _ensure_vertex_model(self):
        if self._vertex_init_attempted:
            return
        self._vertex_init_attempted = True

        try:
            import vertexai
            from vertexai.language_models import TextEmbeddingModel
            from ..config import settings

            vertexai.init(project=settings.gcp_project_id, location=settings.gemini_location)
            self._vertex_model = TextEmbeddingModel.from_pretrained(settings.embedding_model)
        except Exception:
            self._vertex_model = None

    def _ensure_kaggle_tfhub_model(self) -> None:
        """Lazy load TF-Hub models hosted on Kaggle.

        Note: This requires outbound access to kaggle.com and the TF Hub stack.
        """
        if self._kaggle_init_attempted:
            return
        self._kaggle_init_attempted = True

        try:
            # Required for the Kaggle BERT preprocessor SavedModel (text ops like CaseFoldUTF8).
            import tensorflow_text  # noqa: F401
            import tensorflow_hub as hub

            # Keep these URLs aligned with the DB schema (768 dims).
            self._kaggle_preprocessor = hub.KerasLayer(
                "https://kaggle.com/models/tensorflow/bert/TensorFlow2/en-uncased-preprocess/3"
            )
            self._kaggle_encoder = hub.KerasLayer(
                "https://www.kaggle.com/models/google/universal-sentence-encoder/TensorFlow2/cmlm-en-base/1"
            )
        except Exception as e:
            self._kaggle_preprocessor = None
            self._kaggle_encoder = None
            try:
                self._kaggle_last_error = f"TF-Hub Kaggle model init failed: {e}"
            except Exception:
                self._kaggle_last_error = "TF-Hub Kaggle model init failed"

    def _kaggle_tfhub_embeddings(self, texts: List[str]) -> Optional[List[List[float]]]:
        self._ensure_kaggle_tfhub_model()
        if self._kaggle_preprocessor is None or self._kaggle_encoder is None:
            return None

        try:
            import tensorflow as tf

            text_tensor = tf.constant(texts)
            preprocessed = self._kaggle_preprocessor(text_tensor)
            embedding_output = self._kaggle_encoder(preprocessed)

            # The encoder returns a dict-like output; use the pooled 768-dim embedding.
            arr = embedding_output["default"].numpy()
            return [self._coerce_dims([float(x) for x in row.tolist()], dims=768) for row in arr]
        except Exception as e:
            try:
                self._kaggle_last_error = f"TF-Hub Kaggle embedding failed: {e}"
            except Exception:
                self._kaggle_last_error = "TF-Hub Kaggle embedding failed"
            return None

    @staticmethod
    def _hash_embedding(text: str, dims: int = 768) -> List[float]:
        """Deterministic, lightweight embedding for offline use.

        Uses feature hashing over tokens into a fixed-size vector and L2 normalizes.
        This is not as semantically rich as a real embedding model but keeps search usable.
        """
        if not text:
            return [0.0] * dims

        vec = [0.0] * dims
        tokens = re.findall(r"[a-z0-9_\-]{2,}", text.lower())
        if not tokens:
            return [0.0] * dims

        for tok in tokens:
            h = int(hashlib.sha256(tok.encode("utf-8")).hexdigest(), 16)
            idx = h % dims
            sign = -1.0 if ((h >> 1) & 1) else 1.0
            vec[idx] += sign

        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            return vec
        return [x / norm for x in vec]

    @staticmethod
    def _coerce_dims(values: List[float], dims: int = 768) -> List[float]:
        if len(values) == dims:
            return values
        if len(values) > dims:
            return values[:dims]
        return values + ([0.0] * (dims - len(values)))
    
    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate 768-dimensional embedding for text
        
        Args:
            text: Input text to embed
            
        Returns:
            List of 768 floats representing the embedding
        """
        provider = self._embedding_provider()
        strict = bool(getattr(settings, "embedding_strict", False))

        # 1) Kaggle TF-Hub (optional)
        if provider in {"kaggle_tfhub", "auto"}:
            embs = self._kaggle_tfhub_embeddings([text])
            if embs is not None:
                return embs[0]
            if provider == "kaggle_tfhub" and strict:
                detail = self._kaggle_last_error or "Kaggle TF-Hub provider failed"
                raise RuntimeError(f"{detail} (EMBEDDING_PROVIDER=kaggle_tfhub, EMBEDDING_STRICT=1)")

        # 2) Vertex AI embeddings (optional)
        if provider in {"vertexai", "auto"}:
            self._ensure_vertex_model()
            if self._vertex_model is not None:
                try:
                    embeddings = self._vertex_model.get_embeddings([text])
                    values = list(embeddings[0].values)
                    return self._coerce_dims([float(x) for x in values], dims=768)
                except Exception:
                    if provider == "vertexai" and strict:
                        raise RuntimeError("Vertex AI embedding provider failed and EMBEDDING_STRICT is enabled")

        # 3) Deterministic local fallback
        if provider == "hash":
            return self._hash_embedding(text, dims=768)

        if strict and provider not in {"auto"}:
            raise RuntimeError(f"Embedding provider '{provider}' failed and EMBEDDING_STRICT is enabled")

        return self._hash_embedding(text, dims=768)
    
    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embeddings, each 768 floats
        """
        provider = self._embedding_provider()
        strict = bool(getattr(settings, "embedding_strict", False))

        if provider in {"kaggle_tfhub", "auto"}:
            embs = self._kaggle_tfhub_embeddings(texts)
            if embs is not None:
                return embs
            if provider == "kaggle_tfhub" and strict:
                detail = self._kaggle_last_error or "Kaggle TF-Hub provider failed"
                raise RuntimeError(f"{detail} (EMBEDDING_PROVIDER=kaggle_tfhub, EMBEDDING_STRICT=1)")

        if provider in {"vertexai", "auto"}:
            self._ensure_vertex_model()
            if self._vertex_model is not None:
                try:
                    embeddings = self._vertex_model.get_embeddings(texts)
                    return [
                        self._coerce_dims([float(x) for x in list(e.values)], dims=768)
                        for e in embeddings
                    ]
                except Exception:
                    if provider == "vertexai" and strict:
                        raise RuntimeError("Vertex AI embedding provider failed and EMBEDDING_STRICT is enabled")

        if provider == "hash":
            return [self._hash_embedding(t, dims=768) for t in texts]

        if strict and provider not in {"auto"}:
            raise RuntimeError(f"Embedding provider '{provider}' failed and EMBEDDING_STRICT is enabled")

        return [self._hash_embedding(t, dims=768) for t in texts]


# Global singleton instance
_embedding_service = None

def get_embedding_service() -> EmbeddingService:
    """Get or create the embedding service singleton"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
