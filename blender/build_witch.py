"""Build the rigged anime witch character in Blender.

Run with Blender 4.2+ / 5.x:
    blender --background --python blender/build_witch.py
or with the `bpy` Python module:
    python blender/build_witch.py

Outputs (next to this script):
    witch_character.blend      the rigged, posed and animated character
    textures/face.png          the painted face texture (also packed in the .blend)
    renders/*.png              hero render and front/side/back turnaround

Everything is generated procedurally: the body, clothes and props are built
from lofted tubes and ellipsoids, the hair from tapered curves, and the face
is painted into a texture with Pillow. The armature is weighted by distance
to each bone. Hair tails and chest use spring physics that is simulated here
and baked into the idle animation, so it plays back in any software.
"""

import math
import os
import sys

import bpy  # noqa: I001  (bpy must be imported before bmesh)
import bmesh
from mathutils import Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
TEX_DIR = os.path.join(HERE, "textures")
RENDER_DIR = os.path.join(HERE, "renders")
QUICK = "--quick" in sys.argv
FPS = 24
FRAMES = 96

# ---------------------------------------------------------------------------
# Palette (sRGB hex, sampled from the reference sheet)
# ---------------------------------------------------------------------------
COL = {
    "skin": ("#efd3cd", "#d4a5a3"),
    "hair": ("#b85d6b", "#8a3d4f", "#d98a93"),
    "jacket": ("#22363a", "#142224", "#35505a"),
    "panel": ("#a98aa9", "#7c6283"),
    "sleeve": ("#e8b7cd", "#c88fad"),
    "shorts": ("#527779", "#3b5a5c"),
    "sock": ("#efe6e6", "#cdbfc5"),
    "boot": ("#24373a", "#162427"),
    "bootcuff": ("#4d7072", "#36565a"),
    "ribbon": ("#162021", "#0c1314"),
    "gem": ("#ef7f97", "#c25570"),
    "staff": ("#efede8", "#c4c0bb"),
    "gold": ("#e8b93a", "#b98c1f"),
    "line": ("#141414", "#141414"),
    "navel": ("#c48a8a", "#c48a8a"),
}
BG = "#596262"
OUTLINE = "#1d1416"
LIGHT = Vector((-0.45, -0.6, 0.66)).normalized()

# Body landmarks (meters, Z up, character faces -Y; +X is her left side).
HEAD_C = Vector((0.0, 0.008, 1.65))
HEAD_R = Vector((0.087, 0.097, 0.104))
SHOULDER = Vector((0.15, 0.0, 1.385))
ELBOW = Vector((0.31, 0.0, 1.17))
WRIST = Vector((0.45, -0.01, 0.99))
HIP = Vector((0.085, 0.0, 0.92))
KNEE = Vector((0.078, -0.005, 0.50))
ANKLE = Vector((0.072, 0.01, 0.085))
STAFF_REST = Vector((-0.62, -0.05, 0.0))


def mirror(v, s):
    return Vector((v.x * s, v.y, v.z))


# ---------------------------------------------------------------------------
# Scene and materials
# ---------------------------------------------------------------------------
def lin(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def rgba(h):
    return (*lin(h), 1.0)


def sock(sockets, ident):
    for s in sockets:
        if s.identifier == ident:
            return s
    raise KeyError(ident)


MATS = {}


def toon(name, base, shade, hi=None, thresh=0.0, alpha=1.0, image=None):
    """Cel-shaded material: two (or three) flat tones picked by N·L.

    It is emission-only, so it renders identically in Cycles and EEVEE and
    needs no lights. The light direction is baked into the node tree.
    """
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    m["base_color"] = base
    nt = m.node_tree
    nt.nodes.clear()
    N = nt.nodes.new
    L = nt.links.new
    out = N("ShaderNodeOutputMaterial")
    geo = N("ShaderNodeNewGeometry")
    dot = N("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = LIGHT
    L(geo.outputs["Normal"], dot.inputs[0])
    remap = N("ShaderNodeMath")
    remap.operation = "MULTIPLY_ADD"
    remap.inputs[1].default_value = 0.5
    remap.inputs[2].default_value = 0.5
    L(dot.outputs["Value"], remap.inputs[0])
    ramp = N("ShaderNodeValToRGB")
    cr = ramp.color_ramp
    cr.interpolation = "CONSTANT"
    cr.elements[0].position = 0.0
    cr.elements[0].color = rgba(shade)
    cr.elements[1].position = thresh * 0.5 + 0.5
    cr.elements[1].color = rgba(base)
    if hi:
        e = cr.elements.new(0.93)
        e.color = rgba(hi)
    L(remap.outputs["Value"], ramp.inputs["Fac"])
    color = ramp.outputs["Color"]
    if image is not None:
        tex = N("ShaderNodeTexImage")
        tex.image = image
        tex.interpolation = "Cubic"
        mix = N("ShaderNodeMix")
        mix.data_type = "RGBA"
        L(tex.outputs["Alpha"], sock(mix.inputs, "Factor_Float"))
        L(color, sock(mix.inputs, "A_Color"))
        L(tex.outputs["Color"], sock(mix.inputs, "B_Color"))
        color = sock(mix.outputs, "Result_Color")
    em = N("ShaderNodeEmission")
    L(color, em.inputs["Color"])
    shader = em.outputs[0]
    if alpha < 1.0:
        tr = N("ShaderNodeBsdfTransparent")
        ms = N("ShaderNodeMixShader")
        ms.inputs[0].default_value = alpha
        L(tr.outputs[0], ms.inputs[1])
        L(shader, ms.inputs[2])
        shader = ms.outputs[0]
        try:
            m.surface_render_method = "BLENDED"
        except Exception:
            pass
    L(shader, out.inputs["Surface"])
    m.diffuse_color = rgba(base)
    MATS[name] = m
    return m


def outline_material():
    """Inverted-hull outline drawn from a slightly larger, flipped shell."""
    m = bpy.data.materials.new("Outline")
    try:
        m.use_nodes = True
    except Exception:
        pass
    m.use_backface_culling = True
    nt = m.node_tree
    nt.nodes.clear()
    N = nt.nodes.new
    out = N("ShaderNodeOutputMaterial")
    geo = N("ShaderNodeNewGeometry")
    tr = N("ShaderNodeBsdfTransparent")
    em = N("ShaderNodeEmission")
    em.inputs["Color"].default_value = rgba(OUTLINE)
    ms = N("ShaderNodeMixShader")
    nt.links.new(geo.outputs["Backfacing"], ms.inputs[0])
    # The shell's near side faces away from the camera and must vanish; only
    # its far side, peeking out around the silhouette, is drawn dark.
    nt.links.new(em.outputs[0], ms.inputs[1])
    nt.links.new(tr.outputs[0], ms.inputs[2])
    nt.links.new(ms.outputs[0], out.inputs["Surface"])
    m.diffuse_color = rgba(OUTLINE)
    return m


def build_materials(face_image):
    for k, v in COL.items():
        base, shade = v[0], v[1]
        hi = v[2] if len(v) > 2 else None
        toon(k, base, shade, hi, thresh=-0.05)
    toon("face", COL["skin"][0], COL["skin"][1], thresh=-0.45, image=face_image)
    toon("sleeve_glass", COL["sleeve"][0], COL["sleeve"][1], thresh=-0.1, alpha=0.62)
    toon("ribbon_glass", "#f0b6d2", "#d48cb3", alpha=0.45)
    MATS["outline"] = outline_material()


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
COLLECTIONS = {}


def collection(name):
    if name not in COLLECTIONS:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
        COLLECTIONS[name] = c
    return COLLECTIONS[name]


PARTS = []  # (object, allowed bones or a single bone name, outline thickness)


def make_obj(name, bm, mats, coll="Character", bones=None, outline=0.0035):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces) if all(e.is_manifold for e in bm.edges) else None
    for f in bm.faces:
        f.smooth = True
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(MATS[m])
    ob = bpy.data.objects.new(name, me)
    collection(coll).objects.link(ob)
    PARTS.append((ob, bones, outline))
    return ob


def catmull(p0, p1, p2, p3, s):
    s2, s3 = s * s, s * s * s
    return 0.5 * ((2 * p1) + (-p0 + p2) * s + (2 * p0 - 5 * p1 + 4 * p2 - p3) * s2 + (-p0 + 3 * p1 - 3 * p2 + p3) * s3)


class Path:
    """Smooth path through key points, each with an elliptical radius."""

    def __init__(self, keys):
        self.P = [Vector(k[0]) for k in keys]
        self.rx = [k[1] for k in keys]
        self.ry = [k[2] if len(k) > 2 else k[1] for k in keys]
        L = [0.0]
        for i in range(1, len(self.P)):
            L.append(L[-1] + (self.P[i] - self.P[i - 1]).length)
        self.u = [l / L[-1] for l in L]
        self.length = L[-1]

    def _seg(self, t):
        t = min(max(t, 0.0), 1.0)
        n = len(self.P)
        for i in range(n - 1):
            if t <= self.u[i + 1] or i == n - 2:
                s = (t - self.u[i]) / max(self.u[i + 1] - self.u[i], 1e-9)
                return i, min(max(s, 0.0), 1.0)

    def _interp(self, arr, t):
        i, s = self._seg(t)
        n = len(arr)
        a = arr[max(i - 1, 0)]
        b = arr[i]
        c = arr[i + 1]
        d = arr[min(i + 2, n - 1)]
        if i == 0:
            a = b - (c - b) if isinstance(b, Vector) else b
        if i + 2 > n - 1:
            d = c + (c - b) if isinstance(c, Vector) else c
        return catmull(a, b, c, d, s)

    def at(self, t):
        return self._interp(self.P, t)

    def radius(self, t):
        return max(self._interp(self.rx, t), 0.0005), max(self._interp(self.ry, t), 0.0005)

    def tangent(self, t):
        e = 0.002
        d = self.at(min(t + e, 1)) - self.at(max(t - e, 0))
        return d.normalized()

    def t_at_z(self, z):
        lo, hi = 0.0, 1.0
        rising = self.at(1).z > self.at(0).z
        for _ in range(40):
            mid = (lo + hi) / 2
            if (self.at(mid).z < z) == rising:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2


def frame(tan):
    ref = Vector((1, 0, 0))
    if abs(tan.dot(ref)) > 0.95:
        ref = Vector((0, -1, 0))
    n1 = (ref - tan * ref.dot(tan)).normalized()
    n2 = tan.cross(n1)
    return n1, n2


def tube(bm, path, t0, t1, add=0.0, segs=28, rings=None, cap0=False, cap1=False, mat=0):
    """Loft an elliptical tube along `path` between params t0..t1.

    `add` thickens the tube (for clothing shells) and may be a function of
    the local parameter s in 0..1.
    """
    if rings is None:
        rings = max(4, int(abs(t1 - t0) * path.length / 0.012))
    rows = []
    for k in range(rings):
        s = k / (rings - 1)
        t = t0 + (t1 - t0) * s
        c = path.at(t)
        n1, n2 = frame(path.tangent(t))
        rx, ry = path.radius(t)
        a = add(s) if callable(add) else add
        row = []
        for j in range(segs):
            ang = 2 * math.pi * j / segs
            row.append(bm.verts.new(c + n1 * math.cos(ang) * (rx + a) + n2 * math.sin(ang) * (ry + a)))
        rows.append(row)
    faces = []
    for k in range(rings - 1):
        A, B = rows[k], rows[k + 1]
        for j in range(segs):
            f = bm.faces.new((A[j], A[(j + 1) % segs], B[(j + 1) % segs], B[j]))
            f.material_index = mat
            faces.append(f)
    if t1 < t0:
        for f in faces:
            f.normal_flip()
    for cap, row, flip in ((cap0, rows[0], True), (cap1, rows[-1], False)):
        if cap:
            ctr = bm.verts.new(sum((v.co for v in row), Vector()) / len(row))
            for j in range(segs):
                tri = (row[j], row[(j + 1) % segs], ctr)
                f = bm.faces.new(tri[::-1] if flip != (t1 < t0) else tri)
                f.material_index = mat
    return rows


def ellipsoid(bm, center, radii, rot=None, segs=28, rings=16, mat=0):
    M = Matrix.Translation(Vector(center))
    if rot is not None:
        M = M @ rot.to_matrix().to_4x4()
    M = M @ Matrix.Diagonal((*radii, 1.0))
    res = bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=1.0, matrix=M)
    for v in res["verts"]:
        for f in v.link_faces:
            f.material_index = mat
    return res["verts"]


def cone(bm, base, direction, r1, r2, depth, segs=16, flat=1.0, mat=0):
    d = Vector(direction).normalized()
    rot = Vector((0, 0, 1)).rotation_difference(d)
    M = Matrix.Translation(Vector(base) + d * depth / 2) @ rot.to_matrix().to_4x4() @ Matrix.Diagonal((1, flat, 1, 1))
    res = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segs, radius1=r1, radius2=r2, depth=depth, matrix=M)
    for v in res["verts"]:
        for f in v.link_faces:
            f.material_index = mat
    return res["verts"]


def new_bm():
    return bmesh.new()


# ---------------------------------------------------------------------------
# Body
# ---------------------------------------------------------------------------
TORSO = Path([
    ((0, 0.0, 0.80), 0.105, 0.075),
    ((0, 0.012, 0.86), 0.148, 0.098),
    ((0, 0.012, 0.93), 0.150, 0.098),
    ((0, 0.006, 1.00), 0.128, 0.087),
    ((0, 0.0, 1.07), 0.106, 0.077),
    ((0, 0.0, 1.14), 0.116, 0.080),
    ((0, 0.0, 1.22), 0.128, 0.085),
    ((0, 0.004, 1.30), 0.137, 0.087),
    ((0, 0.006, 1.365), 0.142, 0.080),
    ((0, 0.006, 1.41), 0.105, 0.064),
    ((0, 0.004, 1.445), 0.050, 0.046),
])
NECK = Path([((0, 0.002, 1.40), 0.041), ((0, 0.004, 1.48), 0.038), ((0, 0.008, 1.57), 0.036)])


def leg_path(s):
    h, k, a = mirror(HIP, s), mirror(KNEE, s), mirror(ANKLE, s)
    return Path([
        (h, 0.086, 0.088),
        (h.lerp(k, 0.25) + Vector((0, -0.004, 0)), 0.080, 0.082),
        (h.lerp(k, 0.55), 0.068, 0.070),
        (h.lerp(k, 0.82), 0.054, 0.056),
        (k, 0.046, 0.049),
        (k.lerp(a, 0.22) + Vector((0, 0.008, 0)), 0.050, 0.054),
        (k.lerp(a, 0.45) + Vector((0, 0.006, 0)), 0.046, 0.048),
        (k.lerp(a, 0.75), 0.034, 0.036),
        (a, 0.028, 0.031),
    ])


def arm_path(s):
    sh, el, wr = mirror(SHOULDER, s), mirror(ELBOW, s), mirror(WRIST, s)
    return Path([
        (sh, 0.047, 0.045),
        (sh.lerp(el, 0.45), 0.041, 0.040),
        (el, 0.033, 0.032),
        (el.lerp(wr, 0.35), 0.035, 0.031),
        (wr, 0.024, 0.019),
    ])


def head_deform(u):
    ux, uy, uz = u
    if uz < 0:
        f = -uz
        ux *= 1 - 0.30 * f ** 1.5
        uy *= 1 - 0.12 * f
        uz *= 1 + 0.02 * f
    if uy < 0:
        uy *= 0.92
    elif uz > -0.3:
        uy *= 1.06
    return Vector((ux, uy, uz))


def head_point(u, scale=1.0):
    d = head_deform(u)
    return HEAD_C + Vector((d.x * HEAD_R.x, d.y * HEAD_R.y, d.z * HEAD_R.z)) * scale


def shell(theta, phi, scale=1.0):
    th, ph = math.radians(theta), math.radians(phi)
    u = Vector((math.sin(th) * math.cos(ph), -math.cos(th) * math.cos(ph), math.sin(ph)))
    return head_point(u, scale)


def build_body():
    bm = new_bm()
    tube(bm, TORSO, 0, 1, cap0=True)
    tube(bm, NECK, 0, 1)
    for s in (-1, 1):
        tube(bm, leg_path(s), 0, 1, cap1=True)
        tube(bm, arm_path(s), 0, 1, cap1=True)
    make_obj("Body", bm, ["skin"], bones="body")

    bm = new_bm()
    ellipsoid(bm, (0, -0.0765, 1.062), (0.005, 0.003, 0.009), segs=12, rings=8)
    make_obj("Navel", bm, ["navel"], bones="spine", outline=0)

    # Head: an ellipsoid with a tapered jaw, UV-projected from the front for the face.
    bm = new_bm()
    res = bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=32, radius=1.0)
    for v in res["verts"]:
        v.co = head_point(v.co.normalized())
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for l in f.loops:
            p = l.vert.co - HEAD_C
            if p.y < -0.015:
                l[uv].uv = (p.x * 5.2632 + 0.5, (p.z + 0.12) * 5.0)
            else:
                l[uv].uv = (0.002, 0.002)
    make_obj("Head", bm, ["face"], bones="head")

    for s in (-1, 1):
        bm = new_bm()
        ellipsoid(bm, HEAD_C + Vector((s * 0.084, 0.016, -0.012)), (0.012, 0.019, 0.025), segs=16, rings=10)
        make_obj("Ear" + (".L" if s > 0 else ".R"), bm, ["skin"], bones="head")

    # Hands: open hand on the hip side, a fist for the staff.
    for s in (-1, 1):
        ap = arm_path(s)
        w = ap.at(1)
        z = ap.tangent(1)
        x = (Vector((1, 0, 0)) - z * z.x).normalized()
        y = z.cross(x)
        R = Matrix((x, y, z)).transposed().to_4x4()
        palm_side = -x * s
        bm = new_bm()

        def part(off, radii, tilt=0.0):
            M = Matrix.Translation(w + R.to_3x3() @ Vector(off)) @ R @ Matrix.Rotation(tilt, 4, "X") @ Matrix.Diagonal((*radii, 1))
            bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=1.0, matrix=M)

        part((0, 0, 0.045), (0.017, 0.037, 0.05))
        if s < 0:  # fist around the staff
            part((-s * 0.012 * 0, 0, 0.088), (0.03, 0.04, 0.034))
            part((0.0, -0.035, 0.06), (0.012, 0.012, 0.03), tilt=0.5)
        else:
            part((0, 0.004, 0.115), (0.013, 0.034, 0.05))
            part((0.0, -0.036, 0.055), (0.011, 0.011, 0.034), tilt=0.45)
        del palm_side
        make_obj("Glove.Hand" + (".L" if s > 0 else ".R"), bm, ["jacket"], bones="hand" + (".L" if s > 0 else ".R"))


# ---------------------------------------------------------------------------
# Clothing
# ---------------------------------------------------------------------------
def build_clothes():
    T = TORSO
    # Cropped jacket: dark front, lavender side panels.
    bm = new_bm()
    tube(bm, T, T.t_at_z(1.150), T.t_at_z(1.44), add=lambda s: 0.010 - 0.004 * s)
    for f in bm.faces:
        c = f.calc_center_median()
        if abs(c.x) > 0.098 and c.y > -0.055:
            f.material_index = 1
    tube(bm, T, T.t_at_z(1.146), T.t_at_z(1.175), add=0.016, mat=0)
    make_obj("Jacket", bm, ["jacket", "panel"], bones="torso_upper")

    for s in (-1, 1):
        bm = new_bm()
        rot = Quaternion((0, 0, 1), s * math.radians(-14)) @ Quaternion((1, 0, 0), math.radians(8))
        ellipsoid(bm, (s * 0.063, -0.058, 1.275), (0.066, 0.064, 0.062), rot=rot)
        make_obj("Bust" + (".L" if s > 0 else ".R"), bm, ["jacket"], bones="breast" + (".L" if s > 0 else ".R"))

    # High collar, open at the front.
    collar = Path([((0, 0.002, 1.405), 0.064, 0.060), ((0, 0.004, 1.47), 0.056, 0.054), ((0, 0.008, 1.545), 0.062, 0.060)])
    bm = new_bm()
    tube(bm, collar, 0, 1, segs=32, rings=10)
    make_obj("Collar", bm, ["jacket"], bones="neck")

    # Ribbon tie and the pink gem at the collar.
    bm = new_bm()
    for s in (-1, 1):
        rib = Path([((s * 0.004, -0.062, 1.425), 0.012, 0.003), ((s * 0.018, -0.105, 1.36), 0.018, 0.003),
                    ((s * 0.026, -0.128, 1.29), 0.020, 0.003), ((s * 0.036, -0.122, 1.21), 0.016, 0.003)])
        tube(bm, rib, 0, 1, segs=10, rings=16, cap1=True)
        lp = Path([((0, -0.063, 1.42), 0.006, 0.006), ((s * 0.03, -0.075, 1.43), 0.016, 0.006), ((s * 0.05, -0.07, 1.415), 0.004, 0.004)])
        tube(bm, lp, 0, 1, segs=10, rings=10, cap1=True)
    ellipsoid(bm, (0, -0.065, 1.42), (0.011, 0.008, 0.010))
    make_obj("Ribbon", bm, ["ribbon"], bones="chest", outline=0.0015)
    bm = new_bm()
    cone(bm, (0, -0.064, 1.452), (0, -0.25, -1), 0.016, 0.0, 0.034, segs=4, flat=0.6)
    make_obj("Gem", bm, ["gem"], bones="neck", outline=0.002)

    for s in (-1, 1):
        side = ".L" if s > 0 else ".R"
        ap = arm_path(s)
        te = ap.u[2]
        # Puffed translucent sleeve, dark cuff at the elbow, gold charms.
        bm = new_bm()
        tube(bm, ap, 0.0, te * 0.8, add=lambda q: 0.012 + 0.02 * math.sin(math.pi * min(q * 1.1, 1.0)))
        make_obj("Sleeve" + side, bm, ["sleeve_glass"], bones="upper_arm" + side, outline=0.0025)
        bm = new_bm()
        tube(bm, ap, te * 0.74, te * 0.98, add=0.022, cap0=False)
        make_obj("SleeveCuff" + side, bm, ["jacket"], bones="upper_arm" + side)
        if s > 0:
            bm = new_bm()
            for k, off in enumerate((0.0, 0.025, -0.022)):
                c = ap.at(te * 0.7 - 0.03 * k) + Vector((0.0, -0.058, off * 0.4))
                cone(bm, c, (0, -1, 0), 0.008, 0.008, 0.004, segs=5)
            make_obj("SleeveCharms", bm, ["gold"], bones="upper_arm.L", outline=0.0015)
        # Glove sleeve with a wide cuff.
        bm = new_bm()
        tube(bm, ap, te + (1 - te) * 0.18, 1.0, add=0.006)
        tube(bm, ap, te + (1 - te) * 0.12, te + (1 - te) * 0.36, add=0.019, cap0=False)
        make_obj("Glove" + side, bm, ["jacket"], bones="forearm" + side)

    # Shorts with waistband, plus the dark thigh garters.
    bm = new_bm()
    tube(bm, T, T.t_at_z(0.80), T.t_at_z(1.035), add=0.009, cap0=True)
    for s in (-1, 1):
        lp = leg_path(s)
        tube(bm, lp, lp.t_at_z(0.93), lp.t_at_z(0.775), add=0.013)
    make_obj("Shorts", bm, ["shorts"], bones="torso_lower")
    bm = new_bm()
    tube(bm, T, T.t_at_z(1.012), T.t_at_z(1.042), add=0.015)
    for s in (-1, 1):
        lp = leg_path(s)
        tube(bm, lp, lp.t_at_z(0.795), lp.t_at_z(0.775), add=0.017)
    make_obj("Waistband", bm, ["jacket"], bones="torso_lower")
    for s in (-1, 1):
        lp = leg_path(s)
        side = ".L" if s > 0 else ".R"
        bm = new_bm()
        tube(bm, lp, lp.t_at_z(0.745), lp.t_at_z(0.718), add=0.006, segs=32)
        # Triangle cut-out notches along the garter.
        for j in range(8):
            ang = 2 * math.pi * j / 8 + 0.2
            t = lp.t_at_z(0.735)
            c = lp.at(t)
            n1, n2 = frame(lp.tangent(t))
            rx, ry = lp.radius(t)
            p = c + n1 * math.cos(ang) * (rx + 0.0075) + n2 * math.sin(ang) * (ry + 0.0075)
            nrm = (n1 * math.cos(ang) + n2 * math.sin(ang)).normalized()
            cone(bm, p + Vector((0, 0, -0.006)), Vector((0, 0, 1)), 0.008, 0.0, 0.013, segs=3, flat=0.3,
                 mat=1)
            del nrm
        make_obj("Garter" + side, bm, ["jacket", "skin"], bones="thigh" + side, outline=0.002)

        # Socks: thigh-high on her left, short on her right.
        bm = new_bm()
        top = 0.665 if s > 0 else 0.40
        tube(bm, lp, lp.t_at_z(top), lp.t_at_z(0.09), add=0.0035)
        make_obj("Sock" + side, bm, ["sock"], bones="leg" + side)

        # Boots: shaft, folded cuff, ankle strap, foot and sole.
        bm = new_bm()
        tube(bm, lp, lp.t_at_z(0.30), lp.t_at_z(0.06), add=lambda q: 0.016 + 0.004 * q)
        tube(bm, lp, lp.t_at_z(0.125), lp.t_at_z(0.10), add=0.026, mat=0)
        a = mirror(ANKLE, s)
        foot_c = Vector((a.x + s * 0.004, -0.045, 0.05))
        vs = ellipsoid(bm, foot_c, (0.05, 0.12, 0.055))
        for v in vs:
            v.co.z = max(v.co.z, 0.018)
        make_obj("Boot" + side, bm, ["boot"], bones="leg" + side)
        bm = new_bm()
        tube(bm, lp, lp.t_at_z(0.335), lp.t_at_z(0.262), add=lambda q: 0.03 - 0.006 * q)
        make_obj("BootCuff" + side, bm, ["bootcuff"], bones="leg" + side)
        bm = new_bm()
        vs = ellipsoid(bm, (foot_c.x, foot_c.y - 0.004, 0.012), (0.054, 0.126, 0.016), segs=24, rings=10)
        make_obj("Sole" + side, bm, ["ribbon"], bones="foot" + side, outline=0.002)


# ---------------------------------------------------------------------------
# Hair
# ---------------------------------------------------------------------------
TAIL_KEYS = {}


def curve_obj(name, strands, width, coll="Hair"):
    """strands: list of point lists (Vector) with per-point radius factors."""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = width
    cu.bevel_resolution = 3
    cu.use_fill_caps = True
    for pts in strands:
        sp = cu.splines.new("POLY")
        sp.points.add(len(pts) - 1)
        for p, (co, r) in zip(sp.points, pts):
            p.co = (*co, 1.0)
            p.radius = r
    ob = bpy.data.objects.new(name + "_curve", cu)
    collection(coll).objects.link(ob)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    bpy.data.objects.remove(ob)
    bpy.data.curves.remove(cu)
    for p in me.polygons:
        p.use_smooth = True
    me.materials.append(MATS["hair"])
    mo = bpy.data.objects.new(name, me)
    collection(coll).objects.link(mo)
    return mo


def lock(t0, p0, t1, p1, s0=1.11, s1=1.075, n=14, bow=0.035):
    pts = []
    for i in range(n):
        s = i / (n - 1)
        e = s ** 0.85
        th = t0 + (t1 - t0) * e
        ph = p0 + (p1 - p0) * s
        sc = s0 + (s1 - s0) * s + bow * math.sin(math.pi * s)
        pts.append((shell(th, ph, sc), 1 - 0.88 * s ** 1.3))
    return pts


def build_hair():
    # Cap: head shape scaled up, with the face window cut out.
    bm = new_bm()
    res = bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=32, radius=1.0)
    kill = []
    for v in res["verts"]:
        u = v.co.normalized()
        if (u.y < -0.18 and u.z < 0.40 and abs(u.x) < 0.84) or (u.z < -0.42 and u.y < 0.4) or u.z < -0.72:
            kill.append(v)
        v.co = head_point(u, 1.075)
    bmesh.ops.delete(bm, geom=kill, context="VERTS")
    make_obj("HairCap", bm, ["hair"], bones="head", coll="Hair", outline=0.003)

    # Side-parted bangs sweeping toward her left, plus face-framing locks.
    bangs = [
        (-20, 64, -48, 6, 0.017), (-26, 60, -64, -14, 0.016), (-14, 67, 6, 14, 0.019),
        (-8, 69, 24, 10, 0.020), (-2, 69, 42, 3, 0.020), (6, 67, 58, -10, 0.019),
        (-12, 66, -16, 12, 0.017), (12, 64, 70, -24, 0.017),
    ]
    strands, widths = [], []
    for th0, ph0, th1, ph1, w in bangs:
        strands.append(lock(th0, ph0, th1, ph1))
        widths.append(w)
    for s in (-1, 1):
        strands.append(lock(s * 56, 46, s * 72, -64, s0=1.10, s1=1.06, n=16, bow=0.02))
        strands.append(lock(s * 68, 40, s * 86, -44, s0=1.09, s1=1.06, n=14, bow=0.015))
        widths += [0.016, 0.014]
    # One curve per width class keeps this simple: scale radii to a shared bevel.
    pts = [[(c, r * w / 0.02) for c, r in st] for st, w in zip(strands, widths)]
    curve_obj("HairBangs", pts, 0.02)
    PARTS.append((bpy.data.objects["HairBangs"], "head", 0.0025))

    # Twin high ponytails: bundles of wavy strands around a centerline.
    for s in (-1, 1):
        side = ".L" if s > 0 else ".R"
        root = shell(s * 128, 46, 1.0)
        keys = [root, root + Vector((s * 0.05, 0.035, 0.06)), Vector((s * 0.15, 0.115, 1.80)),
                Vector((s * 0.19, 0.155, 1.62)), Vector((s * 0.195, 0.175, 1.42)), Vector((s * 0.185, 0.175, 1.22)),
                Vector((s * 0.17, 0.165, 1.04)), Vector((s * 0.15, 0.15, 0.88))]
        cl = Path([(k, 0.02) for k in keys])
        TAIL_KEYS[s] = [cl.at(i / 7) for i in range(8)]
        strands = []
        for i in range(8):
            a0 = 2 * math.pi * i / 8
            pts = []
            n = 46
            for k in range(n):
                t = k / (n - 1)
                c = cl.at(t)
                n1, n2 = frame(cl.tangent(t))
                spread = 0.006 + 0.03 * math.sin(math.pi * min(t * 1.6, 1.0)) * (1 - 0.45 * t)
                wave = 0.026 * max(0.0, min(1.0, (t - 0.25) / 0.3)) * (1 - 0.3 * t)
                ang = a0 + 0.9 * t
                ph = 2 * math.pi * 3.2 * t + i * 0.8
                off = (n1 * math.cos(ang) + n2 * math.sin(ang)) * spread
                off += (n1 * math.sin(ph) + n2 * math.cos(ph) * 0.6) * wave
                pts.append((c + off, (1 - 0.82 * t ** 1.4) * (0.85 + 0.15 * math.sin(i * 2.1))))
            strands.append(pts)
        ob = curve_obj("HairTail" + side, strands, 0.024)
        PARTS.append((ob, "tail" + side, 0.0025))

        # Hair tie and cat-ear bow.
        bm = new_bm()
        d = (keys[1] - keys[0]).normalized()
        tie = Path([(keys[0] + d * 0.006, 0.024), (keys[0] + d * 0.04, 0.022)])
        tube(bm, tie, 0, 1, segs=20, rings=4, cap0=True, cap1=True)
        up = Vector((s * 0.55, 0.15, 1.0)).normalized()
        base = keys[0] + d * 0.02 + Vector((0, 0, 0.012))
        cone(bm, base, up, 0.030, 0.0, 0.06, segs=3, flat=0.4)
        make_obj("HairBow" + side, bm, ["jacket"], bones="head", coll="Hair", outline=0.0025)


# ---------------------------------------------------------------------------
# Props
# ---------------------------------------------------------------------------
def build_staff():
    o = STAFF_REST
    bm = new_bm()
    rod = Path([(o + Vector((0, 0, 0.05)), 0.0095), (o + Vector((0, 0, 0.8)), 0.011), (o + Vector((0, 0, 1.6)), 0.0115)])
    tube(bm, rod, 0, 1, segs=16, cap0=True, cap1=True)
    ring_c = o + Vector((0, 0, 1.92))
    R = 0.28

    def rp(deg, r=R):
        a = math.radians(deg)
        return ring_c + Vector((math.cos(a) * r, 0, math.sin(a) * r))

    keys = [(rp(70) + Vector((-0.05, 0, -0.03)), 0.006)]
    keys += [(rp(a), 0.012) for a in range(70, 371, 15)]
    keys += [(rp(370) + Vector((-0.045, 0, 0.035)), 0.006)]
    tube(bm, Path([(k, r) for k, r in keys]), 0, 1, segs=14, rings=160, cap0=True, cap1=True)
    for a in (250, 290):
        fork = Path([(o + Vector((0, 0, 1.585)), 0.010), (rp(a, R * 0.55) + Vector((0, 0, -0.06)), 0.009), (rp(a), 0.010)])
        tube(bm, fork, 0, 1, segs=12, rings=12)
    tube(bm, Path([(o + Vector((0, 0, 1.54)), 0.015), (o + Vector((0, 0, 1.6)), 0.016)]), 0, 1, segs=16, rings=4, cap0=True, cap1=True)
    make_obj("Staff", bm, ["staff"], bones="staff", coll="Props", outline=0.003)

    bm = new_bm()
    cone(bm, o, (0, 0, 1), 0.004, 0.0105, 0.06, segs=14)
    tip0, tip1 = keys[0][0], keys[-1][0]
    cone(bm, tip0, tip0 - rp(80), 0.009, 0.0, 0.035, segs=10)
    cone(bm, tip1, tip1 - rp(360), 0.009, 0.0, 0.035, segs=10)
    cone(bm, o + Vector((0, 0, 1.6)), (0, 0, 1), 0.006, 0.0, 0.17, segs=10)
    ellipsoid(bm, ring_c + Vector((-0.12, -0.004, 0.14)), (0.034, 0.006, 0.042), segs=20, rings=8)
    ellipsoid(bm, ring_c + Vector((0.17, -0.004, -0.06)), (0.024, 0.006, 0.032), segs=20, rings=8)
    for p in (Vector((-0.05, 0, 0.07)), Vector((0.02, 0, -0.12)), Vector((-0.2, 0, -0.05)), Vector((0.08, 0, 0.02))):
        ellipsoid(bm, ring_c + p + Vector((0, -0.004, 0)), (0.008, 0.004, 0.008), segs=10, rings=6)
    make_obj("StaffGold", bm, ["gold"], bones="staff", coll="Props", outline=0.002)

    bm = new_bm()
    for a, b in ((95, 280), (128, 335), (200, 355), (112, 240), (160, 300), (230, 15)):
        tube(bm, Path([(rp(a, R * 0.98), 0.0016), (rp(b, R * 0.98), 0.0016)]), 0, 1, segs=6, rings=2)
    make_obj("StaffLines", bm, ["line"], bones="staff", coll="Props", outline=0)


def build_hat():
    bm = new_bm()
    # Brim with a soft droop and a gentle wave.
    rows = []
    for k in range(10):
        r = 0.095 + 0.15 * k / 9
        row = []
        for j in range(48):
            a = 2 * math.pi * j / 48
            z = -0.035 * ((r - 0.095) / 0.15) ** 2 + 0.008 * math.sin(3 * a) * (k / 9)
            row.append(bm.verts.new((math.cos(a) * r, math.sin(a) * r, z)))
        rows.append(row)
    for k in range(9):
        for j in range(48):
            bm.faces.new((rows[k][j], rows[k + 1][j], rows[k + 1][(j + 1) % 48], rows[k][(j + 1) % 48]))
    bmesh.ops.solidify(bm, geom=bm.faces[:], thickness=0.008)
    crown = Path([((0, 0, -0.01), 0.108), ((0, 0, 0.12), 0.082), ((0.012, 0, 0.22), 0.052), ((0.05, 0, 0.30), 0.028),
                  ((0.12, 0, 0.335), 0.012), ((0.165, 0, 0.31), 0.002)])
    tube(bm, crown, 0, 1, segs=32, cap0=True, cap1=True)
    tube(bm, Path([((0, 0, 0.0), 0.112), ((0, 0, 0.05), 0.104)]), 0, 1, segs=32, rings=4, mat=1)
    cone(bm, (0, -0.108, 0.025), (0, -1, 0), 0.016, 0.016, 0.006, segs=4, mat=2)
    M = Matrix.Translation((0.30, 0.10, 2.0)) @ Matrix.Rotation(math.radians(-14), 4, "Y") @ Matrix.Rotation(math.radians(-10), 4, "X")
    bm.transform(M)
    make_obj("WitchHat", bm, ["boot", "ribbon", "gold"], bones="hat", coll="Props", outline=0.003)


# ---------------------------------------------------------------------------
# Armature
# ---------------------------------------------------------------------------
BONES = {}  # name -> (head, tail, parent)


def define_bones():
    B = BONES
    B["root"] = (Vector((0, 0, 0)), Vector((0, 0.3, 0)), None)
    B["hips"] = (Vector((0, 0.005, 0.90)), Vector((0, 0.005, 1.05)), "root")
    B["spine"] = (Vector((0, 0.005, 1.05)), Vector((0, 0.004, 1.20)), "hips")
    B["chest"] = (Vector((0, 0.004, 1.20)), Vector((0, 0.004, 1.40)), "spine")
    B["neck"] = (Vector((0, 0.004, 1.40)), Vector((0, 0.008, 1.55)), "chest")
    B["head"] = (Vector((0, 0.008, 1.55)), Vector((0, 0.008, 1.80)), "neck")
    for s in (-1, 1):
        x = ".L" if s > 0 else ".R"
        B["breast" + x] = (Vector((s * 0.058, -0.02, 1.285)), Vector((s * 0.07, -0.13, 1.27)), "chest")
        ap = arm_path(s)
        w = ap.at(1)
        B["upper_arm" + x] = (mirror(SHOULDER, s), mirror(ELBOW, s), "chest")
        B["forearm" + x] = (mirror(ELBOW, s), w, "upper_arm" + x)
        B["hand" + x] = (w, w + ap.tangent(1) * 0.1, "forearm" + x)
        B["thigh" + x] = (mirror(HIP, s) + Vector((0, 0, -0.02)), mirror(KNEE, s), "hips")
        B["shin" + x] = (mirror(KNEE, s), mirror(ANKLE, s), "thigh" + x)
        B["foot" + x] = (mirror(ANKLE, s), mirror(ANKLE, s) + Vector((0, -0.12, -0.06)), "shin" + x)
        keys = TAIL_KEYS[s]
        parent = "head"
        for i in range(7):
            n = f"tail{x}.{i}"
            B[n] = (keys[i], keys[i + 1], parent)
            parent = n
    B["staff"] = (STAFF_REST.copy(), STAFF_REST + Vector((0, 0, 0.4)), "root")
    B["hat"] = (Vector((0.30, 0.10, 2.0)), Vector((0.30, 0.10, 2.2)), "root")


def build_armature():
    arm = bpy.data.armatures.new("WitchRig")
    arm.display_type = "STICK"
    ob = bpy.data.objects.new("WitchRig", arm)
    collection("Character").objects.link(ob)
    ob.show_in_front = True
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for name, (h, t, p) in BONES.items():
        eb = arm.edit_bones.new(name)
        eb.head, eb.tail = h, t
        if name.startswith("thigh") or name.startswith("shin") or name.startswith("upper_arm") or name.startswith("forearm"):
            eb.roll = 0.0
    for name, (h, t, p) in BONES.items():
        if p:
            eb = arm.edit_bones[name]
            eb.parent = arm.edit_bones[p]
            eb.use_connect = (eb.head - eb.parent.tail).length < 1e-5 and name.startswith("tail")
    for name in BONES:
        arm.edit_bones[name].use_deform = name not in ("root",)
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in ob.pose.bones:
        pb.rotation_mode = "QUATERNION"
    ob["jiggle_bones"] = "tail.L.*, tail.R.*, breast.L, breast.R"
    return ob


GROUPS = {
    "body": ["hips", "spine", "chest", "neck", "upper_arm.L", "upper_arm.R", "forearm.L", "forearm.R", "hand.L",
             "hand.R", "thigh.L", "thigh.R", "shin.L", "shin.R", "foot.L", "foot.R"],
    "torso_upper": ["spine", "chest", "neck", "upper_arm.L", "upper_arm.R"],
    "torso_lower": ["hips", "spine", "thigh.L", "thigh.R"],
    "leg.L": ["shin.L", "foot.L", "thigh.L"],
    "leg.R": ["shin.R", "foot.R", "thigh.R"],
}


def seg_dist(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return (p - (a + ab * t)).length


def bind(rig):
    tails = {s: [f"tail{'.L' if s > 0 else '.R'}.{i}" for i in range(7)] for s in (-1, 1)}
    GROUPS["tail.L"] = tails[1]
    GROUPS["tail.R"] = tails[-1]
    for ob, bones, _ in PARTS:
        allowed = GROUPS.get(bones, [bones])
        groups = {b: ob.vertex_groups.new(name=b) for b in allowed}
        for v in ob.data.vertices:
            p = v.co
            cands = []
            for b in allowed:
                # Keep left and right limbs from pulling on each other.
                if b.endswith(".L") and p.x < -0.03 and not b.startswith("tail"):
                    continue
                if b.endswith(".R") and p.x > 0.03 and not b.startswith("tail"):
                    continue
                h, t, _ = BONES[b]
                d = seg_dist(p, h, t)
                cands.append((d, b))
            if not cands:
                cands = [(0.0, allowed[0])]
            cands.sort()
            best = cands[:3]
            ws = [1.0 / (d * d + 1e-5) ** 2 for d, _ in best]
            tot = sum(ws)
            for (d, b), w in zip(best, ws):
                if w / tot > 0.01:
                    groups[b].add([v.index], w / tot, "REPLACE")
        ob.parent = rig
        mod = ob.modifiers.new("Armature", "ARMATURE")
        mod.object = rig


def add_outlines():
    for ob, _, thick in PARTS:
        if thick <= 0:
            continue
        n = len(ob.data.materials)
        for _ in range(n):
            ob.data.materials.append(MATS["outline"])
        mod = ob.modifiers.new("Outline", "SOLIDIFY")
        mod.thickness = thick
        mod.offset = 1.0
        mod.use_flip_normals = True
        mod.use_even_offset = False  # even offset spikes on thin ribbons
        mod.use_quality_normals = True
        mod.material_offset = n
        mod.material_offset_rim = n


# ---------------------------------------------------------------------------
# Posing: manual forward kinematics so poses and physics can be computed
# exactly, then written to the bones as keyframes.
# ---------------------------------------------------------------------------
class Poser:
    def __init__(self, rig):
        self.rig = rig
        self.rest = {b.name: b.matrix_local.copy() for b in rig.data.bones}
        self.parent = {b.name: (b.parent.name if b.parent else None) for b in rig.data.bones}
        self.basis = {}
        self.loc = {}
        self.M = {}

    def base(self, name):
        p = self.parent[name]
        if p is None:
            return self.rest[name].copy()
        return self.M[p] @ self.rest[p].inverted() @ self.rest[name]

    def set(self, name, q=None, loc=None):
        q = q or Quaternion()
        self.basis[name] = q
        A = self.base(name)
        if loc is not None:
            self.loc[name] = loc
            A = A @ Matrix.Translation(loc)
        self.M[name] = A @ q.to_matrix().to_4x4()
        return self.M[name]

    def set_world_offset(self, name, world_off, q=None):
        A = self.base(name)
        local = A.to_3x3().inverted() @ world_off
        return self.set(name, q, local)

    def aim(self, name, d, twist=0.0):
        A = self.base(name)
        ay = A.col[1].xyz.normalized()
        Q = ay.rotation_difference(Vector(d).normalized())
        A3 = A.to_3x3()
        B = A3.inverted() @ Q.to_matrix() @ A3
        q = B.to_quaternion()
        if twist:
            q = q @ Quaternion((0, 1, 0), twist)
        return self.set(name, q)

    def head(self, name):
        return self.base(name).translation.copy()

    def length(self, name):
        return self.rig.data.bones[name].length

    def two_bone(self, a, b, target, pole):
        S = self.head(a)
        L1, L2 = self.length(a), self.length(b)
        d = target - S
        dist = min(max(d.length, abs(L1 - L2) + 1e-4), L1 + L2 - 1e-4)
        dn = d.normalized()
        x = (L1 * L1 - L2 * L2 + dist * dist) / (2 * dist)
        h = math.sqrt(max(L1 * L1 - x * x, 0.0))
        pp = (pole - dn * pole.dot(dn)).normalized()
        E = S + dn * x + pp * h
        self.aim(a, E - S)
        self.aim(b, target - E)

    def key(self, frame):
        for name, q in self.basis.items():
            pb = self.rig.pose.bones[name]
            pb.rotation_quaternion = q
            pb.keyframe_insert("rotation_quaternion", frame=frame)
            if name in self.loc:
                pb.location = self.loc[name]
                pb.keyframe_insert("location", frame=frame)


STAFF_GRIP = Vector((-0.40, -0.14, 0.98))
HIP_HAND = Vector((0.205, 0.035, 0.985))


def pose_frame(P, f, sims, dt):
    ph = 2 * math.pi * f / FRAMES
    bob = 0.024 * (0.5 - 0.5 * math.cos(ph * 4))
    breath = math.sin(ph * 2)
    sway = 0.025 * math.sin(ph)
    P.set("root")
    P.set_world_offset("hips", Vector((-0.018, 0.0, -0.012 - bob)),
                       Quaternion((0, 1, 0), 0.045 + sway) @ Quaternion((0, 0, 1), -0.12))
    P.set("spine", Quaternion((0, 0, 1), 0.04 - sway * 0.6) @ Quaternion((1, 0, 0), -0.02))
    P.set("chest", Quaternion((0, 1, 0), -0.05 - sway * 0.5) @ Quaternion((1, 0, 0), -0.03 + 0.012 * breath))
    P.set("neck", Quaternion((1, 0, 0), 0.04))
    P.set("head", Quaternion((0, 1, 0), -0.32) @ Quaternion((0, 0, 1), 0.10 + 0.02 * math.sin(ph * 2)) @ Quaternion((1, 0, 0), 0.06))

    # Right hand grips the planted staff; left hand rests on the hip.
    grip = STAFF_GRIP
    wrist_r = grip + Vector((0.055, 0.035, 0.0))
    P.two_bone("upper_arm.R", "forearm.R", wrist_r, Vector((-0.2, 1.0, -0.4)))
    P.aim("hand.R", grip - wrist_r + Vector((0, 0, -0.01)), twist=0.0)
    hip_m = P.M["hips"]
    wrist_l = hip_m @ (P.rest["hips"].inverted() @ HIP_HAND)
    P.two_bone("upper_arm.L", "forearm.L", wrist_l, Vector((1.0, 0.7, 0.1)))
    P.aim("hand.L", Vector((-0.45, 0.25, -0.85)))

    # Legs: two-bone IK to planted feet, weight on her right leg.
    P.two_bone("thigh.R", "shin.R", Vector((-0.085, 0.03, 0.09)), Vector((0, -1, 0)))
    P.aim("foot.R", Vector((-0.12, -0.9, -0.45)))
    P.two_bone("thigh.L", "shin.L", Vector((0.11, -0.13, 0.09)), Vector((0.25, -1, 0)))
    P.aim("foot.L", Vector((0.3, -0.85, -0.45)))

    P.set_world_offset("staff", Vector((grip.x - STAFF_REST.x, grip.y - STAFF_REST.y, 0.0)), Quaternion((0, 1, 0), -0.45))
    P.set("hat", Quaternion((0, 0, 1), 0.05 * math.sin(ph * 2)), Vector((0, 0.012 * math.sin(ph * 2), 0)))

    # --- spring physics -------------------------------------------------
    # Breasts: a damped spring point trailing a rest target on the chest.
    for s in (-1, 1):
        x = ".L" if s > 0 else ".R"
        name = "breast" + x
        A = P.base(name)
        rest_tip = A @ Vector((0, P.length(name), 0))
        st = sims.setdefault(name, {"p": rest_tip.copy(), "v": Vector()})
        k, c = 170.0, 4.5
        for _ in range(4):
            h = dt / 4
            acc = (rest_tip - st["p"]) * k - st["v"] * c
            st["v"] += acc * h
            st["p"] += st["v"] * h
        off = st["p"] - rest_tip
        if off.length > 0.035:
            off = off.normalized() * 0.035
            st["p"] = rest_tip + off
        P.aim(name, (rest_tip + off * 1.6) - A.translation)

    # Hair tails: verlet chain with shape memory toward the rest curve.
    for s in (-1, 1):
        x = ".L" if s > 0 else ".R"
        names = [f"tail{x}.{i}" for i in range(7)]
        # Rest positions of the chain under the current head pose.
        rest = [P.base(names[0]).translation.copy()]
        Mh = P.M["head"]
        for n in names:
            rest.append(Mh @ (P.rest["head"].inverted() @ (P.rest[n] @ Vector((0, P.length(n), 0)))))
        st = sims.setdefault("tail" + x, {"p": [r.copy() for r in rest], "q": [r.copy() for r in rest]})
        p, q = st["p"], st["q"]
        sub = 4
        for _ in range(sub):
            p[0] = rest[0].copy()
            q[0] = rest[0].copy()
            for i in range(1, len(p)):
                vel = (p[i] - q[i]) * 0.96
                q[i] = p[i].copy()
                p[i] = p[i] + vel + Vector((0, 0, -0.35)) * (dt / sub) ** 2
            for i in range(1, len(p)):
                stiff = 0.10 * (1 - 0.55 * i / len(p))
                tgt = p[i - 1] + (rest[i] - rest[i - 1])
                p[i] = p[i] + (tgt - p[i]) * stiff
            for i in range(1, len(p)):
                seg = (rest[i] - rest[i - 1]).length
                d = p[i] - p[i - 1]
                p[i] = p[i - 1] + d.normalized() * seg
                # keep the tails from swinging into the back
                if p[i].y < 0.13:
                    p[i].y = 0.13
        for i, n in enumerate(names):
            P.aim(n, p[i + 1] - P.head(n))


def animate(rig):
    scn = bpy.context.scene
    scn.render.fps = FPS
    scn.frame_start, scn.frame_end = 1, FRAMES
    P = Poser(rig)
    sims = {}
    dt = 1.0 / FPS
    for f in range(1, FRAMES * 2 + 1):  # first loop settles the physics
        P.basis.clear()
        P.loc.clear()
        P.M.clear()
        pose_frame(P, f, sims, dt)
        if f > FRAMES:
            P.key(f - FRAMES)
    action = rig.animation_data.action
    action.name = "Idle_Jiggle"
    scn.frame_set(1)


# ---------------------------------------------------------------------------
# Face texture
# ---------------------------------------------------------------------------
def paint_face(path):
    from PIL import Image, ImageDraw, ImageFilter

    S = 2048
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    def px(x, z):  # head-local meters -> pixels
        return ((x * 5.2632 + 0.5) * S, (1 - (z + 0.12) * 5.0) * S)

    def bez(p0, p1, p2, n=24):
        return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                 (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in (i / n for i in range(n + 1))]

    blush = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blush)
    for s in (-1, 1):
        cx, cy = px(s * 0.047, -0.032)
        bd.ellipse((cx - 90, cy - 40, cx + 90, cy + 40), fill=(232, 120, 140, 85))
    img = Image.alpha_composite(img, blush.filter(ImageFilter.GaussianBlur(28)))
    d = ImageDraw.Draw(img)

    lash = (40, 22, 28, 255)
    for s in (-1, 1):
        ex, ez = s * 0.034, -0.008
        cx, cy = px(ex, ez)
        w, h = 0.0215 * 5.2632 * S, 0.0155 * 5.0 * S

        def E(x, y):  # eye-local (outer corner at x=+1) -> pixels
            return (cx + s * x * w, cy - y * h)

        upper = bez(E(-1, -0.05), E(-0.1, 1.15), E(1.0, 0.18))
        lower = bez(E(1.0, 0.18), E(0.15, -0.85), E(-1, -0.05))
        white = upper + lower
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).polygon(white, fill=255)
        layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.polygon(white, fill=(252, 246, 244, 255))
        ix, iy = E(0.02, 0.05)
        r = 0.60 * h
        for k in range(24):  # iris gradient, dark at the top
            t = k / 23
            col = tuple(int(a + (b - a) * t) for a, b in zip((86, 30, 44), (200, 112, 120)))
            rr = r * (1 - 0.012 * k)
            ld.ellipse((ix - rr, iy - r + t * 0.15 * r - rr + r, ix + rr, iy - r + t * 0.15 * r + rr + r),
                       fill=(*col, 255))
        ld.ellipse((ix - r, iy - r, ix + r, iy + r), outline=(70, 26, 36, 255), width=7)
        ld.ellipse((ix - r * 0.38, iy - r * 0.45, ix + r * 0.38, iy + r * 0.45), fill=(42, 14, 22, 255))
        ld.polygon(bez(E(-1, -0.05), E(-0.1, 1.15), E(1.0, 0.18)) + [E(1, 1.3), E(-1, 1.3)], fill=(150, 90, 100, 90))
        clipped = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        clipped.paste(layer, (0, 0), mask)
        img = Image.alpha_composite(img, clipped)
        d = ImageDraw.Draw(img)
        d.ellipse((ix - s * r * 0.35 - 15, iy - r * 0.45 - 17, ix - s * r * 0.35 + 15, iy - r * 0.45 + 17), fill=(255, 255, 255, 255))
        d.ellipse((ix + s * r * 0.3 - 7, iy + r * 0.35 - 7, ix + s * r * 0.3 + 7, iy + r * 0.35 + 7), fill=(255, 255, 255, 230))
        d.line(upper, fill=lash, width=15, joint="curve")
        d.line(bez(E(0.55, 0.62), E(1.05, 0.5), E(1.32, 0.62), 10), fill=lash, width=12, joint="curve")
        d.line(bez(E(1.0, 0.18), E(0.5, -0.62), E(-0.2, -0.75), 16), fill=(120, 60, 66, 255), width=5)
        d.line(bez(E(-0.75, 0.85), E(0.0, 1.55), E(0.85, 0.9), 16), fill=(150, 90, 96, 200), width=5)
        # Brow
        bx, by = px(s * 0.031, 0.026)
        d.line(bez((bx - s * 110, by + 18), (bx, by - 26), (bx + s * 125, by + 6), 20), fill=(120, 50, 62, 255), width=10, joint="curve")

    # Nose and mouth
    nx, ny = px(0.004, -0.036)
    d.line([(nx + 6, ny - 26), (nx - 6, ny + 8), (nx + 10, ny + 12)], fill=(176, 118, 118, 255), width=6, joint="curve")
    mx, my = px(0.0, -0.072)
    d.line(bez((mx - 92, my - 8), (mx, my + 20), (mx + 100, my - 16), 24), fill=(120, 48, 58, 255), width=9, joint="curve")
    d.line(bez((mx - 40, my + 26), (mx, my + 38), (mx + 44, my + 24), 16), fill=(196, 128, 132, 200), width=6, joint="curve")
    img = img.resize((1024, 1024), Image.LANCZOS)
    img.save(path)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def setup_render():
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.device = "CPU"
    scn.cycles.samples = 12 if QUICK else 48
    scn.cycles.use_denoising = False
    scn.cycles.max_bounces = 4
    scn.cycles.transparent_max_bounces = 32
    scn.render.film_transparent = False
    scn.view_settings.view_transform = "Standard"
    scn.view_settings.look = "None"
    world = bpy.data.worlds.new("Backdrop")
    world.color = lin(BG)
    try:
        world.use_nodes = True
    except Exception:
        pass
    bgn = world.node_tree.nodes.get("Background")
    bgn.inputs["Color"].default_value = rgba(BG)
    scn.world = world


def camera(name, loc, target, lens=None, ortho=None):
    cam = bpy.data.cameras.new(name)
    if ortho:
        cam.type = "ORTHO"
        cam.ortho_scale = ortho
    else:
        cam.lens = lens
    ob = bpy.data.objects.new(name, cam)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    d = Vector(target) - Vector(loc)
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return ob


def render(cam, path, rx, ry):
    scn = bpy.context.scene
    scn.camera = cam
    scn.render.resolution_x, scn.render.resolution_y = rx, ry
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)


def export_glb():
    """Export a .glb for game engines. glTF cannot carry the node-based toon
    shading or the outline shells, so materials fall back to flat base colors."""
    for m in bpy.data.materials:
        if "base_color" not in m:
            continue
        nt = m.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.inputs["Base Color"].default_value = rgba(m["base_color"])
        bsdf.inputs["Roughness"].default_value = 0.8
        nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    for ob, _, _ in PARTS:
        mod = ob.modifiers.get("Outline")
        if mod:
            ob.modifiers.remove(mod)
    bpy.ops.export_scene.gltf(filepath=os.path.join(HERE, "witch_character.glb"), export_format="GLB",
                              export_animations=True, export_skins=True, export_apply=False)


def compose_sheet():
    """Lay the renders out like the reference: turnaround on the left, hero on the right."""
    from PIL import Image

    def load(n):
        return Image.open(os.path.join(RENDER_DIR, n)).convert("RGB")

    hero = load("hero.png")
    views = [load(f"turnaround_{k}.png") for k in ("front", "side", "back")]
    H = hero.height
    vh = int(H * 0.8)
    views = [v.resize((int(v.width * vh / v.height), vh)) for v in views]
    W = sum(v.width for v in views) + hero.width
    sheet = Image.new("RGB", (W, H), tuple(int(BG[i:i + 2], 16) for i in (1, 3, 5)))
    x = 0
    for v in views:
        sheet.paste(v, (x, H - vh))
        x += v.width
    sheet.paste(hero, (x, 0))
    sheet.save(os.path.join(RENDER_DIR, "character_sheet.png"))


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    os.makedirs(TEX_DIR, exist_ok=True)
    os.makedirs(RENDER_DIR, exist_ok=True)
    face_path = os.path.join(TEX_DIR, "face.png")
    paint_face(face_path)
    face = bpy.data.images.load(face_path)
    face.pack()
    build_materials(face)
    build_body()
    build_clothes()
    build_hair()
    build_staff()
    build_hat()
    define_bones()
    rig = build_armature()
    bind(rig)
    add_outlines()
    animate(rig)
    setup_render()

    cams = {
        "hero": camera("Cam_Hero", (-1.4, -2.75, 1.28), (-0.1, 0, 1.12), lens=35),
        "face": camera("Cam_Face", (-0.25, -0.75, 1.66), (0, 0, 1.64), lens=50),
        "front": camera("Cam_Front", (0, -5, 1.0), (0, 0, 1.0), ortho=2.25),
        "side": camera("Cam_Side", (5, 0, 1.0), (0, 0, 1.0), ortho=2.25),
        "back": camera("Cam_Back", (0, 5, 1.0), (0, 0, 1.0), ortho=2.25),
    }
    scn = bpy.context.scene
    scn.camera = cams["hero"]
    blend = os.path.join(HERE, "witch_character.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True)

    if "--no-render" not in sys.argv:
        big = 1 if QUICK else 2
        render(cams["hero"], os.path.join(RENDER_DIR, "hero.png"), 600 * big, 800 * big)
        render(cams["face"], os.path.join(RENDER_DIR, "face_closeup.png"), 500 * big, 500 * big)
        rig.data.pose_position = "REST"
        hat = bpy.data.objects["WitchHat"]
        for k in ("front", "side", "back"):
            render(cams[k], os.path.join(RENDER_DIR, f"turnaround_{k}.png"), 400 * big, 640 * big)
        rig.data.pose_position = "POSE"
        del hat
        compose_sheet()
    if "--glb" in sys.argv:
        export_glb()
    print("Saved", blend)


if __name__ == "__main__":
    main()
