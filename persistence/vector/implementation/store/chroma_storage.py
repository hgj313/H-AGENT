import logging
import os
from typing import Optional, Literal

import chromadb
from chromadb.config import Settings, DEFAULT_TENANT, DEFAULT_DATABASE

from persistence.vector.protocol.storage import BaseVectorStorage
from persistence.vector.implementation.domain.engine import EngineVectorItem
from persistence.vector.implementation.domain.id_generator import VectorIdGenerator

logger = logging.getLogger(__name__)


class ChromaVectorStorage(BaseVectorStorage):
    """ChromaDB 向量存储实现"""
    
    def __init__(
        self,
        dimension: int = 1024,
        collection_name: str = "vectors",
        persist_directory: Optional[str] = None,
        client: Optional[chromadb.Client] = None,
        auto_generate_id: bool = True,
        skip_duplicates: bool = True,
        use_remote: bool = False,
        remote_host: str = "localhost",
        remote_port: int = 8000,
    ):
        super().__init__(dimension)
        
        self._collection_name = collection_name
        self._auto_generate_id = auto_generate_id
        self._skip_duplicates = skip_duplicates
        
        if persist_directory is None:
            _module_dir = os.path.dirname(os.path.abspath(__file__))
            _project_root = os.path.dirname(os.path.dirname(os.path.dirname(_module_dir)))
            persist_directory = os.path.join(_project_root, "data", "chroma_db")
        
        self._persist_directory = persist_directory
        
        os.makedirs(self._persist_directory, exist_ok=True)
        
        if client is None:
            if use_remote:
                self._client = chromadb.HttpClient(
                    host=remote_host,
                    port=remote_port,
                    ssl=False,
                    settings=Settings(),
                    tenant=DEFAULT_TENANT,
                    database=DEFAULT_DATABASE,
                )
                logger.info(f"ChromaStore connected to remote: {remote_host}:{remote_port}")
            else:
                self._client = chromadb.PersistentClient(
                    path=persist_directory,
                    settings=Settings(),
                    tenant=DEFAULT_TENANT,
                    database=DEFAULT_DATABASE,
                )
                logger.info(f"ChromaStore initialized locally: path={persist_directory}")
            
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        else:
            self._client = client
        
        try:
            self._collection = self._client.get_collection(name=self._collection_name)
            logger.info(f"Connected to existing ChromaDB collection: {self._collection_name}")
        except Exception:
            self._collection = self._client.create_collection(
                name=self._collection_name,
                metadata={"dimension": dimension}
            )
            logger.info(f"Created new ChromaDB collection: {self._collection_name}")
    
    @property
    def count(self) -> int:
        return self._collection.count()
    
    @property
    def distance_metric(self) -> Literal["cosine", "l2", "ip"]:
        collection_metadata = self._collection.metadata or {}
        return collection_metadata.get("hnsw:space", "cosine")
    
    @property
    def collection_name(self) -> str:
        return self._collection_name
    
    def add_vectors(self, items: list[EngineVectorItem]) -> int:
        if not items:
            return 0
        
        processed_items = []
        skipped_count = 0
        
        for item in items:
            item_id = item.id
            
            if self._auto_generate_id and not item_id:
                item_id = VectorIdGenerator.generate(item.content)
                item = EngineVectorItem(
                    id=item_id,
                    content=item.content,
                    vector=item.vector,
                    metadata=item.metadata,
                    chunk_index=item.chunk_index,
                    chunk_type=item.chunk_type
                )
            
            if self._skip_duplicates and item_id:
                existing = self._collection.get(ids=[item_id])
                if existing and existing.get('ids') and item_id in existing['ids']:
                    logger.debug(f"Skipping duplicate ID: {item_id}")
                    skipped_count += 1
                    continue
            
            processed_items.append(item)
        
        if not processed_items:
            logger.info(f"All {skipped_count} items were duplicates, skipped")
            return 0
        
        ids = [item.id for item in processed_items]
        embeddings = [item.vector for item in processed_items]
        documents = [item.content for item in processed_items]
        metadatas = [item.metadata for item in processed_items]
        
        logger.debug(f"Adding vectors - count: {len(ids)}, embeddings sample: {embeddings[0][:5] if embeddings and embeddings[0] else None}")
        
        self._collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )
        
        total = len(processed_items)
        logger.info(f"Added {total} vectors to ChromaDB collection {self._collection_name}" +
                   (f", skipped {skipped_count} duplicates" if skipped_count > 0 else ""))
        
        return total
    
    def get_vectors(self, ids: list[str]) -> list[EngineVectorItem]:
        if not ids:
            return []
        
        results = self._collection.get(
            ids=ids,
            include=["embeddings", "documents", "metadatas"]
        )
        
        if not results or not results.get('ids'):
            logger.debug(f"No results found for ids: {ids}")
            return []
        
        logger.debug(f"Get results - ids count: {len(results.get('ids', []))}")
        logger.debug(f"Get results - embeddings type: {type(results.get('embeddings'))}")
        logger.debug(f"Get results - embeddings value: {results.get('embeddings')}")
        
        items = []
        for i, vector_id in enumerate(results['ids']):
            item = EngineVectorItem.from_chroma_result(vector_id, i, results)
            items.append(item)
        
        return items
    
    def delete_vectors(self, ids: list[str]) -> int:
        if not ids:
            return 0
        
        self._collection.delete(ids=ids)
        logger.info(f"Deleted {len(ids)} vectors from ChromaDB collection {self._collection_name}")
        return len(ids)
    
    def update_vectors(self, items: list[EngineVectorItem]) -> int:
        if not items:
            return 0
        
        ids = [item.id for item in items]
        embeddings = [item.vector for item in items]
        documents = [item.content for item in items]
        metadatas = [item.metadata for item in items]
        
        self._collection.update(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )
        
        logger.info(f"Updated {len(items)} vectors in ChromaDB collection {self._collection_name}")
        return len(items)