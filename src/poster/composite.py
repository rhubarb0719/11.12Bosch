"""产品原图合成：保证最终图里的产品像素 100% 来自品牌方原图。

流程：
  1. cutout()      从白底产品图抠出产品（得到带透明通道的 RGBA）
  2. place()       按构图把产品放进 3:4 画布，其余区域留空，作为千问编辑接口的图1
  3. paste_back()  千问围绕产品补全环境后，把产品原图按原位置贴回出图
  4. verify()      逐像素核对：产品区域必须与原图完全一致

只依赖 Pillow。
"""
from PIL import Image, ImageChops, ImageFilter

CANVAS = (1536, 2048)          # 3:4
FILL = (214, 214, 214)         # 画布空白区域的中性灰


def cutout(path, threshold=12, feather=1):
    """白底产品图 → RGBA 抠图（裁到产品外框）。
    背景 = 接近白色、且与图片四边连通的区域；产品内部的白色（白门板、开门后的内胆）不会被误抠。"""
    im = Image.open(path).convert("RGB")
    diff = ImageChops.difference(im, Image.new("RGB", im.size, (255, 255, 255))).convert("L")
    near_white = diff.point(lambda v: 0 if v > threshold else 255)      # 255 = 接近白色
    bg = _border_connected(near_white)
    mask = ImageChops.invert(bg)
    if feather:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    rgba = im.convert("RGBA")
    rgba.putalpha(mask)
    box = mask.point(lambda v: 255 if v > 128 else 0).getbbox()
    out = rgba.crop(box)
    out.info["crop_box"] = box          # 抠图在原图中的位置，用于把原图坐标换算到抠图坐标
    return out


def quad_to_cutout(quad, product):
    """原图坐标的四角 → 抠图坐标。"""
    x0, y0 = product.info.get("crop_box", (0, 0, 0, 0))[:2]
    return [(x - x0, y - y0) for x, y in quad]


def _border_connected(near_white):
    """从四边出发，把与边缘连通的“接近白色”像素标为背景（255）。"""
    from PIL import ImageDraw
    w, h = near_white.size
    work = near_white.copy()          # 255 = 候选背景，0 = 产品
    for x in range(w):
        for y in (0, h - 1):
            if work.getpixel((x, y)) == 255:
                ImageDraw.floodfill(work, (x, y), 128)
    for y in range(h):
        for x in (0, w - 1):
            if work.getpixel((x, y)) == 255:
                ImageDraw.floodfill(work, (x, y), 128)
    return work.point(lambda v: 255 if v == 128 else 0)


def place(product, height_frac=0.62, center_x=0.38, bottom_y=0.92, canvas=CANVAS, fill=FILL):
    """把抠好的产品放进画布。返回 (画布 RGB, 放好产品的 RGBA 图层, 产品外框 (x0,y0,x1,y1))。
    height_frac：产品高度占画布高度；center_x：产品中心的横向位置；bottom_y：产品底边的纵向位置。"""
    W, H = canvas
    ph = int(H * height_frac)
    pw = int(product.width * ph / product.height)      # 等比缩放，不拉伸
    prod = product.resize((pw, ph), Image.LANCZOS)
    x0 = int(W * center_x - pw / 2)
    y0 = int(H * bottom_y - ph)
    layer = Image.new("RGBA", canvas, (0, 0, 0, 0))
    layer.alpha_composite(prod, (x0, y0))
    base = Image.new("RGBA", canvas, fill + (255,))
    base.alpha_composite(layer)
    return base.convert("RGB"), layer, (x0, y0, x0 + pw, y0 + ph)


def paste_back(generated, layer):
    """把产品图层原样贴回千问出图（先把出图缩放到画布尺寸）。"""
    gen = generated.convert("RGBA")
    if gen.size != layer.size:
        gen = gen.resize(layer.size, Image.LANCZOS)
    gen.alpha_composite(layer)
    return gen.convert("RGB")


def verify(final, layer, erode=3):
    """核对产品区域：产品不透明区域（向内收缩几个像素，避开羽化边）必须与原图逐像素一致。
    返回 (是否一致, 不一致像素数, 核对像素数)。"""
    alpha = layer.getchannel("A").point(lambda v: 255 if v == 255 else 0)
    if erode:
        alpha = alpha.filter(ImageFilter.MinFilter(erode * 2 + 1))
    src = layer.convert("RGB")
    diff = ImageChops.difference(final.convert("RGB"), src).convert("L")
    diff = ImageChops.multiply(diff, alpha)
    checked = sum(1 for v in alpha.getdata() if v)
    bad = sum(1 for v in diff.getdata() if v)
    return bad == 0, bad, checked


def aspect(layer):
    """产品在画面中的宽高比（用不透明外框计算），用于和规格比例核对。"""
    x0, y0, x1, y1 = layer.getchannel("A").point(lambda v: 255 if v > 128 else 0).getbbox()
    return (x1 - x0) / (y1 - y0)


# ---------------- 斜侧角度：正面 / 侧面分离，柜体遮挡与透明度 ----------------

def hide_mask(product, hide_polys):
    """hide_polys：要被柜体遮挡的区域（侧面、顶面、支脚），抠图坐标的多边形列表。
    返回 (保留遮罩, 遮挡遮罩)。适合开门图：伸出正面之外的门板也会完整保留。"""
    from PIL import ImageDraw
    alpha = product.getchannel("A")
    hide = Image.new("L", product.size, 0)
    d = ImageDraw.Draw(hide)
    for poly in hide_polys:
        d.polygon([tuple(p) for p in poly], fill=255)
    hide = ImageChops.multiply(hide, alpha)
    return ImageChops.subtract(alpha, hide), hide


def face_mask(product, front_quad):
    """front_quad：冰箱正面四个角在【抠图后产品图】坐标系中的位置 [(x,y)×4]，按顺时针。
    返回 (正面遮罩, 侧面+顶面遮罩)，都是 L 模式。"""
    from PIL import ImageDraw
    alpha = product.getchannel("A")
    front = Image.new("L", product.size, 0)
    ImageDraw.Draw(front).polygon([tuple(p) for p in front_quad], fill=255)
    front = ImageChops.multiply(front, alpha)
    side = ImageChops.subtract(alpha, front)
    return front, side


def place_faces(product, front_quad, height_frac=0.62, center_x=0.38, bottom_y=0.92, canvas=CANVAS, fill=FILL):
    """和 place() 一样摆放产品，但画布上只显示冰箱正面，侧面和顶面涂成灰色（交给模型画柜体）。
    返回 (画布, 正面图层, 侧面图层, 外框)。"""
    if isinstance(front_quad, dict):          # {"hide_polys": [...]}
        front_m, side_m = hide_mask(product, front_quad["hide_polys"])
    else:
        front_m, side_m = face_mask(product, front_quad)
    W, H = canvas
    ph = int(H * height_frac)
    pw = int(product.width * ph / product.height)
    x0, y0 = int(W * center_x - pw / 2), int(H * bottom_y - ph)

    def layer_of(mask):
        p = product.copy()
        p.putalpha(mask)
        p = p.resize((pw, ph), Image.LANCZOS)
        L = Image.new("RGBA", canvas, (0, 0, 0, 0))
        L.alpha_composite(p, (x0, y0))
        return L

    front_l, side_l = layer_of(front_m), layer_of(side_m)
    base = Image.new("RGBA", canvas, fill + (255,))
    base.alpha_composite(front_l)
    return base.convert("RGB"), front_l, side_l, (x0, y0, x0 + pw, y0 + ph)


def cabinet_variants(generated, front_l, side_l, transparencies=(0, 30, 50, 70)):
    """由一张模型出图得到不同柜体透明度的版本。
    transparency=0：柜体不透明，冰箱侧面完全被挡住；
    transparency=70：柜体 70% 透明，冰箱侧面以 70% 的强度透出来。
    正面始终是原图。返回 {透明度: 图}。"""
    gen = generated.convert("RGBA")
    if gen.size != front_l.size:
        gen = gen.resize(front_l.size, Image.LANCZOS)
    out = {}
    for t in transparencies:
        img = gen.copy()
        if t:
            side = side_l.copy()
            side.putalpha(side_l.getchannel("A").point(lambda v, k=t / 100: int(v * k)))
            img.alpha_composite(side)
        img.alpha_composite(front_l)
        out[t] = img.convert("RGB")
    return out


def contact_sheet(variants, width=600, label=True):
    """把不同透明度的版本横排拼成一张对比图。"""
    from PIL import ImageDraw
    items = list(variants.items())
    w = width
    h = int(items[0][1].height * w / items[0][1].width)
    sheet = Image.new("RGB", (w * len(items), h + (40 if label else 0)), (255, 255, 255))
    for i, (t, im) in enumerate(items):
        sheet.paste(im.resize((w, h), Image.LANCZOS), (i * w, 0))
        if label:
            ImageDraw.Draw(sheet).text((i * w + 10, h + 8), "柜体不透明" if t == 0 else f"柜体透明 {t}%",
                                       fill=(0, 0, 0), font=_font(24))
    return sheet


def _font(size):
    """优先用系统里能显示中文的字体，找不到就用默认字体。"""
    from PIL import ImageFont
    import glob
    for pat in ("/usr/share/fonts/**/*CJK*", "/usr/share/fonts/**/*unifont.otf", "/System/Library/Fonts/PingFang*",
                "C:/Windows/Fonts/msyh*"):
        for f in glob.glob(pat, recursive=True):
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                continue
    return ImageFont.load_default()
