from abc import ABC, abstractmethod
from typing import Optional, Literal


class BaseSearchEngine(ABC):
    """搜索引擎统一接口（列表式）

    设计原则：
        - 唯一入口 batch_search(query_vectors, ...) -> 二维结果
        - 单条查询 = list 长度为 1，调用方负责包装
        - 返回 list[list[(vector_id, score_vector)]]，外层 index 对应 query
    """
    @property
    def distance_metric(self) -> Literal["cosine", "l2", "ip"]:
        return "cosine"

    @abstractmethod
    def batch_search(
        self,
        query_vectors: list[list[float]],
        k: int = 4,
        filter_metadata: Optional[dict] = None,
        include_full: bool = False
    ) -> list[list[tuple[str, list[float]]]]:
        """批量查询（统一入口）

        Args:
            query_vectors: 多条 query 向量；单条场景传 [vector]
            k: 每条 query 的 top-k
            filter_metadata: where filter（对所有 query 共享）
            include_full:
                False -> 返回 [(id, [sim, dist])]
                True  -> 返回 [(id, [sim, dist, content, metadata, embedding])]

        Returns:
            list[list[(vector_id, score_vector)]]，外层 index 对应 query
        """
        pass
