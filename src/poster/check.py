"""内容检查：替换为品牌方最终内容后，出图前先跑一遍。

只检查格式和已知的乱码风险，不判断文案好坏。
ERROR 必须修改；WARN 可以出图，但乱码或排版风险更高。
"""
import re
from pathlib import Path

FIELDS = {"主标题", "副标题", "产品", "卖点", "产品名", "钩子"}
LIMITS = {"主标题": 12, "副标题": 10, "卖点": 8}  # 超过即提示（不含空格）
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def _len(s):
    """中文按 1 字、英文和数字按半字计，不含空格。"""
    s = s.replace(" ", "")
    return sum(0.5 if ch.isascii() else 1 for ch in s)


COMPARE_FIELDS = {"主标题", "副标题", "钩子", "产品1", "产品2", "场景", "参考图"}
COMPARE_LIMITS = {"主标题": 6, "副标题": 4, "钩子": 8}


def _product_risk(desc):
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9 -]*[A-Za-z0-9]|[A-Za-z0-9]", desc)  # 英文、型号、数字


def check_compare(content, images=None):
    """对比图（风格3）内容：主标题 ≤6 字、副标题 ≤4 字、钩子 ≤8 字、两个产品只写外观。"""
    out = []
    err = lambda m: out.append(("ERROR", m))
    warn = lambda m: out.append(("WARN", m))
    for k in ("主标题", "副标题", "钩子", "产品1", "产品2"):
        if not content.get(k) or (isinstance(content.get(k), str) and not content[k].strip()):
            err(f"缺少字段或为空：{k}")
    for k in set(content) - COMPARE_FIELDS:
        warn(f"未知字段 {k}，不会进入 prompt")
    for k, limit in COMPARE_LIMITS.items():
        v = content.get(k, "")
        for t in (v if isinstance(v, list) else [v]):  # 列表 = 候选池，每张随机抽一句
            if not isinstance(t, str) or not t.strip():
                err(f"{k} 里有空内容")
                continue
            if '"' in t:
                err(f"{k}「{t}」含英文双引号，会打乱 prompt；请改用中文引号“”")
            if _len(t) > limit:
                warn(f"{k}「{t}」约 {_len(t):g} 字，对比图建议不超过 {limit} 字")
            if k == "钩子" and re.search(r"[A-Za-z0-9]", t):
                warn(f"钩子「{t}」含英文或数字，错字风险更高")
    if not content.get("参考图"):
        for k in ("产品1", "产品2"):
            risky = _product_risk(content.get(k, ""))
            if risky:
                warn(f"{k} 描述含英文或数字 {risky}，可能被印到产品上；只写中文外观")
    if content.get("参考图") and (not images or len(images) != 2):
        warn("参考图模式需要 2 张产品图（图1 左、图2 右），出图时加 --image 图1 图2")
    return out


def check_content(content, images=None):
    if "产品1" in content or "产品2" in content:
        out = check_compare(content, images)
        for src in images or []:
            if not src.startswith(("https://", "data:")) and not Path(src).exists():
                out.append(("ERROR", f"产品图不存在：{src}"))
        return out
    out = []
    err = lambda m: out.append(("ERROR", m))
    warn = lambda m: out.append(("WARN", m))

    for k in ("主标题", "副标题", "产品", "卖点"):
        if k not in content:
            err(f"缺少字段：{k}")
    for k in set(content) - FIELDS:
        warn(f"未知字段 {k}，不会进入 prompt")
    points = content.get("卖点", [])
    if not isinstance(points, list) or not all(isinstance(p, str) for p in points):
        err("卖点必须是文字列表，例如 [\"全嵌\", \"隐嵌\", \"零缝嵌入\"]")
        points = []

    texts = [("主标题", content.get("主标题", "")), ("副标题", content.get("副标题", ""))] + \
            [(f"卖点{i}", p) for i, p in enumerate(points, 1)]
    for name, t in texts:
        if not isinstance(t, str) or not t.strip():
            err(f"{name} 为空")
            continue
        if '"' in t:
            err(f"{name}「{t}」含英文双引号，会打乱 prompt；请改用中文引号“”")
        limit = LIMITS.get(re.sub(r"\d+$", "", name))
        if name.startswith("卖点"):
            limit = None  # 卖点长度按“最多 1 个长卖点”统一判断
        if limit and _len(t) > limit:
            warn(f"{name}「{t}」约 {_len(t):g} 字，超过建议的 {limit} 字（英文按半字计），错字风险更高")
    seen = [t for _, t in texts]
    for t in {t for t in seen if seen.count(t) > 1}:
        warn(f"文字「{t}」重复出现")

    # 中等难度标准：3 个卖点、最多 1 个长卖点、共 5 段（2026-11-04 审核确认）
    if points and len(points) != 3:
        warn(f"卖点 {len(points)} 个，中等难度标准为 3 个（共 5 段文字）；多了乱码风险高，少了画面偏空")
    long_points = [p for p in points if _len(p) > LIMITS["卖点"]]
    if len(long_points) > 1:
        warn(f"长卖点（超过 {LIMITS['卖点']} 字）有 {len(long_points)} 个：{long_points}，中等难度标准最多 1 个")

    product = content.get("产品", "")
    risky = re.findall(r"[A-Za-z0-9][A-Za-z0-9 -]*[A-Za-z0-9]|[A-Za-z0-9]", product)  # 英文、型号、数字
    if risky and not content.get("产品名"):
        warn(f"产品描述含英文或数字 {risky}，模型会把它印到产品上（实测“slot in”被印在门板上）；产品描述只写中文外观，型号请放进卖点")

    if content.get("产品名") and not images:
        warn("填写了产品名（参考图模式），但没有提供产品图，出图时请加 --image")
    for src in images or []:
        if src.startswith(("https://", "data:")):
            continue
        p = Path(src)
        if not p.exists():
            err(f"产品图不存在：{src}")
        elif p.suffix.lower() not in IMAGE_EXT:
            warn(f"产品图格式 {p.suffix} 未验证过，建议用 PNG / JPG")
    if images and len(images) > 3:
        err(f"产品图 {len(images)} 张，接口最多 3 张")
    return out
