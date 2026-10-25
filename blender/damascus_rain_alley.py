# مطر على حارة دمشقية: زقاق من دمشق القديمة ليلاً تحت المطر، في Blender 4.2 أو أحدث.
#
# المشهد: زقاق حجري ضيق مبلل ببرك تعكس الضوء، جدران سفلية من الحجر الأبلق (صفوف بازلت أسود
# وحجر كلسي فاتح)، طوابق علوية بارزة فوق الزقاق بمشربيات خشبية مضيئة من الداخل، أبواب خشبية،
# «ساباط» (غرفة تعبر فوق الزقاق)، فوانيس جدارية، ياسمينة متدلية، مطر متحرك وضباب.
# الكاميرا تتقدم ببطء ثم تعود، وتتكرر الحلقة (10 ثوانٍ) بلا قطع واضح.
#
# الاستخدام (مثل سكربت الفناء):
#   افتح Blender ← Scripting ← Open ← هذا الملف ← Run Script، ثم F12 لصورة واحدة.
#   صورة تجريبية سريعة:  blender -b -P damascus_rain_alley.py -- --preview preview.png
#   رندر الحلقة كاملة:   blender -b -P damascus_rain_alley.py -- --render out/frame_
#   بلا تنزيل خامات:      أضف --offline
#
# الخامات الحقيقية تُنزَّل من Poly Haven إلى ~/BlenderAssets/polyhaven (تحتاج Allow Online Access).

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

ALLEY_W, ALLEY_L = 3.2, 30.0  # عرض الزقاق وطوله بالمتر
GROUND_H = 3.2  # ارتفاع الطابق الأرضي الحجري

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
    "cobble": ["cobblestone", "cobble", "pavement", "paving"],
    "plaster": ["plaster", "stucco", "beige_wall"],
    "wood": ["planks", "wood"],
    "door": ["wooden_door", "old_wood", "weathered_wood", "wood"],
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


_models = {}


def ph_model(asset_id):
    # نموذج ثلاثي الأبعاد حقيقي من Poly Haven (glTF 1k)، يُستورد مرة واحدة إلى مجموعة مخفية
    # ثم يُكرَّر بنسخ خفيفة عبر place_model. يعيد None بلا إنترنت، فيكمل المشهد بالأشكال البسيطة.
    if asset_id in _models:
        return _models[asset_id]
    folder = os.path.join(ASSETS_DIR, "models", asset_id)
    path = None
    if os.path.isdir(folder):
        path = next((os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".gltf")), None)
    if not path and not OFFLINE:
        try:
            print(f"تنزيل نموذج: {asset_id}")
            entry = ph_get(f"/files/{asset_id}")["gltf"]
            entry = entry.get("1k") or entry.get("2k")
            gltf = entry["gltf"]
            for rel, inc in gltf.get("include", {}).items():
                download(inc["url"], os.path.join(folder, *rel.split("/")))
            path = os.path.join(folder, os.path.basename(gltf["url"]))
            download(gltf["url"], path)
            with open(os.path.join(folder, "source.txt"), "w") as f:
                f.write(f"https://polyhaven.com/a/{asset_id}\n")
        except Exception as e:
            print(f"تعذر تنزيل نموذج {asset_id}: {e}")
            path = None
    if not path:
        _models[asset_id] = None
        return None
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    objs = [o for o in bpy.data.objects if o not in before]
    coll = bpy.data.collections.new("PH_" + asset_id)
    for o in objs:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
    # قاعدة النموذج في منتصفه السفلي، حتى يقف على الأرض حيث نضعه.
    pts = [o.matrix_world @ mathutils.Vector(c) for o in objs if o.type == "MESH" for c in o.bound_box]
    lo = mathutils.Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = mathutils.Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    coll.instance_offset = ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z)
    coll["height"] = hi.z - lo.z
    _models[asset_id] = coll
    return coll


def place_model(coll, name, loc, height, rot_z=0.0):
    # نسخة من النموذج بارتفاع محدد بالمتر.
    ob = bpy.data.objects.new(name, None)
    ob.instance_type = "COLLECTION"
    ob.instance_collection = coll
    ob.location = loc
    ob.rotation_euler = (0, 0, rot_z)
    s = height / max(coll["height"], 1e-4)
    ob.scale = (s, s, s)
    bpy.context.scene.collection.objects.link(ob)
    return ob


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




# ---------- alley materials ----------

def ablaq_material():
    # الحجر الأبلق الدمشقي: صفوف أفقية تتناوب بين بازلت أسود وحجر كلسي فاتح، بحجارة متفاوتة.
    mat, nt, bsdf = node_mat("Ablaq")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Position"], sep.inputs["Vector"])
    course = nt.nodes.new("ShaderNodeMath")
    course.operation = "DIVIDE"
    course.inputs[1].default_value = 0.28  # ارتفاع الصف
    nt.links.new(sep.outputs["Z"], course.inputs[0])
    flo = nt.nodes.new("ShaderNodeMath")
    flo.operation = "FLOOR"
    nt.links.new(course.outputs["Value"], flo.inputs[0])
    mod = nt.nodes.new("ShaderNodeMath")
    mod.operation = "FLOORED_MODULO"
    mod.inputs[1].default_value = 3.0
    nt.links.new(flo.outputs["Value"], mod.inputs[0])
    is_dark = nt.nodes.new("ShaderNodeMath")  # صف بازلت بعد كل صفين من الحجر الفاتح
    is_dark.operation = "LESS_THAN"
    is_dark.inputs[1].default_value = 0.5
    nt.links.new(mod.outputs["Value"], is_dark.inputs[0])
    brick = nt.nodes.new("ShaderNodeTexBrick")
    brick.inputs["Scale"].default_value = 1.0
    brick.inputs["Brick Width"].default_value = 0.7
    brick.inputs["Row Height"].default_value = 0.28
    brick.inputs["Mortar Size"].default_value = 0.02
    brick.inputs["Mortar Smooth"].default_value = 0.6  # حواف متآكلة
    brick.inputs["Color1"].default_value = (1.0, 1.0, 1.0, 1)
    brick.inputs["Color2"].default_value = (0.6, 0.6, 0.6, 1)
    brick.inputs["Bias"].default_value = 0.0
    brick.inputs["Mortar"].default_value = (0.25, 0.25, 0.25, 1)
    # نُسقط الطوب على مستوى الجدار (طوله أفقياً و Z عمودياً) أياً كان اتجاهه.
    comb = nt.nodes.new("ShaderNodeCombineXYZ")
    add = nt.nodes.new("ShaderNodeMath")
    add.operation = "ADD"
    nt.links.new(sep.outputs["X"], add.inputs[0])
    nt.links.new(sep.outputs["Y"], add.inputs[1])
    nt.links.new(add.outputs["Value"], comb.inputs["X"])
    nt.links.new(sep.outputs["Z"], comb.inputs["Y"])
    # تشويه خفيف للإحداثيات: حواف حجارة غير مستقيمة كالحجر المنحوت يدوياً.
    jitter = nt.nodes.new("ShaderNodeTexNoise")
    jitter.inputs["Scale"].default_value = 6.0
    nt.links.new(comb.outputs["Vector"], jitter.inputs["Vector"])
    jit = nt.nodes.new("ShaderNodeVectorMath")
    jit.operation = "MULTIPLY_ADD"
    jit.inputs[1].default_value = (0.035, 0.02, 0.0)
    jit.inputs[2].default_value = (-0.017, -0.01, 0.0)
    nt.links.new(jitter.outputs["Color"], jit.inputs[0])
    warped = nt.nodes.new("ShaderNodeVectorMath")
    warped.operation = "ADD"
    nt.links.new(comb.outputs["Vector"], warped.inputs[0])
    nt.links.new(jit.outputs["Vector"], warped.inputs[1])
    nt.links.new(warped.outputs["Vector"], brick.inputs["Vector"])
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 4.0
    noise.inputs["Detail"].default_value = 12.0
    noise.inputs["Roughness"].default_value = 0.65
    dark = nt.nodes.new("ShaderNodeValToRGB")  # بازلت
    dark.color_ramp.elements[0].color = (0.025, 0.024, 0.023, 1)
    dark.color_ramp.elements[1].color = (0.07, 0.065, 0.06, 1)
    light = nt.nodes.new("ShaderNodeValToRGB")  # حجر كلسي
    light.color_ramp.elements[0].color = (0.42, 0.37, 0.3, 1)
    light.color_ramp.elements[1].color = (0.66, 0.6, 0.5, 1)
    for ramp in (dark, light):
        nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    pick = nt.nodes.new("ShaderNodeMix")
    pick.data_type = "RGBA"
    nt.links.new(is_dark.outputs["Value"], pick.inputs["Factor"])
    nt.links.new(light.outputs["Color"], pick.inputs["A"])
    nt.links.new(dark.outputs["Color"], pick.inputs["B"])
    shade = nt.nodes.new("ShaderNodeMix")
    shade.data_type = "RGBA"
    shade.blend_type = "MULTIPLY"
    shade.inputs["Factor"].default_value = 1.0
    nt.links.new(pick.outputs["Result"], shade.inputs["A"])
    nt.links.new(brick.outputs["Color"], shade.inputs["B"])
    nt.links.new(shade.outputs["Result"], bsdf.inputs["Base Color"])
    # الحجر مبلل: أكثر لمعاناً من الجاف.
    bsdf.inputs["Roughness"].default_value = 0.45
    bp = nt.nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = 0.6
    nt.links.new(brick.outputs["Fac"], bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def wet_ground_material():
    # أرض مبلطة بحجارة، مبللة، فيها برك ماء ترتعش من المطر.
    maps = texture_maps("cobble")
    mat, nt, bsdf = node_mat("WetCobbles")
    if "color" in maps:
        vec = mapping(nt, 0.5)
        color = image_node(nt, maps["color"], vec).outputs["Color"]
        rough = image_node(nt, maps["rough"], vec, color=False).outputs["Color"] if "rough" in maps else None
        height = image_node(nt, maps["disp"], vec, color=False).outputs["Color"] if "disp" in maps else None
    else:
        coord = nt.nodes.new("ShaderNodeTexCoord")
        vor = nt.nodes.new("ShaderNodeTexVoronoi")
        vor.feature = "DISTANCE_TO_EDGE"
        vor.inputs["Scale"].default_value = 3.2
        nt.links.new(coord.outputs["Object"], vor.inputs["Vector"])
        cells = nt.nodes.new("ShaderNodeTexVoronoi")
        cells.inputs["Scale"].default_value = 3.2
        nt.links.new(coord.outputs["Object"], cells.inputs["Vector"])
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = (0.1, 0.095, 0.09, 1)
        ramp.color_ramp.elements[1].color = (0.32, 0.3, 0.27, 1)
        bw = nt.nodes.new("ShaderNodeRGBToBW")
        nt.links.new(cells.outputs["Color"], bw.inputs["Color"])
        nt.links.new(bw.outputs["Val"], ramp.inputs["Fac"])
        gap = nt.nodes.new("ShaderNodeMapRange")
        gap.inputs["From Min"].default_value = 0.0
        gap.inputs["From Max"].default_value = 0.09
        nt.links.new(vor.outputs["Distance"], gap.inputs["Value"])
        dirt = nt.nodes.new("ShaderNodeMix")
        dirt.data_type = "RGBA"
        dirt.blend_type = "MULTIPLY"
        nt.links.new(gap.outputs["Result"], dirt.inputs["Factor"])
        dirt.inputs["A"].default_value = (0.02, 0.018, 0.015, 1)
        nt.links.new(ramp.outputs["Color"], dirt.inputs["B"])
        color, rough, height = dirt.outputs["Result"], None, gap.outputs["Result"]
    # أين البرك: بقع واسعة من ضجيج ناعم.
    coord2 = nt.nodes.new("ShaderNodeTexCoord")
    pn = nt.nodes.new("ShaderNodeTexNoise")
    pn.inputs["Scale"].default_value = 0.45
    pn.inputs["Detail"].default_value = 3.0
    nt.links.new(coord2.outputs["Object"], pn.inputs["Vector"])
    puddle = nt.nodes.new("ShaderNodeMapRange")
    puddle.inputs["From Min"].default_value = 0.52
    puddle.inputs["From Max"].default_value = 0.56
    nt.links.new(pn.outputs["Fac"], puddle.inputs["Value"])
    # لون أغمق في الماء، وخشونة شبه معدومة.
    darker = nt.nodes.new("ShaderNodeMix")
    darker.data_type = "RGBA"
    darker.blend_type = "MULTIPLY"
    darker.inputs["B"].default_value = (0.45, 0.45, 0.45, 1)
    darker.inputs["Factor"].default_value = 1.0
    nt.links.new(color, darker.inputs["A"])
    wetcol = nt.nodes.new("ShaderNodeMix")
    wetcol.data_type = "RGBA"
    nt.links.new(puddle.outputs["Result"], wetcol.inputs["Factor"])
    nt.links.new(darker.outputs["Result"], wetcol.inputs["A"])
    wetcol.inputs["B"].default_value = (0.01, 0.01, 0.012, 1)
    nt.links.new(wetcol.outputs["Result"], bsdf.inputs["Base Color"])
    base_rough = nt.nodes.new("ShaderNodeMath")
    base_rough.operation = "MULTIPLY"
    base_rough.inputs[1].default_value = 0.45  # الحجر المبلل يلمع
    if rough is not None:
        nt.links.new(rough, base_rough.inputs[0])
    else:
        base_rough.inputs[0].default_value = 0.6
    r_mix = nt.nodes.new("ShaderNodeMix")
    nt.links.new(puddle.outputs["Result"], r_mix.inputs["Factor"])
    nt.links.new(base_rough.outputs["Value"], r_mix.inputs["A"])
    r_mix.inputs["B"].default_value = 0.02
    nt.links.new(r_mix.outputs["Result"], bsdf.inputs["Roughness"])
    # ارتعاش سطح البرك: ضجيج رباعي الأبعاد يتحرك مع الوقت.
    ripple = nt.nodes.new("ShaderNodeTexNoise")
    ripple.noise_dimensions = "4D"
    ripple.inputs["Scale"].default_value = 40.0
    nt.links.new(coord2.outputs["Object"], ripple.inputs["Vector"])
    w = ripple.inputs["W"]
    w.default_value = 0.0
    w.keyframe_insert("default_value", frame=1)
    w.default_value = 25.0
    w.keyframe_insert("default_value", frame=FRAMES + 1)
    for fc in fcurves_of(nt.animation_data.action):
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
    h_mix = nt.nodes.new("ShaderNodeMix")
    nt.links.new(puddle.outputs["Result"], h_mix.inputs["Factor"])
    if height is not None:
        nt.links.new(height, h_mix.inputs["A"])
    small = nt.nodes.new("ShaderNodeMath")
    small.operation = "MULTIPLY"
    small.inputs[1].default_value = 0.05
    nt.links.new(ripple.outputs["Fac"], small.inputs[0])
    nt.links.new(small.outputs["Value"], h_mix.inputs["B"])
    bp = nt.nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = 0.5
    bp.inputs["Distance"].default_value = 0.02
    nt.links.new(h_mix.outputs["Result"], bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def mashrabiya_material(wood):
    # شبكة خشبية معينية (مشربية) يشعّ من خلالها ضوء البيت الدافئ.
    mat = bpy.data.materials.new("Mashrabiya")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    rot = nt.nodes.new("ShaderNodeMapping")
    rot.inputs["Rotation"].default_value = (math.radians(45), 0, math.radians(45))
    nt.links.new(coord.outputs["Object"], rot.inputs["Vector"])
    brick = nt.nodes.new("ShaderNodeTexBrick")
    brick.offset = 0.0
    brick.inputs["Scale"].default_value = 9.0
    brick.inputs["Mortar Size"].default_value = 0.06
    brick.inputs["Brick Width"].default_value = 0.5
    brick.inputs["Row Height"].default_value = 0.5
    nt.links.new(rot.outputs["Vector"], brick.inputs["Vector"])
    glow = nt.nodes.new("ShaderNodeEmission")
    glow.inputs["Color"].default_value = (1.0, 0.6, 0.28, 1)
    glow.inputs["Strength"].default_value = 0.3  # ضوء يتسرب من بين فتحات الشبكة فقط
    wood_bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    wood_bsdf.inputs["Base Color"].default_value = (0.09, 0.045, 0.02, 1)
    wood_bsdf.inputs["Roughness"].default_value = 0.5
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(brick.outputs["Fac"], mix.inputs["Fac"])  # 1 على خطوط الشبكة = خشب
    nt.links.new(glow.outputs["Emission"], mix.inputs[1])
    nt.links.new(wood_bsdf.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat


def rain_drop_material():
    # قطرة شبه شفافة: تلتقط ضوء الفوانيس دون أن تغطي المشهد.
    mat, nt, bsdf = node_mat("RainDrop")
    bsdf.inputs["Base Color"].default_value = (0.85, 0.9, 1.0, 1)
    bsdf.inputs["Roughness"].default_value = 0.1
    bsdf.inputs["Alpha"].default_value = 0.35
    bsdf.inputs["Emission Color"].default_value = (0.7, 0.75, 0.85, 1)
    bsdf.inputs["Emission Strength"].default_value = 0.04
    return mat


# ---------- old lantern ----------

def old_lantern(name, loc, side, iron, seed):
    # فانوس قديم سداسي بزجاج مغبّش وإطار حديدي، معلق بسلسلة من ذراع حديدي مزخرف.
    x, y, z = loc
    wall_x = side * ALLEY_W / 2
    box(name + "_arm", (abs(wall_x - x) + 0.05, 0.03, 0.03), ((wall_x + x) / 2, y, z + 0.62), iron)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.1, minor_radius=0.008, location=((wall_x + x) / 2, y, z + 0.5),
                                     rotation=(math.pi / 2, 0, 0))
    scroll = bpy.context.view_layer.objects.active
    scroll.name = name + "_scroll"
    scroll.data.materials.append(iron)
    cylinder(name + "_chain", 0.006, 0.3, (x, y, z + 0.47), iron, verts=6)
    model = ph_model("Lantern_01")
    if model:
        # فانوس حقيقي من Poly Haven، وفي داخله لهب صغير يضيء الزجاج.
        for o in model.objects:
            o.visible_shadow = False
        place_model(model, name + "_model", (x, y, z - 0.12), 0.42, rot_z=seed)
        bpy.ops.mesh.primitive_ico_sphere_add(radius=0.025, subdivisions=2, location=(x, y, z + 0.04))
        flame = bpy.context.view_layer.objects.active
        flame.name = name + "_flame"
        flame.scale.z = 1.8
        flame.data.materials.append(emission_material(name + "_fire", (1.0, 0.45, 0.12), 25.0))
        flame.visible_shadow = False
    else:
        old_lantern_body(name, x, y, z, iron)
    lantern_light(name, x, y, z, seed)


def old_lantern_body(name, x, y, z, iron):
    glass = emission_material(name + "_glass", (1.0, 0.5, 0.15), 2.0)
    bpy.ops.mesh.primitive_cone_add(vertices=6, radius1=0.08, radius2=0.12, depth=0.3, location=(x, y, z))
    body = bpy.context.view_layer.objects.active
    body.name = name + "_body"
    body.data.materials.append(glass)
    body.visible_shadow = False
    bpy.ops.mesh.primitive_cone_add(vertices=6, radius1=0.085, radius2=0.125, depth=0.3, location=(x, y, z))
    frame = bpy.context.view_layer.objects.active
    frame.name = name + "_frame"
    frame.data.materials.append(iron)
    frame.modifiers.new("Frame", "WIREFRAME").thickness = 0.012
    bpy.ops.mesh.primitive_cone_add(vertices=6, radius1=0.15, radius2=0.015, depth=0.14, location=(x, y, z + 0.22))
    roof = bpy.context.view_layer.objects.active
    roof.name = name + "_roof"
    roof.data.materials.append(iron)
    cylinder(name + "_base", 0.09, 0.03, (x, y, z - 0.16), iron, verts=6)


def lantern_light(name, x, y, z, seed):
    bpy.ops.object.light_add(type="POINT", location=(x, y, z))
    light = bpy.context.view_layer.objects.active
    light.name = name + "_light"
    light.data.color = (1.0, 0.52, 0.18)
    light.data.shadow_soft_size = 0.06
    drv = light.data.driver_add("energy").driver
    drv.type = "SCRIPTED"
    f = FRAMES
    # ضوء خافت يرتعش كلهب زيت، ويعود لنقطته الأولى في آخر الحلقة.
    drv.expression = (
        f"22 + 5*sin(frame*6.2832*9/{f}+{seed}) + 4*sin(frame*6.2832*17/{f}+{seed * 2})"
        f" + 2*sin(frame*6.2832*37/{f}+{seed * 3})"
    )


# ---------- aging ----------

def age_material(mat, patch_color, patch_amount=0.25, streaks=True, base_dirt=True):
    # يضيف للخامة أثر الزمن فوق لونها الأصلي: بقع متقشرة يظهر تحتها لون آخر (طين أو حجر)،
    # خطوط رطوبة عمودية تنزل من الأعلى، واتساخ داكن عند أسفل الجدار.
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    sock = bsdf.inputs["Base Color"]
    old = next((l for l in nt.links if l.to_socket == sock), None)
    color = old.from_socket if old else None
    if color is None:
        rgb = nt.nodes.new("ShaderNodeRGB")
        rgb.outputs[0].default_value = sock.default_value[:]
        color = rgb.outputs[0]
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    # بقع التقشر: ضجيج بحواف حادة.
    pn = nt.nodes.new("ShaderNodeTexNoise")
    pn.inputs["Scale"].default_value = 2.6
    pn.inputs["Detail"].default_value = 12.0
    pn.inputs["Roughness"].default_value = 0.7
    nt.links.new(geo.outputs["Position"], pn.inputs["Vector"])
    mask = nt.nodes.new("ShaderNodeMapRange")
    mask.inputs["From Min"].default_value = 0.62 - patch_amount * 0.3
    mask.inputs["From Max"].default_value = 0.70 - patch_amount * 0.3
    nt.links.new(pn.outputs["Fac"], mask.inputs["Value"])
    patch = nt.nodes.new("ShaderNodeMix")
    patch.data_type = "RGBA"
    nt.links.new(mask.outputs["Result"], patch.inputs["Factor"])
    nt.links.new(color, patch.inputs["A"])
    patch.inputs["B"].default_value = (*patch_color, 1)
    color = patch.outputs["Result"]
    # البقع منخفضة قليلاً عن السطح (الجص سقط منها).
    bp = nt.nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = 0.6
    bp.inputs["Distance"].default_value = 0.01
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(mask.outputs["Result"], inv.inputs[1])
    nt.links.new(inv.outputs["Value"], bp.inputs["Height"])
    old_n = next((l for l in nt.links if l.to_socket == bsdf.inputs["Normal"]), None)
    if old_n:
        nt.links.new(old_n.from_socket, bp.inputs["Normal"])
    nt.links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])
    if streaks:
        # خطوط رطوبة: ضجيج ممطوط عمودياً.
        st_map = nt.nodes.new("ShaderNodeMapping")
        st_map.inputs["Scale"].default_value = (6.0, 6.0, 0.35)
        nt.links.new(geo.outputs["Position"], st_map.inputs["Vector"])
        st = nt.nodes.new("ShaderNodeTexNoise")
        st.inputs["Scale"].default_value = 2.0
        st.inputs["Detail"].default_value = 4.0
        nt.links.new(st_map.outputs["Vector"], st.inputs["Vector"])
        st_r = nt.nodes.new("ShaderNodeMapRange")
        st_r.inputs["From Min"].default_value = 0.45
        st_r.inputs["From Max"].default_value = 0.75
        st_r.inputs["To Min"].default_value = 1.0
        st_r.inputs["To Max"].default_value = 0.75
        nt.links.new(st.outputs["Fac"], st_r.inputs["Value"])
        dark = nt.nodes.new("ShaderNodeMix")
        dark.data_type = "RGBA"
        dark.blend_type = "MULTIPLY"
        dark.inputs["Factor"].default_value = 1.0
        nt.links.new(color, dark.inputs["A"])
        comb = nt.nodes.new("ShaderNodeCombineColor")
        for k in ("Red", "Green", "Blue"):
            nt.links.new(st_r.outputs["Result"], comb.inputs[k])
        nt.links.new(comb.outputs["Color"], dark.inputs["B"])
        color = dark.outputs["Result"]
    if base_dirt:
        # اتساخ ورطوبة صاعدة من الأرض حتى ارتفاع متر تقريباً، بحافة متموجة.
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(geo.outputs["Position"], sep.inputs["Vector"])
        wob = nt.nodes.new("ShaderNodeTexNoise")
        wob.inputs["Scale"].default_value = 3.0
        nt.links.new(geo.outputs["Position"], wob.inputs["Vector"])
        hz = nt.nodes.new("ShaderNodeMath")
        hz.operation = "MULTIPLY_ADD"
        hz.inputs[2].default_value = -0.3
        nt.links.new(wob.outputs["Fac"], hz.inputs[0])
        hz.inputs[1].default_value = 0.6
        add = nt.nodes.new("ShaderNodeMath")
        add.operation = "ADD"
        nt.links.new(sep.outputs["Z"], add.inputs[0])
        nt.links.new(hz.outputs["Value"], add.inputs[1])
        rise = nt.nodes.new("ShaderNodeMapRange")
        rise.inputs["From Min"].default_value = 0.2
        rise.inputs["From Max"].default_value = 1.1
        rise.inputs["To Min"].default_value = 0.35
        rise.inputs["To Max"].default_value = 1.0
        nt.links.new(add.outputs["Value"], rise.inputs["Value"])
        dirt = nt.nodes.new("ShaderNodeMix")
        dirt.data_type = "RGBA"
        dirt.blend_type = "MULTIPLY"
        dirt.inputs["Factor"].default_value = 1.0
        nt.links.new(color, dirt.inputs["A"])
        comb2 = nt.nodes.new("ShaderNodeCombineColor")
        nt.links.new(rise.outputs["Result"], comb2.inputs["Red"])
        nt.links.new(rise.outputs["Result"], comb2.inputs["Green"])
        g = nt.nodes.new("ShaderNodeMath")  # الرطوبة تميل للأخضر قليلاً
        g.operation = "MULTIPLY"
        g.inputs[1].default_value = 0.92
        nt.links.new(rise.outputs["Result"], g.inputs[0])
        nt.links.new(g.outputs["Value"], comb2.inputs["Blue"])
        nt.links.new(comb2.outputs["Color"], dirt.inputs["B"])
        color = dirt.outputs["Result"]
    nt.links.new(color, sock)
    return mat


def warp(ob, strength=0.06, scale=1.5, cuts=24):
    # يجعل الجدار المستقيم غير منتظم قليلاً: انتفاخات وميلان كما في البيوت القديمة.
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.subdivide(number_cuts=cuts)
    bpy.ops.object.mode_set(mode="OBJECT")
    tex = bpy.data.textures.get("WallWarp") or bpy.data.textures.new("WallWarp", "CLOUDS")
    tex.noise_scale = scale
    mod = ob.modifiers.new("Warp", "DISPLACE")
    mod.texture = tex
    mod.texture_coords = "GLOBAL"
    mod.direction = "X"
    mod.strength = strength
    mod.mid_level = 0.5


def half_disc(name, radius, thickness, center, side, mat, segments=16):
    # نصف دائرة (قوس فوق الباب) بسماكة، تواجه الزقاق.
    cx, cy, cz = center
    verts = []
    for k in range(segments + 1):
        a = math.pi * k / segments
        for t in (0, thickness):
            verts.append((cx - side * t, cy + radius * math.cos(a), cz + radius * math.sin(a)))
    verts += [(cx, cy, cz), (cx - side * thickness, cy, cz)]
    c0, c1 = len(verts) - 2, len(verts) - 1
    faces = []
    for k in range(segments):
        a0, a1, b0, b1 = 2 * k, 2 * k + 1, 2 * k + 2, 2 * k + 3
        faces += [(a0, b0, b1, a1), (c0, b0, a0), (c1, a1, b1)]
    faces.append((0, 1, c1, c0))
    faces.append((2 * segments, c0, c1, 2 * segments + 1))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(mat)
    ob = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(ob)
    return ob


def wire(name, a, b, sag, mat):
    # سلك كهرباء متدلٍّ بين نقطتين (منحنى سلسلة).
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.006
    spline = curve.splines.new("POLY")
    n = 16
    spline.points.add(n)
    for k in range(n + 1):
        t = k / n
        x = a[0] + (b[0] - a[0]) * t
        y = a[1] + (b[1] - a[1]) * t
        z = a[2] + (b[2] - a[2]) * t - sag * 4 * t * (1 - t)
        spline.points[k].co = (x, y, z, 1)
    curve.materials.append(mat)
    ob = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(ob)
    return ob


# ---------- buildings ----------

def facade_segments(rng):
    # نقسم كل جانب من الزقاق إلى بيوت بعروض وارتفاعات مختلفة.
    segs, y = [], -2.0
    while y < ALLEY_L:
        w = rng.uniform(3.5, 6.0)
        segs.append((y, min(w, ALLEY_L + 2 - y), rng.uniform(6.5, 8.5)))
        y += w
    return segs


def house(name, side, y0, width, height, mats, rng):
    # side = -1 يسار، 1 يمين. الواجهة تطل على الزقاق عند x = side * ALLEY_W / 2.
    ablaq, plaster, wood, door_mat, lattice, window = mats
    jog = rng.uniform(-0.08, 0.08)  # البيوت القديمة لا تصطف تماماً
    face = side * (ALLEY_W / 2 + jog)
    yc = y0 + width / 2
    # جدار طيني مكسو بالجص فوق قاعدة حجرية منخفضة (كما في أزقة دمشق، لا واجهة حجرية كاملة).
    warp(box(name + "_ground", (0.5, width, GROUND_H), (face + side * 0.25, yc, GROUND_H / 2), plaster), strength=0.07)
    plinth_h = rng.uniform(0.9, 1.4)
    warp(box(name + "_plinth", (0.12, width, plinth_h), (face - side * 0.04, yc, plinth_h / 2), ablaq), strength=0.03, cuts=12)
    upper = box(name + "_upper", (0.5, width, height - GROUND_H), (face + side * 0.25, yc, GROUND_H + (height - GROUND_H) / 2), plaster)
    warp(upper, strength=0.1)
    # جسور خشبية أفقية ظاهرة في الجدار الطيني، كما في بيوت دمشق القديمة.
    for bz in (GROUND_H + 0.05, GROUND_H + 1.6 + rng.uniform(-0.2, 0.2)):
        if bz < height - 0.3:
            box(f"{name}_timber{bz:.2f}", (0.08, width, 0.12), (face - side * 0.02, yc, bz), wood)
    # سقف خشبي بارز بسيط في الأعلى.
    box(name + "_eave", (0.5, width, 0.1), (face - side * 0.1, yc, height + 0.05), wood)
    # باب خشبي في الطابق الأرضي.
    if rng.random() < 0.7:
        dy = yc + rng.uniform(-width / 4, width / 4)
        box(name + "_doorframe", (0.06, 1.3, 2.35), (face - side * 0.01, dy, 1.17), ablaq)
        box(name + "_door", (0.08, 1.1, 2.2), (face - side * 0.02, dy, 1.1), door_mat)
        # قوس حجري نصف دائري فوق الباب، وعتبة حجرية متآكلة أمامه.
        half_disc(name + "_arch", 0.68, 0.1, (face - side * 0.01, dy, 2.32), side, ablaq)
        half_disc(name + "_fan", 0.52, 0.06, (face - side * 0.04, dy, 2.32), side, door_mat)
        step = box(name + "_step", (0.35, 1.4, 0.14), (face - side * 0.15, dy, 0.07), ablaq)
        bevel(step, 0.04)
        for bz in (0.5, 1.7):
            box(f"{name}_band{bz}", (0.02, 1.1, 0.06), (face - side * 0.065, dy, bz), bpy.data.materials["Iron"])
        # مسامير حديدية كبيرة على الباب.
        stud = bpy.data.objects.get("DoorStud")
        if stud is None:
            bpy.ops.mesh.primitive_uv_sphere_add(radius=0.022, segments=8, ring_count=6, location=(0, 0, -100))
            stud = bpy.context.view_layer.objects.active
            stud.name = "DoorStud"
            stud.data.materials.append(bpy.data.materials["Iron"])
        for i in range(4):
            for j in range(6):
                instance(stud, f"{name}_stud{i}{j}", (face - side * 0.065, dy - 0.42 + i * 0.28, 0.3 + j * 0.34))
        cylinder(name + "_knocker", 0.05, 0.02, (face - side * 0.07, dy + 0.3, 1.2), bpy.data.materials["Brass"], verts=12, rot=(0, math.pi / 2, 0))
    # نافذة صغيرة بقضبان حديد مضيئة من الداخل.
    if rng.random() < 0.5:
        wy = yc + rng.uniform(-width / 3, width / 3)
        box(name + "_lowwin", (0.04, 0.6, 0.8), (face - side * 0.01, wy, 2.0), wood)  # مغلقة ومظلمة
        for k in range(4):
            cylinder(f"{name}_bar{k}", 0.012, 0.8, (face - side * 0.05, wy - 0.22 + k * 0.15, 2.0), bpy.data.materials["Iron"], verts=6)
    # الطابق العلوي البارز فوق الزقاق، محمول على كوابيل خشبية، وفيه مشربية مضيئة.
    if rng.random() < 0.75:
        bw = width * rng.uniform(0.5, 0.8)
        by = yc + rng.uniform(-(width - bw) / 2, (width - bw) / 2)
        depth = rng.uniform(0.55, 0.8)
        z0, z1 = GROUND_H + 0.3, min(height - 0.4, GROUND_H + 2.6)
        box(name + "_bay", (depth, bw, z1 - z0), (face - side * depth / 2, by, (z0 + z1) / 2), plaster)
        box(name + "_bayfloor", (depth + 0.1, bw + 0.1, 0.12), (face - side * depth / 2, by, z0 - 0.06), wood)
        box(name + "_bayroof", (depth + 0.15, bw + 0.15, 0.1), (face - side * depth / 2, by, z1 + 0.05), wood)
        box(name + "_lattice", (0.03, bw * 0.75, (z1 - z0) * 0.6), (face - side * (depth + 0.005), by, (z0 + z1) / 2 + 0.1), lattice)
        for k in range(3):
            ky = by - bw / 2 + 0.25 + k * (bw - 0.5) / 2
            branch(f"{name}_corbel{k}", (face, ky, z0 - 0.9), (face - side * depth * 0.9, ky, z0 - 0.1), 0.05, wood)
        # ضوء دافئ يخرج من المشربية ويضيء الزقاق.
        bpy.ops.object.light_add(type="AREA", location=(face - side * (depth + 0.05), by, (z0 + z1) / 2))
        light = bpy.context.view_layer.objects.active
        light.name = name + "_baylight"
        light.data.shape = "RECTANGLE"
        light.data.size, light.data.size_y = bw * 0.7, (z1 - z0) * 0.5
        light.data.energy = 3
        light.data.color = (1.0, 0.62, 0.3)
        light.rotation_euler = (0, -side * math.pi / 2, 0)
    # نافذة علوية مضيئة بلون مختلف قليلاً.
    if rng.random() < 0.6:
        wy = yc + rng.uniform(-width / 3, width / 3)
        box(name + "_topwin", (0.04, 0.7, 1.0), (face - side * 0.01, wy, height - 1.4), window)
        # درفتا شباك خشبيتان مفتوحتان على الجدار.
        for s2 in (-1, 1):
            box(f"{name}_shutter{s2}", (0.04, 0.36, 1.05), (face - side * 0.04, wy + s2 * 0.56, height - 1.4), wood)


def sabat(y, plaster, wood, lattice):
    # «الساباط»: غرفة تعبر فوق الزقاق وتصل بين بيتين، من معالم دمشق القديمة.
    depth, z0, z1 = 3.0, 3.7, 6.3
    box("Sabat", (ALLEY_W + 1, depth, z1 - z0), (0, y, (z0 + z1) / 2), plaster)
    for k in range(5):
        box(f"SabatBeam{k}", (ALLEY_W + 0.2, 0.14, 0.16), (0, y - depth / 2 + 0.3 + k * (depth - 0.6) / 4, z0 - 0.08), wood)
    box("SabatWindow", (1.4, 0.03, 1.1), (0, y - depth / 2 - 0.01, (z0 + z1) / 2 + 0.2), lattice)


def jasmine(name, x, y, z_top, leaf, bark, rng):
    # ياسمينة تتدلى من أعلى الجدار: كتلة أوراق كثيفة مع زهور بيضاء صغيرة.
    side = 1 if x > 0 else -1
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(x - side * 0.15, y, z_top - 0.9), segments=16, ring_count=12)
    em = bpy.context.view_layer.objects.active
    em.name = name
    em.scale = (0.35, 1.3, 1.1)
    bpy.ops.object.transform_apply(scale=True)
    scatter_leaves(em, leaf, 5000, 0.07, rng.randint(0, 9999))
    flower = bpy.data.objects.get("JasmineFlower")
    if flower is None:
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.025, location=(0, 0, -100))
        flower = bpy.context.view_layer.objects.active
        flower.name = "JasmineFlower"
        flower.data.materials.append(plain_material("JasminePetal", (0.95, 0.95, 0.9), rough=0.5))
    for k in range(70):
        a, b = rng.uniform(0, 2 * math.pi), rng.uniform(-1, 1)
        instance(flower, f"{name}_flower{k}", (x - side * 0.15 + 0.36 * math.cos(a) * math.sqrt(1 - b * b),
                                                y + 1.3 * b * 0.9, z_top - 0.9 + 1.1 * math.sin(a) * math.sqrt(1 - b * b)))


def rain(scene):
    # مطر بعقد الهندسة (Geometry Nodes): آلاف القطرات بمواقع عشوائية ثابتة، تسقط بسرعة 9 م/ث،
    # وتعود إلى الأعلى عند وصولها للأرض. ارتفاع «صندوق المطر» يقسم مسافة السقوط في الحلقة،
    # فتعود كل قطرة إلى مكانها تماماً في آخر صورة: لا قطع عند التكرار.
    speed = 9.0 / FPS  # متر لكل صورة
    height = speed * FRAMES / 8  # 11.25 متر: كل قطرة تسقطه 8 مرات في الحلقة
    bpy.ops.mesh.primitive_cylinder_add(radius=0.0018, depth=0.28, vertices=6, location=(0, 0, -100))
    drop = bpy.context.view_layer.objects.active
    drop.name = "RainDrop"
    drop.data.materials.append(rain_drop_material())

    ng = bpy.data.node_groups.new("Rain", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    n, link = ng.nodes, ng.links.new
    out = n.new("NodeGroupOutput")
    points = n.new("GeometryNodePoints")
    points.inputs["Count"].default_value = 14000
    rnd = n.new("FunctionNodeRandomValue")
    rnd.data_type = "FLOAT_VECTOR"
    vec_in = [s for s in rnd.inputs if s.enabled and s.type == "VECTOR"]
    vec_in[0].default_value = (-ALLEY_W / 2 - 0.5, 2.5, 0.0)  # لا قطرات ملاصقة للكاميرا
    vec_in[1].default_value = (ALLEY_W / 2 + 0.5, ALLEY_L + 2.0, height)
    rnd_out = next(s for s in rnd.outputs if s.enabled and s.type == "VECTOR")
    link(rnd_out, points.inputs["Position"])
    # z = (z0 - frame * speed) mod height
    pos = n.new("GeometryNodeInputPosition")
    sep = n.new("ShaderNodeSeparateXYZ")
    link(pos.outputs["Position"], sep.inputs["Vector"])
    time = n.new("GeometryNodeInputSceneTime")
    fall = n.new("ShaderNodeMath")
    fall.operation = "MULTIPLY"
    fall.inputs[1].default_value = speed
    link(time.outputs["Frame"], fall.inputs[0])
    sub = n.new("ShaderNodeMath")
    sub.operation = "SUBTRACT"
    link(sep.outputs["Z"], sub.inputs[0])
    link(fall.outputs["Value"], sub.inputs[1])
    wrap = n.new("ShaderNodeMath")
    wrap.operation = "FLOORED_MODULO"
    wrap.inputs[1].default_value = height
    link(sub.outputs["Value"], wrap.inputs[0])
    comb = n.new("ShaderNodeCombineXYZ")
    link(sep.outputs["X"], comb.inputs["X"])
    link(sep.outputs["Y"], comb.inputs["Y"])
    link(wrap.outputs["Value"], comb.inputs["Z"])
    setpos = n.new("GeometryNodeSetPosition")
    link(points.outputs["Points"], setpos.inputs["Geometry"])
    link(comb.outputs["Vector"], setpos.inputs["Position"])
    info = n.new("GeometryNodeObjectInfo")
    info.inputs["Object"].default_value = drop
    info.inputs["As Instance"].default_value = True
    inst = n.new("GeometryNodeInstanceOnPoints")
    link(setpos.outputs["Geometry"], inst.inputs["Points"])
    link(info.outputs["Geometry"], inst.inputs["Instance"])
    link(inst.outputs["Instances"], out.inputs["Geometry"])

    mesh = bpy.data.meshes.new("RainField")
    field = bpy.data.objects.new("RainField", mesh)
    bpy.context.collection.objects.link(field)
    field.modifiers.new("Rain", "NODES").node_group = ng
    return field


# ---------- scene ----------

def build():
    scene = clear_scene()
    scene.frame_start, scene.frame_end = 1, FRAMES
    scene.render.fps = FPS
    rng = random.Random(11)

    plaster = material("plaster", 0.5, lambda: noise_material("Plaster", (0.55, 0.47, 0.37), (0.75, 0.67, 0.54), bump=0.15), tint=(0.78, 0.69, 0.55))
    wood = material("wood", 0.7, lambda: noise_material("Wood", (0.08, 0.04, 0.02), (0.22, 0.12, 0.06), scale=12, rough=0.55))
    door_mat = material("door", 1.0, lambda: noise_material("DoorWood", (0.1, 0.05, 0.025), (0.25, 0.13, 0.06), scale=8, rough=0.5))
    plain_material("Brass", (0.4, 0.26, 0.08), rough=0.3)
    plain_material("Iron", (0.03, 0.03, 0.03), rough=0.4)
    ablaq = ablaq_material()
    # أثر الزمن: جص متقشر يظهر تحته الطين، حجر متسخ رطب من الأسفل، خشب باهت.
    age_material(plaster, (0.32, 0.24, 0.16), patch_amount=0.22)
    age_material(ablaq, (0.12, 0.11, 0.09), patch_amount=0.1, streaks=False)
    age_material(wood, (0.2, 0.19, 0.17), patch_amount=0.25, base_dirt=False)
    age_material(door_mat, (0.22, 0.2, 0.18), patch_amount=0.2, base_dirt=False)
    lattice = mashrabiya_material(wood)
    window = emission_material("WindowGlow", (1.0, 0.55, 0.22), 0.45)
    mats = (ablaq, plaster, wood, door_mat, lattice, window)

    ground = box("Ground", (ALLEY_W + 1.2, ALLEY_L + 8, 0.2), (0, ALLEY_L / 2, -0.1), wet_ground_material())
    # أرض غير مستوية قليلاً، تتجمع الماء في منخفضاتها.
    bpy.context.view_layer.objects.active = ground
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.subdivide(number_cuts=60)
    bpy.ops.object.mode_set(mode="OBJECT")
    gtex = bpy.data.textures.new("GroundWarp", "CLOUDS")
    gtex.noise_scale = 1.2
    gmod = ground.modifiers.new("Uneven", "DISPLACE")
    gmod.texture = gtex
    gmod.texture_coords = "GLOBAL"
    gmod.strength = 0.05
    # قناة تصريف ضحلة في منتصف الزقاق تتجمع فيها مياه المطر.
    box("Gutter", (0.25, ALLEY_L + 8, 0.02), (0, ALLEY_L / 2, 0.001), plain_material("GutterWater", (0.005, 0.006, 0.008), rough=0.02))

    for s in (-1, 1):
        for i, (y0, w, h) in enumerate(facade_segments(rng)):
            house(f"House{'L' if s < 0 else 'R'}{i}", s, y0, w, h, mats, rng)
    sabat(14.0, plaster, wood, lattice)
    # نهاية الزقاق: جدار ببوابة مضيئة يغلق المنظر بدل فراغ أسود.
    box("EndWall", (ALLEY_W + 2, 0.5, 8), (0, ALLEY_L + 2, 4), plaster)
    box("EndGate", (1.6, 0.05, 2.6), (0, ALLEY_L + 1.74, 1.3), door_mat)
    box("EndWindow", (0.8, 0.05, 1.0), (0.6, ALLEY_L + 1.74, 5.2), window)

    leaf = leaf_mesh("JasmineLeaf", 1.0, 0.5, leaf_material("JasmineLeaves", (0.015, 0.06, 0.02), (0.07, 0.18, 0.06)))
    bark = noise_material("Bark", (0.05, 0.035, 0.025), (0.14, 0.1, 0.07), scale=30, rough=0.95, bump=0.8)
    jasmine("JasmineL", -ALLEY_W / 2, 7.0, 6.8, leaf, bark, rng)
    jasmine("JasmineR", ALLEY_W / 2, 20.0, 7.2, leaf, bark, rng)

    metal = bpy.data.materials["Brass"]
    for i, y in enumerate((3.0, 9.0, 17.5, 24.0)):
        s = -1 if i % 2 == 0 else 1
        x = s * (ALLEY_W / 2 - 0.35)
        old_lantern(f"Lamp{i}", (x, y, 3.0), s, bpy.data.materials["Iron"], seed=i + 3)

    # أسلاك كهرباء متدلية تعبر الزقاق، وأخرى تمتد على الجدران.
    cable = plain_material("Cable", (0.01, 0.01, 0.01), rough=0.5)
    for i, y in enumerate((5.0, 11.0, 19.0, 26.0)):
        z = rng.uniform(5.2, 6.4)
        wire(f"WireAcross{i}", (-ALLEY_W / 2, y, z), (ALLEY_W / 2, y + rng.uniform(-1.5, 1.5), z + rng.uniform(-0.3, 0.3)), rng.uniform(0.25, 0.5), cable)
    for s in (-1, 1):
        for k in range(2):
            z = 4.9 + k * 0.15
            wire(f"WireAlong{s}{k}", (s * (ALLEY_W / 2 - 0.05), -2, z), (s * (ALLEY_W / 2 - 0.05), ALLEY_L, z - 0.2), 0.35, cable)
    # أصص ونباتات وأغراض بيت حقيقية (Poly Haven) على جانبي الزقاق، وإلا أصص بسيطة.
    props = (
        ("potted_plant_02", 0.75, (-1, 4.2)), ("planter_pot_clay", 0.45, (1, 8.4)),
        ("wooden_bucket_01", 0.3, (1, 8.95)), ("wooden_stool_01", 0.45, (-1, 11.3)),
        ("potted_plant_02", 0.8, (-1, 15.5)), ("wooden_crate_02", 0.4, (1, 17.0)),
        ("antique_ceramic_vase_01", 0.55, (1, 22.5)), ("potted_plant_02", 0.7, (-1, 25.0)),
    )
    clay = noise_material("Clay", (0.3, 0.12, 0.05), (0.5, 0.22, 0.1), scale=10, rough=0.8)
    for i, (asset, h, (s, y)) in enumerate(props):
        x = s * (ALLEY_W / 2 - 0.3)
        model = ph_model(asset)
        if model:
            place_model(model, f"Prop{i}", (x, y, 0.0), h, rot_z=rng.uniform(0, 6.28))
            continue
        pot = cylinder(f"Pot{i}", 0.18, 0.35, (x, y, 0.17), clay, verts=16)
        bevel(pot, 0.03)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.28, location=(x, y, 0.6), segments=12, ring_count=8)
        bush = bpy.context.view_layer.objects.active
        bush.name = f"PotPlant{i}"
        scatter_leaves(bush, leaf, 900, 0.08, rng.randint(0, 9999))

    # المطر يُضاف لاحقاً فوق الفيديو (rain_post.py) إلا إذا طُلب داخل المشهد.
    if "--blender-rain" in ARGV:
        rain(scene)

    # سماء غائمة داكنة وضباب ماطر يرسم هالة حول كل ضوء.
    world = bpy.data.worlds.new("RainyNight")
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes["Background"].inputs["Color"].default_value = (0.005, 0.009, 0.022, 1)
    nt.nodes["Background"].inputs["Strength"].default_value = 1.0
    fog = nt.nodes.new("ShaderNodeVolumePrincipled")
    fog.inputs["Density"].default_value = 0.012
    fog.inputs["Color"].default_value = (0.6, 0.7, 0.9, 1)
    nt.links.new(fog.outputs["Volume"], nt.nodes["World Output"].inputs["Volume"])
    scene.world = world
    # ضوء قمري بارد خافت خلف الغيوم، يوازن دفء الفوانيس.
    bpy.ops.object.light_add(type="SUN", rotation=(math.radians(35), 0, math.radians(160)))
    sky = bpy.context.view_layer.objects.active
    sky.name = "CloudLight"
    sky.data.energy = 0.18
    sky.data.color = (0.55, 0.65, 1.0)
    sky.data.angle = math.radians(20)

    # كاميرا بارتفاع العين تتقدم ببطء في الزقاق ثم تعود.
    cam_loc = (0.25, 0.5, 1.6)
    bpy.ops.object.camera_add(location=cam_loc, rotation=(math.radians(88), 0, 0))
    cam = bpy.context.view_layer.objects.active
    cam.name = "Camera"
    cam.data.lens = 30
    # عمق ميدان خفيف كعدسة سينمائية: الفانوس الأول واضح والعمق يذوب.
    cam.data.dof.use_dof = True
    cam.data.dof.focus_distance = 5.5
    cam.data.dof.aperture_fstop = 2.8
    scene.camera = cam
    for frame, y in ((1, cam_loc[1]), (FRAMES // 2 + 1, cam_loc[1] + 1.2), (FRAMES + 1, cam_loc[1])):
        cam.location.y = y
        cam.keyframe_insert("location", index=1, frame=frame)
    for fc in fcurves_of(cam.animation_data.action):
        for kp in fc.keyframe_points:
            kp.interpolation = "SINE"
            kp.easing = "EASE_IN_OUT"

    render_settings(scene)
    scene.view_settings.exposure = 0.3
    return scene


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
