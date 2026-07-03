"""OCR Extractor - 扫描件走视觉模型 OCR（预留接口）

当前实现：仅暴露接口。
TODO：接入项目底座 LLM (kimi-k2.6 视觉模型) 后，填充 OCR 逻辑。
"""

from typing import Any, Optional
from insurance_agent.domain import InsuredPerson
from .base import BaseExtractor


class OCRExtractor(BaseExtractor):
    """OCR 提取器（扫描件）

    依赖：LLM 视觉模型（项目底座：kimi-k2.6）。

    失败透传：
    - 若 LLM 客户端未注入，返回空列表，**不兜底**
    - 若 LLM 调用失败，异常向上抛，**不兜底**
    """

    def __init__(self, llm_client: Optional[Any] = None, page_images: Optional[list[str]] = None):
        self._llm = llm_client
        self._page_images = page_images or []

    def extract(
        self,
        text: str = "",                # OCR 模式下 text 一般为空
        policy_holder: str = "",
        insurance_company: str = ""
    ) -> list[InsuredPerson]:
        """通过视觉模型 OCR 提取人员信息

        TODO：Phase 3 接入。实现要点：
        1. 将 self._page_images 发送给视觉模型
        2. prompt 强制返回 JSON
        3. 通过 json_stabilizer.parse_json_strict 解析
        4. 映射为 InsuredPerson 列表
        """
        if not self._llm:
            # 失败透传：未配置 LLM，不兜底
            return []
        if not self._page_images:
            return []

        # TODO: 待 Phase 3 实现
        # result = call_vision_model(self._llm, self._page_images, prompt=...)
        # persons = map_ocr_result_to_persons(result)
        # return persons
        return []
