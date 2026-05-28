"""装饰器执行流程可视化"""

print("=" * 80)
print("装饰器完整执行流程")
print("=" * 80)

print("""
┌─────────────────────────────────────────────────────────────────────────────┐
│                         装饰器执行流程详解                                    │
└─────────────────────────────────────────────────────────────────────────────┘

【步骤 1】Python 解释器遇到 @decorator 语法

    @decorator
    def original_function(x, y):
        return x + y

【步骤 2】Python 立即将函数传递给装饰器

    original_function = decorator(original_function)

    等价于执行：
    1. 先定义函数
       def original_function(x, y):
           return x + y
       
    2. 再调用装饰器
       original_function = decorator(original_function)

【步骤 3】装饰器内部发生了什么？

    def decorator(func):
        # func = original_function
        print(f"装饰函数: {func.__name__}")
        
        def wrapper(*args, **kwargs):
            # 添加额外功能
            print("执行前逻辑")
            
            # 调用原函数
            result = func(*args, **kwargs)
            
            print("执行后逻辑")
            return result
        
        # 返回包装函数
        return wrapper

【步骤 4】后续调用使用 wrapper 函数

    original_function(1, 2)
    
    实际调用：
    wrapper(1, 2)  # 不再是 original_function！

""")

print("=" * 80)
print("闭包原理图解")
print("=" * 80)

print("""
┌─────────────────────────────────────────────────────────────────────────────┐
│                              闭包（Closure）                                 │
└─────────────────────────────────────────────────────────────────────────────┘

闭包 = 函数 + 引用环境

示例代码：

    def outer(x):
        # 外部作用域变量 x
        def inner(y):
            # 内部函数引用了外部变量 x
            return x + y
        return inner  # 返回内部函数（包含 x 的引用）

执行过程：

    ┌──────────────────────────────────────┐
    │  closure = outer(10)                │
    │                                      │
    │  1. outer(10) 被调用                 │
    │     ├── x = 10                       │
    │     └── 定义 inner 函数             │
    │         (记住了 x = 10)              │
    │                                      │
    │  2. 返回 inner 函数                 │
    │     (包含了 x 的引用)                 │
    │                                      │
    │  3. outer() 执行完毕                │
    │     但 x 仍然被 inner 引用着         │
    └──────────────────────────────────────┘
    
    ┌──────────────────────────────────────┐
    │  result = closure(5)                 │
    │                                      │
    │  1. 调用闭包 closure                 │
    │     (就是 inner 函数)                │
    │                                      │
    │  2. 执行 inner(5)                    │
    │     - 访问记住的 x = 10              │
    │     - 计算 10 + 5 = 15               │
    │                                      │
    │  3. 返回 15                          │
    └──────────────────────────────────────┘

闭包在装饰器中的作用：

    def decorator(func):
        # func 是外部变量，被内部 wrapper 引用
        
        def wrapper(*args, **kwargs):
            # wrapper 可以访问 func
            # 即使 decorator 已经返回，func 仍然存在
            return func(*args, **kwargs)
        
        return wrapper
                    ↑
                    └── 这个 wrapper 就是闭包

""")

print("=" * 80)
print("装饰器与 Callable 的关系")
print("=" * 80)

print("""
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Callable 与装饰器的关系                             │
└─────────────────────────────────────────────────────────────────────────────┘

Callable 的定义：

    所有可以使用 () 调用的对象都是 Callable：
    
    1. 函数            callable(func) → True
    2. 类              callable(Class) → True（调用创建实例）
    3. 类实例          callable(instance) → 如果有 __call__ 方法
    4. 方法            callable(method) → True
    5. lambda          callable(lambda: None) → True

Callable 类型注解：

    1. Callable[[int, str], bool]
       ↑ 参数类型列表   ↑ 返回类型
       
    2. Callable[..., Any]
       ↑ 任意参数

    3. Callable[P, T]  (泛型)
       ↑ 参数规格       ↑ 返回类型

装饰器中的 Callable：

    def decorator(func: Callable) -> Callable:
        
        参数类型：Callable
        - 期望接收一个可调用对象（通常是函数）
        
        返回类型：Callable
        - 返回一个新的可调用对象（wrapper 函数）

为什么要标注 Callable？

    1. 类型检查
       - 类型检查器知道参数和返回值是什么
       - 避免传入错误的类型
    
    2. IDE 支持
       - 代码补全
       - 错误提示
    
    3. 代码文档
       - 明确函数签名
       - 便于维护

""")

print("=" * 80)
print("@wraps 的作用")
print("=" * 80)

print("""
┌─────────────────────────────────────────────────────────────────────────────┐
│                            @wraps 的重要性                                   │
└─────────────────────────────────────────────────────────────────────────────┘

问题：不使用 @wraps

    def decorator(func):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper

    @decorator
    def add(a, b):
        '''加法函数'''
        return a + b

    print(add.__name__)      # 输出: wrapper
    print(add.__doc__)       # 输出: None
    print(add.__module__)    # 可能错误

问题原因：
    - wrapper 覆盖了原函数的所有元数据
    - add 现在是 wrapper 的引用

解决方案：使用 @wraps

    from functools import wraps
    
    def decorator(func):
        @wraps(func)  # 复制原函数的元数据到 wrapper
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper

    @decorator
    def add(a, b):
        '''加法函数'''
        return a + b

    print(add.__name__)      # 输出: add
    print(add.__doc__)       # 输出: 加法函数
    print(add.__wrapped__)   # 指向原函数

@wraps 做了什么：

    1. __name__ = func.__name__
    2. __doc__ = func.__doc__
    3. __module__ = func.__module__
    4. __annotations__ = func.__annotations__
    5. __dict__ = func.__dict__
    6. __qualname__ = func.__qualname__
    7. 添加 __wrapped__ 属性指向原函数

""")

print("=" * 80)
print("装饰器实战：OSS 注入装饰器解析")
print("=" * 80)

print("""
┌─────────────────────────────────────────────────────────────────────────────┐
│                     @oss_inject 装饰器完整解析                               │
└─────────────────────────────────────────────────────────────────────────────┘

装饰器代码：

    P = ParamSpec("P")      # 捕获参数规格
    T = TypeVar("T")        # 捕获返回类型
    
    def oss_inject(method: Callable[P, T]) -> Callable[P, T]:
        '''
        装饰器签名：完整保留原函数的类型信息
        '''
        
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # 自动注入 OSS 客户端
            if not _registry.is_initialized:
                _registry.initialize()
            
            client = _registry.get_client()
            
            # 调用原函数，自动添加 client 参数
            return method(client, *args, **kwargs)
        
        return wrapper

使用示例：

    class Uploader:
        @oss_inject
        def upload(self, client, request: UploadRequest) -> UploadResult:
            '''
            client 参数由装饰器自动注入
            只需定义 request 参数
            '''
            return client.upload_file(request)

    # 调用时
    uploader = Uploader()
    result = uploader.upload(request)  # 只传 request！
                                          # client 自动注入

执行流程：

    1. uploader.upload(request) 被调用
    
    2. 实际调用 wrapper(request)
    
    3. wrapper 中：
       - 自动获取 client
       - 调用 method(client, request)
    
    4. 返回 UploadResult

类型安全：

    - 装饰器保留了完整类型信息
    - 类型检查器知道 upload 需要 UploadRequest，返回 UploadResult
    - IDE 代码补全正常工作

""")
