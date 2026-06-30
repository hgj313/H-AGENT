"""
P6c 集成测试 - 验证 api/main.py lifespan 显式初始化 OSSRegistry。

覆盖：
  P6c-1  env 完整时 lifespan 自动注册 AliyunOSSAdapter，app.state.oss_backend=aliyun_oss
  P6c-2  env 缺失时 lifespan 跳过注册，app.state.oss_backend=local
  P6c-3  env 抛异常时 lifespan 不挂（app.state.oss_backend=local，warning 日志）
  P6c-4  registry 初始化后，StorageService 第一次访问走 registry 优先（不再懒加载）
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _clear_oss_env():
    for k in list(os.environ.keys()):
        if k.startswith("OSS_"):
            os.environ.pop(k, None)


def _clear_state():
    """重置 module-level singleton + OSSRegistry + env。"""
    _clear_oss_env()
    from api.v1.services import storage_service as ss_mod
    ss_mod._service = None
    from oss.di import OSSRegistry
    OSSRegistry.get_instance().clear()


class P6cLifespanInitTests(unittest.TestCase):
    """api/main.py lifespan 中 OSSRegistry 显式初始化的契约。"""

    def setUp(self) -> None:
        _clear_state()

    def tearDown(self) -> None:
        _clear_state()

    # ── P6c-1 ──────────────────────────────────────────────
    def test_P6c_1_env_complete_registers_adapter(self):
        """env 完整时 lifespan 应注册 AliyunOSSAdapter。"""
        os.environ["OSS_REGION"] = "cn-beijing"
        os.environ["OSS_BUCKET"] = "test-bkt"
        os.environ["OSS_ACCESS_KEY_ID"] = "fake_id"
        os.environ["OSS_ACCESS_KEY_SECRET"] = "fake_secret"
        os.environ["OSS_ENDPOINT"] = "https://oss-cn-beijing.aliyuncs.com"

        from oss.aliyun_oss import AliyunOSSAdapter
        with patch.object(AliyunOSSAdapter, "from_config",
                          return_value=MagicMock(name="mock-aliyun-adapter")):
            # 触发 lifespan
            from fastapi.testclient import TestClient
            from api.main import app
            with TestClient(app) as c:
                # 拿到 app.state.oss_backend
                self.assertEqual(c.app.state.oss_backend, "aliyun_oss")
                # Registry 已注册
                from oss.di import OSSRegistry
                adapter = OSSRegistry.get_instance().get_adapter()
                self.assertIsNotNone(adapter)

    # ── P6c-2 ──────────────────────────────────────────────
    def test_P6c_2_env_incomplete_skips_register(self):
        """env 缺失时 lifespan 跳过注册。"""
        # 故意不设 env
        from fastapi.testclient import TestClient
        from api.main import app
        with TestClient(app) as c:
            self.assertEqual(c.app.state.oss_backend, "local")
            from oss.di import OSSRegistry
            with self.assertRaises(RuntimeError):
                OSSRegistry.get_instance().get_adapter()

    # ── P6c-3 ──────────────────────────────────────────────
    def test_P6c_3_env_blowup_does_not_kill_app(self):
        """env 异常时 lifespan 不挂，app 仍可启动。"""
        os.environ["OSS_REGION"] = "cn-beijing"
        os.environ["OSS_BUCKET"] = "b"
        os.environ["OSS_ACCESS_KEY_ID"] = "k"
        os.environ["OSS_ACCESS_KEY_SECRET"] = "s"

        from oss.aliyun_oss import AliyunOSSAdapter
        # 模拟 from_config 抛异常
        with patch.object(AliyunOSSAdapter, "from_config",
                          side_effect=RuntimeError("simulated OSS init failure")):
            from fastapi.testclient import TestClient
            from api.main import app
            # 不应该 raise
            with TestClient(app) as c:
                self.assertEqual(c.app.state.oss_backend, "local")

    # ── P6c-4 ──────────────────────────────────────────────
    def test_P6c_4_registry_takes_priority_over_lazy_init(self):
        """lifespan 注册后，StorageService 第一次访问走 registry（不再走 provide_oss_client）。"""
        os.environ["OSS_REGION"] = "cn-beijing"
        os.environ["OSS_BUCKET"] = "b"
        os.environ["OSS_ACCESS_KEY_ID"] = "k"
        os.environ["OSS_ACCESS_KEY_SECRET"] = "s"

        from oss.aliyun_oss import AliyunOSSAdapter
        sentinel = MagicMock(name="sentinel-adapter")
        with patch.object(AliyunOSSAdapter, "from_config", return_value=sentinel):
            from fastapi.testclient import TestClient
            from api.main import app
            with TestClient(app) as c:
                # 验证：StorageService 拿到的就是 sentinel
                from api.v1.services.storage_service import get_storage_service
                svc = get_storage_service()
                self.assertIs(svc.adapter, sentinel)
                self.assertEqual(svc.backend_kind, "oss")


if __name__ == "__main__":
    unittest.main(verbosity=2)
