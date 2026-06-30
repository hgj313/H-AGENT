"""
FastAPI 主应用入口。

启动命令:
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.v1 import router as v1_router
from api.v1.services import get_database
from core.registry.agent_registry import AgentRegistry
from core.registry.events import EventBus, Event, EventType

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def _create_registry() -> AgentRegistry:
    """
    创建并配置 AgentRegistry。

    在这里注册所有 Agent。
    """
    event_bus = EventBus()
    registry = AgentRegistry(event_bus=event_bus)

    # 注册事件处理器
    @event_bus.on(EventType.AGENT_REGISTERED)
    def on_agent_registered(event: Event):
        logger.info(f"[EVENT] Agent 已注册: {event.data.get('agent_id')}")

    @event_bus.on(EventType.AGENT_STATUS_CHANGED)
    def on_status_changed(event: Event):
        logger.info(f"[EVENT] Agent 状态变更: {event.data}")

    @event_bus.on(EventType.AGENT_UNREGISTERED)
    def on_agent_unregistered(event: Event):
        logger.info(f"[EVENT] Agent 已注销: {event.data.get('agent_id')}")

    @event_bus.on(EventType.SYSTEM_READY)
    def on_system_ready(event: Event):
        logger.info(f"[EVENT] 系统就绪: {event.data.get('message')}")

    logger.info("事件处理器注册完成")

    # 注册 DesignReviewAgent
    try:
        from core.agents.design_review_agent import register_design_review_agent
        register_design_review_agent(registry)
    except Exception as e:
        logger.warning(f"DesignReviewAgent 注册失败: {e}")

    # 注册 ReactAgent（通用对话）
    try:
        from core.agents.react_agent import register_react_agent
        register_react_agent(registry)
    except Exception as e:
        logger.warning(f"ReactAgent 注册失败: {e}")

    return registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    logger.info("正在初始化应用...")

    # 初始化数据库
    try:
        db = get_database()
        logger.info("数据库初始化成功")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        raise

    # 显式初始化 OSSRegistry（生产用 AliyunOSSAdapter；env 缺失时跳过，
    # 运行时由 storage_service.StorageService fallback 到 LocalStorageBackend）
    try:
        from oss import AliyunOSSAdapter
        from oss.base import OSSConfig
        from oss.di import OSSRegistry

        region = os.getenv("OSS_REGION")
        bucket = os.getenv("OSS_BUCKET")
        ak = os.getenv("OSS_ACCESS_KEY_ID")
        sk = os.getenv("OSS_ACCESS_KEY_SECRET")
        endpoint = os.getenv("OSS_ENDPOINT")
        if all([region, bucket, ak, sk]):
            config = OSSConfig(
                region=region, bucket=bucket,
                access_key_id=ak, access_key_secret=sk,
                endpoint=endpoint,
            )
            adapter = AliyunOSSAdapter.from_config(config)
            OSSRegistry.get_instance().register(adapter)
            logger.info(
                "OSSRegistry 显式初始化成功: region=%s, bucket=%s, adapter=%s",
                region, bucket, type(adapter).__name__,
            )
            app.state.oss_backend = "aliyun_oss"
        else:
            logger.info(
                "OSS 环境变量不完整（需 OSS_REGION/BUCKET/ACCESS_KEY_ID/SECRET）"
                "，跳过显式注册；运行时将回退到 LocalStorageBackend"
            )
            app.state.oss_backend = "local"
    except Exception as e:
        logger.warning(f"OSSRegistry 显式初始化失败: {e}（不影响服务启动）")
        app.state.oss_backend = "local"

    # 初始化 AgentRegistry
    registry = _create_registry()
    app.state.registry = registry

    # 发布系统就绪事件
    registry.event_bus.emit(Event(
        event_type=EventType.SYSTEM_READY,
        source="main",
        data={
            "message": "系统已就绪",
            "oss_backend": getattr(app.state, "oss_backend", "unknown"),
        },
    ))

    logger.info(f"应用初始化完成，已注册 {registry.agent_count} 个 Agent")

    yield

    # 清理资源
    logger.info("正在关闭应用...")
    registry.event_bus.emit(Event(
        event_type=EventType.SYSTEM_SHUTDOWN,
        source="main",
        data={"message": "系统正在关闭"},
    ))


# 创建 FastAPI 应用
app = FastAPI(
    title="H-AGENT API",
    description="H-AGENT 智能体服务 API",
    version="1.0.0",
    lifespan=lifespan,
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由（必须在静态文件挂载之前）
app.include_router(v1_router)


@app.get("/api/health")
async def health():
    """简单健康检查。"""
    return {"status": "ok", "version": "1.0.0"}


# 挂载静态文件（前端）
# 使用 /app 路径避免与 API 路由冲突
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/app", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    # 根路径重定向到 /app
    @app.get("/")
    async def root():
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/app")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
