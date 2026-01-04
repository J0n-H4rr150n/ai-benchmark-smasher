import tensorflow as tf
import tensorflow_hub as hub
from typing import List
import numpy as np

class EmbeddingService:
    """Service to generate embeddings using Universal Sentence Encoder"""
    
    def __init__(self):
        self.preprocessor = None
        self.encoder = None
        self._initialized = False
    
    def _ensure_initialized(self):
        """Lazy load the models"""
        if not self._initialized:
            print("Loading Universal Sentence Encoder...")
            self.preprocessor = hub.KerasLayer(
                "https://kaggle.com/models/tensorflow/bert/TensorFlow2/en-uncased-preprocess/3"
            )
            self.encoder = hub.KerasLayer(
                "https://www.kaggle.com/models/google/universal-sentence-encoder/TensorFlow2/cmlm-en-base/1"
            )
            self._initialized = True
            print("Universal Sentence Encoder loaded successfully")
    
    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate 768-dimensional embedding for text
        
        Args:
            text: Input text to embed
            
        Returns:
            List of 768 floats representing the embedding
        """
        self._ensure_initialized()
        
        # Process text
        text_tensor = tf.constant([text])
        preprocessed = self.preprocessor(text_tensor)
        embedding_output = self.encoder(preprocessed)
        
        # Extract the "default" pooled output (768-dim)
        embedding_vector = embedding_output["default"][0].numpy()
        
        return embedding_vector.tolist()
    
    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embeddings, each 768 floats
        """
        self._ensure_initialized()
        
        # Process batch
        text_tensor = tf.constant(texts)
        preprocessed = self.preprocessor(text_tensor)
        embedding_output = self.encoder(preprocessed)
        
        # Extract embeddings
        embeddings = embedding_output["default"].numpy()
        
        return embeddings.tolist()


# Global singleton instance
_embedding_service = None

def get_embedding_service() -> EmbeddingService:
    """Get or create the embedding service singleton"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
