from langchain.messages import HumanMessage
from agent.graphs.design_review.design_review_graph import create_design_review_graph
from llm_model.reasoning_model.minimax import MinimaxReasoningModelProvider

model_minimax = MinimaxReasoningModelProvider().get_model()

graph = create_design_review_graph(model_minimax)

# 正向测试：直接传入材料，绕过 interrupt/resume
# 用于验证图本身能否跑通，排除 react 节点兜底失效的影响
events = graph.stream(
    {
        "messages": [
            HumanMessage(
                content="原型图地址：https://dr-2.oss-cn-beijing.aliyuncs.com/%E6%B5%8B%E8%AF%95/%E5%B7%A5%E7%A8%8B%E7%9C%8B%E6%9D%BF%E5%8E%9F%E5%9E%8B%E5%9B%BE.jpeg ，prd文档地址：test_data\吉盛园林里程碑看板需求文档.md"
            ),
        ],
        # 显式初始化 reducer 字段，避免残留 channel 值污染 merge
        "node_errors": {},
        # 直接传入材料，绕过 interrupt
        "image_path": ["https://dr-2.oss-cn-beijing.aliyuncs.com/%E6%B5%8B%E8%AF%95/%E5%B7%A5%E7%A8%8B%E7%9C%8B%E6%9D%BF%E5%8E%9F%E5%9E%8B%E5%9B%BE.jpeg"],
        "prd_file_path":[r"test_data\吉盛园林里程碑看板需求文档.md"],
    },
    stream_mode="values",
)

final_state = None
for event in events:
    print("\n=== EVENT ===")
    print(event)
    final_state = event

print("\n=== FINAL STATE ===")
print(final_state)
