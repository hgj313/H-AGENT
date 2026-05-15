from __future__ import annotations

from agent.graphs.simple_graph.models import EdgeDefinition, GraphDefinition, NodeDefinition, NodeKind


def build_demo_graph() -> GraphDefinition:
    nodes = [
        NodeDefinition(
            node_id="collect_input",
            label="收集输入",
            kind=NodeKind.INPUT,
            output_key="numbers",
            metadata={"description": "接收前端提供的两个输入参数"},
        ),
        NodeDefinition(
            node_id="add_numbers",
            label="调用加法工具",
            kind=NodeKind.TOOL,
            depends_on=["collect_input"],
            tool_name="add",
            input_mapping={"a": "request.a", "b": "request.b"},
            output_key="sum_result",
        ),
        NodeDefinition(
            node_id="multiply_numbers",
            label="调用乘法工具",
            kind=NodeKind.TOOL,
            depends_on=["collect_input", "add_numbers"],
            tool_name="multiply",
            input_mapping={"a": "add_numbers", "b": "request.multiplier"},
            output_key="product_result",
        ),
        NodeDefinition(
            node_id="reason_about_result",
            label="推理总结",
            kind=NodeKind.REASONING,
            depends_on=["add_numbers", "multiply_numbers"],
            prompt_template=(
                "请基于以下结果生成中文解释。"
                "加法结果: {sum_result}; 乘法结果: {product_result}; "
                "用户目标: {goal}"
            ),
            input_mapping={
                "sum_result": "add_numbers",
                "product_result": "multiply_numbers",
                "goal": "request.goal",
            },
            output_key="final_answer",
        ),
    ]
    edges = [
        EdgeDefinition(source="collect_input", target="add_numbers"),
        EdgeDefinition(source="collect_input", target="multiply_numbers"),
        EdgeDefinition(source="add_numbers", target="multiply_numbers"),
        EdgeDefinition(source="add_numbers", target="reason_about_result"),
        EdgeDefinition(source="multiply_numbers", target="reason_about_result"),
    ]
    return GraphDefinition(
        graph_id="simple_demo_graph",
        name="Simple Graph Demo",
        version="1.0.0",
        entrypoint="collect_input",
        nodes=nodes,
        edges=edges,
        metadata={"purpose": "演示工具调用、流式推理、快照和会话隔离"},
    )
