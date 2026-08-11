from llm_model.reasoning_model.minimax import MiniMaxReasoningModelProvider
minimax_provider = MiniMaxReasoningModelProvider()
config = {"stream_mode": "messages"}
model = minimax_provider.get_model()
minimax_provider.stream_print(model.stream("你好",config=config))
