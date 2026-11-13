"""笔记封面排版（纯代码合成，不经过模型）。

产品和场景 = 品牌原图像素；文字 = 字体直接排版，不会写错字。
三种类型：
  type1  场景为底图，卖点在顶部
  type2  场景局部抠成拱形 / 圆形贴片，拼贴 + 文字
  type3  场景裁切进拍立得相框，手帐拼贴风
"""
import math
import random

from PIL import Image, ImageDraw, ImageFilter, ImageOps

W, H = 1728, 2304
SERIF_B = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"
SANS_M = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
SANS_R = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
INK = (58, 46, 36)          # 深棕文字
ACCENT = (176, 128, 84)     # 暖木色强调
PAPER = (244, 239, 231)

_fonts = {}


def font(path, size):
    from PIL import ImageFont
    k = (path, size)
    if k not in _fonts:
        _fonts[k] = ImageFont.truetype(path, size, index=2)   # ttc index 2 = SC 简体
    return _fonts[k]


def text_w(d, s, f):
    b = d.textbbox((0, 0), s, font=f)
    return b[2] - b[0]


def center_text(d, y, s, f, fill, cx=W // 2, spacing=0):
    if spacing:
        ws = [text_w(d, c, f) for c in s]
        x = cx - (sum(ws) + spacing * (len(s) - 1)) / 2
        for c, w in zip(s, ws):
            d.text((x, y), c, font=f, fill=fill)
            x += w + spacing
    else:
        d.text((cx - text_w(d, s, f) / 2, y), s, font=f, fill=fill)


def cover_crop(img, box, size):
    return img.crop(box).resize(size, Image.LANCZOS)


def crop_around(img, quad, aspect, height_ratio=1.0, fx=0.5, fy=0.5):
    """以冰箱为中心裁出给定宽高比的区域；fx/fy 是冰箱中心在裁切框里的相对位置。"""
    xs = [p[0] for p in quad]; ys = [p[1] for p in quad]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    h = img.height * height_ratio
    w = h * aspect
    if w > img.width:
        w = img.width; h = w / aspect
    x0 = min(max(cx - w * fx, 0), img.width - w)
    y0 = min(max(cy - h * fy, 0), img.height - h)
    return (round(x0), round(y0), round(x0 + w), round(y0 + h))


def shadow(layer_size, mask, offset=(0, 18), blur=30, alpha=90):
    sh = Image.new("RGBA", layer_size, (0, 0, 0, 0))
    m = Image.new("L", layer_size, 0)
    m.paste(mask, offset)
    m = m.point(lambda v: v * alpha // 255).filter(ImageFilter.GaussianBlur(blur))
    sh.putalpha(m)
    return sh


def paste_with_shadow(canvas, img, pos, mask=None, rotate=0, **kw):
    img = img.convert("RGBA")
    if mask is not None:
        img.putalpha(mask)
    if rotate:
        img = img.rotate(rotate, resample=Image.BICUBIC, expand=True)
    a = img.split()[3]
    pad = 80
    big = Image.new("L", (img.width + 2 * pad, img.height + 2 * pad), 0)
    big.paste(a, (pad, pad))
    sh = shadow(big.size, big, **kw)
    canvas.alpha_composite(sh, (pos[0] - pad, pos[1] - pad))
    canvas.alpha_composite(img, pos)
    return img.size


def paper(size=(W, H), base=PAPER, seed=1):
    """纸张底纹：轻微噪点 + 纤维。"""
    rnd = random.Random(seed)
    im = Image.new("RGB", size, base)
    noise = Image.effect_noise(size, 18).convert("L").filter(ImageFilter.GaussianBlur(0.6))
    im = Image.blend(im, Image.merge("RGB", [noise] * 3), 0.06)
    d = ImageDraw.Draw(im)
    for _ in range(260):
        x, y = rnd.randrange(size[0]), rnd.randrange(size[1])
        a = rnd.random() * math.pi
        L = rnd.randint(8, 30)
        c = tuple(v - rnd.randint(6, 16) for v in base)
        d.line([(x, y), (x + L * math.cos(a), y + L * math.sin(a))], fill=c, width=1)
    return im


def bezier(p, n=60):
    out = []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 3 * p[0][0] + 3 * (1 - t) ** 2 * t * p[1][0] + 3 * (1 - t) * t ** 2 * p[2][0] + t ** 3 * p[3][0]
        y = (1 - t) ** 3 * p[0][1] + 3 * (1 - t) ** 2 * t * p[1][1] + 3 * (1 - t) * t ** 2 * p[2][1] + t ** 3 * p[3][1]
        out.append((x, y))
    return out


def doodle_arrow(d, pts, color, width=7, head=34):
    line = bezier(pts)
    d.line(line, fill=color, width=width, joint="curve")
    (x1, y1), (x2, y2) = line[-4], line[-1]
    a = math.atan2(y2 - y1, x2 - x1)
    for s in (2.6, -2.6):
        d.line([(x2, y2), (x2 + head * math.cos(a + s), y2 + head * math.sin(a + s))], fill=color, width=width)


def underline_swoosh(d, x0, x1, y, color, width=8):
    d.line(bezier([(x0, y + 6), ((x0 * 2 + x1) / 3, y - 10), ((x0 + x1 * 2) / 3, y + 14), (x1, y - 4)]),
           fill=color, width=width, joint="curve")


def sparkle(d, cx, cy, r, color, width=5):
    d.line([(cx, cy - r), (cx, cy + r)], fill=color, width=width)
    d.line([(cx - r, cy), (cx + r, cy)], fill=color, width=width)


def tape(canvas, center, size=(220, 64), angle=-8, color=(236, 226, 205, 210)):
    t = Image.new("RGBA", size, color)
    dd = ImageDraw.Draw(t)
    for x in range(0, size[0], 9):                    # 胶带齿边
        dd.polygon([(x, 0), (x + 4, 5), (x + 9, 0)], fill=(0, 0, 0, 0))
        dd.polygon([(x, size[1]), (x + 4, size[1] - 5), (x + 9, size[1])], fill=(0, 0, 0, 0))
    t = t.rotate(angle, resample=Image.BICUBIC, expand=True)
    canvas.alpha_composite(t, (round(center[0] - t.width / 2), round(center[1] - t.height / 2)))


# ---------------------------------------------------------------- 类型 1
def map_quad(quad, box, size):
    sx, sy = size[0] / (box[2] - box[0]), size[1] / (box[3] - box[1])
    return [((x - box[0]) * sx, (y - box[1]) * sy) for x, y in quad]


def type1(scene, quad, c, variant="crop"):
    """场景为底图，标题和卖点在上方。冰箱区域不加任何遮罩，保持原图实色。
    variant="crop"：冰箱靠右裁成 3:4 满版，文字左对齐放在左上留白处；
    "full"：场景裁成横幅（保留大部分环境）放下方，上方取场景色渐变留白放文字。
    返回 (封面, 冰箱在封面中的四角)。"""
    if variant == "crop":
        box = crop_around(scene, quad, W / H, fx=0.80, fy=0.55)
        canvas = cover_crop(scene, box, (W, H)).convert("RGBA")
        fq = map_quad(quad, box, (W, H))
        # 左上角往右下渐隐的米白薄纱，冰箱区域挖空
        g = Image.radial_gradient("L").resize((2 * W, 2 * 1250)).crop((W, 1250, 2 * W, 2 * 1250))
        g = ImageOps.invert(g).point(lambda v: int(min(255, v * 1.25) * 0.82))
        veil_a = Image.new("L", (W, H), 0); veil_a.paste(g, (0, 0))
        ImageDraw.Draw(veil_a).polygon([(x + dx, y) for (x, y), dx in zip(fq, (-6, 6, 6, -6))], fill=0)
        veil = Image.new("RGBA", (W, H), (250, 246, 240, 255)); veil.putalpha(veil_a)
        canvas.alpha_composite(veil)
        x0, y, align = 110, 170, "left"
    else:
        bh = 1300
        box = crop_around(scene, quad, W / bh, fx=0.62, fy=0.5)
        s = cover_crop(scene, box, (W, bh))
        top = s.crop((0, 0, W, 6)).resize((1, 1), Image.BOX).getpixel((0, 0))
        bg = tuple(min(255, int(v * 0.35 + 250 * 0.65)) for v in top)
        canvas = Image.new("RGBA", (W, H), bg + (255,))
        y0 = H - bh
        canvas.paste(s, (0, y0))
        fq = [(x, y + y0) for x, y in map_quad(quad, box, (W, bh))]
        fade = 220
        g = Image.linear_gradient("L").resize((W, fade)).transpose(Image.FLIP_TOP_BOTTOM)
        band = Image.new("RGBA", (W, fade), bg + (0,)); band.putalpha(g)
        canvas.alpha_composite(band, (0, y0))
        x0, y, align = W // 2, 190, "center"
    d = ImageDraw.Draw(canvas)
    ft = font(SERIF_B, 140 if align == "left" else 132)
    lines = c["主标题"].replace("，", "，\n").split("\n") if align == "left" else [c["主标题"]]
    for ln in lines:
        lw = text_w(d, ln, ft)
        lx = x0 if align == "left" else x0 - lw / 2
        d.text((lx, y), ln, font=ft, fill=INK)
        y += 185
    last_w = text_w(d, lines[-1], ft)
    lx = x0 if align == "left" else x0 - last_w / 2
    underline_swoosh(d, lx + 10, lx + last_w - 10, y + 15, ACCENT)
    sparkle(d, lx + last_w + 45, y - 160, 22, ACCENT)
    y += 80
    fs = font(SANS_R, 52)
    if align == "left":
        d.text((x0, y), c["副标题"], font=fs, fill=INK)
    else:
        center_text(d, y, c["副标题"], fs, INK, spacing=2)
    y += 120
    f = font(SANS_M, 48)
    ws = [text_w(d, s, f) + 76 for s in c["卖点"]]
    if align == "left":                          # 竖排胶囊
        for s, w in zip(c["卖点"], ws):
            d.rounded_rectangle([x0, y, x0 + w, y + 88], radius=44, fill=(255, 255, 255, 235), outline=ACCENT, width=3)
            d.text((x0 + 38, y + 13), s, font=f, fill=INK)
            y += 112
    else:
        gap = 34
        x = W / 2 - (sum(ws) + gap * (len(ws) - 1)) / 2
        for s, w in zip(c["卖点"], ws):
            d.rounded_rectangle([x, y, x + w, y + 88], radius=44, fill=(255, 255, 255, 235), outline=ACCENT, width=3)
            d.text((x + 38, y + 13), s, font=f, fill=INK)
            x += w + gap
    return canvas.convert("RGB"), fq


# ---------------------------------------------------------------- 类型 2
def arch_mask(size, radius=None):
    w, h = size
    r = radius or w // 2
    m = Image.new("L", size, 0)
    dd = ImageDraw.Draw(m)
    dd.rectangle([0, r, w, h], fill=255)
    dd.ellipse([0, 0, w, 2 * r], fill=255)
    return m


def circle_mask(size):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).ellipse([0, 0, size[0] - 1, size[1] - 1], fill=255)
    return m


def type2(main, main_quad, extras, c):
    """主场景冰箱局部切成拱形贴片居中，其他场景切成圆形贴片环绕，配标题与卖点。
    extras: [(scene, quad, 标签), ...]，最多 3 个。"""
    canvas = paper(base=(246, 242, 236)).convert("RGBA")
    d = ImageDraw.Draw(canvas)
    y = 150
    ft = font(SERIF_B, 120)
    center_text(d, y, c["主标题"], ft, INK)
    tw = text_w(d, c["主标题"], ft)
    underline_swoosh(d, W / 2 - tw / 2 + 60, W / 2 + tw / 2 - 60, y + 175, ACCENT)
    center_text(d, y + 220, c["副标题"], font(SANS_R, 50), INK, spacing=2)
    aw, ah = 900, 1180
    box = crop_around(main, main_quad, aw / ah, height_ratio=0.98, fx=0.5, fy=0.5)
    arch = cover_crop(main, box, (aw, ah))
    ax, ay = (W - aw) // 2, 560
    paste_with_shadow(canvas, arch, (ax, ay), mask=arch_mask((aw, ah)))
    ImageDraw.Draw(canvas).arc([ax - 18, ay - 18, ax + aw + 18, ay + aw + 18], 180, 360, fill=ACCENT, width=4)
    spots = [(50, 640, 420, 4), (1250, 760, 420, -5), (1250, 1330, 400, 3)]
    for (sc, q, lab), (x, yy, size, rot) in zip(extras, spots):
        b = crop_around(sc, q, 1.0, height_ratio=0.75, fx=0.5, fy=0.5)
        circ = cover_crop(sc, b, (size, size))
        ring = Image.new("RGBA", (size + 24, size + 24), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse([0, 0, size + 23, size + 23], fill=(255, 255, 255, 255))
        ring.alpha_composite(Image.merge("RGBA", (*circ.split(), circle_mask((size, size)))), (12, 12))
        paste_with_shadow(canvas, ring, (x, yy), alpha=70, blur=22, offset=(0, 12))
        if lab:
            f = font(SANS_M, 40)
            lw = text_w(d, lab, f) + 50
            lx, ly = x + (size + 24 - lw) // 2, yy + size + 6
            d.rounded_rectangle([lx, ly, lx + lw, ly + 66], radius=33, fill=(255, 255, 255, 255))
            d.text((lx + 25, ly + 9), lab, font=f, fill=INK)
    # 卖点：底部三栏
    y = 1900
    f1 = font(SERIF_B, 58)
    n = len(c["卖点"])
    col = W / n
    for i, s in enumerate(c["卖点"]):
        cx = col * (i + 0.5)
        center_text(d, y + 40, s, f1, INK, cx=cx)
        if i:
            d.line([(col * i, y + 30), (col * i, y + 130)], fill=ACCENT, width=3)
    sparkle(d, W - 160, 470, 24, ACCENT); sparkle(d, 170, 520, 16, ACCENT)
    return canvas.convert("RGB")


# ---------------------------------------------------------------- 类型 3
def type3(scene, quad, c, seed=3):
    """拍立得相框（场景裁切）+ 胶带 + 便签卡片，手帐拼贴风。"""
    canvas = paper(seed=seed).convert("RGBA")
    d = ImageDraw.Draw(canvas)
    pw, ph = 1260, 1120                       # 照片区
    box = crop_around(scene, quad, pw / ph, height_ratio=0.95, fx=0.62, fy=0.5)
    photo = cover_crop(scene, box, (pw, ph))
    frame = Image.new("RGB", (pw + 90, ph + 200), (252, 251, 248))
    frame.paste(photo, (45, 45))
    fsz = paste_with_shadow(canvas, frame, (170, 330), rotate=2.5, blur=26, alpha=80)
    tape(canvas, (170 + fsz[0] / 2, 340), size=(240, 70), angle=-4)
    d = ImageDraw.Draw(canvas)
    # 左上角手写感英文 + 星星
    d.text((120, 120), c.get("角标", "Home Notes"), font=font(SERIF_B, 64), fill=ACCENT)
    sparkle(d, 1560, 220, 30, ACCENT)
    # 标题卡（左下，略倾斜）
    card = Image.new("RGBA", (980, 560), (251, 249, 244, 255))
    cd = ImageDraw.Draw(card)
    cd.text((60, 60), c["主标题"], font=font(SERIF_B, 96), fill=INK)
    cd.text((64, 210), c["副标题"], font=font(SANS_R, 42), fill=INK)
    underline_swoosh(cd, 60, 760, 330, ACCENT, width=6)
    if c.get("卡片底"):
        cd.text((64, 380), c["卡片底"], font=font(SANS_M, 44), fill=ACCENT)
    cs = paste_with_shadow(canvas, card, (90, 1560), rotate=-3, blur=20, alpha=70)
    tape(canvas, (90 + cs[0] - 80, 1580), angle=35)
    # 卖点便签（右下）
    note = Image.new("RGBA", (600, 600), (248, 243, 230, 255))
    nd = ImageDraw.Draw(note)
    yy = 70
    for s in c["卖点"]:
        nd.ellipse([56, yy + 26, 74, yy + 44], fill=ACCENT)
        nd.text((100, yy), s, font=font(SANS_M, 54), fill=INK)
        nd.line([(56, yy + 110), (544, yy + 110)], fill=(222, 212, 194), width=2)
        yy += 160
    ns = paste_with_shadow(canvas, note, (1060, 1620), rotate=4, blur=20, alpha=70)
    tape(canvas, (1060 + ns[0] / 2, 1630), size=(200, 60), angle=6)
    d = ImageDraw.Draw(canvas)
    doodle_arrow(d, [(1560, 1560), (1640, 1380), (1560, 1240), (1420, 1200)], ACCENT, width=6)
    return canvas.convert("RGB")
