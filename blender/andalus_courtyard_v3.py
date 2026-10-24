# ليلة في قرطبة (النسخة الثالثة): فناء أندلسي ليلي، في Blender 4.2 أو أحدث.
#
# الجديد في النسخة الثالثة:
#   - أشجار بآلاف الأوراق الحقيقية المتفرقة (بدل الأشكال الملساء)، وأغصان، وأوراق يمر منها الضوء.
#   - جدران أفتح بلون الجص الكريمي، وفوانيس إضافية على الجدار المقابل للكاميرا.
#
# الجديد في هذه النسخة:
#   - خامات حقيقية مصوَّرة من Poly Haven (مجانية حتى للاستخدام التجاري) تُنزَّل تلقائياً
#     عند أول تشغيل إلى المجلد ~/BlenderAssets/polyhaven، ثم تعمل بلا إنترنت.
#     إن فشل التنزيل يكمل السكربت بخامات مصنوعة بالكود، فلا يتوقف.
#   - زخارف جصية: إطار «الألفيز» حول كل قوس، وشريط «سبكة» محفور فوق الأقواس، وأفاريز خشبية.
#   - أعمدة رخامية رفيعة بتيجان بين الأقواس.
#   - أشجار برتقال بثمارها بين أشجار السرو.
#   - قمر كبير في السماء ينعكس في البركة، ونجوم، وضباب ليلي خفيف يُظهر هالة الفوانيس.
#
# الاستخدام:
#   افتح Blender ← تبويب Scripting ← Open ← اختر هذا الملف ← Run Script (انتظر دقيقة لأول مرة).
#   صورة تجريبية سريعة:  blender -b -P andalus_courtyard_v2.py -- --preview preview.png
#   رندر الحلقة كاملة:   blender -b -P andalus_courtyard_v2.py -- --render out/frame_
#   بلا تنزيل خامات:      أضف --offline

import json
import math
import os
import random
import sys
import urllib.request

import bpy
import mathutils

FPS = 24
LOOP_SECONDS = 10
FRAMES = FPS * LOOP_SECONDS

COURT_W, COURT_L = 14.0, 26.0  # عرض وطول الفناء بالمتر
POOL_W, POOL_L = 3.2, 18.0
ARCH_SPAN = 2.4
WALL_H, WALL_D, SPRING = 5.2, 0.6, 2.6  # ارتفاع الجدار وسماكته وارتفاع بداية القوس

ASSETS_DIR = os.path.join(os.path.expanduser("~"), "BlenderAssets", "polyhaven")
API = "https://api.polyhaven.com"
ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OFFLINE = "--offline" in ARGV
if not OFFLINE and not getattr(bpy.app, "online_access", True):
    # Blender 4.2+: يحترم السكربت خيار Preferences ← System ← Network ← Allow Online Access.
    print("التنزيل معطّل: فعّل Allow Online Access في الإعدادات لتنزيل الخامات الحقيقية.")
    OFFLINE = True

# ما نبحث عنه في مكتبة Poly Haven لكل خامة، بالترتيب من الأفضل.
TEXTURE_WANTS = {
    "plaster": ["plaster", "stucco", "beige_wall"],
    "floor": ["terracotta", "floor_tiles", "stone_tiles", "tiles"],
    "marble": ["marble"],
    "wood": ["planks", "wood"],
    "soil": ["soil", "dirt", "ground"],
}


# ---------- Poly Haven ----------

def ph_get(path):
    req = urllib.request.Request(API + path, headers={"User-Agent": "andalus-courtyard-blender-script"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)


def download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "andalus-courtyard-blender-script"})
    with urllib.request.urlopen(req, timeout=120) as res, open(dest + ".part", "wb") as f:
        f.write(res.read())
    os.replace(dest + ".part", dest)


_catalog = {}


def find_asset(kind, keywords):
    # يختار الأكثر تنزيلاً بين الأصول التي يطابق اسمها أو وسومها أول كلمة مفتاحية ممكنة.
    if kind not in _catalog:
        _catalog[kind] = ph_get(f"/assets?type={kind}")
    assets = _catalog[kind]
    for kw in keywords:
        hits = [
            (info.get("download_count", 0), asset_id)
            for asset_id, info in assets.items()
            if kw in asset_id or any(kw in t for t in info.get("tags", []) + info.get("categories", []))
        ]
        if hits:
            return max(hits)[1]
    return None


def pick_file(entry, res):
    # entry: {"2k": {"jpg": {"url": ...}, "png": {...}}, ...}
    for r in (res, "2k", "1k"):
        formats = entry.get(r) or {}
        for fmt in ("jpg", "png", "hdr", "exr"):
            if fmt in formats:
                return formats[fmt]["url"], fmt
    return None, None


def texture_maps(slot):
    # يعيد مسارات الصور {color, normal, rough, disp} لخامة، من الذاكرة المحلية أو بعد تنزيلها.
    folder = os.path.join(ASSETS_DIR, slot)
    roles = {"color": ["Diffuse", "diff"], "normal": ["nor_gl"], "rough": ["Rough", "rough"], "disp": ["Displacement", "disp"]}
    found = {r: os.path.join(folder, f) for r in roles for f in os.listdir(folder) if f.startswith(r + ".")} if os.path.isdir(folder) else {}
    if "color" in found or OFFLINE:
        return found
    try:
        asset_id = find_asset("textures", TEXTURE_WANTS[slot])
        if not asset_id:
            return {}
        print(f"تنزيل خامة {slot}: {asset_id}")
        files = ph_get(f"/files/{asset_id}")
        for role, keys in roles.items():
            entry = next((files[k] for k in keys if k in files), None)
            if not entry:
                continue
            url, fmt = pick_file(entry, "2k")
            if url:
                dest = os.path.join(folder, f"{role}.{fmt}")
                download(url, dest)
                found[role] = dest
        with open(os.path.join(folder, "source.txt"), "w") as f:
            f.write(f"https://polyhaven.com/a/{asset_id}\n")
    except Exception as e:  # بلا إنترنت أو تغيّر في الموقع: نكمل بالخامات المصنوعة بالكود.
        print(f"تعذر تنزيل خامة {slot}: {e}")
    return found


def night_hdri():
    folder = os.path.join(ASSETS_DIR, "sky")
    if os.path.isdir(folder):
        for f in os.listdir(folder):
            if f.startswith("sky."):
                return os.path.join(folder, f)
    if OFFLINE:
        return None
    try:
        asset_id = find_asset("hdris", ["moon", "night"])
        if not asset_id:
            return None
        print(f"تنزيل سماء ليلية: {asset_id}")
        url, fmt = pick_file(ph_get(f"/files/{asset_id}")["hdri"], "2k")
        dest = os.path.join(folder, f"sky.{fmt}")
        download(url, dest)
        return dest
    except Exception as e:
        print(f"تعذر تنزيل السماء: {e}")
        return None


# ---------- materials ----------

def node_mat(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    return mat, nt, nt.nodes["Principled BSDF"]


def mapping(nt, scale):
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (scale, scale, scale)
    nt.links.new(coord.outputs["Object"], mp.inputs["Vector"])
    return mp.outputs["Vector"]


def image_node(nt, path, vector, color=True):
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(path, check_existing=True)
    if not color:
        tex.image.colorspace_settings.name = "Non-Color"
    tex.projection = "BOX"  # يلصق الصورة على كل الأوجه بلا فك UV
    tex.projection_blend = 0.2
    nt.links.new(vector, tex.inputs["Vector"])
    return tex


def pbr_material(name, maps, scale, tint=None, bump=0.0):
    # خامة من صور حقيقية: لون + خشونة + نتوءات.
    mat, nt, bsdf = node_mat(name)
    vec = mapping(nt, scale)
    color = image_node(nt, maps["color"], vec).outputs["Color"]
    if tint:
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MIX"  # نغسل الخامة بلون الجص مع إبقاء تفاصيلها
        mix.inputs["Factor"].default_value = 0.45
        mix.inputs["B"].default_value = (*tint, 1)
        nt.links.new(color, mix.inputs["A"])
        color = mix.outputs["Result"]
    nt.links.new(color, bsdf.inputs["Base Color"])
    if "rough" in maps:
        nt.links.new(image_node(nt, maps["rough"], vec, color=False).outputs["Color"], bsdf.inputs["Roughness"])
    normal_out = None
    if "normal" in maps:
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(image_node(nt, maps["normal"], vec, color=False).outputs["Color"], nm.inputs["Color"])
        normal_out = nm.outputs["Normal"]
    if "disp" in maps and bump:
        bp = nt.nodes.new("ShaderNodeBump")
        bp.inputs["Strength"].default_value = bump
        nt.links.new(image_node(nt, maps["disp"], vec, color=False).outputs["Color"], bp.inputs["Height"])
        if normal_out:
            nt.links.new(normal_out, bp.inputs["Normal"])
        normal_out = bp.outputs["Normal"]
    if normal_out:
        nt.links.new(normal_out, bsdf.inputs["Normal"])
    return mat


def noise_material(name, dark, light, scale=6.0, rough=0.85, bump=0.25):
    mat, nt, bsdf = node_mat(name)
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 10.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*dark, 1)
    ramp.color_ramp.elements[1].color = (*light, 1)
    bp = nt.nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = bump
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(noise.outputs["Fac"], bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])
    bsdf.inputs["Roughness"].default_value = rough
    return mat


def material(slot, scale, fallback, tint=None, bump=0.3):
    maps = texture_maps(slot)
    if "color" in maps:
        return pbr_material(slot.title(), maps, scale, tint, bump)
    return fallback()


def zellige_material():
    # بلاط زليج بلونين مع فواصل، عند غياب خامة أرضية حقيقية.
    mat, nt, bsdf = node_mat("Zellige")
    brick = nt.nodes.new("ShaderNodeTexBrick")
    brick.offset = 0.0
    brick.inputs["Color1"].default_value = (0.08, 0.28, 0.32, 1)
    brick.inputs["Color2"].default_value = (0.72, 0.62, 0.48, 1)
    brick.inputs["Mortar"].default_value = (0.85, 0.82, 0.75, 1)
    brick.inputs["Scale"].default_value = 1.6
    brick.inputs["Mortar Size"].default_value = 0.015
    brick.inputs["Brick Width"].default_value = 0.5
    brick.inputs["Row Height"].default_value = 0.5
    nt.links.new(nt.nodes.new("ShaderNodeTexCoord").outputs["Object"], brick.inputs["Vector"])
    nt.links.new(brick.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.35
    return mat


def sebka_material(base):
    # جص محفور بنقشة «السبكة» المعينية المعروفة في قصر الحمراء: شبكة معينات بارزة.
    mat = base.copy()
    mat.name = "CarvedPlaster"
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    coord = nt.nodes.new("ShaderNodeTexCoord")
    rot = nt.nodes.new("ShaderNodeMapping")
    rot.inputs["Rotation"].default_value = (0, math.radians(45), 0)
    rot.inputs["Scale"].default_value = (3.0, 3.0, 3.0)
    nt.links.new(coord.outputs["Object"], rot.inputs["Vector"])
    wave_a = nt.nodes.new("ShaderNodeTexWave")
    wave_b = nt.nodes.new("ShaderNodeTexWave")
    wave_b.bands_direction = "Z"
    for w in (wave_a, wave_b):
        w.inputs["Scale"].default_value = 1.0
        w.inputs["Distortion"].default_value = 0.0
        nt.links.new(rot.outputs["Vector"], w.inputs["Vector"])
    mult = nt.nodes.new("ShaderNodeMath")
    mult.operation = "MULTIPLY"
    nt.links.new(wave_a.outputs["Fac"], mult.inputs[0])
    nt.links.new(wave_b.outputs["Fac"], mult.inputs[1])
    bp = nt.nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = 0.8
    bp.inputs["Distance"].default_value = 0.05
    nt.links.new(mult.outputs["Value"], bp.inputs["Height"])
    old = next((l for l in nt.links if l.to_socket == bsdf.inputs["Normal"]), None)
    if old:
        nt.links.new(old.from_socket, bp.inputs["Normal"])
    nt.links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def water_material():
    mat, nt, bsdf = node_mat("Water")
    bsdf.inputs["Base Color"].default_value = (0.01, 0.03, 0.04, 1)
    bsdf.inputs["Roughness"].default_value = 0.01
    bsdf.inputs["IOR"].default_value = 1.33
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.noise_dimensions = "4D"
    noise.inputs["Scale"].default_value = 3.0
    bp = nt.nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = 0.04
    nt.links.new(noise.outputs["Fac"], bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])
    w = noise.inputs["W"]
    w.default_value = 0.0
    w.keyframe_insert("default_value", frame=1)
    w.default_value = 1.5
    w.keyframe_insert("default_value", frame=FRAMES + 1)
    for fc in fcurves_of(nt.animation_data.action):
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
    return mat


def plain_material(name, color, rough=0.6):
    mat, nt, bsdf = node_mat(name)
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    return mat


def emission_material(name, color, strength):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*color, 1)
    em.inputs["Strength"].default_value = strength
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return mat


def fcurves_of(action):
    # Blender 4.4+ uses layered actions; older versions expose action.fcurves directly.
    if hasattr(action, "layers") and action.layers:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    yield from bag.fcurves
    else:
        yield from getattr(action, "fcurves", [])


# ---------- geometry helpers ----------

def box(name, size, loc, mat=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    ob = bpy.context.view_layer.objects.active
    ob.name = name
    ob.scale = size
    bpy.ops.object.transform_apply(scale=True)
    if mat:
        ob.data.materials.append(mat)
    return ob


def cylinder(name, r, depth, loc, mat=None, verts=32, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, location=loc, vertices=verts, rotation=rot)
    ob = bpy.context.view_layer.objects.active
    ob.name = name
    if mat:
        ob.data.materials.append(mat)
    return ob


def bevel(ob, width=0.02):
    mod = ob.modifiers.new("Bevel", "BEVEL")
    mod.width = width
    mod.segments = 2


def cut(target, cutter):
    mod = target.modifiers.new("Cut", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cutter
    cutter.hide_render = True
    cutter.display_type = "WIRE"


def instance(src, name, loc):
    # نسخة تشارك نفس الشكل (أخف بكثير من شكل جديد لكل ثمرة).
    ob = bpy.data.objects.new(name, src.data)
    ob.location = loc
    bpy.context.collection.objects.link(ob)
    return ob


class Side:
    # ضلع من أضلاع الفناء: axis هو اتجاه امتداد الجدار، pos موقعه، inward اتجاه الفناء.
    def __init__(self, name, axis, pos, inward):
        self.name, self.axis, self.pos, self.inward = name, axis, pos, inward
        self.length = COURT_W if axis == "x" else COURT_L

    def at(self, along, out, z):
        # نقطة على بعد along على طول الجدار، و out باتجاه الفناء من وجه الجدار الداخلي.
        off = self.pos + self.inward * (WALL_D / 2 + out)
        return (along, off, z) if self.axis == "x" else (off, along, z)

    def size(self, along, across, h):
        return (along, across, h) if self.axis == "x" else (across, along, h)

    def arch_centers(self):
        count = int(self.length // (ARCH_SPAN + 0.6))
        step = self.length / count
        return [-self.length / 2 + step * (i + 0.5) for i in range(count)], step


def arcade(side, plaster, carved, marble, wood):
    radius = ARCH_SPAN * 0.55
    arch_top = SPRING + radius * 1.35
    wall = box(side.name, side.size(side.length, WALL_D, WALL_H), side.at(0, -WALL_D / 2, WALL_H / 2), plaster)
    centers, step = side.arch_centers()
    rot = (math.pi / 2, 0, 0) if side.axis == "x" else (0, math.pi / 2, 0)
    for i, c in enumerate(centers):
        # قوس حدوة الفرس: دائرة مركزها فوق خط الانطلاق فتتجاوز نصف الدائرة، ومستطيل تحتها.
        x, y, _ = side.at(c, -WALL_D / 2, 0)
        cut(wall, cylinder(f"{side.name}_arch{i}", radius, 3.0, (x, y, SPRING + radius * 0.35), rot=rot, verts=64))
        cut(wall, box(f"{side.name}_open{i}", side.size(ARCH_SPAN, 3.0, SPRING + 0.4), (x, y, (SPRING + 0.4) / 2 - 0.2)))
        # الألفيز: إطار مستطيل بارز يحيط بالقوس.
        half = ARCH_SPAN / 2 + 0.3
        frame_top = arch_top + 0.25
        box(f"{side.name}_alfizTop{i}", side.size(half * 2 + 0.12, 0.08, 0.12), side.at(c, 0.03, frame_top), plaster)
        for s in (-1, 1):
            h = frame_top - SPRING + 0.2
            box(f"{side.name}_alfizSide{i}{s}", side.size(0.12, 0.08, h), side.at(c + s * half, 0.03, SPRING - 0.2 + h / 2), plaster)
    # أعمدة رخامية رفيعة بتيجان عند كل دعامة بين قوسين.
    for i in range(1, len(centers)):
        p = -side.length / 2 + step * i
        cx, cy, _ = side.at(p, 0.16, 0)
        col = cylinder(f"{side.name}_col{i}", 0.11, SPRING - 0.35, (cx, cy, (SPRING - 0.35) / 2 + 0.12), marble, verts=24)
        bevel(col, 0.01)
        box(f"{side.name}_capital{i}", (0.34, 0.34, 0.22), (cx, cy, SPRING - 0.12), marble)
        box(f"{side.name}_colbase{i}", (0.3, 0.3, 0.12), (cx, cy, 0.06), marble)
    # شريط جص محفور فوق الأقواس، ثم إفريز وطنف خشبي بارز بعوارض.
    band_lo, band_hi = arch_top + 0.5, WALL_H - 0.35
    box(f"{side.name}_sebka", side.size(side.length, 0.04, band_hi - band_lo), side.at(0, 0.01, (band_lo + band_hi) / 2), carved)
    cornice = box(f"{side.name}_cornice", side.size(side.length, 0.25, 0.18), side.at(0, 0.1, WALL_H - 0.2), plaster)
    bevel(cornice, 0.04)
    box(f"{side.name}_eave", side.size(side.length, 1.0, 0.08), side.at(0, 0.35, WALL_H + 0.05), wood)
    rafter = box(f"{side.name}_rafter", side.size(0.09, 0.9, 0.12), side.at(-side.length / 2 + 0.25, 0.3, WALL_H - 0.05), wood)
    n = int(side.length / 0.45)
    for i in range(1, n):
        loc = list(rafter.location)
        if side.axis == "x":
            loc[0] += i * 0.45
        else:
            loc[1] += i * 0.45
        instance(rafter, f"{side.name}_rafter{i}", loc)
    bevel(wall)
    return wall


def leaf_mesh(name, length, width, mat):
    # ورقة واحدة: شكل بيضوي مدبب منحنٍ قليلاً، تُنسخ آلاف المرات على التاج.
    mesh = bpy.data.meshes.new(name)
    n = 6
    verts = [(0, 0, 0)]
    for i in range(1, n):
        t = i / n
        w = width * math.sin(math.pi * t) * (1 - 0.3 * t)
        bend = 0.15 * length * t * t
        verts += [(-w / 2, t * length, -bend), (w / 2, t * length, -bend)]
    verts.append((0, length, -0.15 * length))
    faces = [(0, 2, 1)]
    for i in range(n - 2):
        a = 1 + 2 * i
        faces.append((a, a + 1, a + 3, a + 2))
    faces.append((len(verts) - 3, len(verts) - 2, len(verts) - 1))
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(mat)
    ob = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(ob)
    # لا نخفيها عن الرندر (فتختفي نسخها أيضاً)، بل نضعها بعيداً تحت الأرض.
    ob.location = (0, 0, -100)
    return ob


def scatter_leaves(emitter, leaf, count, size, seed):
    # جزيئات «شعر» تضع نسخة من الورقة في آلاف النقاط داخل التاج بزوايا عشوائية.
    mod = emitter.modifiers.new("Leaves", "PARTICLE_SYSTEM")
    psys = mod.particle_system
    psys.seed = seed
    ps = psys.settings
    ps.type = "HAIR"
    ps.use_advanced_hair = True
    ps.count = count
    ps.hair_length = 1.0  # حجم نسخة الشعر = الحجم × الطول، فنثبّت الطول على 1
    ps.emit_from = "FACE"  # على سطح التاج، فيبدو كثيفاً من الخارج
    ps.distribution = "RAND"
    ps.render_type = "OBJECT"
    ps.instance_object = leaf
    ps.particle_size = size
    ps.size_random = 0.5
    ps.use_rotations = True
    ps.rotation_mode = "NOR"
    ps.rotation_factor_random = 1.0
    ps.phase_factor_random = 2.0
    ps.display_percentage = 10
    emitter.show_instancer_for_render = False
    emitter.show_instancer_for_viewport = False
    return psys


def branch(name, start, end, r, bark):
    # غصن أسطواني بين نقطتين.
    sx, sy, sz = start
    dx, dy, dz = end[0] - sx, end[1] - sy, end[2] - sz
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    ob = cylinder(name, r, length, (sx + dx / 2, sy + dy / 2, sz + dz / 2), bark, verts=8)
    ob.rotation_euler = mathutils.Vector((dx, dy, dz)).to_track_quat("Z", "Y").to_euler()
    return ob


def cypress(name, x, y, leaf, inner, bark, rng, h=6.0):
    cylinder(name + "_trunk", 0.1, 1.2, (x, y, 0.6), bark, verts=8)
    # تاج داخلي داكن يسد الفراغات، ثم أوراق إبرية كثيفة حوله.
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(x, y, h / 2 + 0.7), segments=16, ring_count=12)
    core = bpy.context.view_layer.objects.active
    core.name = name + "_core"
    core.scale = (0.47, 0.47, h / 2 * 0.95)
    bpy.ops.object.transform_apply(scale=True)
    core.data.materials.append(inner)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(x, y, h / 2 + 0.7), segments=16, ring_count=12)
    crown = bpy.context.view_layer.objects.active
    crown.name = name
    crown.scale = (0.55, 0.55, h / 2)
    bpy.ops.object.transform_apply(scale=True)
    scatter_leaves(crown, leaf, 22000, 0.075, rng.randint(0, 9999))
    return crown


def orange_tree(name, x, y, leaf, inner, bark, fruit_src, rng):
    cz, r = 2.15, 1.0
    cylinder(name + "_trunk", 0.08, 1.5, (x, y, 0.75), bark, verts=8)
    for k in range(4):
        # أغصان رئيسية تتفرع من أعلى الجذع داخل التاج.
        a = k * math.pi / 2 + rng.uniform(-0.4, 0.4)
        branch(f"{name}_branch{k}", (x, y, 1.45), (x + 0.6 * math.cos(a), y + 0.6 * math.sin(a), cz + rng.uniform(-0.1, 0.4)), 0.04, bark)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=r * 0.88, location=(x, y, cz))
    core = bpy.context.view_layer.objects.active
    core.name = name + "_core"
    core.scale = (1, 1, 0.8)
    bpy.ops.object.transform_apply(scale=True)
    core.data.materials.append(inner)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=r, location=(x, y, cz))
    crown = bpy.context.view_layer.objects.active
    crown.name = name
    crown.scale = (1, 1, 0.85)
    bpy.ops.object.transform_apply(scale=True)
    scatter_leaves(crown, leaf, 14000, 0.13, rng.randint(0, 9999))
    for k in range(32):
        # ثمار موزعة قرب سطح التاج، بعضها يختبئ بين الأوراق.
        theta = rng.uniform(0, 2 * math.pi)
        phi = math.acos(rng.uniform(-0.4, 0.9))
        d = r * rng.uniform(1.0, 1.1)
        instance(fruit_src, f"{name}_orange{k}",
                 (x + d * math.sin(phi) * math.cos(theta), y + d * math.sin(phi) * math.sin(theta), cz + 0.85 * d * math.cos(phi)))
    return crown


def leaf_material(name, dark, light):
    # لون يختلف قليلاً من ورقة لأخرى، ويمر منه بعض الضوء كما في الأوراق الحقيقية.
    mat, nt, bsdf = node_mat(name)
    info = nt.nodes.new("ShaderNodeObjectInfo")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*dark, 1)
    ramp.color_ramp.elements[1].color = (*light, 1)
    nt.links.new(info.outputs["Random"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.45
    translucent = nt.nodes.new("ShaderNodeBsdfTranslucent")
    nt.links.new(ramp.outputs["Color"], translucent.inputs["Color"])
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = 0.25
    out = nt.nodes["Material Output"]
    nt.links.new(bsdf.outputs["BSDF"], mix.inputs[1])
    nt.links.new(translucent.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat


def planter(name, x, y, stone, soil):
    bed = box(name, (1.4, 1.4, 0.3), (x, y, 0.15), stone)
    bevel(bed, 0.03)
    box(name + "_soil", (1.25, 1.25, 0.05), (x, y, 0.29), soil)


def lantern(name, loc, metal, seed):
    # فانوس معلّق: غطاء وقاعدة وسلسلة، وزجاج مضيء، وضوء يرتعش بلا قفزة عند تكرار الحلقة.
    x, y, z = loc
    cylinder(name, 0.16, 0.05, (x, y, z + 0.2), metal, verts=8)
    cylinder(name + "_base", 0.13, 0.04, (x, y, z - 0.2), metal, verts=8)
    cylinder(name + "_chain", 0.01, 1.2, (x, y, z + 0.8), metal, verts=6)
    glow = cylinder(name + "_glow", 0.11, 0.34, loc, emission_material(name + "_flame", (1.0, 0.55, 0.18), 6.0), verts=8)
    glow.visible_shadow = False
    bpy.ops.object.light_add(type="POINT", location=loc)
    light = bpy.context.view_layer.objects.active
    light.name = name + "_light"
    light.data.color = (1.0, 0.6, 0.25)
    light.data.shadow_soft_size = 0.08
    drv = light.data.driver_add("energy").driver
    drv.type = "SCRIPTED"
    f = FRAMES
    drv.expression = (
        f"140 + 25*sin(frame*6.2832*7/{f}+{seed}) + 15*sin(frame*6.2832*13/{f}+{seed * 2})"
        f" + 8*sin(frame*6.2832*29/{f}+{seed * 3})"
    )


# ---------- sky ----------

def build_world(scene):
    world = bpy.data.worlds.new("Night")
    world.use_nodes = True
    nt = world.node_tree
    bg = nt.nodes["Background"]
    hdri = night_hdri()
    if hdri:
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(hdri, check_existing=True)
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 0.25
    else:
        # سماء بنجوم: نقاط Voronoi صغيرة فوق تدرّج أزرق داكن.
        coord = nt.nodes.new("ShaderNodeTexCoord")
        vor = nt.nodes.new("ShaderNodeTexVoronoi")
        vor.inputs["Scale"].default_value = 180.0
        nt.links.new(coord.outputs["Generated"], vor.inputs["Vector"])
        stars = nt.nodes.new("ShaderNodeMath")
        stars.operation = "LESS_THAN"
        stars.inputs[1].default_value = 0.05
        nt.links.new(vor.outputs["Distance"], stars.inputs[0])
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.inputs["A"].default_value = (0.004, 0.007, 0.02, 1)
        mix.inputs["B"].default_value = (2.5, 2.5, 2.8, 1)
        nt.links.new(stars.outputs["Value"], mix.inputs["Factor"])
        nt.links.new(mix.outputs["Result"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 1.0
    # ضباب ليلي خفيف يرسم هالة حول الفوانيس وأشعة القمر.
    fog = nt.nodes.new("ShaderNodeVolumePrincipled")
    fog.inputs["Density"].default_value = 0.006
    fog.inputs["Color"].default_value = (0.7, 0.75, 0.9, 1)
    nt.links.new(fog.outputs["Volume"], nt.nodes["World Output"].inputs["Volume"])
    scene.world = world


def build_moon(cam_loc):
    # قمر كبير أمام الكاميرا فوق الجدار الشمالي، فيظهر وينعكس في البركة.
    elev, dist = math.radians(17), 400.0  # بزاوية تسمح بانعكاسه في البركة فوق الجدار
    loc = (0, cam_loc[1] + dist * math.cos(elev), cam_loc[2] + dist * math.sin(elev))
    bpy.ops.mesh.primitive_uv_sphere_add(radius=7.0, location=loc, segments=48, ring_count=24)
    disk = bpy.context.view_layer.objects.active
    disk.name = "MoonDisk"
    mat, nt, bsdf = node_mat("MoonSurface")
    nt.nodes.remove(bsdf)
    out = nt.nodes["Material Output"]
    em = nt.nodes.new("ShaderNodeEmission")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 3.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.55, 0.57, 0.62, 1)  # «بحار» القمر الداكنة
    ramp.color_ramp.elements[1].color = (1.0, 0.98, 0.92, 1)
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], em.inputs["Color"])
    em.inputs["Strength"].default_value = 4.0
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    disk.data.materials.append(mat)
    disk.visible_shadow = False
    # ضوء القمر في نفس اتجاه القرص.
    bpy.ops.object.light_add(type="SUN", rotation=(math.radians(90) + elev, 0, math.radians(180)))
    sun = bpy.context.view_layer.objects.active
    sun.name = "Moonlight"
    sun.data.energy = 0.5
    sun.data.color = (0.65, 0.75, 1.0)
    sun.data.angle = math.radians(1.0)


def clear_scene():
    # نمسح محتوى المشهد يدوياً، لأن إعادة ضبط Blender كاملاً تكسر السياق عند التشغيل من نافذة Scripting.
    scene = bpy.context.scene
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras,
                 bpy.data.textures, bpy.data.worlds, bpy.data.actions):
        for block in list(coll):
            if block.users == 0:
                coll.remove(block)
    return scene


# ---------- scene ----------

def build():
    scene = clear_scene()
    scene.frame_start, scene.frame_end = 1, FRAMES
    scene.render.fps = FPS
    rng = random.Random(7)

    plaster = material("plaster", 0.5, lambda: noise_material("Plaster", (0.74, 0.64, 0.5), (0.93, 0.85, 0.7), bump=0.15), tint=(0.93, 0.83, 0.66))
    carved = sebka_material(plaster)
    floor_mat = material("floor", 0.6, zellige_material)
    marble = material("marble", 0.8, lambda: noise_material("Marble", (0.8, 0.78, 0.74), (0.97, 0.96, 0.93), scale=3, rough=0.25, bump=0.05), bump=0.05)
    wood = material("wood", 0.7, lambda: noise_material("Wood", (0.12, 0.06, 0.03), (0.3, 0.17, 0.08), scale=12, rough=0.6))
    soil = material("soil", 1.5, lambda: noise_material("Soil", (0.05, 0.03, 0.02), (0.14, 0.09, 0.05), scale=20, rough=1.0))
    water = water_material()
    orange_leaf = leaf_mesh("OrangeLeaf", 1.0, 0.45, leaf_material("OrangeLeaves", (0.02, 0.08, 0.025), (0.1, 0.24, 0.07)))
    needle_leaf = leaf_mesh("CypressSprig", 1.0, 0.3, leaf_material("CypressLeaves", (0.015, 0.05, 0.02), (0.05, 0.13, 0.05)))
    inner = plain_material("InnerFoliage", (0.012, 0.04, 0.014), rough=0.9)
    bark = noise_material("Bark", (0.05, 0.035, 0.025), (0.14, 0.1, 0.07), scale=30, rough=0.95, bump=0.8)
    metal = plain_material("Brass", (0.35, 0.22, 0.08), rough=0.4)
    fruit_mat = plain_material("Orange", (0.95, 0.38, 0.02), rough=0.45)

    floor = box("Floor", (COURT_W + 6, COURT_L + 6, 0.2), (0, 0, -0.1), floor_mat)
    cut(floor, box("PoolCut", (POOL_W, POOL_L, 0.8), (0, 0, 0)))
    box("PoolWater", (POOL_W, POOL_L, 0.02), (0, 0, -0.08), water)
    rim = box("PoolRim", (POOL_W + 0.5, POOL_L + 0.5, 0.12), (0, 0, 0.06), marble)
    cut(rim, box("RimCut", (POOL_W, POOL_L, 1.0), (0, 0, 0)))
    bevel(rim)

    fy = POOL_L / 2 + 1.4
    basin = cylinder("FountainBasin", 0.9, 0.35, (0, fy, 0.18), marble, verts=12)
    bevel(basin)
    cylinder("FountainStem", 0.12, 0.8, (0, fy, 0.6), marble, verts=12)
    cylinder("FountainBowl", 0.4, 0.1, (0, fy, 1.0), marble, verts=12)
    cylinder("FountainWater", 0.75, 0.02, (0, fy, 0.32), water, verts=32)

    sides = (
        Side("ArcadeNorth", "x", COURT_L / 2, -1),
        Side("ArcadeSouth", "x", -COURT_L / 2, 1),
        Side("ArcadeEast", "y", COURT_W / 2, -1),
        Side("ArcadeWest", "y", -COURT_W / 2, 1),
    )
    for side in sides:
        arcade(side, plaster, carved, marble, wood)

    # جدران خلف الأروقة بنوافذ مضيئة، حتى لا يظهر فراغ أسود خلف الأقواس.
    window = emission_material("WindowGlow", (1.0, 0.55, 0.2), 1.5)
    for name, size, loc in (
        ("BackNorth", (COURT_W + 6, 0.4, 6), (0, COURT_L / 2 + 2.5, 3.0)),
        ("BackSouth", (COURT_W + 6, 0.4, 7), (0, -COURT_L / 2 - 2.5, 3.5)),
        ("BackEast", (0.4, COURT_L + 6, 7), (COURT_W / 2 + 2.5, 0, 3.5)),
        ("BackWest", (0.4, COURT_L + 6, 7), (-COURT_W / 2 - 2.5, 0, 3.5)),
    ):
        box(name, size, loc, plaster)
    for i, y in enumerate(range(-10, 11, 4)):
        for s in (-1, 1):
            box(f"Window{s}_{i}", (0.05, 0.5, 0.9), (s * (COURT_W / 2 + 2.28), y, 1.8), window)

    # صفّان من الأشجار على جانبي البركة: سرو وبرتقال بالتناوب، كل شجرة في حوض حجري.
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.075, segments=12, ring_count=8)
    fruit_src = bpy.context.view_layer.objects.active
    fruit_src.name = "OrangeFruit"
    fruit_src.data.materials.append(fruit_mat)
    fruit_src.hide_render = True
    fruit_src.hide_viewport = True
    for i, y in enumerate((-7.5, -3.75, 0, 3.75, 7.5)):
        for s in (-1, 1):
            x = s * (POOL_W / 2 + 2.2)
            planter(f"Planter{s}_{i}", x, y, marble, soil)
            if i % 2 == 0:
                orange_tree(f"Orange{s}_{i}", x, y, orange_leaf, inner, bark, fruit_src, rng)
            else:
                cypress(f"Cypress{s}_{i}", x, y, needle_leaf, inner, bark, rng)

    for i, y in enumerate((-10, -5, 0, 5, 10)):
        lantern(f"LanternL{i}", (-COURT_W / 2 + 0.6, y, 3.2), metal, seed=i + 1)
        lantern(f"LanternR{i}", (COURT_W / 2 - 0.6, y, 3.2), metal, seed=i + 7)
    # فوانيس على الجدار المقابل للكاميرا (وخلفها)، فلا يبقى الجدار الشمالي مظلماً.
    for i, x in enumerate((-COURT_W / 2 + 0.9, 0.0, COURT_W / 2 - 0.9)):
        lantern(f"LanternN{i}", (x, COURT_L / 2 - 0.7, 3.4), metal, seed=i + 13)
        lantern(f"LanternS{i}", (x, -COURT_L / 2 + 0.7, 3.4), metal, seed=i + 17)

    # كاميرا بارتفاع العين تتقدم ببطء ثم تعود، لتتكرر الحلقة بلا قطع.
    cam_loc = (0, -COURT_L / 2 + 1.5, 1.7)
    bpy.ops.object.camera_add(location=cam_loc, rotation=(math.radians(90), 0, 0))
    cam = bpy.context.view_layer.objects.active
    cam.name = "Camera"
    cam.data.lens = 26
    scene.camera = cam
    for frame, y in ((1, cam_loc[1]), (FRAMES // 2 + 1, cam_loc[1] + 1.5), (FRAMES + 1, cam_loc[1])):
        cam.location.y = y
        cam.keyframe_insert("location", index=1, frame=frame)
    for fc in fcurves_of(cam.animation_data.action):
        for kp in fc.keyframe_points:
            kp.interpolation = "SINE"
            kp.easing = "EASE_IN_OUT"

    build_world(scene)
    build_moon(cam_loc)
    render_settings(scene)
    return scene


def render_settings(scene):
    scene.render.engine = "CYCLES"
    cycles = scene.cycles
    cycles.samples = 128  # مع إزالة التشويش تكفي؛ على GTX 1660 SUPER حوالي دقيقة لكل صورة
    cycles.use_denoising = True
    cycles.volume_step_rate = 4.0  # ضباب أسرع رندراً مع فرق بسيط في الشكل
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        # نحترم الجهاز الذي اخترته في الإعدادات، وإلا نجرب الأنواع واحداً واحداً.
        kinds = [prefs.compute_device_type] if prefs.compute_device_type != "NONE" else []
        for kind in kinds + ["OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"]:
            try:
                prefs.compute_device_type = kind
                prefs.get_devices()
                if any(d.type != "CPU" for d in prefs.devices):
                    break
            except TypeError:
                continue
        for d in prefs.devices:
            d.use = True
        cycles.device = "GPU" if any(d.type != "CPU" for d in prefs.devices) else "CPU"
    except Exception:
        cycles.device = "CPU"  # بلا كرت شاشة يعمل لكن أبطأ بكثير.
    print("جهاز الرندر:", cycles.device)
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"


if __name__ == "__main__":
    scene = build()
    if "--render" in ARGV:
        scene.render.filepath = ARGV[ARGV.index("--render") + 1]
        bpy.ops.render.render(animation=True)
    elif "--preview" in ARGV:
        # صورة واحدة سريعة للتجربة.
        scene.cycles.samples = 32
        scene.render.resolution_percentage = 50
        scene.frame_set(1)
        scene.render.filepath = ARGV[ARGV.index("--preview") + 1]
        bpy.ops.render.render(write_still=True)
