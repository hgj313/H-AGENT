"""Interceptor Middleware Module

Provides request and response interceptors for middleware system.
"""

from typing import Any, Callable, Optional
from dataclasses import dataclass

from .core import Middleware, MiddlewareContext, MiddlewareOrder


@dataclass
class RequestData:
    node_name: str
    state: Any
    input_data: Any
    metadata: dict[str, Any]


@dataclass
class ResponseData:
    node_name: str
    result: Any
    state: Any
    metadata: dict[str, Any]


RequestInterceptor = Callable[[RequestData, MiddlewareContext], Optional[Any]]
ResponseInterceptor = Callable[[ResponseData, MiddlewareContext], Any]


class InterceptorMiddleware(Middleware[Any]):
    """Middleware for intercepting requests and responses.
    
    Features:
    - Request interception with modification
    - Response interception with modification
    - Conditional interception
    - Data transformation
    """
    
    def __init__(
        self,
        name: Optional[str] = None,
        request_interceptor: Optional[RequestInterceptor] = None,
        response_interceptor: Optional[ResponseInterceptor] = None,
        intercept_condition: Optional[Callable[[str, Any], bool]] = None,
        modify_state: bool = False,
        **kwargs
    ):
        super().__init__(name=name or "interceptor", **kwargs)
        self.request_interceptor = request_interceptor
        self.response_interceptor = response_interceptor
        self.intercept_condition = intercept_condition
        self.modify_state = modify_state
    
    async def _aprocess(
        self,
        context: MiddlewareContext,
        state: Any,
        next_handler: Callable
    ) -> Any:
        """Intercept and potentially modify requests and responses."""
        node_name = context.node_name or ""
        
        if self.intercept_condition and not self.intercept_condition(node_name, state):
            return await next_handler()
        
        request_data = RequestData(
            node_name=node_name,
            state=state,
            input_data=None,
            metadata={}
        )
        
        if self.request_interceptor:
            modified = self.request_interceptor(request_data, context)
            if modified is not None and self.modify_state:
                state = modified
        
        result = await next_handler()
        
        response_data = ResponseData(
            node_name=node_name,
            result=result,
            state=state,
            metadata={}
        )
        
        if self.response_interceptor:
            result = self.response_interceptor(response_data, context)
        
        return result
    
    def _process(
        self,
        context: MiddlewareContext,
        state: Any,
        next_handler: Callable
    ) -> Any:
        """Sync version of request/response interception."""
        node_name = context.node_name or ""
        
        if self.intercept_condition and not self.intercept_condition(node_name, state):
            return next_handler()
        
        request_data = RequestData(
            node_name=node_name,
            state=state,
            input_data=None,
            metadata={}
        )
        
        if self.request_interceptor:
            modified = self.request_interceptor(request_data, context)
            if modified is not None and self.modify_state:
                state = modified
        
        result = next_handler()
        
        response_data = ResponseData(
            node_name=node_name,
            result=result,
            state=state,
            metadata={}
        )
        
        if self.response_interceptor:
            result = self.response_interceptor(response_data, context)
        
        return result


class RateLimitMiddleware(Middleware[Any]):
    """Middleware for rate limiting node execution."""
    
    def __init__(
        self,
        name: Optional[str] = None,
        max_calls: int = 100,
        window_seconds: int = 60,
        key_func: Optional[Callable[[MiddlewareContext, Any], str]] = None,
        **kwargs
    ):
        import threading
        import time
        
        super().__init__(name=name or "rate_limit", **kwargs)
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.key_func = key_func or (lambda ctx, _: ctx.thread_id or "default")
        self._lock = threading.Lock()
        self._call_times: dict[str, list[float]] = {}
    
    async def _aprocess(
        self,
        context: MiddlewareContext,
        state: Any,
        next_handler: Callable
    ) -> Any:
        """Apply rate limiting."""
        key = self.key_func(context, state)
        
        with self._lock:
            current_time = time.time()
            
            if key in self._call_times:
                self._call_times[key] = [
                    t for t in self._call_times[key]
                    if current_time - t < self.window_seconds
                ]
            
            if len(self._call_times.get(key, [])) >= self.max_calls:
                raise RuntimeError(
                    f"Rate limit exceeded for key '{key}'. "
                    f"Max {self.max_calls} calls per {self.window_seconds}s"
                )
            
            if key not in self._call_times:
                self._call_times[key] = []
            self._call_times[key].append(current_time)
        
        return await next_handler()


class CachingMiddleware(Middleware[Any]):
    """Middleware for caching node execution results."""
    
    def __init__(
        self,
        name: Optional[str] = None,
        cache_key_func: Optional[Callable[[MiddlewareContext, Any], str]] = None,
        cache_ttl_seconds: int = 300,
        max_cache_size: int = 1000,
        **kwargs
    ):
        import threading
        
        super().__init__(name=name or "cache", **kwargs)
        self.cache_key_func = cache_key_func or (lambda ctx, _: f"{ctx.thread_id}:{ctx.node_name}")
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_cache_size = max_cache_size
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[Any, float]] = {}
    
    def _get_cache_key(self, context: MiddlewareContext, state: Any) -> str:
        """Generate cache key."""
        base_key = self.cache_key_func(context, state)
        import json
        try:
            state_key = json.dumps(state, sort_keys=True, default=str)
            return f"{base_key}:{hash(state_key)}"
        except:
            return base_key
    
    async def _aprocess(
        self,
        context: MiddlewareContext,
        state: Any,
        next_handler: Callable
    ) -> Any:
        """Check cache and return or execute."""
        import time
        
        cache_key = self._get_cache_key(context, state)
        
        with self._lock:
            if cache_key in self._cache:
                result, timestamp = self._cache[cache_key]
                if time.time() - timestamp < self.cache_ttl_seconds:
                    return result
                del self._cache[cache_key]
        
        result = await next_handler()
        
        with self._lock:
            if len(self._cache) >= self.max_cache_size:
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]
            self._cache[cache_key] = (result, time.time())
        
        return result


def create_request_interceptor(
    transform: Callable[[Any, dict], Any],
    filter_nodes: Optional[list[str]] = None
) -> RequestInterceptor:
    """Create a request interceptor function.
    
    Args:
        transform: Function to transform request data
        filter_nodes: Optional list of nodes to intercept
        
    Returns:
        RequestInterceptor function
    """
    def interceptor(request: RequestData, context: MiddlewareContext) -> Optional[Any]:
        if filter_nodes and request.node_name not in filter_nodes:
            return None
        
        transformed = transform(request.state, request.metadata)
        return transformed
    
    return interceptor


def create_response_interceptor(
    transform: Callable[[Any, dict], Any],
    filter_nodes: Optional[list[str]] = None
) -> ResponseInterceptor:
    """Create a response interceptor function.
    
    Args:
        transform: Function to transform response data
        filter_nodes: Optional list of nodes to intercept
        
    Returns:
        ResponseInterceptor function
    """
    def interceptor(response: ResponseData, context: MiddlewareContext) -> Any:
        if filter_nodes and response.node_name not in filter_nodes:
            return response.result
        
        return transform(response.result, response.metadata)
    
    return interceptor