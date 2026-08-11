import os
from persistence.vector.implementation.chunker import GeneralChunker, MarkdownChunker
from persistence.vector.implementation.domain import EngineVectorItem, VectorIdGenerator
from persistence.vector.implementation.store import VectorStoreFactory
from persistence.vector.implementation.query import ListBasedVectorSearcher
from persistence.vector.implementation.engine import SearchEngineFactory
from persistence.vector.implementation.pipeline import PipelineFactory
from persistence.vector.implementation.embedding import EmbedderFactory
from persistence.vector.implementation.transaction import (
    ChromaVectorTransactionManager,
    ChromaVectorStorageConnection
)


# with open("C:\HGJ-T\H-AGENT\\test_data\吉盛园林里程碑看板需求文档.md", "r", encoding="utf-8") as f:
#     text = f.read()

with open("C:\HGJ-T\H-AGENT\\test_data\产品设计标准文档V2.０--25年持续更新.md", "r", encoding="utf-8") as f:
    text = f.read()

metadata = {
    "name": "测试",
    "shit": "boolshit"
}


chunker = MarkdownChunker()
embedder = EmbedderFactory.create("bge-m3")
storage = VectorStoreFactory.create("chroma")
connection = ChromaVectorStorageConnection(storage)
manager = ChromaVectorTransactionManager(connection)
search_engine = SearchEngineFactory.create("chroma", storage=storage)
searcher = ListBasedVectorSearcher(
    embedder=embedder,
    storage=storage,
    search_engine=search_engine
)
id_generator = VectorIdGenerator()
pipeline = PipelineFactory.create_sync(
    embedder=embedder,
    chunker=chunker,
    storage=storage,
    id_generator=id_generator,
    searcher=searcher
)

# 摄入文档
# result = pipeline.ingest_documents([(text, metadata)])

# print(result)

# 自然语言查询
query_result = pipeline.batch_search(["狗屎"])
print("total query count:", len(query_result))
for q_idx, result in enumerate(query_result):
    print("="*50)
    print(f"Q{q_idx + 1}  hits: {len(result)}")
    for hit in result:
        print(f"  - id={hit.id}  score={hit.score:.4f}  content[:60]={hit.content[:60]!r}")
    print()



# 切分文档
# chunker_pip = pipeline.chunker
# chunks = chunker_pip.chunk(text, metadata)

# for i, chunk in enumerate(chunks):
#     print(f"第{i+1}个chunk: {chunk.content}\n")
#     print(f"第{i+1}个chunk的元数据: {chunk.metadata}")
#     print("="*50)