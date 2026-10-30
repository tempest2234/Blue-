"""Build the rigged anime witch character in Blender.

Run with Blender 4.2+ / 5.x:
    blender --background --python blender/build_witch.py -- [--quick] [--glb] [--no-render]
or with the `bpy` Python module (plus Pillow):
    python blender/build_witch.py [--quick] [--glb] [--no-render]

Outputs (next to this script):
    witch_character.blend      the rigged, posed and animated character
    witch_character.glb        (with --glb) game-engine export
    textures/face.png          the painted face texture (also packed in the .blend)
    renders/*.png              hero render, face close-up, turnaround, character sheet

Everything is generated procedurally. The body and garments are lofted
cross-sections (the bust is sculpted into the torso and jacket), hair is
built from flat overlapping clumps, hands have jointed fingers, and the face
is painted with Pillow. Lines are drawn with Freestyle (silhouettes, creases
and marked garment seams). The armature is weighted by distance to each bone,
and spring physics on the ponytails and chest is baked into the idle action.
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
    "skin": ("#efd3cd", "#d9aaa8"),
    "hair": ("#b85d6b", "#8e4152", "#d68790"),
    "hair_dark": ("#9a4859", "#76323f"),
    "jacket": ("#22363a", "#142224", "#35505a"),
    "collar_inset": ("#3d5559", "#2a3d40"),
    "panel": ("#a98aa9", "#7f6585"),
    "sleeve": ("#e8b7cd", "#c88fad"),
    "shorts": ("#527779", "#3d5c5e"),
    "sock": ("#efe6e6", "#cfc2c7"),
    "boot": ("#24373a", "#162427"),
    "bootcuff": ("#4d7072", "#37575a"),
    "ribbon": ("#162021", "#0c1314"),
    "gem": ("#ef7f97", "#c25570", "#ffc2cf"),
    "staff": ("#efede8", "#c9c5bf"),
    "gold": ("#e8b93a", "#b98c1f"),
    "line": ("#1d1416", "#1d1416"),
    "navel": ("#c48a8a", "#c48a8a"),
}
BG = "#596262"
INK = "#1d1416"
LIGHT = Vector((-0.45, -0.6, 0.66)).normalized()
X_AXIS = Vector((1, 0, 0))
Z_AXIS = Vector((0, 0, 1))

# Body landmarks (meters, Z up, character faces -Y; +X is her left side).
HS = 0.92  # head scale relative to the face-texture layout
HEAD_C = Vector((0.0, 0.008, 1.636))
HEAD_R = Vector((0.087, 0.097, 0.104)) * HS
SHOULDER = Vector((0.148, 0.0, 1.385))
ELBOW = Vector((0.31, 0.0, 1.17))
WRIST = Vector((0.45, -0.01, 0.99))
HIP = Vector((0.085, 0.0, 0.92))
KNEE = Vector((0.078, -0.005, 0.50))
ANKLE = Vector((0.072, 0.01, 0.085))
STAFF_REST = Vector((-0.62, -0.05, 0.0))


def mirror(v, s):
    return Vector((v.x * s, v.y, v.z))


def clamp(v, a, b):
    return max(a, min(b, v))


def smoothstep(e0, e1, x):
    t = clamp((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------------------
# Materials
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


def use_nodes(idblock):
    """Blender 4.x needs use_nodes switched on; 5.x always uses nodes."""
    if getattr(idblock, "node_tree", None) is None:
        idblock.use_nodes = True


def toon(name, base, shade, hi=None, thresh=0.0, alpha=1.0, image=None):
    """Cel-shaded material: two (or three) flat tones picked by N·L.

    It is emission-only, so it renders identically in Cycles and EEVEE and
    needs no lights. The light direction is baked into the node tree.
    """
    m = bpy.data.materials.new(name)
    use_nodes(m)
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
        except AttributeError:
            pass
    L(shader, out.inputs["Surface"])
    m.diffuse_color = rgba(base)
    MATS[name] = m
    return m


def build_materials(face_image):
    for k, v in COL.items():
        toon(k, v[0], v[1], v[2] if len(v) > 2 else None, thresh=-0.05)
    toon("face", COL["skin"][0], COL["skin"][1], thresh=-0.5, image=face_image)
    toon("sleeve_glass", COL["sleeve"][0], COL["sleeve"][1], thresh=-0.1, alpha=0.6)
    toon("ribbon_glass", "#f2b8d4", "#d690b6", alpha=0.5)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
COLLECTIONS = {}
PARTS = []  # (object, bone group or bone name)
MARKS = {}  # id(bmesh) -> [(BMVert, BMVert)] edges drawn as Freestyle seams


def collection(name):
    if name not in COLLECTIONS:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
        COLLECTIONS[name] = c
    return COLLECTIONS[name]


def new_bm():
    return bmesh.new()


def mark(bm, a, b):
    MARKS.setdefault(id(bm), []).append((a, b))


def make_obj(name, bm, mats, coll="Character", bones=None):
    for f in bm.faces:
        f.smooth = True
    bm.verts.index_update()
    pairs = [(a.index, b.index) for a, b in MARKS.pop(id(bm), []) if a.is_valid and b.is_valid]
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if pairs:
        lookup = {tuple(sorted(e.vertices)): e.index for e in me.edges}
        attr = me.attributes.new("freestyle_edge", "BOOLEAN", "EDGE")
        for a, b in pairs:
            i = lookup.get(tuple(sorted((a, b))))
            if i is not None:
                attr.data[i].value = True
    for m in mats:
        me.materials.append(MATS[m])
    ob = bpy.data.objects.new(name, me)
    collection(coll).objects.link(ob)
    PARTS.append((ob, bones))
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
        t = clamp(t, 0.0, 1.0)
        n = len(self.P)
        for i in range(n - 1):
            if t <= self.u[i + 1] or i == n - 2:
                s = (t - self.u[i]) / max(self.u[i + 1] - self.u[i], 1e-9)
                return i, clamp(s, 0.0, 1.0)

    def _interp(self, arr, t):
        i, s = self._seg(t)
        n = len(arr)
        b, c = arr[i], arr[i + 1]
        a = arr[i - 1] if i > 0 else (b - (c - b) if isinstance(b, Vector) else b)
        d = arr[i + 2] if i + 2 < n else (c + (c - b) if isinstance(c, Vector) else c)
        return catmull(a, b, c, d, s)

    def at(self, t):
        return self._interp(self.P, t)

    def radius(self, t):
        return max(self._interp(self.rx, t), 0.0005), max(self._interp(self.ry, t), 0.0005)

    def tangent(self, t):
        e = 0.002
        return (self.at(min(t + e, 1)) - self.at(max(t - e, 0))).normalized()

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
    ref = X_AXIS
    if abs(tan.dot(ref)) > 0.95:
        ref = Vector((0, -1, 0))
    n1 = (ref - tan * ref.dot(tan)).normalized()
    return n1, tan.cross(n1)


def call_add(add, s, a):
    if callable(add):
        try:
            return add(s, a)
        except TypeError:
            return add(s)
    return add


def tube(bm, path, t0, t1, add=0.0, segs=36, rings=None, cap0=False, cap1=False, mat=0,
         seams=(), lines=(), deform=None, mat_fn=None):
    """Loft an elliptical tube along `path` between params t0..t1.

    `add` thickens the tube (for garment shells) and may be a function of the
    local parameter s (0..1) and the ring angle. `seams` is a list of
    (world direction, s0, s1) marking a lengthwise Freestyle seam; `lines`
    lists ring positions s marked as circumferential seams. `deform` maps
    each vertex position to a new one (used to sculpt the bust in), and
    `mat_fn` picks a material from a face's undeformed outward direction.
    """
    if rings is None:
        rings = max(4, int(abs(t1 - t0) * path.length / 0.010))
    rows, offs = [], []
    for k in range(rings):
        s = k / (rings - 1)
        t = t0 + (t1 - t0) * s
        c = path.at(t)
        n1, n2 = frame(path.tangent(t))
        rx, ry = path.radius(t)
        row, orow = [], []
        for j in range(segs):
            ang = 2 * math.pi * j / segs
            a = call_add(add, s, ang)
            o = n1 * math.cos(ang) * (rx + a) + n2 * math.sin(ang) * (ry + a)
            p = c + o
            if deform:
                p = deform(p)
            row.append(bm.verts.new(p))
            orow.append(o.normalized())
        rows.append(row)
        offs.append(orow)
    for k in range(rings - 1):
        A, B = rows[k], rows[k + 1]
        for j in range(segs):
            f = bm.faces.new((A[j], A[(j + 1) % segs], B[(j + 1) % segs], B[j]))
            f.material_index = mat_fn(offs[k][j] + offs[k][(j + 1) % segs]) if mat_fn else mat
            if t1 < t0:
                f.normal_flip()
    for d, s0, s1 in seams:
        d = Vector(d).normalized()
        for k in range(rings - 1):
            if s0 <= k / (rings - 1) <= s1:
                j = max(range(segs), key=lambda jj: offs[k][jj].dot(d))
                mark(bm, rows[k][j], rows[k + 1][j])
    for s in lines:
        k = int(round(s * (rings - 1)))
        for j in range(segs):
            mark(bm, rows[k][j], rows[k][(j + 1) % segs])
    for cap, row, flip in ((cap0, rows[0], True), (cap1, rows[-1], False)):
        if cap:
            ctr = bm.verts.new(sum((v.co for v in row), Vector()) / len(row))
            for j in range(segs):
                tri = (row[j], row[(j + 1) % segs], ctr)
                f = bm.faces.new(tri[::-1] if flip != (t1 < t0) else tri)
                f.material_index = mat
    return rows


def surface_point(path, t, direction, add=0.0, deform=None):
    """Point on a tube surface at param t, on the side facing `direction`."""
    c = path.at(t)
    n1, n2 = frame(path.tangent(t))
    rx, ry = path.radius(t)
    d = Vector(direction).normalized()
    best = max(range(180), key=lambda j: (n1 * math.cos(j * math.pi / 90) + n2 * math.sin(j * math.pi / 90)).dot(d))
    ang = best * math.pi / 90
    p = c + n1 * math.cos(ang) * (rx + add) + n2 * math.sin(ang) * (ry + add)
    nrm = (n1 * math.cos(ang) / max(rx, 1e-4) + n2 * math.sin(ang) / max(ry, 1e-4)).normalized()
    if deform:
        q = deform(p + nrm * 0.002)
        p = deform(p)
        nrm = (q - p).normalized()
    return p, nrm


def lens(bm, pts, normals, widths, thicks, segs=12, mat=0, cap0=True):
    """Flat clump with a lens-shaped cross-section (hair locks, ribbons).

    Width lies across the surface, thickness along the given normal.
    """
    n = len(pts)
    rows = []
    for k in range(n):
        t = (pts[min(k + 1, n - 1)] - pts[max(k - 1, 0)]).normalized()
        nn = normals[k] - t * normals[k].dot(t)
        nn = nn.normalized() if nn.length > 1e-6 else frame(t)[1]
        side = nn.cross(t)
        w, h = max(widths[k], 0.0004), max(thicks[k], 0.0003)
        row = []
        for j in range(segs):
            a = 2 * math.pi * j / segs
            c, s = math.cos(a), math.sin(a)
            x = w * math.copysign(abs(c) ** 0.75, c)
            y = h * s * (0.55 + 0.45 * abs(s))
            row.append(bm.verts.new(pts[k] + side * x + nn * y))
        rows.append(row)
    for k in range(n - 1):
        A, B = rows[k], rows[k + 1]
        for j in range(segs):
            f = bm.faces.new((A[j], A[(j + 1) % segs], B[(j + 1) % segs], B[j]))
            f.material_index = mat
    for row, flip in ((rows[0], True), (rows[-1], False)):
        if flip and not cap0:
            continue
        ctr = bm.verts.new(sum((v.co for v in row), Vector()) / len(row))
        for j in range(segs):
            tri = (row[j], row[(j + 1) % segs], ctr)
            f = bm.faces.new(tri[::-1] if flip else tri)
            f.material_index = mat


def ellipsoid(bm, center, radii, rot=None, segs=28, rings=16, mat=0):
    M = Matrix.Translation(Vector(center))
    if rot is not None:
        M = M @ (rot.to_matrix().to_4x4() if hasattr(rot, "to_matrix") else rot)
    M = M @ Matrix.Diagonal((*radii, 1.0))
    res = bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=1.0, matrix=M)
    for v in res["verts"]:
        for f in v.link_faces:
            f.material_index = mat
    return res["verts"]


def cone(bm, base, direction, r1, r2, depth, segs=16, flat=1.0, mat=0):
    d = Vector(direction).normalized()
    rot = Z_AXIS.rotation_difference(d)
    M = Matrix.Translation(Vector(base) + d * depth / 2) @ rot.to_matrix().to_4x4() @ Matrix.Diagonal((1, flat, 1, 1))
    res = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segs, radius1=r1, radius2=r2, depth=depth, matrix=M)
    for v in res["verts"]:
        for f in v.link_faces:
            f.material_index = mat
    return res["verts"]


def box(bm, center, size, axes, mat=0):
    """Box with edges along the given (x, y, z) world axes."""
    R = Matrix((axes[0], axes[1], axes[2])).transposed().to_4x4()
    M = Matrix.Translation(Vector(center)) @ R @ Matrix.Diagonal((*size, 1.0))
    res = bmesh.ops.create_cube(bm, size=1.0, matrix=M)
    for v in res["verts"]:
        for f in v.link_faces:
            f.material_index = mat


def flat_poly(bm, center, normal, pts2d, thick=0.0025, mat=0):
    """Thin prism from a 2D outline, laid on a surface (stars, notches)."""
    n = Vector(normal).normalized()
    u = Z_AXIS - n * n.z
    u = u.normalized() if u.length > 1e-4 else X_AXIS.copy()
    v = n.cross(u)
    top = [bm.verts.new(center + v * x + u * y + n * thick) for x, y in pts2d]
    bot = [bm.verts.new(center + v * x + u * y) for x, y in pts2d]
    bm.faces.new(top).material_index = mat
    bm.faces.new(bot[::-1]).material_index = mat
    m = len(pts2d)
    for i in range(m):
        bm.faces.new((bot[i], bot[(i + 1) % m], top[(i + 1) % m], top[i])).material_index = mat


def star_pts(r, n=5, inner=0.45, rot=0.0):
    return [((r if i % 2 == 0 else r * inner) * math.sin(rot + math.pi * i / n),
             (r if i % 2 == 0 else r * inner) * math.cos(rot + math.pi * i / n)) for i in range(2 * n)]


# ---------------------------------------------------------------------------
# Body
# ---------------------------------------------------------------------------
TORSO = Path([
    ((0, 0.0, 0.80), 0.105, 0.075),
    ((0, 0.012, 0.86), 0.146, 0.097),
    ((0, 0.012, 0.93), 0.148, 0.097),
    ((0, 0.006, 1.00), 0.126, 0.086),
    ((0, 0.0, 1.07), 0.104, 0.075),
    ((0, 0.0, 1.14), 0.113, 0.078),
    ((0, 0.0, 1.22), 0.125, 0.083),
    ((0, 0.004, 1.30), 0.133, 0.085),
    ((0, 0.006, 1.365), 0.138, 0.078),
    ((0, 0.006, 1.41), 0.100, 0.062),
    ((0, 0.004, 1.445), 0.048, 0.045),
])
NECK = Path([((0, 0.002, 1.40), 0.038), ((0, 0.004, 1.48), 0.035), ((0, 0.008, 1.57), 0.033)])


def bust_field(p):
    """Per-side falloff (0..1) of the bust, used for shape and for weights."""
    out = []
    for s in (-1, 1):
        dx = (p.x - s * 0.063) / 0.062
        dz = (p.z - 1.272) / (0.062 if p.z > 1.272 else 0.046)
        front = smoothstep(0.035, -0.045, p.y)
        out.append(math.exp(-(dx * dx + dz * dz) * 1.45) * front)
    return out


def bust_deform(p):
    q = p.copy()
    for s, f in zip((-1, 1), bust_field(p)):
        q += Vector((s * 0.012 * f, -0.058 * f, -0.007 * f))
    return q


def leg_path(s):
    h, k, a = mirror(HIP, s), mirror(KNEE, s), mirror(ANKLE, s)
    return Path([
        (h, 0.082, 0.084),
        (h.lerp(k, 0.25) + Vector((0, -0.004, 0)), 0.073, 0.076),
        (h.lerp(k, 0.55), 0.060, 0.063),
        (h.lerp(k, 0.82), 0.048, 0.051),
        (k, 0.042, 0.045),
        (k.lerp(a, 0.22) + Vector((0, 0.009, 0)), 0.045, 0.050),
        (k.lerp(a, 0.45) + Vector((0, 0.006, 0)), 0.040, 0.043),
        (k.lerp(a, 0.75), 0.029, 0.032),
        (a, 0.026, 0.029),
    ])


def arm_path(s):
    sh, el, wr = mirror(SHOULDER, s), mirror(ELBOW, s), mirror(WRIST, s)
    return Path([
        (sh, 0.045, 0.043),
        (sh.lerp(el, 0.45), 0.039, 0.038),
        (el, 0.031, 0.030),
        (el.lerp(wr, 0.35), 0.033, 0.029),
        (wr, 0.023, 0.018),
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


def face_point(u):
    """Head surface with a small nose and cheek shaping."""
    p = head_point(u)
    ux, uy, uz = u
    if uy < 0:
        ridge = math.exp(-(ux / 0.085) ** 2) * smoothstep(-0.05, -0.30, uz) * smoothstep(-0.48, -0.36, uz)
        tip = math.exp(-(ux / 0.11) ** 2 - ((uz + 0.36) / 0.07) ** 2)
        p.y -= (0.0035 * ridge + 0.0045 * tip) * -uy
        cheek = math.exp(-((abs(ux) - 0.55) / 0.2) ** 2 - ((uz + 0.25) / 0.2) ** 2)
        p.y -= 0.002 * cheek
    return p


def shell(theta, phi, scale=1.0):
    th, ph = math.radians(theta), math.radians(phi)
    u = Vector((math.sin(th) * math.cos(ph), -math.cos(th) * math.cos(ph), math.sin(ph)))
    return head_point(u, scale)


HAND_AXES = {}


def build_hand(s):
    """Gloved hand with jointed fingers: a fist (staff hand) or relaxed."""
    side = ".L" if s > 0 else ".R"
    fist = s < 0
    ap = arm_path(s)
    w = ap.at(1)
    z = ap.tangent(1)
    x = (X_AXIS - z * z.x).normalized()
    y = z.cross(x)  # thumb side
    HAND_AXES[s] = (x, y, z)
    palm = -x * s
    R = Matrix((x, y, z)).transposed()
    bm = new_bm()
    ellipsoid(bm, w + z * 0.046 + palm * 0.002, (0.016, 0.040, 0.050), rot=R.to_4x4(), segs=24, rings=12)
    fingers = [(0.024, (0.040, 0.025, 0.020), 0.0088), (0.008, (0.044, 0.028, 0.022), 0.0092),
               (-0.008, (0.041, 0.026, 0.021), 0.0086), (-0.023, (0.032, 0.021, 0.018), 0.0076)]
    curls = (1.35, 1.55, 1.05) if fist else (0.22, 0.30, 0.22)
    for i, (off, lens_, r) in enumerate(fingers):
        p = w + z * 0.088 + y * off - palm * 0.002
        d = (z + y * (0.08 * (1.5 - i)) * (0 if fist else 1)).normalized()
        axis = d.cross(palm).normalized()
        pts = [(p.copy(), r, r * 0.9)]
        for seg, ang in zip(lens_, curls):
            d = Quaternion(axis, ang) @ d
            p = p + d * seg
            pts.append((p.copy(), r * 0.86, r * 0.78))
        tube(bm, Path(pts), 0, 1, segs=12, rings=10, cap0=True, cap1=True)
    p = w + z * 0.022 + y * 0.03 + palm * 0.006
    d = (z * 0.55 + y * 0.65 + palm * (0.55 if fist else 0.35)).normalized()
    axis = d.cross(palm if fist else -y).normalized()
    pts = [(p.copy(), 0.011, 0.010)]
    for seg, ang in zip((0.034, 0.028), (0.55, 0.45) if fist else (0.15, 0.2)):
        d = Quaternion(axis, ang) @ d
        p = p + d * seg
        pts.append((p.copy(), 0.0095, 0.0085))
    tube(bm, Path(pts), 0, 1, segs=12, rings=10, cap0=True, cap1=True)
    make_obj("Glove.Hand" + side, bm, ["jacket"], bones="hand" + side)


def build_body():
    bm = new_bm()
    tube(bm, TORSO, 0, 1, cap0=True, deform=bust_deform)
    tube(bm, NECK, 0, 1, segs=28)
    for s in (-1, 1):
        tube(bm, leg_path(s), 0, 1, cap1=True)
        tube(bm, arm_path(s), 0, 1, cap1=True, segs=28)
    make_obj("Body", bm, ["skin"], bones="body")

    bm = new_bm()
    ellipsoid(bm, (0, -0.0762, 1.062), (0.0045, 0.003, 0.009), segs=12, rings=8)
    make_obj("Navel", bm, ["navel"], bones="spine")

    # Head: tapered jaw, small nose; UV-projected from the front for the face.
    bm = new_bm()
    res = bmesh.ops.create_uvsphere(bm, u_segments=64, v_segments=48, radius=1.0)
    for v in res["verts"]:
        v.co = face_point(v.co.normalized())
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for l in f.loops:
            p = (l.vert.co - HEAD_C) / HS
            l[uv].uv = (p.x * 5.2632 + 0.5, (p.z + 0.12) * 5.0) if p.y < -0.015 else (0.002, 0.002)
    make_obj("Head", bm, ["face"], bones="head")

    for s in (-1, 1):
        bm = new_bm()
        ellipsoid(bm, HEAD_C + Vector((s * 0.081, 0.014, -0.014)), (0.010, 0.018, 0.024), segs=16, rings=10)
        make_obj("Ear" + (".L" if s > 0 else ".R"), bm, ["skin"], bones="head")
        build_hand(s)


# ---------------------------------------------------------------------------
# Clothing
# ---------------------------------------------------------------------------
def front_point(x, z, add, deform=bust_deform):
    """Point on the (bust-shaped) torso front at a given x and height."""
    t = TORSO.t_at_z(z)
    rx, _ = TORSO.radius(t)
    a = math.asin(clamp(x / (rx + add), -0.95, 0.95))
    return surface_point(TORSO, t, Vector((math.sin(a), -math.cos(a), 0)), add, deform)


def build_clothes():
    T = TORSO
    # Cropped jacket: dark front, lavender sides and back, princess seams.
    bm = new_bm()
    tube(bm, T, T.t_at_z(1.150), T.t_at_z(1.44), add=lambda s: 0.010 - 0.004 * s, deform=bust_deform,
         seams=[((0.62, -0.78, 0), 0.05, 0.86), ((-0.62, -0.78, 0), 0.05, 0.86)],
         mat_fn=lambda o: 1 if math.atan2(abs(o.x), -o.y) > math.radians(66) else 0)
    tube(bm, T, T.t_at_z(1.142), T.t_at_z(1.178), add=0.017, lines=(0.5,))
    make_obj("Jacket", bm, ["jacket", "panel"], bones="torso_upper")

    # Back lacing: two dark X straps.
    bm = new_bm()
    for zc in (1.235, 1.325):
        for sgn in (-1, 1):
            pts, nrm = [], []
            for k in range(6):
                q = k / 5 - 0.5
                p, n = surface_point(T, T.t_at_z(zc + q * 0.06), Vector((sgn * q * 0.9, 1, 0)), 0.0135)
                pts.append(p)
                nrm.append(n)
            lens(bm, pts, nrm, [0.008] * 6, [0.0018] * 6, segs=8)
    make_obj("BackLacing", bm, ["ribbon"], bones="chest")

    # High stand collar with folded flaps at the front.
    collar = Path([((0, 0.002, 1.405), 0.058, 0.055), ((0, 0.004, 1.46), 0.050, 0.048), ((0, 0.008, 1.528), 0.055, 0.053)])
    bm = new_bm()
    tube(bm, collar, 0, 1, segs=36, rings=10, lines=(0.97,))
    for s in (-1, 1):
        p, n = surface_point(collar, 0.62, Vector((s * 0.55, -1, 0)), 0.004)
        xa = Vector((-n.y, n.x, 0)).normalized() * s
        za = (Z_AXIS + n * 0.35).normalized()
        box(bm, p + n * 0.004, (0.034, 0.007, 0.044), (xa, n, za))
        box(bm, p + n * 0.0085 + xa * 0.002 + za * 0.004, (0.022, 0.0015, 0.020), (xa, n, za), mat=1)
    make_obj("Collar", bm, ["jacket", "collar_inset"], bones="neck")

    # Necktie: knot, small loops, and two tails lying over the bust.
    bm = new_bm()
    for s in (-1, 1):
        pts, nrm, ws = [], [], []
        for k in range(14):
            q = k / 13
            z = 1.40 - q * 0.215
            x = s * (0.006 + 0.03 * q ** 1.3)
            p, n = front_point(x, z, 0.0175 + 0.004 * math.sin(math.pi * q))
            pts.append(p)
            nrm.append(n)
            ws.append(0.012 + 0.012 * q)
        lens(bm, pts, nrm, ws, [0.0022] * 14, segs=10)
        loop = []
        for k in range(8):
            q = k / 7
            p, n = front_point(s * (0.008 + 0.03 * math.sin(q * math.pi * 0.9)), 1.413 + 0.012 * math.sin(q * math.pi), 0.024)
            loop.append((p, n))
        lens(bm, [p for p, _ in loop], [n for _, n in loop], [0.008 * (1 - 0.5 * abs(2 * k / 7 - 1)) + 0.003 for k in range(8)],
             [0.003] * 8, segs=10)
    kp, kn = front_point(0, 1.41, 0.026)
    ellipsoid(bm, kp, (0.012, 0.008, 0.011))
    make_obj("Necktie", bm, ["ribbon"], bones="tie")
    bm = new_bm()
    gp, gn = surface_point(collar, 0.02, Vector((0, -1, 0)), 0.012)
    cone(bm, gp + Vector((0, -0.006, 0.02)), (0, -0.35, -1), 0.024, 0.0, 0.06, segs=3, flat=0.45)
    make_obj("Gem", bm, ["gem"], bones="neck")

    for s in (-1, 1):
        side = ".L" if s > 0 else ".R"
        ap = arm_path(s)
        te = ap.u[2]
        # Puffed translucent sleeve, gathered into the shoulder and cuff.
        bm = new_bm()

        def puff(q, a):
            gather = math.sin(math.pi * min(q * 1.1, 1.0))
            return 0.008 + 0.017 * gather + 0.003 * math.cos(9 * a) * (0.4 + 0.6 * (1 - gather))
        tube(bm, ap, 0.0, te * 0.66, add=puff)
        make_obj("Sleeve" + side, bm, ["sleeve_glass"], bones="upper_arm" + side)
        bm = new_bm()
        tube(bm, ap, te * 0.6, te * 0.84, add=0.02, lines=(0.12, 0.88))
        make_obj("SleeveCuff" + side, bm, ["jacket"], bones="upper_arm" + side)
        if s > 0:  # gold star and moon charms on her left cuff
            bm = new_bm()
            for k, (tt, dz) in enumerate(((0.67, 0.0), (0.76, 0.25), (0.72, -0.3))):
                p, n = surface_point(ap, te * tt, Vector((0.35, -1, dz)), 0.0205)
                pts = star_pts(0.009, rot=0.3) if k < 2 else [
                    (0.008 * math.cos(a) - (0.004 if i >= 12 else 0), 0.008 * math.sin(a))
                    for i, a in enumerate([math.pi * 0.25 + j * math.pi * 1.5 / 11 for j in range(12)])]
                flat_poly(bm, p, n, pts, thick=0.0018)
            make_obj("SleeveCharms", bm, ["gold"], bones="upper_arm.L")
        # Long glove with a wide turned-back cuff.
        bm = new_bm()
        tube(bm, ap, te + (1 - te) * 0.16, 1.0, add=0.005)
        tube(bm, ap, te + (1 - te) * 0.10, te + (1 - te) * 0.36, add=0.018, lines=(0.15,))
        make_obj("Glove" + side, bm, ["jacket"], bones="forearm" + side)

    # Shorts: waist, flared legs, waistband with belt loops, fly and pockets.
    bm = new_bm()
    tube(bm, T, T.t_at_z(0.81), T.t_at_z(1.03), add=0.009, cap0=True,
         seams=[((0, -1, 0), 0.35, 0.72), ((1, 0, 0), 0.3, 1), ((-1, 0, 0), 0.3, 1)])
    for s in (-1, 1):
        lp = leg_path(s)
        tube(bm, lp, lp.t_at_z(0.94), lp.t_at_z(0.805), add=lambda q: 0.012 + 0.008 * q,
             seams=[((s, 0, 0), 0, 1)], lines=(0.84,))
    make_obj("Shorts", bm, ["shorts"], bones="torso_lower")
    bm = new_bm()
    for s in (-1, 1):
        pts, nrm = [], []
        for k in range(10):
            q = k / 9
            a = math.radians(-90 + s * (38 + 30 * q ** 0.8))
            p, n = surface_point(T, T.t_at_z(1.012 - 0.085 * q), Vector((math.cos(a), math.sin(a), 0)), 0.0102)
            pts.append(p)
            nrm.append(n)
        lens(bm, pts, nrm, [0.0011] * 10, [0.0009] * 10, segs=6)
    for s in (-1, 1):
        pts, nrm = [], []
        for k in range(10):
            q = k / 9
            p, n = front_point(s * 0.03 * q ** 1.4, 0.875 - 0.04 * q, 0.0102, deform=None)
            pts.append(p)
            nrm.append(n)
        lens(bm, pts, nrm, [0.0012] * 10, [0.0009] * 10, segs=6)
    make_obj("PocketSeams", bm, ["line"], bones="torso_lower")
    bm = new_bm()
    tube(bm, T, T.t_at_z(1.010), T.t_at_z(1.044), add=0.015, lines=(0.5,))
    for ang in (-90 - 52, -90 + 52, 0, 180, 90 - 40, 90 + 40):
        a = math.radians(ang)
        p, n = surface_point(T, T.t_at_z(1.027), Vector((math.cos(a), math.sin(a), 0)), 0.017)
        box(bm, p, (0.010, 0.004, 0.040), (Z_AXIS.cross(n).normalized(), n, Z_AXIS))
    make_obj("Waistband", bm, ["jacket"], bones="torso_lower")

    for s in (-1, 1):
        lp = leg_path(s)
        side = ".L" if s > 0 else ".R"
        # Dark garter band with skin-colored triangle cut-outs.
        bm = new_bm()
        tube(bm, lp, lp.t_at_z(0.79), lp.t_at_z(0.755), add=0.006, segs=40)
        for j in range(10):
            a = 2 * math.pi * j / 10
            p, n = surface_point(lp, lp.t_at_z(0.773), Vector((math.cos(a), math.sin(a), 0)), 0.0062)
            up = 1 if j % 2 else -1
            flat_poly(bm, p, n, [(-0.008, -0.007 * up), (0.008, -0.007 * up), (0.0, 0.008 * up)], thick=0.0012, mat=1)
        make_obj("Garter" + side, bm, ["jacket", "skin"], bones="thigh" + side)

        # Socks: thigh-high on her left, short on her right.
        bm = new_bm()
        top = 0.665 if s > 0 else 0.40
        tube(bm, lp, lp.t_at_z(top), lp.t_at_z(0.09), add=0.0035, lines=(0.03,))
        make_obj("Sock" + side, bm, ["sock"], bones="leg" + side)

        # Boots: shaft, folded cuff, strap with buckle, shaped foot and sole.
        bm = new_bm()
        tube(bm, lp, lp.t_at_z(0.24), lp.t_at_z(0.06), add=lambda q: 0.016 + 0.004 * q,
             seams=[((0, -1, 0), 0.05, 0.75)])
        tube(bm, lp, lp.t_at_z(0.128), lp.t_at_z(0.102), add=0.027)
        bp, bn = surface_point(lp, lp.t_at_z(0.115), Vector((s, -0.3, 0)), 0.027)
        box(bm, bp, (0.016, 0.004, 0.02), (Z_AXIS.cross(bn).normalized(), bn, Z_AXIS), mat=1)
        ax = ANKLE.x * s + s * 0.004
        foot = Path([((ax, 0.05, 0.06), 0.034, 0.042), ((ax, 0.0, 0.062), 0.046, 0.056),
                     ((ax + s * 0.004, -0.07, 0.045), 0.050, 0.040), ((ax + s * 0.006, -0.125, 0.036), 0.040, 0.029),
                     ((ax + s * 0.006, -0.142, 0.033), 0.022, 0.018)])
        rows = tube(bm, foot, 0, 1, segs=28, cap0=True, cap1=True)
        for row in rows:
            for v in row:
                v.co.z = max(v.co.z, 0.021)
        make_obj("Boot" + side, bm, ["boot", "gold"], bones="leg" + side)
        bm = new_bm()
        tube(bm, lp, lp.t_at_z(0.275), lp.t_at_z(0.205), add=lambda q: 0.027 - 0.005 * q, lines=(0.5,))
        make_obj("BootCuff" + side, bm, ["bootcuff"], bones="leg" + side)
        bm = new_bm()
        sole = Path([((ax, 0.056, 0.012), 0.038, 0.012), ((ax, 0.0, 0.012), 0.050, 0.012),
                     ((ax + s * 0.004, -0.07, 0.012), 0.054, 0.012), ((ax + s * 0.006, -0.128, 0.012), 0.044, 0.012),
                     ((ax + s * 0.006, -0.15, 0.012), 0.022, 0.011)])
        tube(bm, sole, 0, 1, segs=24, cap0=True, cap1=True)
        make_obj("Sole" + side, bm, ["ribbon"], bones="foot" + side)

    # Translucent pink ribbon looped on her left wrist, trailing past the hand.
    x, y, z = HAND_AXES[1]
    w = arm_path(1).at(1)
    bm = new_bm()
    ring = Path([(w - z * 0.01 + (x * math.cos(a) + y * math.sin(a)) * 0.032, 0.006, 0.002)
                 for a in [2 * math.pi * k / 16 for k in range(17)]])
    tube(bm, ring, 0, 1, segs=10, rings=60)
    for k, off in enumerate((-0.012, 0.014)):
        pts, nrm, ws = [], [], []
        for i in range(24):
            q = i / 23
            p = w + y * (off + 0.02 * math.sin(q * 5 + k)) + z * (0.02 + 0.30 * q) + x * (0.03 * math.sin(q * 3.5 + k * 1.3) - 0.012)
            pts.append(p)
            nrm.append((x + y * 0.3 * math.cos(q * 4)).normalized())
            ws.append(0.012 * (1 - 0.6 * q) + 0.002)
        lens(bm, pts, nrm, ws, [0.0012] * 24, segs=8)
    make_obj("WristRibbon", bm, ["ribbon_glass"], bones="hand.L")


# ---------------------------------------------------------------------------
# Hair
# ---------------------------------------------------------------------------
TAIL_KEYS = {}


def head_clump(bm, th0, ph0, th1, ph1, w, thick=0.008, s0=1.10, s1=1.065, bow=0.025, n=20, ease=0.85, mat=0):
    pts, nrm, ws, ts = [], [], [], []
    for i in range(n):
        s = i / (n - 1)
        e = s ** ease
        th = th0 + (th1 - th0) * e
        ph = ph0 + (ph1 - ph0) * s
        sc = s0 + (s1 - s0) * s + bow * math.sin(math.pi * s)
        p = shell(th, ph, sc)
        pts.append(p)
        nrm.append((p - HEAD_C).normalized())
        ws.append(w * (0.62 + 0.55 * math.sin(math.pi * min(s * 1.15, 1.0))) * (1 - s ** 2.6) + 0.0006)
        ts.append(thick * (1 - 0.65 * s))
    lens(bm, pts, nrm, ws, ts, mat=mat)


def build_hair():
    # Base cap under the clumps, with the face window cut out.
    bm = new_bm()
    res = bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=32, radius=1.0)
    kill = []
    for v in res["verts"]:
        u = v.co.normalized()
        if (u.y < -0.18 and u.z < 0.40 and abs(u.x) < 0.84) or (u.z < -0.42 and u.y < 0.4) or u.z < -0.72:
            kill.append(v)
        v.co = head_point(u, 1.07)
    bmesh.ops.delete(bm, geom=kill, context="VERTS")
    make_obj("HairCap", bm, ["hair_dark"], bones="head", coll="Hair")

    # Clumps that flow from the side part and hairline up into each tail.
    bm = new_bm()
    roots = {s: (s * 128, 46) for s in (-1, 1)}
    starts = {
        -1: [(-20, 72), (-40, 54), (-64, 34), (-90, 10), (-125, -10), (-165, -28), (-35, 80)],
        1: [(-12, 76), (14, 66), (40, 52), (64, 36), (92, 12), (128, -10), (165, -28), (20, 80), (178, 40)],
    }
    for s in (-1, 1):
        rt, rp = roots[s]
        for th, ph in starts[s]:
            head_clump(bm, th, ph, rt, rp, 0.042, thick=0.007, s0=1.085, s1=1.0, bow=0.02, n=16, ease=1.0)
    make_obj("HairCrown", bm, ["hair"], bones="head", coll="Hair")

    # Bangs swept from the part on her right across to her left, and
    # face-framing locks down to the jaw.
    bm = new_bm()
    bangs = [
        (-22, 72, 46, -6, 0.036), (-18, 74, 28, 6, 0.030), (-26, 68, 62, -30, 0.032), (-14, 75, 12, 10, 0.028),
        (-30, 64, -4, 12, 0.026), (-35, 60, -38, -8, 0.030), (-45, 54, -60, -40, 0.030), (-52, 48, -72, -72, 0.028),
        (-8, 76, 38, 14, 0.026), (-26, 70, 20, 16, 0.024),
        (58, 42, 74, -68, 0.028), (70, 36, 88, -50, 0.025), (64, 40, 80, -30, 0.022),
    ]
    for th0, ph0, th1, ph1, w in bangs:
        head_clump(bm, th0, ph0, th1, ph1, w, thick=0.008, s0=1.105, s1=1.062, bow=0.03, n=22)
    make_obj("HairBangs", bm, ["hair"], bones="head", coll="Hair")

    # Twin high ponytails: flat clumps around a wavy centerline.
    for s in (-1, 1):
        side = ".L" if s > 0 else ".R"
        root = shell(s * 128, 46, 1.0)
        keys = [root, root + Vector((s * 0.05, 0.035, 0.065)), Vector((s * 0.15, 0.115, 1.80)),
                Vector((s * 0.19, 0.155, 1.62)), Vector((s * 0.195, 0.175, 1.42)), Vector((s * 0.185, 0.18, 1.22)),
                Vector((s * 0.17, 0.17, 1.04)), Vector((s * 0.15, 0.155, 0.88))]
        cl = Path([(k, 0.02) for k in keys])
        TAIL_KEYS[s] = [cl.at(i / 7) for i in range(8)]
        bm = new_bm()
        nclumps = 9
        for i in range(nclumps):
            a0 = 2 * math.pi * i / nclumps
            pts, nrm, ws, ts = [], [], [], []
            n = 60
            ext = 1.0 - 0.12 * ((i * 7) % 5) / 4  # uneven clump lengths
            for k in range(n):
                t = k / (n - 1) * ext
                c = cl.at(t)
                n1, n2 = frame(cl.tangent(t))
                spread = 0.006 + 0.036 * math.sin(math.pi * min(t * 1.5, 1.0)) * (1 - 0.4 * t)
                wave = 0.048 * smoothstep(0.18, 0.45, t) * (1 - 0.25 * t)
                ph = 2 * math.pi * 2.1 * t
                own = 2 * math.pi * 3.0 * t + i * 1.7
                od = n1 * math.cos(a0 + 0.6 * t) + n2 * math.sin(a0 + 0.6 * t)
                p = c + od * spread + (n1 * math.sin(ph) + n2 * 0.55 * math.cos(ph)) * wave
                p += (n1 * math.sin(own) + n2 * math.cos(own)) * 0.010 * smoothstep(0.3, 0.6, t)
                pts.append(p)
                nrm.append(od)
                ws.append(0.056 * (0.5 + 0.6 * math.sin(math.pi * min(t * 1.4, 1.0))) * (1 - (t / ext) ** 2.4) + 0.0008)
                ts.append(0.012 * (1 - 0.6 * t))
            lens(bm, pts, nrm, ws, ts, segs=10)
        # Solid core so the tail reads as one mass with a few strand lines.
        core = []
        for k in range(40):
            t = k / 39 * 0.9
            c = cl.at(t)
            n1, n2 = frame(cl.tangent(t))
            ph = 2 * math.pi * 2.1 * t
            wave = 0.048 * smoothstep(0.18, 0.45, t) * (1 - 0.25 * t)
            r = 0.006 + 0.034 * math.sin(math.pi * min(t * 1.5, 1.0)) * (1 - 0.5 * t) * (1 - (t / 0.9) ** 3)
            core.append((c + (n1 * math.sin(ph) + n2 * 0.55 * math.cos(ph)) * wave, r + 0.002))
        tube(bm, Path(core), 0, 1, segs=20, rings=60, cap0=True, cap1=True)
        make_obj("HairTail" + side, bm, ["hair"], bones="tail" + side, coll="Hair")

        # Hair tie and a curved cat-ear bow.
        bm = new_bm()
        d = (keys[1] - keys[0]).normalized()
        tube(bm, Path([(keys[0] + d * 0.006, 0.024), (keys[0] + d * 0.042, 0.022)]), 0, 1, segs=20, rings=4, cap0=True, cap1=True)
        up = Vector((s * 0.5, 0.05, 1.0)).normalized()
        fwd = Vector((s * 0.15, -1, 0.1))
        fwd = (fwd - up * fwd.dot(up)).normalized()
        across = up.cross(fwd)
        base = keys[0] + d * 0.02 + Vector((0, -0.01, 0.01))
        grid = []
        N = 8
        for vi in range(N + 1):
            v = vi / N
            row = []
            for ui in range(N + 1):
                u = ui / N
                q = base + across * (u - 0.5) * 0.085 * (1 - v) ** 0.9 + up * v * 0.085 - fwd * 0.014 * (1 - (2 * u - 1) ** 2) * (1 - v)
                row.append(bm.verts.new(q))
            grid.append(row)
        for vi in range(N):
            for ui in range(N):
                bm.faces.new((grid[vi][ui], grid[vi][ui + 1], grid[vi + 1][ui + 1], grid[vi + 1][ui]))
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
        bmesh.ops.solidify(bm, geom=bm.faces[:], thickness=0.007)
        make_obj("HairBow" + side, bm, ["jacket"], bones="head", coll="Hair")


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
    make_obj("Staff", bm, ["staff"], bones="staff", coll="Props")

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
    make_obj("StaffGold", bm, ["gold"], bones="staff", coll="Props")

    bm = new_bm()
    for a, b in ((95, 280), (128, 335), (200, 355), (112, 240), (160, 300), (230, 15)):
        tube(bm, Path([(rp(a, R * 0.98), 0.0016), (rp(b, R * 0.98), 0.0016)]), 0, 1, segs=6, rings=2)
    make_obj("StaffLines", bm, ["line"], bones="staff", coll="Props")


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
    make_obj("WitchHat", bm, ["boot", "ribbon", "gold"], bones="hat", coll="Props")


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
        parent = "head"
        for i in range(7):
            n = f"tail{x}.{i}"
            B[n] = (TAIL_KEYS[s][i], TAIL_KEYS[s][i + 1], parent)
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
    for name, (h, t, _) in BONES.items():
        eb = arm.edit_bones.new(name)
        eb.head, eb.tail = h, t
    for name, (_, _, p) in BONES.items():
        if p:
            eb = arm.edit_bones[name]
            eb.parent = arm.edit_bones[p]
            eb.use_connect = name.startswith("tail") and (eb.head - eb.parent.tail).length < 1e-5
        arm.edit_bones[name].use_deform = name != "root"
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in ob.pose.bones:
        pb.rotation_mode = "QUATERNION"
    return ob


GROUPS = {
    "body": ["hips", "spine", "chest", "neck", "upper_arm.L", "upper_arm.R", "forearm.L", "forearm.R", "hand.L",
             "hand.R", "thigh.L", "thigh.R", "shin.L", "shin.R", "foot.L", "foot.R"],
    "torso_upper": ["spine", "chest", "neck", "upper_arm.L", "upper_arm.R"],
    "torso_lower": ["hips", "spine", "thigh.L", "thigh.R"],
    "tie": ["chest", "neck"],
    "leg.L": ["shin.L", "foot.L", "thigh.L"],
    "leg.R": ["shin.R", "foot.R", "thigh.R"],
    "tail.L": [f"tail.L.{i}" for i in range(7)],
    "tail.R": [f"tail.R.{i}" for i in range(7)],
}
BUST_GROUPS = ("body", "torso_upper", "tie")


def seg_dist(p, a, b):
    ab = b - a
    t = clamp((p - a).dot(ab) / ab.length_squared, 0.0, 1.0)
    return (p - (a + ab * t)).length


def bind(rig):
    for ob, bones in PARTS:
        allowed = GROUPS.get(bones, [bones])
        names = set(allowed)
        if bones in BUST_GROUPS:
            names |= {"breast.L", "breast.R"}
        groups = {b: ob.vertex_groups.new(name=b) for b in names}
        for v in ob.data.vertices:
            p = v.co
            cands = []
            for b in allowed:
                # Keep left and right limbs from pulling on each other.
                if not b.startswith("tail") and ((b.endswith(".L") and p.x < -0.03) or (b.endswith(".R") and p.x > 0.03)):
                    continue
                h, t, _ = BONES[b]
                cands.append((seg_dist(p, h, t), b))
            cands = sorted(cands)[:3] or [(0.0, allowed[0])]
            ws = [1.0 / (d * d + 1e-5) ** 2 for d, _ in cands]
            tot = sum(ws)
            weights = {b: w / tot for (_, b), w in zip(cands, ws)}
            if bones in BUST_GROUPS and 1.15 < p.z < 1.42:
                fl, fr = bust_field(p)
                fl, fr = clamp(fl * 1.3, 0, 1), clamp(fr * 1.3, 0, 1)
                keep = max(0.0, 1.0 - fl - fr)
                weights = {b: w * keep for b, w in weights.items()}
                weights["breast.R"], weights["breast.L"] = fl, fr
            for b, w in weights.items():
                if w > 0.01:
                    groups[b].add([v.index], w, "REPLACE")
        ob.parent = rig
        ob.modifiers.new("Armature", "ARMATURE").object = rig


# ---------------------------------------------------------------------------
# Posing: manual forward kinematics so poses and physics can be computed
# exactly, then written to the bones as keyframes.
# ---------------------------------------------------------------------------
class Poser:
    def __init__(self, rig):
        self.rig = rig
        self.rest = {b.name: b.matrix_local.copy() for b in rig.data.bones}
        self.parent = {b.name: (b.parent.name if b.parent else None) for b in rig.data.bones}
        self.basis, self.loc, self.M = {}, {}, {}

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
        return self.set(name, q, A.to_3x3().inverted() @ world_off)

    def aim(self, name, d):
        A = self.base(name)
        Q = A.col[1].xyz.normalized().rotation_difference(Vector(d).normalized())
        A3 = A.to_3x3()
        return self.set(name, (A3.inverted() @ Q.to_matrix() @ A3).to_quaternion())

    def aim_align(self, name, d, axis_rest, target):
        """Aim the bone along d, then twist it so a rest-space axis of the
        skinned mesh points as close to `target` as possible."""
        self.aim(name, d)
        cur = self.M[name].to_3x3() @ self.rest[name].to_3x3().inverted() @ axis_rest
        dn = Vector(d).normalized()
        a = (cur - dn * cur.dot(dn)).normalized()
        b = (target - dn * target.dot(dn)).normalized()
        ang = math.atan2(a.cross(b).dot(dn), a.dot(b))
        return self.set(name, self.basis[name] @ Quaternion((0, 1, 0), ang))

    def head(self, name):
        return self.base(name).translation.copy()

    def length(self, name):
        return self.rig.data.bones[name].length

    def two_bone(self, a, b, target, pole):
        S = self.head(a)
        L1, L2 = self.length(a), self.length(b)
        d = target - S
        dist = clamp(d.length, abs(L1 - L2) + 1e-4, L1 + L2 - 1e-4)
        dn = d.normalized()
        x = (L1 * L1 - L2 * L2 + dist * dist) / (2 * dist)
        h = math.sqrt(max(L1 * L1 - x * x, 0.0))
        E = S + dn * x + (pole - dn * pole.dot(dn)).normalized() * h
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

    # Right fist around the planted staff, thumb on top.
    d_r = Vector((-0.84, -0.54, 0.0)).normalized()
    palm_r = Z_AXIS.cross(d_r).normalized()
    wrist_r = STAFF_GRIP - d_r * 0.07 - palm_r * 0.024
    P.two_bone("upper_arm.R", "forearm.R", wrist_r, Vector((-0.2, 1.0, -0.4)))
    P.aim_align("hand.R", d_r, HAND_AXES[-1][1], Z_AXIS)
    # Left hand on the hip, palm against the body.
    wrist_l = P.M["hips"] @ (P.rest["hips"].inverted() @ HIP_HAND)
    P.two_bone("upper_arm.L", "forearm.L", wrist_l, Vector((1.0, 0.7, 0.1)))
    P.aim_align("hand.L", Vector((-0.45, 0.25, -0.85)), HAND_AXES[1][0], Vector((1, -0.1, 0)))

    # Legs: two-bone IK to planted feet, weight on her right leg.
    P.two_bone("thigh.R", "shin.R", Vector((-0.085, 0.03, 0.09)), Vector((0, -1, 0)))
    P.aim("foot.R", Vector((-0.12, -0.9, -0.45)))
    P.two_bone("thigh.L", "shin.L", Vector((0.11, -0.13, 0.09)), Vector((0.25, -1, 0)))
    P.aim("foot.L", Vector((0.3, -0.85, -0.45)))

    P.set_world_offset("staff", Vector((STAFF_GRIP.x - STAFF_REST.x, STAFF_GRIP.y - STAFF_REST.y, 0.0)),
                       Quaternion((0, 1, 0), -0.45))
    P.set("hat", Quaternion((0, 0, 1), 0.05 * math.sin(ph * 2)), Vector((0, 0.012 * math.sin(ph * 2), 0)))

    # Breasts: a damped spring point trailing a rest target on the chest.
    for s in (-1, 1):
        name = "breast" + (".L" if s > 0 else ".R")
        A = P.base(name)
        rest_tip = A @ Vector((0, P.length(name), 0))
        st = sims.setdefault(name, {"p": rest_tip.copy(), "v": Vector()})
        for _ in range(4):
            h = dt / 4
            st["v"] += ((rest_tip - st["p"]) * 170.0 - st["v"] * 4.5) * h
            st["p"] += st["v"] * h
        off = st["p"] - rest_tip
        if off.length > 0.035:
            off = off.normalized() * 0.035
            st["p"] = rest_tip + off
        P.aim(name, (rest_tip + off * 1.6) - A.translation)

    # Ponytails: verlet chains with shape memory toward the rest curve.
    for s in (-1, 1):
        x = ".L" if s > 0 else ".R"
        names = [f"tail{x}.{i}" for i in range(7)]
        rest = [P.base(names[0]).translation.copy()]
        Mh = P.M["head"]
        for n in names:
            rest.append(Mh @ (P.rest["head"].inverted() @ (P.rest[n] @ Vector((0, P.length(n), 0)))))
        st = sims.setdefault("tail" + x, {"p": [r.copy() for r in rest], "q": [r.copy() for r in rest]})
        p, q = st["p"], st["q"]
        sub = 4
        for _ in range(sub):
            p[0], q[0] = rest[0].copy(), rest[0].copy()
            for i in range(1, len(p)):
                vel = (p[i] - q[i]) * 0.96
                q[i] = p[i].copy()
                p[i] = p[i] + vel + Vector((0, 0, -0.35)) * (dt / sub) ** 2
            for i in range(1, len(p)):
                p[i] = p[i] + (p[i - 1] + (rest[i] - rest[i - 1]) - p[i]) * 0.10 * (1 - 0.55 * i / len(p))
            for i in range(1, len(p)):
                p[i] = p[i - 1] + (p[i] - p[i - 1]).normalized() * (rest[i] - rest[i - 1]).length
                p[i].y = max(p[i].y, 0.13)  # keep the tails off her back
        for i, n in enumerate(names):
            P.aim(n, p[i + 1] - P.head(n))


def animate(rig):
    scn = bpy.context.scene
    scn.render.fps = FPS
    scn.frame_start, scn.frame_end = 1, FRAMES
    P = Poser(rig)
    sims = {}
    for f in range(1, FRAMES * 2 + 1):  # the first loop settles the physics
        P.basis.clear()
        P.loc.clear()
        P.M.clear()
        pose_frame(P, f, sims, 1.0 / FPS)
        if f > FRAMES:
            P.key(f - FRAMES)
    rig.animation_data.action.name = "Idle_Jiggle"
    scn.frame_set(1)


# ---------------------------------------------------------------------------
# Face texture
# ---------------------------------------------------------------------------
def paint_face(path):
    from PIL import Image, ImageDraw, ImageFilter

    S = 2048
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    def px(x, z):  # unit-head meters -> pixels
        return ((x * 5.2632 + 0.5) * S, (1 - (z + 0.12) * 5.0) * S)

    def bez(p0, p1, p2, n=28):
        return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                 (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in (i / n for i in range(n + 1))]

    def taper_line(d, pts, w0, w1, col):
        for i in range(len(pts) - 1):
            w = w0 + (w1 - w0) * i / (len(pts) - 2 or 1)
            d.line([pts[i], pts[i + 1]], fill=col, width=max(1, int(w)))
            d.ellipse((pts[i][0] - w / 2, pts[i][1] - w / 2, pts[i][0] + w / 2, pts[i][1] + w / 2), fill=col)

    soft = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(soft)
    for s in (-1, 1):
        cx, cy = px(s * 0.046, -0.034)
        sd.ellipse((cx - 85, cy - 36, cx + 85, cy + 36), fill=(226, 120, 138, 70))
    img = Image.alpha_composite(img, soft.filter(ImageFilter.GaussianBlur(30)))
    d = ImageDraw.Draw(img)

    lash = (36, 20, 26, 255)
    for s in (-1, 1):
        cx, cy = px(s * 0.034, -0.008)
        w, h = 0.021 * 5.2632 * S, 0.0145 * 5.0 * S

        def E(x, y):  # eye-local (outer corner at x=+1) -> pixels
            return (cx + s * x * w, cy - y * h)

        upper = bez(E(-1, -0.08), E(0.15, 1.25), E(1.0, 0.28))
        lower = bez(E(1.0, 0.28), E(0.2, -0.95), E(-1, -0.08))
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).polygon(upper + lower, fill=255)
        layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.polygon(upper + lower, fill=(250, 244, 242, 255))
        ix, iy = E(0.02, 0.08)
        rx, ry = 0.62 * h, 0.72 * h
        for k in range(28):  # iris gradient, dark at the top
            t = k / 27
            col = tuple(int(a + (b - a) * t) for a, b in zip((78, 24, 38), (196, 104, 114)))
            top = iy - ry + t * ry * 1.2
            ld.ellipse((ix - rx * (1 - 0.1 * t), top, ix + rx * (1 - 0.1 * t), iy + ry), fill=(*col, 255))
        ld.ellipse((ix - rx, iy - ry, ix + rx, iy + ry), outline=(64, 20, 32, 255), width=8)
        ld.ellipse((ix - rx * 0.4, iy - ry * 0.42, ix + rx * 0.4, iy + ry * 0.42), fill=(40, 12, 20, 255))
        ld.polygon(upper + [E(1.2, 1.4), E(-1.2, 1.4)], fill=(120, 60, 76, 110))  # lid shadow
        clipped = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        clipped.paste(layer, (0, 0), mask)
        img = Image.alpha_composite(img, clipped)
        d = ImageDraw.Draw(img)
        hx, hy = ix - s * rx * 0.35, iy - ry * 0.4
        d.ellipse((hx - 15, hy - 18, hx + 15, hy + 18), fill=(255, 255, 255, 255))
        d.ellipse((ix + s * rx * 0.35 - 7, iy + ry * 0.4 - 7, ix + s * rx * 0.35 + 7, iy + ry * 0.4 + 7), fill=(255, 238, 240, 230))
        taper_line(d, upper, 9, 17, lash)
        taper_line(d, bez(E(0.75, 0.62), E(1.15, 0.52), E(1.42, 0.68), 12), 15, 4, lash)
        taper_line(d, bez(E(1.0, 0.28), E(0.55, -0.62), E(-0.15, -0.8), 18), 5, 2, (116, 56, 64, 255))
        d.line(bez(E(-0.7, 1.0), E(0.1, 1.7), E(0.95, 1.08), 18), fill=(140, 82, 90, 220), width=5)
        for k in range(3):  # tiny under-eye marks, as in the reference
            fx, fy = E(0.1 + 0.35 * k, -1.35 - 0.1 * k)
            d.line([(fx, fy), (fx + s * 6, fy + 9)], fill=(190, 120, 120, 170), width=4)
        bx, by = px(s * 0.012, 0.024)
        ex, ey = px(s * 0.058, 0.030)
        taper_line(d, bez((bx, by), ((bx + ex) / 2, by - 30), (ex, ey), 20), 13, 5, (128, 50, 64, 255))

    nx, ny = px(0.003, -0.040)
    d.line([(nx - 12, ny + 2), (nx + 14, ny + 6)], fill=(170, 110, 112, 255), width=6)
    d.line([(nx - 22, ny - 40), (nx - 14, ny - 6)], fill=(214, 168, 166, 200), width=5)
    ul = bez(px(-0.022, -0.066), px(0.0, -0.069), px(0.022, -0.064))
    ll = bez(px(0.019, -0.066), px(0.0, -0.083), px(-0.019, -0.067))
    d.polygon(ul + ll, fill=(122, 42, 54, 255))
    teeth = bez(px(-0.018, -0.0665), px(0.0, -0.0705), px(0.018, -0.065)) + bez(px(0.016, -0.0695), px(0.0, -0.0745), px(-0.016, -0.0705))
    d.polygon(teeth, fill=(250, 244, 242, 255))
    taper_line(d, ul, 6, 8, (96, 36, 46, 255))
    d.line(bez(px(-0.012, -0.0875), px(0.0, -0.091), px(0.012, -0.087), 12), fill=(204, 136, 140, 220), width=6)
    img.resize((1024, 1024), Image.LANCZOS).save(path)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def setup_render():
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.device = "CPU"
    scn.cycles.samples = 12 if QUICK else 40
    scn.cycles.use_denoising = False
    scn.cycles.max_bounces = 4
    scn.cycles.transparent_max_bounces = 32
    scn.view_settings.view_transform = "Standard"
    scn.view_settings.look = "None"
    world = bpy.data.worlds.new("Backdrop")
    world.color = lin(BG)
    use_nodes(world)
    world.node_tree.nodes["Background"].inputs["Color"].default_value = rgba(BG)
    scn.world = world

    # Freestyle ink: silhouettes, creases, material borders and marked seams.
    scn.render.use_freestyle = True
    scn.render.line_thickness_mode = "RELATIVE"
    vl = scn.view_layers[0]
    vl.use_freestyle = True
    fs = vl.freestyle_settings
    fs.crease_angle = math.radians(100)
    ls = fs.linesets[0]
    ls.select_by_visibility = True
    ls.visibility = "VISIBLE"
    ls.select_by_edge_types = True
    for attr in ("select_silhouette", "select_border", "select_crease", "select_material_boundary",
                 "select_edge_mark", "select_external_contour", "select_contour"):
        setattr(ls, attr, True)
    if ls.linestyle is None:
        ls.linestyle = bpy.data.linestyles.new("Ink")
    st = ls.linestyle
    st.color = lin(INK)
    st.thickness = 0.55
    st.thickness_position = "CENTER"


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
    ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return ob


def render(cam, path, rx, ry):
    scn = bpy.context.scene
    scn.camera = cam
    scn.render.resolution_x, scn.render.resolution_y = rx, ry
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)


def export_glb():
    """Export a .glb for game engines. glTF cannot carry the node-based toon
    shading or Freestyle lines, so materials fall back to flat base colors."""
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
    sheet = Image.new("RGB", (sum(v.width for v in views) + hero.width, H), tuple(int(BG[i:i + 2], 16) for i in (1, 3, 5)))
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
    animate(rig)
    setup_render()

    cams = {
        "hero": camera("Cam_Hero", (-1.4, -2.75, 1.28), (-0.1, 0, 1.12), lens=35),
        "face": camera("Cam_Face", (-0.3, -0.75, 1.64), (-0.02, 0, 1.62), lens=50),
        "front": camera("Cam_Front", (0, -5, 1.0), (0, 0, 1.0), ortho=2.25),
        "side": camera("Cam_Side", (5, 0, 1.0), (0, 0, 1.0), ortho=2.25),
        "back": camera("Cam_Back", (0, 5, 1.0), (0, 0, 1.0), ortho=2.25),
    }
    bpy.context.scene.camera = cams["hero"]
    blend = os.path.join(HERE, "witch_character.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True)

    if "--no-render" not in sys.argv:
        big = 1 if QUICK else 2
        render(cams["hero"], os.path.join(RENDER_DIR, "hero.png"), 600 * big, 800 * big)
        render(cams["face"], os.path.join(RENDER_DIR, "face_closeup.png"), 500 * big, 500 * big)
        rig.data.pose_position = "REST"
        for k in ("front", "side", "back"):
            render(cams[k], os.path.join(RENDER_DIR, f"turnaround_{k}.png"), 400 * big, 640 * big)
        rig.data.pose_position = "POSE"
        compose_sheet()
    if "--glb" in sys.argv:
        export_glb()
    print("Saved", blend)


if __name__ == "__main__":
    main()
