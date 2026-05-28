"""闭包详解 - 逐步执行"""

print("=" * 70)
print("闭包（Closure）逐步执行过程详解")
print("=" * 70)

print("""
┌─────────────────────────────────────────────────────────────────┐
│                        代码                                      │
└─────────────────────────────────────────────────────────────────┘

def outer(x):                    # 定义外部函数
    def inner(y):                # 定义内部函数
        return x + y            # 使用外部变量 x
    return inner                 # 返回内部函数

closure = outer(10)              # 调用外部函数
result = closure(5)             # 调用返回的内部函数

""")

print("=" * 70)
print("执行步骤 1：调用 outer(10)")
print("=" * 70)

def outer_step1(x):
    """模拟 outer(10) 的执行"""
    print(f"Step 1: outer(10) 被调用")
    print(f"         创建局部变量: x = {x}")
    print()

    def inner_step2(y):
        """内部函数（未执行）"""
        print(f"Step 2: inner(y) 定义了，但还没调用")
        print(f"         x = {x}（来自外部作用域）")
        print(f"         y = {y}（参数）")
        print(f"         return {x} + {y}")
        return x + y

    print(f"Step 3: return inner")
    print(f"         outer 执行完毕，但 x 变量还在内存中")
    print()
    return inner_step2

print("执行: closure = outer(10)")
closure = outer_step1(10)

print("=" * 70)
print("执行步骤 2：调用 closure(5)")
print("=" * 70)

print("\n注意：此时 outer(10) 已经执行完毕")
print("但 closure（就是 inner 函数）仍然可以访问 x = 10")
print()

print("执行: result = closure(5)")
result = closure(5)
print(f"\n最终结果: {result}")

print("\n" + "=" * 70)
print("关键理解：为什么 x 没有消失？")
print("=" * 70)

print("""
┌─────────────────────────────────────────────────────────────────┐
│                        正常情况                                  │
└─────────────────────────────────────────────────────────────────┘

def normal_function():
    x = 10
    print(f"x = {x}")  # 使用 x
    return "done"

result = normal_function()
# 函数结束后，x 被销毁（垃圾回收）

┌─────────────────────────────────────────────────────────────────┐
│                        闭包情况                                  │
└─────────────────────────────────────────────────────────────────┘

def outer(x):            # x = 10
    def inner(y):
        return x + y     # inner 引用了 x
    return inner          # 返回 inner（包含 x 的引用）

closure = outer(10)       # outer 结束，但 x 仍被 inner 引用
                           # Python 保留 x 在内存中！

result = closure(5)       # 可以使用 x

┌─────────────────────────────────────────────────────────────────┐
│                        形象比喻                                  │
└─────────────────────────────────────────────────────────────────┘

闭包就像：
  1. 爸爸（outer）给孩子（inner）一个玩具（x）
  2. 爸爸出门了（outer 执行完毕）
  3. 但孩子还拿着玩具（inner 引用着 x）
  4. 玩具不会被扔掉（x 保留在内存中）
  5. 任何时候都可以玩这个玩具（inner 可以访问 x）

""")

print("=" * 70)
print("装饰器中的闭包应用")
print("=" * 70)

def decorator_step_by_step():
    """逐步演示装饰器中的闭包"""
    
    print("""
┌─────────────────────────────────────────────────────────────────┐
│                    装饰器代码                                    │
└─────────────────────────────────────────────────────────────────┘

def decorator(func):
    # func 是外部变量
    
    def wrapper(*args, **kwargs):
        # wrapper 引用了 func
        return func(*args, **kwargs)
    
    return wrapper  # 返回 wrapper（包含 func 的引用）

@decorator
def original():
    return "Hello"

""")

    print("执行过程：")
    print()
    print("1. @decorator 装饰器被调用")
    print("   decorator(original) 被执行")
    print()

    func = "original_function"  # 模拟原函数
    print(f"   接收参数: func = {func}")
    print()

    print("2. 定义 wrapper 函数")
    print("   wrapper 可以访问 func（来自外部作用域）")
    print()

    def wrapper():
        return f"调用 {func}()"
    print(f"   wrapper 定义完成")
    print()

    print("3. decorator 返回 wrapper")
    print("   original 现在是 wrapper")
    print(f"   original = {wrapper}")
    print()

    print("4. 后续调用 original()")
    print("   实际调用 wrapper()")
    result = wrapper()
    print(f"   返回: {result}")
    print()

    print("关键点：")
    print("  - decorator 执行完毕后，func 仍然存在")
    print("  - wrapper 闭包引用着 func")
    print("  - Python 保留 func 在内存中")

decorator_step_by_step()

print("\n" + "=" * 70)
print("简化理解记忆法")
print("=" * 70)

print("""
┌─────────────────────────────────────────────────────────────────┐
│                      记住这个图                                  │
└─────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐
    │    outer(x)      │
    │                  │
    │  x = 10         │  ← 外部变量
    │  ┌──────────┐   │
    │  │ inner()  │   │
    │  │          │   │
    │  │ return   │   │  ← 内部函数引用 x
    │  │  x + y   │   │
    │  └──────────┘   │
    │       ↓         │
    │    return       │
    │    inner        │
    └──────────────────┘
           ↓
    outer(10) 执行完毕
           ↓
    ┌──────────────────┐
    │    closure       │
    │                  │
    │  可以访问 x = 10 │
    │  可以访问 y = 5  │
    │  x + y = 15     │
    └──────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      一句话总结                                  │
└─────────────────────────────────────────────────────────────────┘

闭包 = 函数 + 环境
  - 函数记住了创建时的外部变量
  - 即使外部函数结束，变量仍然存在

""")

print("=" * 70)
print("最终代码验证")
print("=" * 70)

def outer(x):
    def inner(y):
        return x + y
    return inner

closure = outer(10)
result = closure(5)

print(f"outer(10) 返回一个函数（闭包）")
print(f"闭包调用 closure(5) = {result}")
print(f"解释：x = 10（来自 outer），y = 5（参数），x + y = 15")
