import operator
from langchain.messages import AnyMessage
from typing_extensions import Annotated,TypedDict

class DRState(TypedDict):
    messages: Annotated[list[AnyMessage],operator.add]
    llm_calls:int