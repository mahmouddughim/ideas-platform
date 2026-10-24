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
    brick.inputs["Mortar Size"].default_value = 0.012
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
    nt.links.new(comb.outputs["Vector"], brick.inputs["Vector"])
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
    bsdf.inputs["Roughness"].default_value = 0.35
    bp = nt.nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = 0.35
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
    glow.inputs["Strength"].default_value = 1.8
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
    mat, nt, bsdf = node_mat("RainDrop")
    bsdf.inputs["Base Color"].default_value = (0.8, 0.85, 0.9, 1)
    bsdf.inputs["Roughness"].default_value = 0.05
    bsdf.inputs["Transmission Weight"].default_value = 1.0
    bsdf.inputs["IOR"].default_value = 1.33
    bsdf.inputs["Emission Color"].default_value = (0.7, 0.75, 0.85, 1)
    bsdf.inputs["Emission Strength"].default_value = 0.5  # يكفي ليظهر المطر في الظلام
    return mat


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
    box(name + "_ground", (0.5, width, GROUND_H), (face + side * 0.25, yc, GROUND_H / 2), ablaq)
    box(name + "_upper", (0.5, width, height - GROUND_H), (face + side * 0.25, yc, GROUND_H + (height - GROUND_H) / 2), plaster)
    # سقف خشبي بارز بسيط في الأعلى.
    box(name + "_eave", (0.5, width, 0.1), (face - side * 0.1, yc, height + 0.05), wood)
    # باب خشبي في الطابق الأرضي.
    if rng.random() < 0.7:
        dy = yc + rng.uniform(-width / 4, width / 4)
        box(name + "_doorframe", (0.06, 1.3, 2.35), (face - side * 0.01, dy, 1.17), ablaq)
        box(name + "_door", (0.08, 1.1, 2.2), (face - side * 0.02, dy, 1.1), door_mat)
        for bz in (0.5, 1.7):
            box(f"{name}_band{bz}", (0.02, 1.1, 0.06), (face - side * 0.065, dy, bz), bpy.data.materials["Iron"])
        cylinder(name + "_knocker", 0.05, 0.02, (face - side * 0.07, dy + 0.3, 1.2), bpy.data.materials["Brass"], verts=12, rot=(0, math.pi / 2, 0))
    # نافذة صغيرة بقضبان حديد مضيئة من الداخل.
    if rng.random() < 0.5:
        wy = yc + rng.uniform(-width / 3, width / 3)
        box(name + "_lowwin", (0.04, 0.6, 0.8), (face - side * 0.01, wy, 2.0), window)
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
        light.data.energy = 10
        light.data.color = (1.0, 0.62, 0.3)
        light.rotation_euler = (0, -side * math.pi / 2, 0)
    # نافذة علوية مضيئة بلون مختلف قليلاً.
    if rng.random() < 0.6:
        wy = yc + rng.uniform(-width / 3, width / 3)
        box(name + "_topwin", (0.04, 0.7, 1.0), (face - side * 0.01, wy, height - 1.4), window)


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
    # جزيئات مطر تسقط بسرعة ثابتة من سطح فوق الزقاق، وتبدو خطوطاً بفضل ضبابية الحركة.
    bpy.ops.mesh.primitive_cylinder_add(radius=0.005, depth=0.2, vertices=6, location=(0, 0, -100))
    drop = bpy.context.view_layer.objects.active
    drop.name = "RainDrop"
    drop.data.materials.append(rain_drop_material())
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, ALLEY_L / 2 - 4, 10))
    emitter = bpy.context.view_layer.objects.active
    emitter.name = "RainCloud"
    emitter.scale = (ALLEY_W + 3, ALLEY_L, 1)
    bpy.ops.object.transform_apply(scale=True)
    mod = emitter.modifiers.new("Rain", "PARTICLE_SYSTEM")
    ps = mod.particle_system.settings
    ps.type = "EMITTER"
    ps.count = 70000
    ps.frame_start = -40  # يبدأ قبل أول صورة فيكون المطر ممتلئاً من البداية
    ps.frame_end = FRAMES + 1
    ps.lifetime = 30
    ps.emit_from = "FACE"
    ps.normal_factor = -9.0  # 9 متر/ثانية نحو الأسفل
    ps.factor_random = 0.4
    ps.effector_weights.gravity = 0.0
    ps.render_type = "OBJECT"
    ps.instance_object = drop
    ps.particle_size = 1.0
    ps.size_random = 0.4
    ps.use_rotations = True
    ps.rotation_mode = "VEL"
    ps.display_percentage = 5
    emitter.show_instancer_for_render = False
    scene.render.use_motion_blur = True
    scene.render.motion_blur_shutter = 0.5
    # نحسب المطر من بدايته حتى أول صورة، فيكون ممتلئاً عند الضغط على F12 مباشرة.
    for f in range(int(ps.frame_start), 2):
        scene.frame_set(f)
    return emitter


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
    lattice = mashrabiya_material(wood)
    window = emission_material("WindowGlow", (1.0, 0.58, 0.25), 1.2)
    mats = (ablaq, plaster, wood, door_mat, lattice, window)

    ground = box("Ground", (ALLEY_W + 1.2, ALLEY_L + 8, 0.2), (0, ALLEY_L / 2, -0.1), wet_ground_material())
    # قناة تصريف ضحلة في منتصف الزقاق تتجمع فيها مياه المطر.
    box("Gutter", (0.25, ALLEY_L + 8, 0.02), (0, ALLEY_L / 2, 0.001), plain_material("GutterWater", (0.005, 0.006, 0.008), rough=0.02))

    for s in (-1, 1):
        for i, (y0, w, h) in enumerate(facade_segments(rng)):
            house(f"House{'L' if s < 0 else 'R'}{i}", s, y0, w, h, mats, rng)
    sabat(14.0, plaster, wood, lattice)
    # نهاية الزقاق: جدار ببوابة مضيئة يغلق المنظر بدل فراغ أسود.
    box("EndWall", (ALLEY_W + 2, 0.5, 8), (0, ALLEY_L + 2, 4), plaster)
    box("EndGate", (1.6, 0.05, 2.6), (0, ALLEY_L + 1.74, 1.3), window)

    leaf = leaf_mesh("JasmineLeaf", 1.0, 0.5, leaf_material("JasmineLeaves", (0.015, 0.06, 0.02), (0.07, 0.18, 0.06)))
    bark = noise_material("Bark", (0.05, 0.035, 0.025), (0.14, 0.1, 0.07), scale=30, rough=0.95, bump=0.8)
    jasmine("JasmineL", -ALLEY_W / 2, 7.0, 6.8, leaf, bark, rng)
    jasmine("JasmineR", ALLEY_W / 2, 20.0, 7.2, leaf, bark, rng)

    metal = bpy.data.materials["Brass"]
    for i, y in enumerate((3.0, 9.0, 17.5, 24.0)):
        s = -1 if i % 2 == 0 else 1
        x = s * (ALLEY_W / 2 - 0.35)
        box(f"LampArm{i}", (0.4, 0.04, 0.04), (s * (ALLEY_W / 2 - 0.18), y, 3.55), bpy.data.materials["Iron"])
        lantern(f"Lamp{i}", (x, y, 3.2), metal, seed=i + 3)

    rain(scene)

    # سماء غائمة داكنة وضباب ماطر يرسم هالة حول كل ضوء.
    world = bpy.data.worlds.new("RainyNight")
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes["Background"].inputs["Color"].default_value = (0.02, 0.03, 0.055, 1)
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
    sky.data.energy = 0.25
    sky.data.color = (0.55, 0.65, 1.0)
    sky.data.angle = math.radians(20)

    # كاميرا بارتفاع العين تتقدم ببطء في الزقاق ثم تعود.
    cam_loc = (0.25, 0.5, 1.6)
    bpy.ops.object.camera_add(location=cam_loc, rotation=(math.radians(88), 0, 0))
    cam = bpy.context.view_layer.objects.active
    cam.name = "Camera"
    cam.data.lens = 24
    scene.camera = cam
    for frame, y in ((1, cam_loc[1]), (FRAMES // 2 + 1, cam_loc[1] + 1.2), (FRAMES + 1, cam_loc[1])):
        cam.location.y = y
        cam.keyframe_insert("location", index=1, frame=frame)
    for fc in fcurves_of(cam.animation_data.action):
        for kp in fc.keyframe_points:
            kp.interpolation = "SINE"
            kp.easing = "EASE_IN_OUT"

    render_settings(scene)
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
