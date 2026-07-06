"""analyze_prototype 工具的单元测试（不调用网络）。"""

from agent.graphs.design_review.tools.analyze_prototype.analyze_prototype import (
    analyze_prototype,
)


def test_tool_rejects_empty_list():
    result = analyze_prototype.invoke({"image_urls": []})
    assert result == "未检测到图片，无法执行原型分析。"


def test_tool_schema_has_image_urls_parameter():
    try:
        schema = analyze_prototype.args_schema.model_json_schema()
    except AttributeError:
        schema = analyze_prototype.args_schema.schema()
    properties = schema.get("properties", {})
    assert "image_urls" in properties
    assert properties["image_urls"]["type"] == "array"
    assert properties["image_urls"]["items"]["type"] == "string"


def test_tool_name_is_analyze_prototype():
    assert analyze_prototype.name == "analyze_prototype"


def test_tool_pydantic_validation_rejects_non_list_input():
    import pytest
    with pytest.raises(Exception):
        analyze_prototype.invoke({"image_urls": "not_a_list"})


if __name__ == "__main__":
    test_tool_rejects_empty_list()
    test_tool_schema_has_image_urls_parameter()
    test_tool_name_is_analyze_prototype()
    test_tool_pydantic_validation_rejects_non_list_input()
    print("ALL PASS")