import os
from dotenv import load_dotenv

from langchain.chat_models import BaseChatModel
from langchain.chat_models import init_chat_model

load_dotenv()

api_key = os.getenv("DASHSCOPE_API_KEY")
base_url = os.getenv("DASHSCOPE_BASE_URL")

if api_key and base_url:
    print("api_key 和 base_url 加载成功")
else:
    print("api_key 或 base_url 未加载成功")

class VisionModelProvider:
    def __init__(self):
        self.model = "kimi-k2.6"

    def get_model(self) -> BaseChatModel:
        return init_chat_model(
            model=self.model,
            model_provider="openai",
            api_key=api_key,
            base_url=base_url,
        )
