"""مطر واقعي يُضاف فوق إطارات المشهد بعد الرندر.

المطر الحقيقي ليلاً لا يُرى إلا حيث يقع عليه الضوء: خطوط شفافة ضبابية
بأطوال وسماكات مختلفة حسب بعدها عن العدسة، مع رذاذ صغير على الأرض المبللة.
هذا السكربت يرسم ذلك بـ numpy فقط، ويعمل:
  - مع Pillow:  python rain_post.py <إطارات_المشهد> <مجلد_الناتج>
  - داخل Blender بلا أي تثبيت:
        blender -b --factory-startup --python rain_post.py -- <إطارات_المشهد> <مجلد_الناتج>
الحركة متكررة بلا قطع: الإطار الأخير يتصل بالأول.
"""
import math
import os
import sys

import numpy as np

ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]

# طبقات المطر من البعيد إلى القريب.
# count: عدد القطرات، length: طول الخط بالبكسل (ضبابية الحركة)، blur: نعومة الحواف،
# speed: بكسل لكل إطار، alpha: الشفافية، tilt: ميلان الريح.
LAYERS = (
    dict(count=2600, length=(18, 34), blur=0.8, speed=26, alpha=0.30, tilt=0.06),
    dict(count=1300, length=(40, 70), blur=1.3, speed=46, alpha=0.36, tilt=0.07),
    dict(count=420, length=(90, 150), blur=2.4, speed=80, alpha=0.34, tilt=0.08),
    dict(count=70, length=(220, 360), blur=5.0, speed=150, alpha=0.24, tilt=0.09),
)
SPLASHES_PER_FRAME = 14
GROUND_TOP = 0.56  # أعلى نقطة من الأرض تظهر عليها دوائر الرذاذ (نسبة من الارتفاع)
HORIZON = 0.40  # نقطة التلاشي في عمق الزقاق (نسبة من الارتفاع)
FLOOR_SPREAD = 0.62  # عرض أرض الزقاق: يتسع كلما اقتربت من الكاميرا


# ---------- قراءة وكتابة الصور ----------
try:
    from PIL import Image

    def load(path):
        return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0

    def save(path, rgb):
        Image.fromarray((np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8)).save(path)

except ImportError:
    import bpy

    def load(path):
        img = bpy.data.images.load(path)
        w, h = img.size
        px = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
        bpy.data.images.remove(img)
        # Blender يخزن الصورة من الأسفل إلى الأعلى.
        return px.reshape(h, w, 4)[::-1, :, :3].copy()

    def save(path, rgb):
        h, w, _ = rgb.shape
        img = bpy.data.images.new("out", w, h, alpha=False)
        rgba = np.ones((h, w, 4), dtype=np.float32)
        rgba[:, :, :3] = np.clip(rgb, 0, 1)
        img.pixels.foreach_set(rgba[::-1].ravel())
        img.filepath_raw = path
        img.file_format = "PNG"
        img.save()
        bpy.data.images.remove(img)


# ---------- أدوات ----------
def box_blur(a, r, axis):
    if r < 1:
        return a
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float32)
    hi = np.take(c, np.arange(2 * r + 1, c.shape[axis]), axis=axis)
    lo = np.take(c, np.arange(0, c.shape[axis] - 2 * r - 1), axis=axis)
    return (hi - lo) / (2 * r + 1)


def gaussian(a, sigma):
    # ثلاث مرات تمويه صندوقي تقارب التمويه الغاوسي.
    r = max(0, int(round(sigma * 0.9)))
    for _ in range(3):
        a = box_blur(box_blur(a, r, 0), r, 1)
    return a


def soft_blur(a, sigma):
    if sigma < 1.2:
        k = np.array([0.25, 0.5, 0.25], dtype=np.float32) if sigma >= 0.6 else None
        if k is None:
            return a
        a = k[0] * np.roll(a, 1, 1) + k[1] * a + k[2] * np.roll(a, -1, 1)
        return a
    return gaussian(a, sigma)


# ---------- المطر ----------
class Rain:
    def __init__(self, w, h, frames, seed=7):
        self.w, self.h, self.n = w, h, frames
        rng = np.random.default_rng(seed)
        self.layers = []
        # القيم مضبوطة على 1080p، وتتناسب مع أي دقة أخرى حتى لا يتغير شكل المطر.
        k = h / 1080.0
        for spec in LAYERS:
            spec = dict(spec, speed=spec["speed"] * k, blur=spec["blur"] * k)
            lo, hi = spec["length"][0] * k, spec["length"][1] * k
            length = rng.uniform(lo, hi, spec["count"]).astype(np.float32)
            # مسافة الدورة تقسم مسار الإطارات كلها بعدد صحيح، فتتكرر الحركة بلا قطع.
            travel = spec["speed"] * frames
            loops = max(1, int(travel // (h + hi + 40)))
            period = travel / loops
            x0 = rng.uniform(-0.15 * w, 1.15 * w, spec["count"]).astype(np.float32)
            y0 = rng.uniform(0, period, spec["count"]).astype(np.float32)
            bright = rng.uniform(0.45, 1.0, spec["count"]).astype(np.float32)
            self.layers.append((spec, length, x0, y0, bright, period))
        # أحداث الرذاذ: موضع وزمن بداية، تتكرر كل دورة.
        total = SPLASHES_PER_FRAME * frames
        sy = GROUND_TOP + (1 - GROUND_TOP) * np.sqrt(rng.uniform(0, 1, total))
        # الرذاذ على أرض الزقاق فقط، لا على الجدران.
        half = (sy - HORIZON) * h * FLOOR_SPREAD
        self.splash = (
            (w / 2 + rng.uniform(-1, 1, total) * half).astype(np.float32),
            (sy * h).astype(np.float32),
            rng.integers(0, frames, total),
            rng.uniform(0.5, 1.0, total).astype(np.float32),
        )

    def streaks(self, f):
        h, w = self.h, self.w
        out = np.zeros((h, w), dtype=np.float32)
        for spec, length, x0, y0, bright, period in self.layers:
            layer = np.zeros((h, w), dtype=np.float32)
            head = (y0 + spec["speed"] * f) % period - 40
            steps = int(length.max())
            t = np.linspace(0, 1, steps, dtype=np.float32)
            # شدة الخط على طوله: أطراف ناعمة ووسط ثابت، كما تصوره الكاميرا.
            profile = np.clip(np.minimum(t, 1 - t) * 6, 0, 1) ** 0.8
            ys = head[:, None] - t[None, :] * length[:, None]
            xs = x0[:, None] + spec["tilt"] * ys
            weight = bright[:, None] * profile[None, :]
            # النقاط التي تتجاوز طول القطرة نفسها لا تُرسم.
            weight = np.where(t[None, :] * length.max() <= length[:, None], weight, 0)
            xi = np.round(xs).astype(np.int32).ravel()
            yi = np.round(ys).astype(np.int32).ravel()
            wv = weight.ravel()
            ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h) & (wv > 0)
            np.add.at(layer, (yi[ok], xi[ok]), wv[ok])
            out += soft_blur(layer, spec["blur"]) * spec["alpha"]
        return out

    def splashes(self, f):
        h, w = self.h, self.w
        out = np.zeros((h, w), dtype=np.float32)
        sx, sy, start, strength = self.splash
        life = 7
        age = (f - start) % self.n
        live = age < life
        yy, xx = np.mgrid[-14:15, -30:31].astype(np.float32)
        for x, y, a, s in zip(sx[live], sy[live], age[live], strength[live]):
            depth = (y / h - HORIZON) / (1 - HORIZON)  # أكبر قرب الكاميرا
            r = (1.5 + a * 1.4) * (0.4 + depth * 1.4) * h / 1080.0
            rr = np.sqrt(xx ** 2 + (yy / 0.32) ** 2)
            ring = np.exp(-((rr - r) ** 2) / (2 * (1.0 + depth * 1.5) ** 2))
            ring *= s * (1 - a / life) ** 1.5 * 0.22
            ix, iy = int(x), int(y)
            y1, y2 = max(0, iy - 14), min(h, iy + 15)
            x1, x2 = max(0, ix - 30), min(w, ix + 31)
            out[y1:y2, x1:x2] += ring[y1 - iy + 14:y2 - iy + 14, x1 - ix + 30:x2 - ix + 30]
        return out

    def apply(self, bg, f):
        # المطر يأخذ لونه وشدته من الضوء حوله: يلمع قرب الفوانيس ويختفي في الظلام.
        glow = gaussian(bg, 28) if bg.shape[0] <= 1200 else gaussian(bg, 40)
        lum = glow @ np.array([0.3, 0.55, 0.15], dtype=np.float32)
        light = np.clip(0.12 + 3.5 * lum, 0, 1.8)[:, :, None]
        tint = 0.55 * (glow / (lum[:, :, None] + 1e-3)).clip(0, 2) + 0.45
        rain = self.streaks(f)[:, :, None] * light * tint * 0.9
        sp = self.splashes(f)[:, :, None] * (0.15 + 4.0 * lum[:, :, None]) * tint
        top = np.clip(rain + sp, 0, 1)
        return 1 - (1 - bg) * (1 - top)  # مزج «شاشة» كضوء منعكس على القطرات


def main():
    src, dst = ARGV[0], ARGV[1]
    os.makedirs(dst, exist_ok=True)
    names = sorted(n for n in os.listdir(src) if n.lower().endswith(".png"))
    frames = int(ARGV[ARGV.index("--frames") + 1]) if "--frames" in ARGV else len(names)
    first = load(os.path.join(src, names[0]))
    rain = Rain(first.shape[1], first.shape[0], frames)
    for i, name in enumerate(names):
        bg = first if i == 0 else load(os.path.join(src, name))
        save(os.path.join(dst, name), rain.apply(bg, i))
        print(f"{i + 1}/{len(names)} {name}", flush=True)


if __name__ == "__main__":
    main()
