from llm_model.reasoning_model.minimax import minimax_reasoning_model

minimax = minimax_reasoning_model()
config = {"stream_mode": "messages"}
model = minimax.get_model()
minimax.stream_print(model.stream("你好",config=config))
