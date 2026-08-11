from agent.graphs.design_review.tools.retrive_standard.full_search_str import get_strong_rule_queries


_texts = get_strong_rule_queries()
query_texts_list =[text["query"] for text in _texts if text]
query_texts = "\n".join(query_texts_list)

RETRIEVE_STANDARDS_PROMPT = """从设计标准知识库中检索与以下查询相关的内容：

{query_texts}

返回相关标准片段列表。"""


print(RETRIEVE_STANDARDS_PROMPT.format(query_texts=query_texts_list))