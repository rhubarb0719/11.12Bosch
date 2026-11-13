"""真实手机质感调色（纯代码，不经过模型）。冰箱区域保持品牌原图像素，只调冰箱以外的场景。

阴天自然光：中和暖色偏色、压高光（灯带、阳光光斑变柔）、提暗部、降对比；
低饱和 ins 风：整体降饱和；手机质感：细颗粒噪点、轻微暗角。
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def phone_look(img, sat=0.62, neutral=0.55, cool=4, lift=18, shoulder=0.35, contrast=0.86, grain=3.2, vignette=0.10, seed=0):
    a = np.asarray(img.convert("RGB"), float)
    # 1. 白平衡：把整体平均色往中性灰拉 neutral，再整体略偏冷 cool
    mean = a.reshape(-1, 3).mean(0)
    gain = 1 + neutral * (mean.mean() / mean - 1)
    a = a * gain + np.array([-cool, 0, cool])
    # 2. 降饱和
    lum = (a * [0.299, 0.587, 0.114]).sum(-1, keepdims=True)
    a = lum + (a - lum) * sat
    # 3. 降对比、压高光、提暗部
    x = np.clip(a / 255, 0, 1.2)
    x = 0.5 + (x - 0.5) * contrast
    x = np.where(x > 0.7, 0.7 + (x - 0.7) * (1 - shoulder), x)       # 高光肩部压缩
    x = lift / 255 + x * (1 - lift / 255 - 0.02)
    a = x * 255
    # 4. 暗角
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / np.sqrt(2)
    a = a * (1 - vignette * r[..., None] ** 2)
    # 5. 颗粒（亮度噪点）
    rng = np.random.default_rng(seed)
    a = a + rng.normal(0, grain, (h, w, 1))
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8"))


def keep_product(graded, original, quad, feather=1.5):
    """冰箱 quad 内用原图像素（羽化 feather 像素），其余用调色后的场景。"""
    m = Image.new("L", original.size, 0)
    ImageDraw.Draw(m).polygon([tuple(p) for p in quad], fill=255)
    if feather:
        m = m.filter(ImageFilter.GaussianBlur(feather))
    return Image.composite(original.convert("RGB"), graded, m)


def crop_34(img, quad, fx=0.6, W=1728, H=2304):
    """整张高度、按 3:4 裁切，冰箱中心放在横向 fx 处。返回 (裁切缩放后的图, 冰箱在新图中的四角)。"""
    xs = [p[0] for p in quad]
    cx = (min(xs) + max(xs)) / 2
    w = img.height * W / H
    x0 = min(max(cx - w * fx, 0), img.width - w)
    box = (round(x0), 0, round(x0 + w), img.height)
    s = W / (box[2] - box[0])
    return img.crop(box).resize((W, H), Image.LANCZOS), [((x - box[0]) * s, y * H / img.height) for x, y in quad]
