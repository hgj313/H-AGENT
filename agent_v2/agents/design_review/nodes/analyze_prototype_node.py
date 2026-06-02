"""Analyze Prototype Node

Design review agent node for prototype/image analysis.
Follows the architecture: Node = business logic
"""

from langchain_core.messages import HumanMessage

from ..states.dr_state import DesignReviewState, detect_image_in_message


class AnalyzePrototypeNode:
    """Analyze prototype node for image-based design review
    
    Analyzes prototype images and extracts design information.
    """
    
    def __init__(self, analyzer=None):
        """Initialize analyzer
        
        Args:
            analyzer: Optional custom analyzer function
        """
        self.analyzer = analyzer or self._default_analyzer
    
    def __call__(self, state: DesignReviewState) -> dict:
        """Execute prototype analysis
        
        Args:
            state: Current state with messages
            
        Returns:
            State with analysis results
        """
        messages = state.get("messages", [])
        last_msg = messages[-1] if messages else None
        
        if not last_msg:
            return {"analysis_result": []}
        
        has_image, image_urls = self._detect_image_in_message(last_msg)
        
        if not has_image or not image_urls:
            return {"analysis_result": []}
        
        result = self.analyze(image_urls)
        
        return {
            "analysis_result": result if isinstance(result, list) else [result],
            "has_image": True,
            "image_paths": image_urls,
        }
    
    def analyze(self, image_urls: list[str]) -> dict:
        """Analyze prototype images
        
        Args:
            image_urls: List of image URLs to analyze
            
        Returns:
            Analysis results
        """
        return self.analyzer(image_urls)
    
    def _default_analyzer(self, image_urls: list[str]) -> dict:
        """Default analyzer using analyze_prototype tool
        
        Args:
            image_urls: Image URLs
            
        Returns:
            Analysis result
        """
        from ..tools.analyze_prototype.analyze_prototype import analyze_prototype
        
        result = analyze_prototype.invoke(image_urls)
        
        if hasattr(result, 'content'):
            return [result.content]
        elif isinstance(result, list):
            processed = []
            for msg in result:
                if hasattr(msg, 'content'):
                    processed.append(msg.content)
                else:
                    processed.append(str(msg))
            return processed
        else:
            return [str(result)]
    
    @staticmethod
    def _detect_image_in_message(last_msg) -> tuple[bool, list[str]]:
        """Detect images in message (delegated to state module)"""
        return detect_image_in_message(last_msg)


def analyze_prototype_node(state: DesignReviewState) -> dict:
    """Standalone function for prototype analysis
    
    Args:
        state: Current state
        
    Returns:
        State with analysis results
    """
    analyzer = AnalyzePrototypeNode()
    return analyzer(state)