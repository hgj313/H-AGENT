import os
from dotenv import load_dotenv
import time
from typing import Iterator
from langchain.chat_models import init_chat_model
from langchain.chat_models.base import BaseChatModel
from langchain.messages import HumanMessage, AIMessage, SystemMessage, AIMessageChunk


load_dotenv()

api_key = os.getenv("MINIMAX_API_KEY")
base_url_openai = os.getenv("MINIMAX_BASE_URL_OPENAI")
base_url_anthropic = os.getenv("MINIMAX_BASE_URL_ANTHROPIC")



if api_key :
    print("api_key 加载成功")
else:
    print("api_key 未加载成功")

if base_url_anthropic:
    print("base_url_anthropic 加载成功")
if base_url_openai:
    print("base_url_openai 加载成功")
if not base_url_anthropic and not base_url_openai:
    print("base_url 全部未加载成功")

class  MinimaxVisionModelProvider:
    def __init__(self, model_name:str="MiniMax-M3", provider:str="anthropic"):
        self.model_name = model_name
        self.provider = provider
        self.base_url = None

    def get_model(self)->BaseChatModel:
        if self.provider == "openai":
            base_url = base_url_openai
        elif self.provider == "anthropic":
            base_url = base_url_anthropic
        else:
            raise ValueError(f"不支持的minimax提供商: {self.provider}")
        model = init_chat_model(
            model=self.model_name,
            model_provider=self.provider,
            api_key=api_key,
            base_url=base_url,
        )
        return model



