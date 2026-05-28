import logging
import os
from typing import Optional

import chromadb
from chromadb.config import Settings, DEFAULT_TENANT, DEFAULT_DATABASE

from persistence.vector.protocol.storage import BaseVectorStorage
from persistence.vector.implementation.domain import VectorItem
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
    def collection_name(self) -> str:
        return self._collection_name
    
    def add_vectors(self, items: list[VectorItem]) -> int:
        if not items:
            return 0
        
        processed_items = []
        skipped_count = 0
        
        for item in items:
            item_id = item.id
            
            if self._auto_generate_id and not item_id:
                item_id = VectorIdGenerator.generate(item.content)
                item = VectorItem(
                    id=item_id,
                    vector=item.vector,
                    content=item.content,
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
    
    def get_vectors(self, ids: list[str]) -> list[VectorItem]:
        if not ids:
            return []
        
        results = self._collection.get(ids=ids)
        
        if not results or not results.get('ids'):
            return []
        
        items = []
        for i, vector_id in enumerate(results['ids']):
            vector = results['embeddings'][i] if 'embeddings' in results else None
            content = results['documents'][i] if 'documents' in results else ""
            metadata = results['metadatas'][i] if 'metadatas' in results else {}
            
            items.append(VectorItem(
                id=vector_id,
                vector=vector,
                content=content,
                metadata=metadata
            ))
        
        return items
    
    def delete_vectors(self, ids: list[str]) -> int:
        if not ids:
            return 0
        
        self._collection.delete(ids=ids)
        logger.info(f"Deleted {len(ids)} vectors from ChromaDB collection {self._collection_name}")
        return len(ids)
    
    def update_vectors(self, items: list[VectorItem]) -> int:
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
    
    def search(
        self,
        query_vector: list[float],
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[tuple[VectorItem, float]]:
        results = self._collection.query(
            query_embeddings=[query_vector],
            n_results=k,
            where=filter_metadata
        )
        
        if not results or not results.get('ids'):
            return []
        
        items_with_scores = []
        for i, vector_id in enumerate(results['ids'][0]):
            vector = results['embeddings'][0][i] if 'embeddings' in results else None
            content = results['documents'][0][i] if 'documents' in results else ""
            metadata = results['metadatas'][0][i] if 'metadatas' in results else {}
            distance = results['distances'][0][i] if 'distances' in results else 0.0
            
            item = VectorItem(
                id=vector_id,
                vector=vector,
                content=content,
                metadata=metadata
            )
            items_with_scores.append((item, distance))
        
        return items_with_scores