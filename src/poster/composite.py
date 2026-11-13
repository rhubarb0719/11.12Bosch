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
    return rgba.crop(box)


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
