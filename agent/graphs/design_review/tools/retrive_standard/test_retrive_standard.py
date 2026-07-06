from agent.graphs.design_review.tools.retrive_standard.retrive_standard import retrive_standard


content = retrive_standard.invoke(input={
    "query": " 这是一个测试吉盛园林里程碑看板需求文档.md",
    })

think_text: str = ""
response_text: str = ""
if isinstance(content, list):
    for block in content:
        if isinstance(block, dict):
            block_type = block.get("type", "")
            if block_type == "thinking" or "thinking" in block:
                think_text = block.get("thinking", "")
            elif block_type == "text" or "text" in block:
                response_text = block.get("text", "")
if think_text.strip():
    print("[思考中]:")
    print(think_text)
if response_text.strip():
    print("[回复]:")
    print(response_text)
if isinstance(content, str):
    print(content)
print("+"*50)
print("\n")