"""
API V1 模块 - 第一版 API 接口。
"""
from fastapi import APIRouter

from api.v1.endpoints import chat, agents, files, react_agent, design_review, oss

router = APIRouter(prefix="/api/v1")

router.include_router(chat.router, prefix="/chat", tags=["chat"])
router.include_router(agents.router, prefix="/agents", tags=["agents"])
router.include_router(files.router, prefix="/files", tags=["files"])
router.include_router(react_agent.router, prefix="/react-agent", tags=["react-agent"])
router.include_router(design_review.router, prefix="/design-review", tags=["design-review"])
router.include_router(oss.router, prefix="/oss", tags=["oss"])
