# Python 装饰器完整指南

## 📚 目录

1. [Callable 详解](#1-callable-详解)
2. [装饰器基础原理](#2-装饰器基础原理)
3. [闭包机制](#3-闭包机制)
4. [装饰器的类型注解](#4-装饰器的类型注解)
5. [实战案例](#5-实战案例oss-注入装饰器)
6. [常见问题](#6-常见问题)

---

## 1. Callable 详解

### 1.1 什么是 Callable？

**Callable（可调用对象）** 是指任何可以使用 `()` 语法调用的对象。

### 1.2 所有 Callable 类型

```python
# 1. 普通函数
def greet(name):
    return f"Hello, {name}!"

# 2. Lambda 函数
square = lambda x: x ** 2

# 3. 类（调用类会创建实例）
class Calculator:
    pass

# 4. 类实例（如果有 __call__ 方法）
class Counter:
    def __init__(self):
        self.count = 0
    def __call__(self):
        self.count += 1
        return self.count

# 5. 内置函数
len, print, int

# 6. 方法（绑定到对象）
obj.method
```

### 1.3 Callable 类型注解

```python
from typing import Callable

# Callable[[参数类型列表], 返回类型]

# 无参数函数
def no_args() -> int:
    return 42

# 单参数函数
def single_arg(x: int) -> str:
    return str(x)

# 多参数函数
def multi_args(a: int, b: str, c: float) -> bool:
    return True

# 任意参数
def any_args(func: Callable[..., Any]):
    pass

# 使用示例
def process(func: Callable[[int, str], bool], x: int, y: str) -> bool:
    return func(x, y)
```

### 1.4 为什么需要 Callable 类型注解？

```python
# ❌ 没有类型注解 - 不知道参数和返回值
def execute(func, x):
    return func(x)

# ✅ 有类型注解 - 完全清楚函数签名
def execute(func: Callable[[int], str], x: int) -> str:
    return func(x)
```

**优势**：
- IDE 代码补全
- 类型检查器验证
- 文档自动生成
- 重构更安全

---

## 2. 装饰器基础原理

### 2.1 装饰器的本质

**装饰器是一个函数，它接收一个函数作为参数，返回一个新的函数。**

```python
def my_decorator(func):
    """装饰器"""
    def wrapper(*args, **kwargs):
        """新函数（包装器）"""
        # 添加额外功能
        print("调用前")
        result = func(*args, **kwargs)
        print("调用后")
        return result
    return wrapper

@my_decorator
def original_function():
    print("原函数执行")
```

### 2.2 装饰器的执行时机

```python
# @decorator 在函数定义时立即执行
@my_decorator
def hello():
    return "Hello"

# 等价于
def hello():
    return "Hello"
hello = my_decorator(hello)

# 调用时才执行 wrapper 逻辑
result = hello()  # 实际调用 wrapper()
```

### 2.3 装饰器的工作流程

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  定义函数时：                                                │
│    @decorator                                               │
│    def target():                                            │
│        pass                                                 │
│                                                             │
│    ↓ 等价于                                                  │
│                                                             │
│    def target():                                            │
│        pass                                                 │
│    target = decorator(target)                               │
│                                                             │
│  调用函数时：                                                │
│    target()                                                 │
│                                                             │
│    ↓ 等价于                                                  │
│                                                             │
│    target()  # 实际调用 wrapper                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 闭包机制

### 3.1 什么是闭包？

**闭包 = 函数 + 外部作用域的变量引用**

```python
def outer(x):
    """外部函数"""
    def inner(y):
        """内部函数 - 闭包"""
        return x + y  # 引用了外部变量 x
    return inner

closure = outer(10)  # x = 10 被"封闭"了
result = closure(5)  # 返回 10 + 5 = 15
```

### 3.2 闭包在装饰器中的作用

```python
def decorator(func):
    # func 是外部变量，被 wrapper 引用
    # 即使 decorator 返回，func 仍然存在

    def wrapper(*args, **kwargs):
        # wrapper 可以访问 func
        return func(*args, **kwargs)

    return wrapper
```

**关键点**：
- `func` 是外部作用域变量
- `wrapper` 闭包引用了 `func`
- 即使 `decorator()` 执行完毕，`func` 也不会被垃圾回收

---

## 4. 装饰器的类型注解

### 4.1 基本类型注解

```python
def basic_decorator(func: Callable) -> Callable:
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper
```

### 4.2 使用 TypeVar 保留返回类型

```python
from typing import TypeVar, Callable

T = TypeVar("T")

def typed_decorator(func: Callable[..., T]) -> Callable[..., T]:
    def wrapper(*args, **kwargs) -> T:
        return func(*args, **kwargs)
    return wrapper

@typed_decorator
def add(a: int, b: int) -> int:
    return a + b

@typed_decorator
def greet(name: str) -> str:
    return f"Hello, {name}!"

# 类型检查器知道：
# - add(1, 2) 返回 int
# - greet("Alice") 返回 str
```

### 4.3 使用 ParamSpec 完整保留函数签名（Python 3.10+）

```python
from typing import TypeVar, ParamSpec, Callable

P = ParamSpec("P")  # 捕获参数规格
T = TypeVar("T")    # 捕获返回类型

def full_signature_decorator(
    func: Callable[P, T]
) -> Callable[P, T]:
    """完整保留参数和返回类型"""
    @wraps(func)  # 保留元数据
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        print(f"调用 {func.__name__}")
        return func(*args, **kwargs)
    return wrapper

@full_signature_decorator
def calculate(a: int, b: int, c: int = 1) -> int:
    """计算乘法"""
    return a * b * c

# 类型检查器完全知道函数签名！
# calculate(a: int, b: int, c: int = 1) -> int
```

---

## 5. 实战案例：OSS 注入装饰器

### 5.1 问题背景

在 OSS 项目中，希望：
- 业务函数不需要关心 OSS 客户端的创建
- 自动注入 `client` 参数
- 保持类型安全

### 5.2 解决方案

```python
from typing import TypeVar, ParamSpec, Callable

P = ParamSpec("P")
T = TypeVar("T")

# 全局注册表
_oss_registry = OSSRegistry.get_instance()

def oss_inject(method: Callable[P, T]) -> Callable[P, T]:
    """
    OSS 客户端依赖注入装饰器
    自动注入 client 参数
    """
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        # 1. 确保客户端已初始化
        if not _oss_registry.is_initialized():
            _oss_registry.initialize()

        # 2. 获取客户端
        client = _oss_registry.get_client()

        # 3. 调用原函数，自动注入 client
        return method(client, *args, **kwargs)

    return wrapper
```

### 5.3 使用示例

```python
class Uploader:
    @oss_inject
    def upload(self, client, request: UploadRequest) -> UploadResult:
        """只需定义业务参数，client 自动注入"""
        return client.upload_file(request)

# 调用时
uploader = Uploader()
result = uploader.upload(request)  # 只传 request
                                    # client 自动注入！
```

### 5.4 执行流程

```
1. uploader.upload(request) 被调用

2. 实际调用 wrapper(request)
   
3. wrapper 中：
   - 检查并初始化客户端
   - 获取 client = _oss_registry.get_client()
   - 调用 method(client, request)
     即：original_function(client, request)

4. 返回 UploadResult
```

---

## 6. 常见问题

### 6.1 装饰器执行时机

```python
@decorator
def func():
    pass

# 装饰器在定义时立即执行
# 不是在调用时执行
```

### 6.2 保留原函数元数据

```python
from functools import wraps

def decorator(func):
    @wraps(func)  # 保留原函数的 __name__, __doc__ 等
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper
```

**不使用 @wraps**：
```python
@decorator
def add(a, b):
    """加法函数"""
    return a + b

print(add.__name__)  # 输出: wrapper ❌
print(add.__doc__)   # 输出: None ❌
```

**使用 @wraps**：
```python
@decorator
def add(a, b):
    """加法函数"""
    return a + b

print(add.__name__)  # 输出: add ✅
print(add.__doc__)   # 输出: 加法函数 ✅
```

### 6.3 带参数的装饰器

```python
def repeat(times: int):
    """装饰器工厂"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            results = []
            for _ in range(times):
                results.append(func(*args, **kwargs))
            return results
        return wrapper
    return decorator

@repeat(times=3)
def greet(name: str) -> str:
    return f"Hello, {name}!"

result = greet("Alice")
# ['Hello, Alice!', 'Hello, Alice!', 'Hello, Alice!']
```

### 6.4 类装饰器

```python
class CountCalls:
    def __init__(self, func: Callable):
        self.func = func
        self.count = 0
        wraps(func)(self)  # 保留元数据

    def __call__(self, *args, **kwargs):
        self.count += 1
        print(f"调用 {self.count} 次")
        return self.func(*args, **kwargs)

@CountCalls
def fibonacci(n: int) -> int:
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)
```

---

## 🎯 总结

| 概念 | 说明 | 关键点 |
|------|------|--------|
| **Callable** | 可调用对象 | 函数、类、lambda、有 `__call__` 的实例 |
| **装饰器** | 修改函数行为的函数 | 接收函数，返回包装函数 |
| **闭包** | 函数 + 环境引用 | 保持对外部变量的引用 |
| **@wraps** | 保留元数据 | 保持 `__name__`, `__doc__` 等 |
| **ParamSpec** | 保留参数规格 | Python 3.10+ 类型安全 |

**核心公式**：
```python
@decorator
def func():
    pass

# 等价于
func = decorator(func)
```

**闭包原理**：
```python
def outer(x):
    def inner(y):
        return x + y  # x 被"封闭"
    return inner
```

**类型安全装饰器**：
```python
P = ParamSpec("P")
T = TypeVar("T")

def decorator(func: Callable[P, T]) -> Callable[P, T]:
    ...
```
