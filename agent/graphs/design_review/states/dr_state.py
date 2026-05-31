import operator
from langchain.messages import AnyMessage
from typing_extensions import Annotated, TypedDict


class DRState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    llm_calls: int = 0
    has_image: bool = False
    image_path: list[str] | None = None
    analysis_result: list[dict] | None = None
    report: str | None = None