"""Middleware Infrastructure Module

Provides middleware functionality for workflow interception and modification.
Following the architecture: Middleware = interception layer

Components:
- core: Core middleware abstractions and implementations
- manager: Middleware lifecycle management
- interceptor: Request/response interceptors

Features:
- Logging middleware
- Timing middleware
- Error handling middleware
- Rate limiting middleware
- Request/response interception
"""

from .core import (
    MiddlewareOrder,
    MiddlewareContext,
    MiddlewareResult,
    MiddlewareChain,
    Middleware,
    LoggingMiddleware,
    TimingMiddleware,
    ErrorHandlerMiddleware,
)

from .manager import (
    IntegrationMode,
    MiddlewareConfig,
    MiddlewareManager,
    create_middleware_manager,
)

from .interceptor import (
    RequestData,
    ResponseData,
    RequestInterceptor,
    ResponseInterceptor,
    InterceptorMiddleware,
    RateLimitMiddleware,
)


__all__ = [
    # Core
    "MiddlewareOrder",
    "MiddlewareContext",
    "MiddlewareResult",
    "MiddlewareChain",
    "Middleware",
    "LoggingMiddleware",
    "TimingMiddleware",
    "ErrorHandlerMiddleware",
    # Manager
    "IntegrationMode",
    "MiddlewareConfig",
    "MiddlewareManager",
    "create_middleware_manager",
    # Interceptor
    "RequestData",
    "ResponseData",
    "RequestInterceptor",
    "ResponseInterceptor",
    "InterceptorMiddleware",
    "RateLimitMiddleware",
]