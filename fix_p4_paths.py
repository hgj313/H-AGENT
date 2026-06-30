"""一次性把 P4 测试里所有 prd_path 字符串替换为 self._tmp_prd 真实路径。"""
import re
from pathlib import Path

p = Path(r"tests\test_p4_design_review_e2e.py")
s = p.read_text(encoding="utf-8")

# 替换 prd_path 字符串值（任何 ".md" / 纯字符串）
new = re.sub(
    r'"prd_path"\s*:\s*"[^"]+"',
    '"prd_path": str(self._tmp_prd)',
    s,
)
# 替换 image_urls 里的占位 https://x
new = re.sub(
    r'"image_urls"\s*:\s*\["https://x"\]',
    '"image_urls": [self._mock_image_url]',
    new,
)
# 替换残留的 "https://x"（不在 image_urls 键内的）
new = new.replace('"https://x"', "self._mock_image_url")

p.write_text(new, encoding="utf-8")

print("替换完成")
print("剩余 x.md 引用:", new.count("x.md"))
print("剩余 a.md/b.md 引用:", new.count("a.md") + new.count("b.md"))
print("剩余 https://x 引用:", new.count("https://x"))
print("self._tmp_prd 引用次数:", new.count("self._tmp_prd"))
print("self._mock_image_url 引用次数:", new.count("self._mock_image_url"))
