"""Model Adapter for Multimodal Support

Handles different model types and output formats.
Following the architecture:支持多模态模型适配
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional
import base64
from pathlib import Path


class ModelType(Enum):
    """Model type enumeration"""
    TEXT_ONLY = "text_only"
    MULTIMODAL = "multimodal"
    VISION = "vision"


class OutputFormat(Enum):
    """Output format enumeration"""
    BASE64 = "base64"
    URL = "url"
    BINARY = "binary"
    FILE_ID = "file_id"
    RAW = "raw"


@dataclass
class ProcessedContent:
    """Processed content result"""
    content: str
    format: OutputFormat
    success: bool
    error: Optional[str] = None
    metadata: Optional[dict] = None


class ModelRegistry:
    """Registry for model configurations"""
    
    MODELS = {
        "gpt-4-vision": ModelType.MULTIMODAL,
        "gpt-4o": ModelType.MULTIMODAL,
        "claude-3": ModelType.MULTIMODAL,
        "claude-3.5": ModelType.MULTIMODAL,
        "gemini-pro-vision": ModelType.MULTIMODAL,
        "qwen-vl": ModelType.VISION,
        "qwen-max": ModelType.TEXT_ONLY,
        "gpt-4": ModelType.TEXT_ONLY,
        "gpt-3.5-turbo": ModelType.TEXT_ONLY,
    }
    
    @classmethod
    def get_model_type(cls, model_name: str) -> ModelType:
        """Get model type by name"""
        return cls.MODELS.get(model_name, ModelType.TEXT_ONLY)


def detect_model_type() -> ModelType:
    """Detect current model type
    
    Returns:
        ModelType
    """
    try:
        from llm_model.registry import ModelRegistry as LLMModelRegistry
        
        current_model = LLMModelRegistry.get_current_model()
        return ModelRegistry.get_model_type(current_model)
    except ImportError:
        return ModelType.MULTIMODAL


def is_multimodal_model(model_name: Optional[str] = None) -> bool:
    """Check if model supports multimodal input
    
    Args:
        model_name: Optional model name
        
    Returns:
        True if multimodal
    """
    if model_name:
        model_type = ModelRegistry.get_model_type(model_name)
    else:
        model_type = detect_model_type()
    
    return model_type in {ModelType.MULTIMODAL, ModelType.VISION}


class ModelAdapter:
    """Adapter for different model types
    
    Converts content to format suitable for model input.
    """
    
    def __init__(self, model_type: ModelType = None):
        """Initialize adapter
        
        Args:
            model_type: Target model type
        """
        self.model_type = model_type or detect_model_type()
    
    def adapt(
        self,
        content: str,
        file_path: str,
        output_format: OutputFormat = OutputFormat.BASE64
    ) -> ProcessedContent:
        """Adapt content for model
        
        Args:
            content: Input content
            file_path: Source file path
            output_format: Desired output format
            
        Returns:
            ProcessedContent
        """
        try:
            if self.model_type == ModelType.TEXT_ONLY:
                return self._adapt_for_text_only(content, output_format)
            elif self.model_type in {ModelType.MULTIMODAL, ModelType.VISION}:
                return self._adapt_for_multimodal(content, file_path, output_format)
            else:
                return ProcessedContent(
                    content=content,
                    format=OutputFormat.RAW,
                    success=True
                )
        except Exception as e:
            return ProcessedContent(
                content="",
                format=output_format,
                success=False,
                error=str(e)
            )
    
    def _adapt_for_text_only(
        self,
        content: str,
        output_format: OutputFormat
    ) -> ProcessedContent:
        """Adapt content for text-only model
        
        Args:
            content: Input content
            output_format: Output format
            
        Returns:
            ProcessedContent
        """
        if output_format == OutputFormat.RAW:
            return ProcessedContent(
                content=content,
                format=OutputFormat.RAW,
                success=True
            )
        
        return ProcessedContent(
            content=content,
            format=OutputFormat.RAW,
            success=True
        )
    
    def _adapt_for_multimodal(
        self,
        content: str,
        file_path: str,
        output_format: OutputFormat
    ) -> ProcessedContent:
        """Adapt content for multimodal model
        
        Args:
            content: Input content (file path or base64)
            file_path: Source file path
            output_format: Output format
            
        Returns:
            ProcessedContent
        """
        if output_format == OutputFormat.BASE64:
            return self._to_base64(content, file_path)
        elif output_format == OutputFormat.URL:
            return self._to_url(content, file_path)
        elif output_format == OutputFormat.RAW:
            return self._to_raw(content)
        
        return ProcessedContent(
            content=content,
            format=OutputFormat.RAW,
            success=True
        )
    
    def _to_base64(self, content: str, file_path: str) -> ProcessedContent:
        """Convert to base64 format
        
        Args:
            content: Input content
            file_path: File path
            
        Returns:
            ProcessedContent with base64
        """
        path = Path(file_path)
        
        if path.exists():
            with open(path, 'rb') as f:
                encoded = base64.b64encode(f.read()).decode('utf-8')
                mime_type = self._get_mime_type(path.suffix)
                return ProcessedContent(
                    content=f"data:{mime_type};base64,{encoded}",
                    format=OutputFormat.BASE64,
                    success=True
                )
        
        return ProcessedContent(
            content=content,
            format=OutputFormat.RAW,
            success=True
        )
    
    def _to_url(self, content: str, file_path: str) -> ProcessedContent:
        """Convert to URL format
        
        Args:
            content: Input content
            file_path: File path
            
        Returns:
            ProcessedContent with URL
        """
        path = Path(file_path)
        
        if path.exists():
            return ProcessedContent(
                content=f"file://{path.absolute()}",
                format=OutputFormat.URL,
                success=True
            )
        
        return ProcessedContent(
            content=content,
            format=OutputFormat.RAW,
            success=True
        )
    
    def _to_raw(self, content: str) -> ProcessedContent:
        """Keep content as raw
        
        Args:
            content: Input content
            
        Returns:
            ProcessedContent
        """
        return ProcessedContent(
            content=content,
            format=OutputFormat.RAW,
            success=True
        )
    
    def _get_mime_type(self, extension: str) -> str:
        """Get MIME type from extension"""
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.pdf': 'application/pdf',
        }
        return mime_types.get(extension.lower(), 'application/octet-stream')