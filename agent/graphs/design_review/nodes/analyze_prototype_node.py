from langchain_core.messages import HumanMessage
from agent.graphs.design_review.tools.analyze_prototype.analyze_prototype import analyze_prototype


class AnalyzePrototypeNode:
    @staticmethod
    def _detect_image_in_message(last_msg) -> tuple[bool, list[str]]:
        if not isinstance(last_msg, HumanMessage):
            return False, []

        content = last_msg.content
        image_urls = []

        if isinstance(content, str):
            return False, []
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "image_url":
                        image_url = item.get("image_url", {})
                        if isinstance(image_url, dict):
                            url = image_url.get("url", "")
                        elif isinstance(image_url, str):
                            url = image_url
                        else:
                            continue
                        if url:
                            image_urls.append(url)
                    elif item.get("type") == "image" and item.get("source") == "base64":
                        pass

        return len(image_urls) > 0, image_urls

    def analyze(self, image_urls: list[str]) -> dict:
        if not image_urls:
            return {"analysis_result": []}

        result = analyze_prototype.invoke(image_urls)
        
        if hasattr(result, 'content'):
            return {"analysis_result": [result.content]}
        elif isinstance(result, list):
            processed = []
            for msg in result:
                if hasattr(msg, 'content'):
                    processed.append(msg.content)
                else:
                    processed.append(str(msg))
            return {"analysis_result": processed}
        else:
            return {"analysis_result": [str(result)]}