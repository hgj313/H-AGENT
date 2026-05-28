from typing import Any

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None


def _to_list_safe(value: Any, index: int, default: Any = None) -> Any:
    """安全提取列表元素，处理 numpy 数组和 None 情况"""
    if value is None:
        return default
    if isinstance(value, list):
        return value[index] if index < len(value) else default
    if HAS_NUMPY and isinstance(value, np.ndarray):
        return value[index].tolist() if index < len(value) else default
    return default