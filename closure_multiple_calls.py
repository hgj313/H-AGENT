"""闭包中的变量绑定 - 关键问题解答"""

print("=" * 70)
print("问题：多次调用 closure(5) 会变成 20 吗？")
print("=" * 70)

def outer(x):
    """外部函数"""
    def inner(y):
        """内部函数 - 每次调用都重新计算"""
        return x + y
    return inner

print("\n代码：")
print("""
def outer(x):
    def inner(y):
        return x + y
    return inner

closure = outer(10)  # 创建闭包，x = 10
""")

# 创建闭包
closure = outer(10)

print("\n" + "=" * 70)
print("执行多次调用")
print("=" * 70)

print("\n第一次调用：result1 = closure(5)")
result1 = closure(5)
print(f"  计算过程：x = {10} + y = {5} = {result1}")

print("\n第二次调用：result2 = closure(5)")
result2 = closure(5)
print(f"  计算过程：x = {10} + y = {5} = {result2}")

print("\n第三次调用：result3 = closure(5)")
result3 = closure(5)
print(f"  计算过程：x = {10} + y = {5} = {result3}")

print("\n" + "=" * 70)
print("答案：所有结果都是 15，不会变成 20！")
print("=" * 70)

print("""
原因分析：

┌─────────────────────────────────────────────────────────────┐
│  闭包中的变量绑定                                            │
└─────────────────────────────────────────────────────────────┘

1. outer(10) 调用一次，创建闭包
   → x = 10（固定不变）

2. 每次调用 closure(5)：
   → y = 5（参数）
   → x + y = 10 + 5 = 15（每次都重新计算）

3. x 的值始终是 10，不会累积！
   → 不是 x = x + y
   → 而是 return x + y（读取 x 的值）

┌─────────────────────────────────────────────────────────────┐
│  类比理解                                                    │
└─────────────────────────────────────────────────────────────┘

闭包中的变量就像：
  - x = 10 是"模具"（固定不变）
  - y = 5 是"原料"（每次不同）
  - 结果 = 模具 + 原料

  每次放入原料，都得到相同的结果（因为模具不变）

""")

print("=" * 70)
print("那什么时候会累积变化？")
print("=" * 70)

print("""
如果要让变量累积变化，需要在闭包中修改变量：

┌─────────────────────────────────────────────────────────────┐
│  情况 1：直接修改变量（不推荐）                               │
└─────────────────────────────────────────────────────────────┘

def outer():
    x = 10  # 初始值
    
    def inner(y):
        # ❌ 不能直接修改外部变量
        # x = x + y  # 这会创建新的局部变量！
        return x + y
    
    return inner

┌─────────────────────────────────────────────────────────────┐
│  情况 2：使用 nonlocal 声明（正确方式）                       │
└─────────────────────────────────────────────────────────────┘

def outer():
    x = 10  # 初始值
    
    def inner(y):
        nonlocal x  # 声明要修改外部变量
        x = x + y   # 累积变化！
        return x
    
    return inner

closure = outer()
print(closure(5))  # 10 + 5 = 15
print(closure(5))  # 15 + 5 = 20  ← 会累积！
print(closure(5))  # 20 + 5 = 25  ← 继续累积！

""")

print("=" * 70)
print("实际验证：累积变化")
print("=" * 70)

def outer_accumulator():
    """会累积变化的闭包"""
    x = 10  # 初始值
    
    def inner(y):
        nonlocal x
        x = x + y  # 累积变化
        return x
    
    return inner

print("\n使用 nonlocal 的闭包：")
acc_closure = outer_accumulator()

result1 = acc_closure(5)
print(f"  acc_closure(5) = {result1}  (10 + 5)")

result2 = acc_closure(5)
print(f"  acc_closure(5) = {result2}  (15 + 5) ← 累积了！")

result3 = acc_closure(5)
print(f"  acc_closure(5) = {result3}  (20 + 5) ← 继续累积！")

print("\n" + "=" * 70)
print("总结")
print("=" * 70)

print("""
┌─────────────────────────────────────────────────────────────┐
│  普通闭包（return x + y）                                    │
│  → 变量值不变，每次计算结果相同                               │
│  → closure(5) = 15, closure(5) = 15, closure(5) = 15        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  累积闭包（nonlocal x; x = x + y）                           │
│  → 变量值累积变化，每次计算结果不同                           │
│  → closure(5) = 15, closure(5) = 20, closure(5) = 25      │
└─────────────────────────────────────────────────────────────┘
""")
