from langchain_core.tools import tool
from persistence.vector.protocol.pipeline.sync_protocol import SyncVectorPipelineProtocol
from llm_model.reasoning_model.minimax import MinimaxReasoningModelProvider

reasoning_model = MinimaxReasoningModelProvider().get_model()
sync_vc_pipeline = SyncVectorPipelineProtocol()

@tool
def retrive_standard(query_texts: list[str]) -> str:
    standards = sync_vc_pipeline.batch_search(query_texts)
    standard_content = [standard.content for standard in standards]
    result = reasoning_model.invoke(standard_content)
    if hasattr(result, "content"):
        return result.content
    if isinstance(result, list):
        parts = [getattr(m, "content", str(m)) for m in result]
        return "\n".join(parts)
    return str(result)



