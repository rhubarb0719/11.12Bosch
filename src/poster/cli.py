"""命令行入口。

  python3 -m poster styles
  python3 -m poster prompt   --style style1-sticker --content examples/content/中等.json [--random 7 | --pick 1,1,2,...]
  python3 -m poster generate --style style1-sticker --content examples/content/中等.json [--count 6] [--n 1] [--image ref.png]

需要环境变量 CR_API_KEY（generate）。结果在 output/<时间>/：result.json 记录 prompt、参数、task_id、图片链接。
"""
import argparse
import base64
import concurrent.futures as cf
import datetime
import json
import mimetypes
import os
import random
import sys
import time
from pathlib import Path

from . import prompt as P
from .client import CRClient, CRError, EDIT, GENERATE

ROOT = Path(__file__).resolve().parents[2]


def to_image_ref(src):
    if src.startswith(("https://", "data:")):
        return src
    mime = mimetypes.guess_type(src)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(Path(src).read_bytes()).decode()


def picks_for(style, a, i, content=None):
    if a.pick:
        return P.pick(style, "index", indices=[int(x) for x in a.pick.split(",")], content=content)
    if a.random is not None or a.count > 1:
        return P.pick(style, "random", seed=(a.random or 0) + i, content=content)
    return P.pick(style, "first", content=content)


def run_one(client, style, content, idx, a, i, outdir, images):
    # 每张图一个 seed 并记录下来，方便复现；--seed 固定起始值
    seed = (a.seed + i) if a.seed is not None else random.randint(0, 2147483647)
    body = P.build_request(style, content, idx, n=a.n, seed=seed, images=images)
    rec = {"no": i + 1, "picks": {c: (style["options"][c][j - 1] if not c.startswith("@") else content[c[1:]][j - 1])
                                  for c, j in idx.items()},
           "request": {**body, "image": "<参考图>"} if images else body}
    for attempt in range(4):  # 上游限流（upstream_rate_limited）时等待后重新提交
        try:
            task, rec["usage_id"] = client.submit(body, EDIT if images else GENERATE)
            rec["task_id"] = task["id"]
            res = client.wait(task["id"])
        except (CRError, OSError, TimeoutError) as e:
            rec.update(status="error", error=str(e))
            return rec
        if (res.get("error") or {}).get("code") != "upstream_rate_limited" or attempt == 3:
            break
        time.sleep(10 * (attempt + 1))
    rec["status"] = res.get("status")
    rec["error"] = res.get("error")
    rec["urls"] = [d["url"] for d in res.get("data", []) if d.get("url")]
    rec["files"] = []
    for k, url in enumerate(rec["urls"], 1):
        f = outdir / f"{i + 1:02d}_{k}.png"
        try:
            client.download(url, f)
            rec["files"].append(f.name)
        except OSError as e:
            rec["download_error"] = str(e)
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(prog="poster")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("styles", help="列出可用风格")
    c = sub.add_parser("check", help="检查内容 JSON（替换最终内容后先跑）")
    c.add_argument("content", nargs="+", help="一个或多个内容 JSON")
    c.add_argument("--image", nargs="+", help="产品参考图，检查是否存在、数量是否超限")
    for name in ("prompt", "generate"):
        s = sub.add_parser(name)
        s.add_argument("--style", required=True)
        s.add_argument("--content", required=True, help="内容 JSON：主标题、副标题、产品、卖点")
        s.add_argument("--random", type=int, metavar="SEED", help="随机抽选项的种子")
        s.add_argument("--pick", help="手动指定每类选项序号，逗号分隔，顺序同 style.json 的 options")
        s.add_argument("--count", type=int, default=1, help="出几种不同组合")
        if name == "generate":
            s.add_argument("--n", type=int, default=1, help="每种组合出几张（1–6）")
            s.add_argument("--seed", type=int, help="图片 seed；--count>1 时依次 +1")
            s.add_argument("--image", nargs="+", help="产品参考图（本地路径或 HTTPS URL，最多 3 张）")
            s.add_argument("--workers", type=int, default=3, help="并发数，超过 3 容易被上游限流")
    a = ap.parse_args(argv)

    if a.cmd == "styles":
        for sid in P.list_styles():
            st = P.load_style(sid)
            print(f"{sid}\t{st['name']}\t{st.get('status', '')}")
        return

    if a.cmd == "check":
        from .check import check_content
        bad = False
        for f in a.content:
            items = check_content(json.loads(Path(f).read_text(encoding="utf-8")), a.image)
            bad |= any(lv == "ERROR" for lv, _ in items)
            print(f"{'✗' if any(lv == 'ERROR' for lv, _ in items) else '✓'} {f}")
            for lv, msg in items:
                print(f"   {lv}  {msg}")
        sys.exit(1 if bad else 0)

    style = P.load_style(a.style)
    content = json.loads(Path(a.content).read_text(encoding="utf-8"))

    if a.cmd == "prompt":
        for i in range(a.count):
            idx = picks_for(style, a, i, content)
            p, neg = P.build(style, content, idx)
            print(json.dumps({"picks": idx, "prompt": p, "negative_prompt": neg}, ensure_ascii=False, indent=2))
        return

    key = os.environ.get("CR_API_KEY") or sys.exit("请设置环境变量 CR_API_KEY")
    images = [to_image_ref(s) for s in a.image[:3]] if a.image else None
    outdir = ROOT / "output" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir.mkdir(parents=True)
    client = CRClient(key)
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(run_one, client, style, content, picks_for(style, a, i, content), a, i, outdir, images)
                for i in range(a.count)]
        recs = sorted((f.result() for f in futs), key=lambda r: r["no"])
    (outdir / "result.json").write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in recs:
        print(f"[{r['no']}] {r['status']}  task_id={r.get('task_id')}  {r.get('error') or ''}")
        for f in r.get("files", []):
            print("   文件：", outdir / f)
        if r.get("download_error"):
            for u in r.get("urls", []):
                print("   链接：", u)
    print("记录：", outdir / "result.json")


if __name__ == "__main__":
    main()
