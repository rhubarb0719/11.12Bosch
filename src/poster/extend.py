"""品牌图扩图 + 场景淡化。原图像素（包括冰箱和原有环境）全部保留，模型只补全新增的画布区域。

  1. outpaint_canvas()  横版原图等比放进 3:4 画布中间，上下留灰色空白
  2. 千问编辑接口补全空白（延续天花板、墙面、地面）
  3. paste_original()   把整张原图按原位置贴回出图
  4. fade_scene()       冰箱区域保持原图，其余场景往白色淡化（场景不透明度可调）
"""
from PIL import Image, ImageDraw, ImageFilter

CANVAS = (1728, 2304)      # 3:4，与千问 2K 输出尺寸一致
FILL = (200, 200, 200)

PROMPT = ("图1中间是一张完整、清晰的室内家居照片，上方和下方是模糊的待补全区域。请把上下两块模糊区域画成清晰、真实的室内摄影画面：向上自然延伸原照片的天花板、吊顶和墙面，"
          "向下自然延伸原照片的地面和地毯；材质、颜色、光线方向、透视和色调与原照片完全一致，接缝处自然过渡、看不出拼接；上方要出现完整的天花板（可有吊顶灯带或筒灯），下方要出现完整的地面和家具的下半部分。"
          "中间原照片里的所有内容保持不变，不要改动冰箱和柜体。不要新增人物、文字、字母、数字、logo 或水印。")
NEGATIVE = "模糊, 拼接痕迹, 接缝, 色差, 透视错误, 灰色区域, 纯色块, 新增冰箱, 人物, 文字, logo, 水印, 低分辨率"


def outpaint_canvas(orig, canvas=CANVAS, fill=FILL, center_y=0.5, prefill=True, blur=40):
    """返回 (画布, 原图在画布中的位置 (x0,y0,x1,y1), 缩放比例)。
    prefill：用原图上下边缘拉伸并模糊后的内容预填空白（比纯灰色更容易让模型补全为真实场景）。"""
    W, H = canvas
    s = W / orig.width
    w, h = W, round(orig.height * s)
    y0 = round((H - h) * center_y)
    src = orig.convert("RGB").resize((w, h), Image.LANCZOS)
    img = Image.new("RGB", canvas, fill)
    if prefill:
        band = max(8, h // 10)
        top = src.crop((0, 0, w, band)).resize((w, y0 + 1)).filter(ImageFilter.GaussianBlur(blur))
        bot = src.crop((0, h - band, w, h)).resize((w, H - y0 - h + 1)).filter(ImageFilter.GaussianBlur(blur))
        img.paste(top, (0, 0))
        img.paste(bot, (0, y0 + h))
    img.paste(src, (0, y0))
    return img, (0, y0, w, y0 + h), s


def paste_original(generated, orig, box):
    """把整张原图贴回原位（出图先缩放到画布尺寸）。"""
    out = generated.convert("RGB").resize(CANVAS, Image.LANCZOS) if generated.size != CANVAS else generated.convert("RGB")
    x0, y0, x1, y1 = box
    out.paste(orig.convert("RGB").resize((x1 - x0, y1 - y0), Image.LANCZOS), (x0, y0))
    return out


def quad_to_canvas(quad, box, s):
    return [(box[0] + x * s, box[1] + y * s) for x, y in quad]


def fade_scene(img, quad, scene_opacity, color=(255, 255, 255), feather=1.5):
    """冰箱（quad 内）保持原样，其余场景按 scene_opacity（0–100）向 color 淡化。"""
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).polygon([tuple(p) for p in quad], fill=255)
    if feather:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    faded = Image.blend(Image.new("RGB", img.size, color), img, scene_opacity / 100)
    return Image.composite(img, faded, mask)


def refine_quad(img, quad, search=40):
    """在大致的四角附近，沿四条边找亮度变化最大的位置，微调四角（图像坐标）。"""
    L = img.convert("L").load()
    (tlx, tly), (trx, try_), (brx, bry), (blx, bly) = quad

    def best_x(y, x_guess):
        cand = [(abs(L[x + 3, y] - L[x - 3, y]), x) for x in range(int(x_guess - search), int(x_guess + search))]
        return max(cand)[1]

    def best_y(x, y_guess):
        cand = [(abs(L[x, y + 3] - L[x, y - 3]), y) for y in range(int(y_guess - search), int(y_guess + search))]
        return max(cand)[1]

    lx = sorted(best_x(int(tly + (bly - tly) * t), tlx + (blx - tlx) * t) for t in (0.2, 0.4, 0.6, 0.8))[2]
    rx = sorted(best_x(int(try_ + (bry - try_) * t), trx + (brx - trx) * t) for t in (0.2, 0.4, 0.6, 0.8))[1]
    ty = lambda x: best_y(int(x), tly + (try_ - tly) * (x - tlx) / (trx - tlx))
    by = lambda x: best_y(int(x), bly + (bry - bly) * (x - blx) / (brx - blx))
    i = 3                                              # 往内收几像素，避开边缘反光线
    return [(lx + i, ty(lx + 10) + i), (rx - i, ty(rx - 10) + i), (rx - i, by(rx - 10) - i), (lx + i, by(lx + 10) - i)]


def align_original(generated, orig, box, coarse=None):
    """模型重画中间区域时常有整体偏移/缩放（约 1–2%、十几像素）。
    搜索 (scale, dx, dy)，使原图按此等比缩放+平移后与模型出图最吻合。返回 (scale, dx, dy, 误差, 不变换误差)。"""
    import numpy as np
    gen = np.asarray(generated.convert("L").resize(CANVAS, Image.LANCZOS), float)
    w, h = box[2] - box[0], box[3] - box[1]
    ref = np.asarray(orig.convert("L").resize((w, h), Image.LANCZOS), float)
    cx, cy = box[0] + w / 2, box[1] + h / 2
    ys, xs = np.arange(80, h - 80, 5), np.arange(80, w - 80, 5)

    def err(sc, dx, dy):
        Y = (cy + (ys + box[1] - cy) * sc + dy).round().astype(int).clip(0, CANVAS[1] - 1)
        X = (cx + (xs + box[0] - cx) * sc + dx).round().astype(int).clip(0, CANVAS[0] - 1)
        return np.abs(gen[np.ix_(Y, X)] - ref[np.ix_(ys, xs)]).mean()

    best = min((err(sc, dx, dy), sc, dx, dy) for sc in np.arange(0.97, 1.0301, 0.005)
               for dx in range(-30, 31, 2) for dy in range(-30, 31, 2))
    _, s0, x0, y0 = best
    best = min((err(sc, dx, dy), sc, dx, dy) for sc in np.arange(s0 - 0.004, s0 + 0.0041, 0.001)
               for dx in range(x0 - 2, x0 + 3) for dy in range(y0 - 2, y0 + 3))
    return round(float(best[1]), 4), best[2], best[3], round(float(best[0]), 2), round(float(err(1.0, 0, 0)), 2)


def blend_original(generated, orig, box, scale=1.0, dx=0, dy=0, feather=60):
    """原图按 (scale, dx, dy) 等比缩放对齐到模型出图上，上下边缘 feather 像素渐变融合。
    返回 (结果图, 原图实际所在框, 100% 原图区域的 y 范围)。"""
    out = generated.convert("RGB").resize(CANVAS, Image.LANCZOS)
    w, h = box[2] - box[0], box[3] - box[1]
    cx, cy = box[0] + w / 2, box[1] + h / 2
    nw, nh = round(w * scale), round(h * scale)
    x0, y0 = round(cx - nw / 2 + dx), round(cy - nh / 2 + dy)
    layer = Image.new("RGB", CANVAS)
    layer.paste(orig.convert("RGB").resize((nw, nh), Image.LANCZOS), (x0, y0))
    mask = Image.new("L", CANVAS, 0)
    ImageDraw.Draw(mask).rectangle([max(x0, 0) + 12 if x0 > 0 else -50, y0 + feather,
                                    x0 + nw - 12 if x0 + nw < CANVAS[0] else CANVAS[0] + 50, y0 + nh - feather], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(feather / 2.5))
    solid = (y0 + 2 * feather, y0 + nh - 2 * feather)
    return Image.composite(layer, out, mask), (x0, y0, x0 + nw, y0 + nh), solid
