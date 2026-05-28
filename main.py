# main.py

import logging
import re
from dotenv import load_dotenv

from pathlib import Path

# 1. 初始化适配器并注册（启动时只做一次）
from oss.di import OSSRegistry
from oss import AliyunOSSAdapter, OSSConfig

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 方式 A：从环境变量自动配置（推荐）
from oss.di import provide_oss_client
client = provide_oss_client()   # 读 OSS_* 环境变量，自动注册

# 方式 B：手动配置（更精确控制）
# config = OSSConfig(
#     region="cn-hangzhou",
#     bucket="my-bucket",
#     access_key_id="LTAIxxxx",
#     access_key_secret="your-secret",
#     endpoint="https://oss-cn-hangzhou.aliyuncs.com",
# )
# OSSRegistry.register(AliyunOSSAdapter.from_config(config))


# 2. 导入上传/下载服务
from infrastructure.upload import UploadService, UploadPolicy
from infrastructure.download import DownloadService


# 3. 上传一张照片
def on_progress(uploaded: int, total: int):
    percent = int(uploaded * 100 / total) if total else 0
    print(f"  上传进度: {uploaded}/{total} bytes ({percent}%)")

upload_service = UploadService()

local_photo = r"C:\HGJ-T\H-AGENT\maqima.jpeg"       # 本地文件路径
oss_key = "photos/2025/girlfriends/maqima.jpeg"         # OSS 上存储的路径

logger.info("开始上传照片: %s → oss://%s", local_photo, oss_key)

result = upload_service.upload(
    file_path=local_photo,
    object_name=oss_key,
    content_type="image/jpeg",                # 让浏览器正确识别图片类型
    metadata={"author": "maqima", "location": "重庆"},  # 自定义元数据
    progress_callback=on_progress,             # 可选：实时进度
)

print(f"✅ 上传成功!")
print(result)
print("="*50)
print(f"   对象名称: {result.object_name}")
print(f"   ETag:     {result.etag}")
print(f"   UploadID: {result.upload_id}")


# 4. 下载照片
download_service = DownloadService()

local_save_path = Path(r"c:\HGJ-T\H-AGENT\ls_copy.jpg")

logger.info("开始下载照片: oss://%s → %s", oss_key, local_save_path)

download_result = download_service.download(
    object_name=oss_key,
    target_path=local_save_path,
)

print(f"✅ 下载成功!")
print(download_result)
print("="*50)
print(f"   保存路径: {download_result.target_path}")
print(f"   文件大小: {download_result.written_bytes} bytes")


# 5. 生成私有文件访问链接（可选）
url_result = download_service.get_signed_url(
    object_name=oss_key,
    expire_seconds=3600,    # 链接有效期 1 小时
)

print(f"🔗 临时访问链接（1小时内有效）:")
print(f"   {url_result.url}")