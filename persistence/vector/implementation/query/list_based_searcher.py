"""
统一向量查询器（列表式 / 后端无关）

设计思想：
    ListBasedVectorSearcher 是协议层 BaseVectorSearcher 的**唯一**实现。
    它不绑定任何具体向量数据库（Chroma / Milvus / Qdrant ...），
    而是通过依赖注入适配任意后端：

        BaseVectorSearcher (协议)
                 ↑
        ListBasedVectorSearcher
                 ├── inject: BaseEmbedder        （任意 embedding 模型）
                 ├── inject: BaseVectorStorage   （任意向量库存储）
                 └── inject: BaseSearchEngine   （对应后端的搜索引擎）

    后端切换 = 换注入的 storage / search_engine 实例，无需修改本类任何代码。

    推荐组合（storage 与 search_engine 须来自同一后端）：
        Chroma:  ChromaVectorStorage  + ChromaSearchEngine
        Milvus:  MilvusVectorStorage  + MilvusSearchEngine
        Qdrant:  QdrantVectorStorage  + QdrantSearchEngine
"""
import logging
from typing import Optional

from persistence.vector.protocol.query import BaseVectorSearcher
from persistence.vector.protocol.engine import BaseSearchEngine
from persistence.vector.protocol.storage import BaseVectorStorage
from persistence.vector.protocol.embedding import BaseEmbedder
from persistence.vector.implementation.domain.business import BusinessQueryResult

logger = logging.getLogger(__name__)


class ListBasedVectorSearcher(BaseVectorSearcher):
    """统一列表式查询器实现（后端无关）"""

    def __init__(
        self,
        embedder: BaseEmbedder,
        storage: BaseVectorStorage,
        search_engine: Optional[BaseSearchEngine] = None,
        default_k: int = 4,
        min_score: float = 0.0
    ):
        super().__init__(embedder, storage, search_engine)
        self.default_k = default_k
        self.min_score = min_score

    def batch_search(
        self,
        query_texts: list[str],
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[list[BusinessQueryResult]]:
        """批量自然语言查询（统一入口，后端无关）

        Args:
            query_texts: 多条 query 文本；单条场景传 [text]
            k: 每条 query 的 top-k
            filter_metadata: where filter（所有 query 共享，语义由注入的 search_engine 决定）

        Returns:
            list[list[BusinessQueryResult]]，外层 index 对应 query
        """
        if not query_texts:
            return []

        if self._search_engine is None:
            raise NotImplementedError("Search engine is required for ListBasedVectorSearcher")

        # 1) 一次性 embedding（与后端无关）
        query_vectors = self._embed_queries(query_texts)

        # 2) 引擎层原生 batch（一次 RTT，具体行为由注入的 search_engine 决定）
        self._search_engine.refresh()
        raw_batched = self._search_engine.batch_search(
            query_vectors,
            k=k,
            filter_metadata=filter_metadata,
            include_full=False,
        )

        # 3) 一次性回查 storage 取 content/metadata（与后端无关）
        all_ids: list[str] = []
        for raw in raw_batched:
            for vec_id, _score in raw:
                all_ids.append(vec_id)

        id_to_item: dict[str, object] = {}
        if all_ids:
            items = self._storage.get_vectors(all_ids)
            id_to_item = {it.id: it for it in items}

        # 4) 组装 BusinessQueryResult（rank 是过滤后真实排名，连续递增）
        results: list[list[BusinessQueryResult]] = []
        for raw in raw_batched:
            per_query: list[BusinessQueryResult] = []
            rank = 0
            for vec_id, score_vector in raw:
                score = score_vector[0]
                if self.min_score > 0 and score < self.min_score:
                    continue
                item = id_to_item.get(vec_id)
                per_query.append(BusinessQueryResult(
                    id=vec_id,
                    content=item.content if item else "",
                    score=score,
                    metadata=item.metadata if item else {},
                    rank=rank,
                ))
                rank += 1
            results.append(per_query)

        return results
