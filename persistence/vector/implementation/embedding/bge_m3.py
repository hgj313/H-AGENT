import logging
import os

from dotenv import load_dotenv
load_dotenv()

from sentence_transformers import SentenceTransformer

from persistence.vector.protocol.embedding import BaseEmbedder

logger = logging.getLogger(__name__)


class BgeM3Embedder(BaseEmbedder):
    def __init__(
        self,
        model_name_or_path: str = "BAAI/bge-m3",
        device: str = None,
        normalize_embeddings: bool = True,
    ):
        if device is None:
            device = "cuda" if __import__("torch").cuda.is_available() else "cpu"
        bge_m3_model_path = os.getenv("BGE_M3_MODEL_PATH")
        model_name_or_path = bge_m3_model_path if bge_m3_model_path else model_name_or_path
        self.model = SentenceTransformer(model_name_or_path, device=device)
        self.normalize_embeddings = normalize_embeddings
        self._model_name = model_name_or_path

        logger.info(f"using device: {device} -- normalize_embeddings: {normalize_embeddings} -- model_name_or_path: {model_name_or_path}")

    @property
    def dimension(self) -> int:
        return self.model.get_embedding_dimension()

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=self.normalize_embeddings,
            convert_to_numpy=True,
            batch_size=32,
        )
        return embeddings.tolist()