import time
import os
from collections.abc import Iterator

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.messages import AIMessageChunk

load_dotenv()

api_key = os.getenv("MINIMAX_API_KEY")
base_url_openai = os.getenv("MINIMAX_BASE_URL_OPENAI")
base_url_anthropic = os.getenv("MINIMAX_BASE_URL_ANTHROPIC")


class minimax_reasoning_model:
    def __init__(
        self,
        model_name: str = "MiniMax-M2.7",
        provider: str = "anthropic",
        enable_mock: bool | None = None,
    ):
        self.model_name = model_name
        self.provider = provider
        self.base_url = None
        self.enable_mock = enable_mock if enable_mock is not None else not bool(api_key)

    def can_use_remote_model(self) -> bool:
        if not api_key:
            return False
        if self.provider == "openai":
            return bool(base_url_openai)
        if self.provider == "anthropic":
            return bool(base_url_anthropic)
        return False

    def get_model(self):
        if self.enable_mock or not self.can_use_remote_model():
            return None
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

    def typewriter_print(self, text: str, delay: float = 0.035) -> None:
        for ch in text:
            print(ch, end="", flush=True)
            time.sleep(delay)

    def _mock_reasoning_text(self, prompt: str, context: dict | None = None) -> str:
        context = context or {}
        return (
            "这是一个本地模拟推理结果。"
            f"我收到了提示词: {prompt}。"
            f"上下文摘要: {context}。"
            "图执行已经完成工具调用并生成了可演示的流式结果。"
        )

    def stream_reasoning(self, prompt: str, context: dict | None = None) -> Iterator[str]:
        if self.enable_mock or not self.can_use_remote_model():
            text = self._mock_reasoning_text(prompt, context)
            for token in text:
                yield token
            return

        model = self.get_model()
        if model is None:
            text = self._mock_reasoning_text(prompt, context)
            for token in text:
                yield token
            return

        chunks = model.stream(prompt, config={"stream_mode": "messages"})
        for chunk in chunks:
            content = chunk.content
            if isinstance(content, str) and content:
                yield content
                continue
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text") or item.get("thinking") or ""
                        if text:
                            yield text

    def stream_print(self, chunks: Iterator[AIMessageChunk], delay: float = 0.035):
        # 处理 anthropic 兼容模式
        if self.provider == "anthropic":
            thinking_started_anthropic = False
            last_thinking_text_anthropic = ""
            answer_started_anthropic = False
            for chunk in chunks:
                if isinstance(chunk.content, list) and chunk.content:
                    for item in chunk.content:
                        if not isinstance(item, dict):
                            continue

                        thinking = item.get("thinking")
                        if not thinking:
                            continue

                        if not thinking_started_anthropic:
                            print("\n[思考中...]\n", end="", flush=True)
                            thinking_started_anthropic = True

                        if thinking.startswith(last_thinking_text_anthropic):
                            delta = thinking[len(last_thinking_text_anthropic):]
                        else:
                            delta = thinking

                        for ch in delta:
                            print(ch, end="", flush=True)
                            time.sleep(0.02)

                        last_thinking_text_anthropic = thinking

                if isinstance(chunk.content, str) and chunk.content:
                    if not answer_started_anthropic:
                        print("\n\n[最终回答]\n", end="", flush=True)
                        answer_started_anthropic = True

                    for ch in chunk.content:
                            print(ch, end="", flush=True)
                            time.sleep(delay)
            print()
        # 处理 openai 兼容模式
        else:
            is_thinking_openai = False
            thinking_started_openai = False
            thinking_ended_openai = False

            is_answer_openai = False
            answer_started_openai = False
            for chunk in chunks:
                content = chunk.content
                if not isinstance(content, str) or not content:
                    continue

                # 检测思考开始，避免把 <think> 标签本身打印出来
                if "<think>" in content and not thinking_started_openai:
                    is_thinking_openai = True
                    thinking_started_openai = True
                    print("\n[思考中...]\n", end="", flush=True)
                    content = content.split("<think>", 1)[1]

                # 处于思考阶段时，优先消费思考内容
                if is_thinking_openai:
                    if "</think>" in content:
                        thinking_text, answer_text = content.split("</think>", 1)
                        if thinking_text:
                            self.typewriter_print(thinking_text,delay)

                        is_thinking_openai = False
                        thinking_ended_openai = True
                        is_answer_openai = True

                        if answer_text:
                            if not answer_started_openai:
                                print("\n\n[最终回答]\n", end="", flush=True)
                                answer_started_openai = True
                            self.typewriter_print(answer_text,delay)
                    else:
                        self.typewriter_print(content,delay)
                    continue

                # 不在思考阶段时，按回答内容处理
                if thinking_ended_openai and not answer_started_openai:
                    is_answer_openai = True
                    answer_started_openai = True
                    print("\n\n[最终回答]\n", end="", flush=True)
                if is_answer_openai:
                    self.typewriter_print(content,delay)

            if answer_started_openai:
                print()

    def graph_stream_print(self, chunks: Iterator[AIMessageChunk], delay: float = 0.035):
            # 处理 anthropic 兼容模式
            if self.provider == "anthropic":
                thinking_started_anthropic = False
                last_thinking_text_anthropic = ""
                answer_started_anthropic = False
                for chunk in chunks.values()['messages'][0]:
                    if isinstance(chunk.content, list) and chunk.content:
                        for item in chunk.content:
                            if not isinstance(item, dict):
                                continue

                            thinking = item.get("thinking")
                            if not thinking:
                                continue

                            if not thinking_started_anthropic:
                                print("\n[思考中...]\n", end="", flush=True)
                                thinking_started_anthropic = True

                            if thinking.startswith(last_thinking_text_anthropic):
                                delta = thinking[len(last_thinking_text_anthropic):]
                            else:
                                delta = thinking

                            for ch in delta:
                                print(ch, end="", flush=True)
                                time.sleep(0.02)

                            last_thinking_text_anthropic = thinking

                    if isinstance(chunk.content, str) and chunk.content:
                        if not answer_started_anthropic:
                            print("\n\n[最终回答]\n", end="", flush=True)
                            answer_started_anthropic = True

                        for ch in chunk.content:
                            print(ch, end="", flush=True)
                            time.sleep(delay)
                print()
            # 处理 openai 兼容模式
            else:
                is_thinking_openai = False
                thinking_started_openai = False
                thinking_ended_openai = False

                is_answer_openai = False
                answer_started_openai = False
                for chunk in chunks:
                    content = chunk.content
                    if not isinstance(content, str) or not content:
                        continue

                    # 检测思考开始，避免把 <think> 标签本身打印出来
                    if "<think>" in content and not thinking_started_openai:
                        is_thinking_openai = True
                        thinking_started_openai = True
                        print("\n[思考中...]\n", end="", flush=True)
                        content = content.split("<think>", 1)[1]

                    # 处于思考阶段时，优先消费思考内容
                    if is_thinking_openai:
                        if "</think>" in content:
                            thinking_text, answer_text = content.split("</think>", 1)
                            if thinking_text:
                                self.typewriter_print(thinking_text,delay)

                            is_thinking_openai = False
                            thinking_ended_openai = True
                            is_answer_openai = True

                            if answer_text:
                                if not answer_started_openai:
                                    print("\n\n[最终回答]\n", end="", flush=True)
                                    answer_started_openai = True
                                self.typewriter_print(answer_text,delay)
                        else:
                            self.typewriter_print(content,delay)
                        continue

                    # 不在思考阶段时，按回答内容处理
                    if thinking_ended_openai and not answer_started_openai:
                        is_answer_openai = True
                        answer_started_openai = True
                        print("\n\n[最终回答]\n", end="", flush=True)
                    if is_answer_openai:
                        self.typewriter_print(content,delay)

                if answer_started_openai:
                    print()

