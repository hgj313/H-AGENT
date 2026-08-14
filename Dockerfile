# 保险单识别系统 Dockerfile
#
# 构建（默认基础镜像 python:3.13-slim）：
#   docker build -t insurance-agent:latest .
#
# 国内网络无法访问 Docker Hub 时，可指定镜像源：
#   docker build --build-arg BASE_IMAGE=docker.1ms.run/library/python:3.13-slim -t insurance-agent:latest .
#   （或 docker.m.daocloud.io/library/python:3.13-slim）
#
# 运行（通过环境变量注入 LLM 密钥等敏感配置）：
#   docker run -d --name insurance-agent \
#     -p 8765:8765 \
#     -e MINIMAX_API_KEY=sk-xxx \
#     -e MINIMAX_BASE_URL_ANTHROPIC=https://api.minimaxi.com/anthropic \
#     -v insurance-data:/app/data \
#     -v insurance-policy:/app/policy_library \
#     insurance-agent:latest
#
# 说明：
# - 数据目录 /app/data（SQLite 数据库、打卡数据、保单 PDF）建议挂载卷持久化
# - policy_library 目录建议挂载卷持久化
# - LLM 密钥通过环境变量注入，不写入镜像

# 基础镜像（可通过 --build-arg 指定国内镜像源）
ARG BASE_IMAGE=python:3.13-slim
FROM ${BASE_IMAGE}

# 环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app \
    DATA_DIR=/app/data

# 设置工作目录
WORKDIR /app

# 先复制依赖清单，利用 Docker 层缓存加速构建
COPY requirements.txt .

# 安装依赖（使用国内镜像源加速）
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    -r requirements.txt

# 复制项目代码（web_app + insurance_agent）
COPY web_app/ ./web_app/
COPY insurance_agent/ ./insurance_agent/

# 可选：复制 Excel 模板（若部署环境需要）
# COPY 最新保险数据下载模板.xlsx ./

# 创建运行时目录
RUN mkdir -p /app/data/policy_pdfs \
    /app/policy_library \
    /app/uploads

# 暴露服务端口
EXPOSE 8765

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/api/health', timeout=3)" || exit 1

# 启动服务
CMD ["uvicorn", "web_app.server:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "1"]
