"""注解式依赖注入容器。

通过 @oss_inject 装饰器实现 OSS 存储客户端的运行时注入，
避免上传与下载模块硬编码依赖具体云厂商实现。

依赖链路:
  业务层 ──注入──> OSS 存储服务 ──适配──> AliyunOSSAdapter ──使用──> alibabacloud_oss_v2 SDK
                                  └──替换──> 其他云厂商 Adapter（如 AWS S3、MinIO 等）

使用示例:

  # 在应用启动时注册单例适配器
  from oss.di import OSSRegistry, OSSClient
  from oss import AliyunOSSAdapter, OSSConfig

  config = OSSConfig(region="cn-hangzhou", bucket="my-bucket",
                      access_key_id="xxx", access_key_secret="xxx")
  adapter = AliyunOSSAdapter.from_config(config)
  OSSRegistry.register(adapter)

  # 在业务类中使用 @oss_inject 注入
  class MyUploader:
      def __init__(self, client: OSSClient):
          self._client = client  # 已注入 AliyunOSSAdapter 实例

      @oss_inject
      def upload(self, request: UploadRequest):
          return self._client.upload_file(request)  # 自动解包并调用底层适配器
"""

from __future__ import annotations

import os
import logging
import threading
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    TypeVar,
    ParamSpec,
    Generic,
)

from .base import OSSConfig, StorageService

if TYPE_CHECKING:
    from .base import UploadRequest, MultipartUploadRequest, ResumableUploadRequest, StreamUploadRequest
    from .base import DownloadRequest, StreamDownloadRequest, SignedURLRequest
    from .base import ObjectMetadata, UploadResult, DownloadResult, SignedURLResult


logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


class OSSRegistry:
    """OSS 适配器全局注册表。

    线程安全，支持单例模式注册。
    """

    _instance: OSSRegistry | None = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self) -> None:
        self._adapter: StorageService | None = None
        self._config: OSSConfig | None = None
        self._initialized = False

    @classmethod
    def get_instance(cls) -> OSSRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def register(self, adapter: StorageService) -> None:
        with self._lock:
            self._adapter = adapter
            self._initialized = True
        logger.info("OSS 适配器注册成功: %s", type(adapter).__name__)

    def register_from_config(self, config: OSSConfig) -> None:
        from .aliyun_oss import AliyunOSSAdapter
        adapter = AliyunOSSAdapter.from_config(config)
        self._config = config
        self.register(adapter)

    def get_adapter(self) -> StorageService:
        if self._adapter is None:
            raise RuntimeError(
                "OSS 适配器未注册，请先调用 OSSRegistry.register() 或 register_from_config()"
            )
        return self._adapter

    def clear(self) -> None:
        with self._lock:
            self._adapter = None
            self._config = None
            self._initialized = False


_oss_registry: ClassVar[OSSRegistry] = OSSRegistry.get_instance()


class OSSClient:
    """OSS 存储服务客户端包装器。

    保存已注入的适配器实例，供 @oss_inject 使用。
    """

    __slots__ = ("_adapter",)

    def __init__(self, adapter: StorageService) -> None:
        self._adapter = adapter

    def __getattr__(self, name: str) -> Any:
        return getattr(self._adapter, name)

    def __repr__(self) -> str:
        return f"OSSClient({type(self._adapter).__name__})"


def provide_oss_client(
    env_prefix: str = "OSS_",
    auto_load_config: bool = True,
) -> OSSClient:
    """创建 OSS 客户端实例，支持自动从环境变量加载配置。"""
    if _oss_registry._initialized:
        return OSSClient(_oss_registry.get_adapter())

    if not auto_load_config:
        raise RuntimeError(
            "OSS 适配器未注册且 auto_load_config=False，"
            "请调用 OSSRegistry.register() 显式注册适配器。"
        )

    access_key_id = os.getenv(f"{env_prefix}ACCESS_KEY_ID")
    access_key_secret = os.getenv(f"{env_prefix}ACCESS_KEY_SECRET")
    region = os.getenv(f"{env_prefix}REGION")
    bucket = os.getenv(f"{env_prefix}BUCKET")
    endpoint = os.getenv(f"{env_prefix}ENDPOINT")

    if all([access_key_id, access_key_secret, region, bucket]):
        config = OSSConfig(
            region=region,
            bucket=bucket,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            endpoint=endpoint,
        )
        _oss_registry.register_from_config(config)
        logger.info(
            "从环境变量自动加载 OSS 配置并注册: region=%s, bucket=%s",
            region,
            bucket,
        )
        return OSSClient(_oss_registry.get_adapter())

    raise RuntimeError(
        "OSS 适配器未注册且无法从环境变量自动配置，"
        f"请设置 {env_prefix}ACCESS_KEY_ID / {env_prefix}ACCESS_KEY_SECRET / "
        f"{env_prefix}REGION / {env_prefix}BUCKET"
    )


def oss_inject(method: Callable[P, T]) -> Callable[P, T]:
    """OSS 客户端依赖注入装饰器。

    装饰方法自动接收 OSSClient 参数并解包为 StorageService 适配器。

    用法（无 self 的独立函数）::

        @oss_inject
        def do_upload(client, request: UploadRequest) -> UploadResult:
            return client.upload_file(request)
        result = do_upload(request)  # client 自动注入

    用法（类实例方法）::

        class Uploader:
            @oss_inject
            def upload(self, client, request: UploadRequest) -> UploadResult:
                return client.upload_file(request)
        uploader = Uploader()
        result = uploader.upload(request)  # client 自动注入
    """
    if not callable(method):
        raise TypeError("@oss_inject must be applied to a callable")

    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        if not _oss_registry._initialized:
            try:
                provide_oss_client()
            except RuntimeError:
                raise RuntimeError(
                    f"OSS 适配器未注册，方法 {method.__name__} 无法解析依赖。"
                    f" 请调用 OSSRegistry.register() 显式注册，或设置 OSS_"
                    f" 开头的环境变量。"
                )
        client = _oss_registry.get_adapter()

        return method(client, *args, **kwargs)

    wrapper.__name__ = method.__name__
    wrapper.__doc__ = method.__doc__
    wrapper.__wrapped__ = method
    return wrapper


def inject_oss(method: Callable[P, T]) -> Callable[P, T]:
    """@oss_inject 的别名，提供更显式的命名。"""
    return oss_inject(method)


class OSSInjector(Generic[T]):
    """类型安全的 OSS 注入器基类。

    继承此类以获得类型检查友好的依赖注入::

        class MyUploader(OSSInjector[AliyunOSSAdapter]):
            def upload(self, request: UploadRequest) -> UploadResult:
                return self._oss.upload_file(request)

            @property
            def _oss(self) -> AliyunOSSAdapter:
                return self._resolve_oss()
    """

    @classmethod
    def _resolve_oss(cls) -> T:
        return _oss_registry.get_adapter()