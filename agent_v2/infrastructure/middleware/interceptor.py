"""Interceptor Middleware Module

Provides request and response interceptors for middleware system.
Following the architecture: Middleware = interception layer

Features:
- Request interception with modification
- Response interception with modification
- Conditional interception
- Data transformation
"""

from typing import Any, Callable, Optional
from dataclasses import dataclass

from .core import Middleware, MiddlewareContext, MiddlewareOrder


@dataclass
class RequestData:
    """Data for request interception"""
    node_name: str
    state: Any
    input_data: Any
    metadata: dict[str, Any]


@dataclass
class ResponseData:
    """Data for response interception"""
    node_name: str
    result: Any
    state: Any
    metadata: dict[str, Any]


RequestInterceptor = Callable[[RequestData, MiddlewareContext], Optional[Any]]
ResponseInterceptor = Callable[[ResponseData, MiddlewareContext], Any]


class InterceptorMiddleware(Middleware[Any]):
    """Middleware for intercepting requests and responses
    
    Following the architecture: Middleware = interception layer
    
    Usage:
        def my_request_interceptor(data, context):
            # Modify request data
            data.state['modified'] = True
            return data
        
        def my_response_interceptor(data, context):
            # Modify response
            return data.result
        
        interceptor = InterceptorMiddleware(
            request_interceptor=my_request_interceptor,
            response_interceptor=my_response_interceptor
        )
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
        """Intercept and potentially modify requests and responses"""
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
        """Sync version of interception"""
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
    """Middleware for rate limiting node execution
    
    Features:
    - Request rate limiting
    - Concurrency limiting
    - Adaptive rate limiting
    """
    
    def __init__(
        self,
        name: Optional[str] = None,
        max_requests_per_second: int = 10,
        max_concurrent: int = 5,
        **kwargs
    ):
        super().__init__(name=name or "rate_limit", **kwargs)
        self.max_requests_per_second = max_requests_per_second
        self.max_concurrent = max_concurrent
        self._request_times: list[float] = []
        self._active_count = 0
    
    async def _aprocess(
        self,
        context: MiddlewareContext,
        state: Any,
        next_handler: Callable
    ) -> Any:
        """Apply rate limiting"""
        import time
        
        current_time = time.time()
        
        self._request_times = [
            t for t in self._request_times
            if current_time - t < 1.0
        ]
        
        while len(self._request_times) >= self.max_requests_per_second:
            time.sleep(0.01)
            current_time = time.time()
            self._request_times = [
                t for t in self._request_times
                if current_time - t < 1.0
            ]
        
        while self._active_count >= self.max_concurrent:
            time.sleep(0.01)
        
        self._request_times.append(current_time)
        self._active_count += 1
        
        try:
            return await next_handler()
        finally:
            self._active_count -= 1
    
    def _process(
        self,
        context: MiddlewareContext,
        state: Any,
        next_handler: Callable
    ) -> Any:
        """Sync version of rate limiting"""
        return self._sync_wrap(next_handler)
    
    def _sync_wrap(self, handler):
        import time
        
        current_time = time.time()
        
        self._request_times = [
            t for t in self._request_times
            if current_time - t < 1.0
        ]
        
        while len(self._request_times) >= self.max_requests_per_second:
            time.sleep(0.01)
            current_time = time.time()
            self._request_times = [
                t for t in self._request_times
                if current_time - t < 1.0
            ]
        
        while self._active_count >= self.max_concurrent:
            time.sleep(0.01)
        
        self._request_times.append(current_time)
        self._active_count += 1
        
        try:
            return handler()
        finally:
            self._active_count -= 1