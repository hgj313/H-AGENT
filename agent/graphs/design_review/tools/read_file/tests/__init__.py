"""pytest 配置文件。

提供测试fixtures和钩子函数。
"""

import sys
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(TEST_DIR))


@pytest.fixture(autouse=True)
def reset_registries():
    """在每个测试前后重置单例实例，确保测试隔离。"""
    from file_types import FileTypeRegistry
    from model_adapter import ModelRegistry

    FileTypeRegistry._instance = None
    ModelRegistry._instance = None

    try:
        from oss_adapter import reset_oss_file_id_adapter
        reset_oss_file_id_adapter()
    except (ImportError, AttributeError):
        pass

    yield

    FileTypeRegistry._instance = None
    ModelRegistry._instance = None

    try:
        from oss_adapter import reset_oss_file_id_adapter
        reset_oss_file_id_adapter()
    except (ImportError, AttributeError):
        pass