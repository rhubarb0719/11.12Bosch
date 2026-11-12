"""按风格配置（styles/<id>/style.json）拼接 prompt。

拼接逻辑全部由 style.json 的 template 决定，代码不含任何风格内容；
新增风格只需新建 styles/<id>/style.json。
"""
import json
import random
from pathlib import Path

STYLES_DIR = Path(__file__).resolve().parents[2] / "styles"


def list_styles():
    return sorted(p.parent.name for p in STYLES_DIR.glob("*/style.json") if not p.parent.name.startswith("_"))


def load_style(style_id):
    """style_id：styles/ 下的风格名，或任意风格文件夹路径（如 client/styles/xxx）。"""
    if "/" in style_id:
        path = Path(style_id) / "style.json"
        if not path.exists():
            raise FileNotFoundError(f"没有风格配置：{path}")
        return json.loads(path.read_text(encoding="utf-8"))
    path = STYLES_DIR / style_id / "style.json"
    if not path.exists():
        raise FileNotFoundError(f"没有风格 {style_id}，可选：{list_styles()}")
    return json.loads(path.read_text(encoding="utf-8"))


def _conflicts(style, idx):
    """idx: 类别 → 选项序号（1 起）。命中任一冲突规则返回 True。"""
    return any(all(idx.get(k) == v for k, v in rule.items()) for rule in style.get("conflicts", []))


def _pools(content):
    """内容里的列表字段（卖点除外）是候选池，每张图抽一句，如 "钩子": ["一篇看懂怎么选", "装修党必看"]。"""
    return {k: v for k, v in (content or {}).items() if isinstance(v, list) and k != "卖点"}


def pick(style, mode="first", seed=None, indices=None, content=None):
    """选随机项。mode: first（每类第 1 项）/ random（按 seed 随机，自动跳过冲突组合）/ index（indices 手动指定，1 起）。
    返回 {类别: 选项序号}；内容候选池的选择记为 {"@字段": 序号}（first / index 模式取第 1 句）。"""
    cats = list(style["options"])
    pools = _pools(content)
    if mode == "first":
        return {**{c: 1 for c in cats}, **{f"@{k}": 1 for k in pools}}
    if mode == "index":
        return {**dict(zip(cats, indices)), **{f"@{k}": 1 for k in pools}}
    rng = random.Random(seed)
    while True:
        idx = {c: rng.randint(1, len(style["options"][c])) for c in cats}
        if not _conflicts(style, idx):
            idx.update({f"@{k}": rng.randint(1, len(v)) for k, v in pools.items()})
            return idx


class _Keep(dict):
    """format_map 用：没有的占位符原样保留。"""
    def __missing__(self, key):
        return "{" + key + "}"


def build(style, content, idx):
    """拼 prompt，返回 (prompt, negative_prompt)。

    content 的文字字段（主标题、副标题、产品、产品1、产品2、场景…）都可在 template / 选项 / 风格 / 文字约束中用 {字段名} 引用。
    卖点（列表）展开为 {卖点}（逐个加引号）和 {卖点数}。
    可选：产品名（单产品参考图）、参考图: true（多产品参考图，用 style 的“参考图替换”）。
    style 可选：默认值（缺省字段）、联动（抽到某选项时追加变量）、参考图时固定（覆盖某些类别）。
    """
    base = dict(style.get("默认值", {}))
    base.update({k: v for k, v in content.items() if isinstance(v, str)})
    for k, pool in _pools(content).items():  # 候选池：按 idx 中的 @字段 取一句
        base[k] = pool[idx.get(f"@{k}", 1) - 1]
    idx = {c: i for c, i in idx.items() if not c.startswith("@")}
    if "卖点" in content:
        base["卖点"] = "".join(f'"{p}"' for p in content["卖点"])
        base["卖点数"] = len(content["卖点"])
    if content.get("产品名"):  # 单产品参考图：产品描述改为“保持参考图不变”
        base["产品"] = style["产品来自参考图"].format(产品名=content["产品名"])
    if content.get("参考图"):  # 多产品参考图：如“图1中的产品”
        base.update(style.get("参考图替换", {}))
    for c, i in idx.items():
        base.update(style.get("联动", {}).get(c, {}).get(str(i), {}))
    chosen = {c: style["options"][c][i - 1] for c, i in idx.items()}
    if content.get("产品名") or content.get("参考图"):
        chosen.update(style.get("参考图时固定", {}))
    fmt = lambda s: s.format_map(_Keep(base))
    values = {**base, **{c: fmt(v) for c, v in chosen.items()},
              "风格": fmt(style["风格"]), "文字约束": fmt(style["文字约束"])}
    return "".join(seg.format(**values) for seg in style["template"]), style["negative_prompt"]


def build_request(style, content, idx, n=1, seed=None, images=None):
    """拼出完整请求体。images 为参考图（HTTPS URL 或 data URL，1–3 张）。"""
    prompt, negative = build(style, content, idx)
    body = json.loads(json.dumps(style["params"]))
    body.update(prompt=prompt, negative_prompt=negative, n=n)
    if seed is not None:
        body["seed"] = seed
    if images:
        body["image"] = images if len(images) > 1 else images[0]
    return body
