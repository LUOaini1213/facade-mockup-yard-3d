"""Builds model/site_context.glb: the context around the mock-up yard in its future completed state - the 1-storey shed
(RC columns, ribbed cladding band, duo-pitch roof, overhead crane bridges, roof lattice towers), the 2-storey factory
west and north blocks (bare RC frame + steel roof storey), the accessway truss canopy, boundary hoarding, chain-link
fence and gate, the gantry crane parked on its rails (clear of the mock-ups), high masts, containers + site office,
the temporary viewing platform and stillages. All geometry comes from the layout plan, the site survey (DXF) and site
photos; buildings further away are not modelled. Needs the private survey extract in SOURCES_DIR.
"""
import os, sys, io, json, math, collections, warnings
import numpy as np
import shapely.geometry as sg
from shapely.geometry.polygon import orient
import mapbox_earcut as earcut

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CALLER_CWD = os.getcwd()
SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')

def _env_path(name):
    v = os.environ.get(name)
    return os.path.abspath(os.path.join(CALLER_CWD, v)) if v else None

os.chdir(HERE)
sys.path.insert(0, HERE)
from gltfw import GLB
import materials_lib as ML
from site_frame import r3_to_gltf, s as S_PT

warnings.simplefilter('ignore', UserWarning)

Q6_NORTH_BLOCK_STATE = 'frame'
WEST_FACTORY_STATE = os.environ.get('MOCKUP_WEST_FACTORY_STATE', 'frame')
WEST_TALL_BLOCK_TOP = 29.0 - 4.5
WEST_FACTORY_RC_TOP = 19.8
YELLOW_LATTICE_HOST = 'shed'
PLATFORM_POSITION = 'r3'
PLATFORM_DECK_H = 3.0
INCLUDE_YARD_SLAB = False
SHOW_SITE_OFFICE = True
SHOW_STILLAGES = True
SHOW_MASTS = True
SHOW_MOBILE_PLANT = False
HOARDING_H = 2.4
SOUTH_BOUNDARY_TYPE = 'chainlink_1.8'
CHAINLINK_H = 1.8
CHAINLINK_POST_SPACING = 2.5
CHAINLINK_DIAMOND_M = 0.075
ACCESSWAY_CANOPY = True
# plan rectangle of the accessway canopy, from the layout plan and two site photos only:
#   x (across the accessway): one photo shows the long lattice girder running from the shed end to the north block, so the
#     canopy spans the accessway between the two building lines, 2 pt inside each: x0 = 633.0 (the shed-side line, plan
#     x ~630-631: the accessway edge on the layout plan and the end of the modelled shed / west-block frames), x1 = 692.0
#     (the north-block face, plan x 694).
#   y (along the accessway): the two photo estimates of its position are plan y 200-240 and 230-290; y0 / y1 = the centres of
#     the two ranges (220 / 260). The centre, 240, lies between the shed's end line (y 247) and the north block's end (y 235.4).
ACCESSWAY_CANOPY_PAGE = (633.0, 692.0, 220.0, 260.0)   # plan x0, x1 (across the accessway), y0, y1
ACCESSWAY_CANOPY_TOP = 9.0
NORTH_BLOCK_STAIR = 'ssw_face'
HOARDING_N_EXTEND_M = 170.0
GATE_STATE = 'closed'

GANTRY_RAILS_SOURCE = 'ground'
GANTRY_RAILS_PAGE_X = (493.15, 617.35)
GANTRY_PARK_PAGE_Y = None
GANTRY_PARK_TARGET_Y = 600.4
GANTRY_CAMERA_CLEAR = 0.3
GANTRY_GIRDER_SOFFIT = 10.0
GANTRY_GIRDER_DEPTH = 1.4
GANTRY_GIRDER_W = 0.9
GANTRY_LEG_SPLAY = 5.8
GANTRY_OVERHANG = 1.3
GANTRY_CLEARANCE = 0.6
GANTRY_HOIST_AT = None
GANTRY_HOIST_TARGET_PAGE_X = 562.0
GANTRY_HOIST_TARGET = None

OUT = _env_path('MOCKUP_CONTEXT_OUT') or os.path.join(ROOT, 'model', 'site_context.glb')
SCRATCH = _env_path('MOCKUP_CONTEXT_SCRATCH') or os.path.join(HERE, '_scratch', 'context')
os.makedirs(SCRATCH, exist_ok=True)
os.makedirs(os.path.dirname(OUT), exist_ok=True)

SITE = json.load(open(os.path.join(SOURCES_DIR, 'site_survey.json'), encoding='utf-8'))
_T = SITE['transform_dxf_to_r3m']
_TC, _TS, _TK = math.cos(_T['theta_rad']), math.sin(_T['theta_rad']), _T['scale_m_per_unit']

def dxf(x, y):
    return np.array([_TK * (_TC * x - _TS * y) + _T['tx'], _TK * (_TS * x + _TC * y) + _T['ty']])

def pg(px, py):
    return np.array([px * S_PT, -py * S_PT])

def to_page(P):
    P = np.atleast_2d(P)
    return np.c_[P[:, 0] / S_PT, -P[:, 1] / S_PT]

def gltf_xz_to_r3(xz):
    from site_frame import ex, ey, O
    xz = np.atleast_2d(np.asarray(xz, float)); E = xz[:, 0]; N = -xz[:, 1]
    M = np.array([[ex[0], ey[0]], [ex[1], ey[1]]])
    return (np.linalg.solve(M, np.vstack([E, N])).T + O)

def unit(v):
    v = np.asarray(v, float); n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v

def perp(u):
    return np.array([-u[1], u[0]])

class GLBX(GLB):
    def __init__(s):
        super().__init__(); s.images = []; s.textures = []; s.samplers = []

    def texture_png(s, png):
        bv = s._view(png)
        s.images.append({'bufferView': bv, 'mimeType': 'image/png'})
        if not s.samplers:
            s.samplers.append({'magFilter': 9729, 'minFilter': 9987, 'wrapS': 33071, 'wrapT': 33071})
        s.textures.append({'sampler': 0, 'source': len(s.images) - 1})
        return len(s.textures) - 1

    def material_tex(s, name, tex, metal, rough, extras):
        m = {'name': name, 'pbrMetallicRoughness': {'baseColorFactor': [1.0, 1.0, 1.0, 1.0], 'baseColorTexture': {'index': tex},
                                                    'metallicFactor': float(metal), 'roughnessFactor': float(rough)},
             'doubleSided': True, 'extras': extras}
        s.materials.append(m); s.matidx[name] = len(s.materials) - 1
        return s.matidx[name]

    def save(s, path, extras=None):
        import struct
        while len(s.bin) % 4: s.bin += b'\0'
        g = {'asset': {'version': '2.0', 'generator': 'mock-up site builder (build_context2.py)'}, 'scene': 0,
             'scenes': [{'nodes': s.roots, 'extras': extras or {}}], 'nodes': s.nodes, 'meshes': s.meshes, 'materials': s.materials,
             'accessors': s.accessors, 'bufferViews': s.bufferViews, 'buffers': [{'byteLength': len(s.bin)}]}
        if s.images:
            g['images'] = s.images; g['textures'] = s.textures; g['samplers'] = s.samplers
        js = json.dumps(g, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        while len(js) % 4: js += b' '
        with open(path, 'wb') as f:
            f.write(struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(s.bin)))
            f.write(struct.pack('<II', len(js), 0x4E4F534A)); f.write(js)
            f.write(struct.pack('<II', len(s.bin), 0x004E4942)); f.write(s.bin)

glb = GLBX()
MATS = {}

SUPP = {
    'CTX_STEEL_GREY': ('#8E9499', 0.3, 0.55, None, 'grey painted steel: crane runways, hoist trolleys, stair flights, DB box',
                       ''),
    'CTX_CONTAINER_GREY': ('#A3A7A5', 0.0, 0.50, None, 'light-grey storage containers in the R3 container row (mixed with white)',
                           ''),
    'CTX_LAMP': ('#FFF4DC', 0.0, 0.30, (0.55, 0.52, 0.45), 'floodlight lenses (emissive)', ''),
    'CTX_FENCE_MESH': ('#9AA39C', 0.6, 0.45, None, 'galvanised chain-link mesh panel (SSW 1.8 m fence); alpha 0.35 here, the viewer '
                       'replaces it by its alpha chain-link texture (viewer.js fallbackMaterial)', ''),
}
SUPP_ALPHA = {'CTX_FENCE_MESH': 0.35}

def M(name):
    if name in MATS: return MATS[name]
    if name in SUPP:
        hx, metal, rough, emis, note, src = SUPP[name]
        lin = ML.hex_to_linear(hx)
        MATS[name] = glb.material(name, lin, SUPP_ALPHA.get(name, 1.0), metal, rough, emissive=emis,
                                  extras={'srgb': hx, 'linear': [round(c, 4) for c in lin], 'supplementary': True,
                                          'contract': 'not in contract (build step supplementary)', 'note': '', 'source': ''})
    else:
        MATS[name] = ML.mat(glb, name)
    return MATS[name]

PARTS = collections.OrderedDict()
GROUP_META = collections.OrderedDict()

def group(name, **meta):
    GROUP_META.setdefault(name, {}).update(meta)
    return name

def L(grp, layer, mat, source, confidence, **extra):
    k = (grp, layer)
    if k in PARTS:
        assert PARTS[k]['mat'] == mat, (k, mat)
    else:
        PARTS[k] = dict(mat=mat, V=[], F=[], UV=[], n=0, meta=dict(source='', confidence=confidence, **extra))
    return k

def _add(k, V, F, UV):
    p = PARTS[k]
    p['V'].append(np.asarray(V, float)); p['F'].append(np.asarray(F, np.int64) + p['n']); p['UV'].append(np.asarray(UV, float))
    p['n'] += len(V)

def face_uv(V, n):
    if abs(n[2]) > 0.7:
        return V[:, :2].copy()
    t = np.array([-n[1], n[0], 0.0]); ln = np.linalg.norm(t)
    t = t / ln if ln > 1e-9 else np.array([1.0, 0.0, 0.0])
    return np.c_[V @ t, V[:, 2]]

def poly(k, P, uv=None):
    V = np.asarray(P, float)
    n = np.cross(V[1] - V[0], V[2] - V[0])
    if np.linalg.norm(n) < 1e-12 and len(V) > 3: n = np.cross(V[2] - V[0], V[3] - V[0])
    ln = np.linalg.norm(n)
    if ln < 1e-12: return
    n = n / ln
    F = [[0, i, i + 1] for i in range(1, len(V) - 1)]
    _add(k, V, F, face_uv(V, n) if uv is None else uv)

def quad(k, a, b, c, d, uv=None): poly(k, [a, b, c, d], uv)

def quad_out(k, a, b, c, d, centre):
    V = np.array([a, b, c, d], float); n = np.cross(V[1] - V[0], V[2] - V[0])
    if n @ (V.mean(0) - np.asarray(centre, float)) < 0: V = V[::-1]
    poly(k, V)

def ccw(P):
    P = [np.asarray(p, float)[:2] for p in P]
    a = sum(P[i][0] * P[(i + 1) % len(P)][1] - P[(i + 1) % len(P)][0] * P[i][1] for i in range(len(P)))
    return P if a > 0 else P[::-1]

def prism(k, P, z0, z1, top=True, bottom=True, sides=True):
    P = ccw(P); n = len(P)
    lo = [np.r_[p, z0] for p in P]; hi = [np.r_[p, z1] for p in P]
    if sides:
        for i in range(n):
            j = (i + 1) % n; quad(k, lo[i], lo[j], hi[j], hi[i])
    if n <= 4 and _convex(P):
        if top: poly(k, hi)
        if bottom: poly(k, lo[::-1])
    else:
        v = np.array(P); t = earcut.triangulate_float64(v, np.array([len(v)], np.uint32)).reshape(-1, 3)
        for zz, up in ((z1, top), (z0, bottom)):
            if not up: continue
            V = np.c_[v, np.full(len(v), zz)]
            tt = t.copy()
            a, b, c = V[tt[:, 0]], V[tt[:, 1]], V[tt[:, 2]]
            nz = np.cross(b - a, c - a)[:, 2]
            want = 1 if zz == z1 else -1
            bad = nz * want < 0; tt[bad] = tt[bad][:, ::-1]
            _add(k, V, tt, V[:, :2])

def _convex(P):
    s = None
    for i in range(len(P)):
        a, b, c = P[i], P[(i + 1) % len(P)], P[(i + 2) % len(P)]
        cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cr) < 1e-12: continue
        if s is None: s = cr > 0
        elif (cr > 0) != s: return False
    return True

def obox(k, c, u, hu, hv, z0, z1, **kw):
    u = unit(u); v = perp(u); c = np.asarray(c, float)
    prism(k, [c - u * hu - v * hv, c + u * hu - v * hv, c + u * hu + v * hv, c - u * hu + v * hv], z0, z1, **kw)

def seg_box(k, A, B, w, z0, z1, ext=0.0, **kw):
    A = np.asarray(A, float); B = np.asarray(B, float); d = B - A; ln = np.linalg.norm(d)
    if ln < 1e-6: return
    obox(k, (A + B) / 2, d, ln / 2 + ext, w / 2, z0, z1, **kw)

def member(k, A3, B3, w, h=None, w1=None, h1=None, up=(0, 0, 1)):
    A3 = np.asarray(A3, float); B3 = np.asarray(B3, float); t = unit(B3 - A3)
    ref = np.asarray(up, float)
    if abs(t @ ref) > 0.97: ref = np.array([1.0, 0, 0]) if abs(t[0]) < 0.9 else np.array([0, 1.0, 0])
    a = unit(np.cross(ref, t)); b = np.cross(t, a)
    h = h if h is not None else w; w1 = w1 if w1 is not None else w; h1 = h1 if h1 is not None else h
    ra = [A3 + a * sx * w / 2 + b * sy * h / 2 for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1))]
    rb = [B3 + a * sx * w1 / 2 + b * sy * h1 / 2 for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1))]
    cen = (A3 + B3) / 2
    for i in range(4):
        j = (i + 1) % 4; quad_out(k, ra[i], ra[j], rb[j], rb[i], cen)
    quad_out(k, *ra, cen); quad_out(k, *rb, cen)

def cyl(k, c, r0, r1, z0, z1, n=16, top=True, bottom=False):
    c = np.asarray(c, float); ang = np.linspace(0, 2 * np.pi, n + 1)[:-1]
    cs = np.c_[np.cos(ang), np.sin(ang)]
    lo = np.c_[c + cs * r0, np.full(n, z0)]; hi = np.c_[c + cs * r1, np.full(n, z1)]
    V = np.r_[lo, hi]; F = []
    for i in range(n):
        j = (i + 1) % n; F += [[i, j, n + j], [i, n + j, n + i]]
    UV = np.c_[np.r_[ang, ang] * max(r0, r1), V[:, 2]]
    _add(k, V, F, UV)
    if top: poly(k, list(hi))
    if bottom: poly(k, list(lo[::-1]))

def lattice_panel(k_chord, k_lace, P0, P1, Q0, Q1, n, chord=0.1, lace=0.05):
    P0, P1, Q0, Q1 = [np.asarray(x, float) for x in (P0, P1, Q0, Q1)]
    member(k_chord, P0, P1, chord); member(k_chord, Q0, Q1, chord)
    for i in range(n + 1):
        t = i / n; a = P0 + (P1 - P0) * t; b = Q0 + (Q1 - Q0) * t
        member(k_lace, a, b, lace)
        if i < n:
            t2 = (i + 1) / n; c = Q0 + (Q1 - Q0) * t2 if i % 2 == 0 else P0 + (P1 - P0) * t2
            member(k_lace, a if i % 2 == 0 else b, c, lace)

def prism_poly(k, pl, z0, z1, top=True, bottom=False, sides=True):
    for p in (list(pl.geoms) if hasattr(pl, 'geoms') else [pl]):
        if p.is_empty or p.area < 1e-6: continue
        p = orient(p, 1.0)
        rings = [np.asarray(p.exterior.coords)[:-1]] + [np.asarray(r.coords)[:-1] for r in p.interiors]
        if sides:
            for R_ in rings:
                n = len(R_)
                for i in range(n):
                    j = (i + 1) % n
                    a, b = R_[i], R_[j]
                    if np.linalg.norm(b - a) < 1e-6: continue
                    quad(k, np.r_[a, z0], np.r_[b, z0], np.r_[b, z1], np.r_[a, z1])
        v = np.vstack(rings); ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
        t = earcut.triangulate_float64(v, ends).reshape(-1, 3)
        for zz, want, on in ((z1, 1, top), (z0, -1, bottom)):
            if not on or not len(t): continue
            V = np.c_[v, np.full(len(v), zz)]; tt = t.copy()
            a, b, c = V[tt[:, 0]], V[tt[:, 1]], V[tt[:, 2]]
            bad = np.cross(b - a, c - a)[:, 2] * want < 0; tt[bad] = tt[bad][:, ::-1]
            _add(k, V, tt, V[:, :2])

def polys_of(g):
    if g is None or g.is_empty: return []
    if g.geom_type == 'Polygon': return [g] if g.area >= 0.05 else []
    return [q for gg in getattr(g, 'geoms', []) for q in polys_of(gg)]

def page_band_r3(y0, y1, x0=-4000.0, x1=4000.0):
    A, B = pg(x0, y1), pg(x1, y0)
    return sg.box(min(A[0], B[0]), min(A[1], B[1]), max(A[0], B[0]), max(A[1], B[1]))

def vmu_hulls(z_high=7.0):
    files = ['vmu_cad.glb', 'vmu01_canopy.glb', 'vmu02.glb', 'vmu04.glb', 'vmu05.glb']
    paths = [os.path.join(ROOT, 'model', f) for f in files]
    key = {f: os.path.getmtime(p) for f, p in zip(files, paths) if os.path.exists(p)}
    cache = os.path.join(SCRATCH, 'vmu_hulls_cache.json' if z_high == 7.0 else 'vmu_hulls_cache_z%.1f.json' % z_high)
    if os.path.exists(cache):
        c = json.load(open(cache))
        if c.get('key') == key and c.get('z_high') == z_high:
            return {g: (sg.Polygon(v['all']), sg.Polygon(v['high']) if v['high'] else None, v['zmax']) for g, v in c['hulls'].items()}
    import trimesh
    from shapely.geometry import MultiPoint
    acc = collections.defaultdict(list)
    for f, p in zip(files, paths):
        if not os.path.exists(p): continue
        sc = trimesh.load(p)
        for name in sc.graph.nodes_geometry:
            T, gn = sc.graph[name]
            V = trimesh.transform_points(sc.geometry[gn].vertices, T)
            g = name.split('|')[0].split(' ')[0].upper()
            if not g.startswith(('VMU', 'TRELLIS')): continue
            acc[g[:5] if g.startswith('VMU') else 'TRELLIS'].append(V)
    out = {}
    for g, Vs in acc.items():
        V = np.vstack(Vs); r3 = gltf_xz_to_r3(V[:, [0, 2]])
        ha = MultiPoint(r3).convex_hull
        hi = V[:, 1] > z_high
        hh = MultiPoint(r3[hi]).convex_hull if hi.sum() >= 3 else None
        out[g] = dict(all=list(ha.exterior.coords), high=list(hh.exterior.coords) if hh is not None and hh.geom_type == 'Polygon' else None,
                      zmax=float(V[:, 1].max()))
    json.dump(dict(key=key, z_high=z_high, hulls=out), open(cache, 'w'))
    return {g: (sg.Polygon(v['all']), sg.Polygon(v['high']) if v['high'] else None, v['zmax']) for g, v in out.items()}

HULLS = vmu_hulls()
VMU_ALL = [h[0] for h in HULLS.values()]

def clear_of_vmus(geom, high_only=False, clearance=0.0):
    for g, (ha, hh, zmax) in HULLS.items():
        tgt = hh if high_only else ha
        if tgt is None: continue
        if geom.distance(tgt) < clearance: return False, g
    return True, None

F1 = group('Factory 1 (1-storey shed)', label='1-storey factory (overhead crane bays), roof y 14.0',
           footprint_m='27.22 x 59.975 (DXF x -112000..-84780, y -45580..14395)', source='')
SRC_F1 = ''
F1_X_FRONT, F1_X_REAR = -84780.0, -112000.0
F1_Y0, F1_Y1 = -45580.0, 14395.0
F1_GRID_Y = [-45580.0, -30605.0, -15605.0, -605.0, 14395.0]

def _dxf_columns():
    C = [np.asarray(c['dxf_mm'])[:-1].mean(0) for c in SITE['features']['factory_columns_1000x1000']]
    xs = sorted({round(float(c[0]), 1) for c in C}, reverse=True)
    rows = {x: sorted(round(float(c[1]), 1) for c in C if abs(c[0] - x) < 1.0) for x in xs}
    return xs, rows

_COLX, _COLROWS = _dxf_columns()
F1_ROW1_X, F1_ROW2_X = _COLX[0], _COLX[1]
F1_COL_Y = _COLROWS[F1_ROW2_X]
F1_ROW1_COL_Y_DXF = _COLROWS[F1_ROW1_X]
F1_GRIDO_X = -103440.0
F1_H_EAVE_MAIN, F1_H_RIDGE = 13.7, 14.0
F1_ROOF_MODE = 'r3'
F1_BAND_D = 1.25
F1_H_BAND0 = 10.55
F1_H_CANOPY = (10.42, 10.58)
F1_EAVE_OVERHANG = 0.8
F1_H_BEAM = (9.4, 10.2)
F1_BASE_BAND = 1.5
F1_FRONT_COL_W = 2.0
F1_CORNER_COL_W = 1.26
F1_ROOF_TOWER_D = 8.0

def f1(d, a, z=None):
    p = dxf(F1_X_FRONT - d * 1000.0, F1_Y0 + a * 1000.0)
    return p if z is None else np.r_[p, z]

def dxf_d(x): return (F1_X_FRONT - x) / 1000.0
def dxf_a(y): return (y - F1_Y0) / 1000.0

U_ALONG = unit(f1(0, 1) - f1(0, 0))
U_DEPTH = unit(f1(1, 0) - f1(0, 0))
F1_LEN = dxf_a(F1_Y1); F1_DEPTH = dxf_d(F1_X_REAR)
D_ROW1, D_ROW2, D_GRIDO = dxf_d(F1_ROW1_X), dxf_d(F1_ROW2_X), dxf_d(F1_GRIDO_X)

def f1_box(k, d0, d1, a0, a1, z0, z1, **kw):
    c = (f1(d0, a0) + f1(d1, a1)) / 2
    obox(k, c, U_ALONG, abs(a1 - a0) / 2, abs(d1 - d0) / 2, z0, z1, **kw)

F1_D_EAVE = F1_BAND_D - F1_EAVE_OVERHANG

def f1_roof_breaks():
    return [F1_D_EAVE, D_GRIDO, F1_DEPTH + 0.1]

def f1_roof_z(d):
    d0, dk, d1 = f1_roof_breaks()
    if d <= dk:
        return F1_H_EAVE_MAIN + (F1_H_RIDGE - F1_H_EAVE_MAIN) * max(d - d0, 0.0) / (dk - d0)
    return F1_H_RIDGE + (F1_H_EAVE_MAIN - F1_H_RIDGE) * min((d - dk) / (d1 - dk), 1.0)

def f1_eave():
    return f1_roof_z(F1_D_EAVE)

def col_banded(grp, name, c, u, hu, hv, z_top, src, conf):
    k1 = L(grp, name + ' - base stain band', 'CTX_FACTORY_RC_BASE', '', conf, note='')
    k2 = L(grp, name, 'CTX_FACTORY_RC', '', conf)
    obox(k1, c, u, hu, hv, 0.0, F1_BASE_BAND, top=False)
    obox(k2, c, u, hu, hv, F1_BASE_BAND, z_top, bottom=False)

def build_factory1():
    g = F1
    EAVE = f1_eave()
    GROUP_META[g].update(roof_mode=F1_ROOF_MODE, roof_front_eave_m=round(EAVE, 3), roof_top_max_m=round(max(f1_roof_z(d) for d in f1_roof_breaks()), 3),
                         roof_section='duo-pitch 13.7 / 14.0 (ridge on grid O) / 13.7 (drawing roof level minus the assumed ground level)')
    front_dxf = set(F1_ROW1_COL_Y_DXF)
    for i, ya in enumerate(F1_COL_Y):
        a = dxf_a(ya)
        inferred = not any(abs(ya - yf) < 1.0 for yf in front_dxf)
        cw = F1_CORNER_COL_W if inferred else F1_FRONT_COL_W
        af = a + (cw / 2 - 0.5) * (1 if i == 0 else -1 if i == len(F1_COL_Y) - 1 else 0)
        if inferred:
            col_banded(g, 'RC columns front row - corner (inferred)', f1(D_ROW1, af), U_ALONG, cw / 2, 0.5, F1_H_BEAM[1],
                       '', 'low (inferred)')
        else:
            col_banded(g, 'RC columns front row', f1(D_ROW1, af), U_ALONG, F1_FRONT_COL_W / 2, 0.5, F1_H_BEAM[1],
                       '', 'high (position), medium (size/height)')
        col_banded(g, 'RC columns grid O row (interior)', f1(D_GRIDO, a), U_ALONG, 0.5, 0.5, EAVE, '', 'low (inferred)')
        col_banded(g, 'RC columns row 2', f1(D_ROW2, a), U_ALONG, 0.5, 0.5, EAVE, '', 'high (position)')
        col_banded(g, 'RC columns rear row', f1(F1_DEPTH - 0.6, a), U_ALONG, 0.5, 0.5, EAVE, '', 'medium (inferred from roof frames)')
    a_lo = dxf_a(F1_COL_Y[0]) - 0.5; a_hi = dxf_a(F1_COL_Y[-1]) + 0.5
    kb = L(g, 'Front lintel beam', 'CTX_FACTORY_RC', '', 'medium', note='')
    f1_box(kb, 0.0, 0.9, a_lo, a_hi, F1_H_BEAM[0], F1_H_BEAM[1])
    kf = L(g, 'Canopy fascia + gutter', 'CTX_CLADDING_RIB', '', 'medium', note='')
    f1_box(kf, -0.35, -0.12, a_lo - 0.3, a_hi + 0.3, F1_H_BEAM[1] + 0.02, F1_H_CANOPY[0] + 0.12)
    kr = L(g, 'Canopy roof (front strip)', 'CTX_ROOF_METAL', '', 'medium',
           note='')
    ks = L(g, 'Canopy soffit', 'CTX_BAY_VOID', '', 'medium')
    dA, dB = -0.35, F1_BAND_D - 0.02
    for (kk, dz, flip) in ((kr, 0.0, False), (ks, -0.15, True)):
        pts = [f1(dA, a_lo - 0.3, F1_H_CANOPY[0] + dz), f1(dA, a_hi + 0.3, F1_H_CANOPY[0] + dz),
               f1(dB, a_hi + 0.3, F1_H_CANOPY[1] + dz), f1(dB, a_lo - 0.3, F1_H_CANOPY[1] + dz)]
        n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
        if (n[2] < 0) != flip: pts = pts[::-1]
        poly(kk, pts)
    kc = L(g, 'Ribbed cladding band (front)', 'CTX_CLADDING_RIB', '', 'medium',
           note='')
    f1_box(kc, F1_BAND_D, F1_BAND_D + 0.12, a_lo - 0.25, a_hi + 0.25, F1_H_BAND0, EAVE)
    kcs = L(g, 'Band column strips (lighter)', 'CTX_FACTORY_RC', '', 'medium', note='')
    for i, ya in enumerate(F1_COL_Y):
        a = min(max(dxf_a(ya), a_lo + 0.4), a_hi - 0.4)
        f1_box(kcs, F1_BAND_D - 0.05, F1_BAND_D, a - 0.4, a + 0.4, F1_H_BAND0, EAVE - 0.05)
    kg = L(g, 'Ribbed cladding gables', 'CTX_CLADDING_RIB', '', 'low')
    for a in (a_lo - 0.25, a_hi + 0.25):
        aa = a - 0.06 if a < a_lo else a + 0.06
        c0, c1 = f1(F1_BAND_D, aa), f1(F1_DEPTH, aa)
        obox(kc, (c0 + c1) / 2, U_DEPTH, np.linalg.norm(c1 - c0) / 2, 0.06, F1_H_BAND0, EAVE)
        tri = [f1(F1_BAND_D, aa, F1_H_EAVE_MAIN), f1(D_GRIDO, aa, F1_H_RIDGE), f1(F1_DEPTH, aa, F1_H_EAVE_MAIN)]
        poly(kg, tri[::-1] if a > a_lo else tri)
    kR = L(g, 'Main roof (profiled metal)', 'CTX_ROOF_METAL', '', 'medium',
           note='')
    kS = L(g, 'Main roof soffit (dark interior)', 'CTX_BAY_VOID', '', 'medium')
    d_eave = F1_D_EAVE
    brk = f1_roof_breaks()
    for (d0, d1) in zip(brk[:-1], brk[1:]):
        z0, z1 = f1_roof_z(d0), f1_roof_z(d1)
        pts = [f1(d0, a_lo - 0.4, z0), f1(d1, a_lo - 0.4, z1), f1(d1, a_hi + 0.4, z1), f1(d0, a_hi + 0.4, z0)]
        n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
        if n[2] < 0: pts = pts[::-1]
        poly(kR, pts)
        s = [p - np.array([0, 0, 0.35]) for p in pts][::-1]
        poly(kS, s)
    kgut = L(g, 'Main roof gutters + eave fascia', 'CTX_CLADDING_RIB', '', 'low', note='')
    z_rear = EAVE
    for d, zg in ((d_eave + 0.12, EAVE), (F1_DEPTH - 0.05, z_rear)):
        f1_box(kgut, d - 0.12, d + 0.12, a_lo - 0.4, a_hi + 0.4, zg - 0.3, zg + 0.05)
    kv = L(g, 'Interior rear wall (dark)', 'CTX_BAY_VOID', '', 'medium', note='')
    f1_box(kv, F1_DEPTH - 0.1, F1_DEPTH, a_lo - 0.2, a_hi + 0.2, 0.0, z_rear)
    kst = L(g, 'Roof frames + purlins (interior)', 'CTX_STEEL_GREY', '', 'medium', note='')
    for ya in F1_GRID_Y:
        a = min(max(dxf_a(ya), 0.3), F1_LEN - 0.3)
        f1_box(kst, F1_BAND_D + 0.2, F1_DEPTH - 0.1, a - 0.2, a + 0.2, EAVE - 1.3, EAVE - 0.36)
        f1_box(kst, D_ROW1 + 0.5, D_ROW2 - 0.5, a - 0.15, a + 0.15, F1_H_BEAM[0] + 0.1, F1_H_BEAM[1])
    for d in (F1_BAND_D + 0.4, D_ROW2, D_GRIDO):
        f1_box(kst, d - 0.25, d + 0.25, 0.0, F1_LEN, EAVE - 1.1, EAVE - 0.36)
    for dd in np.arange(F1_BAND_D + 1.5, F1_DEPTH - 0.5, 1.8):
        f1_box(kst, dd - 0.06, dd + 0.06, 0.0, F1_LEN, EAVE - 0.5, EAVE - 0.37)
    krw = L(g, 'Crane runway girders', 'CTX_STEEL_GREY', '', 'medium', note='')
    col_a = [dxf_a(y) for y in F1_COL_Y]
    for i, a in enumerate(col_a):
        for sgn in (-1, 1):
            if (i == 0 and sgn < 0) or (i == len(col_a) - 1 and sgn > 0): continue
            f1_box(krw, D_ROW1 + 0.6, F1_DEPTH - 0.8, a + sgn * 0.75, a + sgn * 1.15, 8.1, 8.9)
    kbr = L(g, 'Overhead crane bridges', 'CTX_SAFETY_YELLOW', '', 'medium (count/positions assumed)')
    khs = L(g, 'Overhead crane hoists', 'CTX_STEEL_GREY', '', 'low')
    bridge_d = [14.0, 8.0, 12.0, 5.0]
    for i in range(4):
        a0, a1 = col_a[i] + 1.15, col_a[i + 1] - 1.15; d = bridge_d[i]
        f1_box(kbr, d - 0.28, d + 0.28, a0 + 0.1, a1 - 0.1, 9.05, 9.9)
        for aa in (a0 + 0.2, a1 - 0.2):
            f1_box(kbr, d - 1.6, d + 1.6, aa - 0.2, aa + 0.2, 8.9, 9.45)
        am = a0 + (a1 - a0) * 0.62
        f1_box(khs, d - 0.45, d + 0.45, am - 0.55, am + 0.55, 8.25, 9.05)
        f1_box(khs, d - 0.12, d + 0.12, am - 0.12, am + 0.12, 6.2, 8.25)
        f1_box(kbr, d - 0.2, d + 0.2, am - 0.18, am + 0.18, 5.8, 6.25)
    if YELLOW_LATTICE_HOST == 'shed':
        kyc = L(g, 'Roof lattice towers (yellow) - chords', 'CTX_SAFETY_YELLOW', '', 'low (form/height from photos, purpose unknown)')
        kyl = L(g, 'Roof lattice towers (yellow) - lacing', 'CTX_SAFETY_YELLOW', '', 'low')
        ktc = L(g, 'Roof lattice truss (grey)', 'STEEL_HDG', '', 'low')
        dT = F1_ROOF_TOWER_D
        GROUP_META[g].update(roof_towers_depth_m=dT, roof_towers_depth_note='')
        zr = f1_roof_z(dT) + 0.02
        Ht = 5.6
        for i, a in enumerate([0.6, 15.0, 30.0, 45.0, 59.4]):
            cs = [f1(dT + sd * 0.4, a + sa * 0.4) for sd, sa in ((-1, -1), (-1, 1), (1, 1), (1, -1))]
            for c in cs: member(kyc, np.r_[c, zr], np.r_[c, zr + Ht], 0.13)
            for j in range(4):
                P0, P1 = cs[j], cs[(j + 1) % 4]
                for zz in np.arange(zr + 0.9, zr + Ht, 0.9):
                    member(kyl, np.r_[P0, zz], np.r_[P1, zz], 0.06)
                    member(kyl, np.r_[P0, zz - 0.9], np.r_[P1, zz], 0.05)
            sgn = (1, 1, -1, -1, -1)[i]
            top = f1(dT, a, zr + Ht - 0.4); foot = f1(dT, a + sgn * 3.2, zr)
            off = U_DEPTH * 0.3
            P0 = np.r_[foot[:2] - off, foot[2]]; P1 = np.r_[top[:2] - off, top[2]]
            Q0 = np.r_[foot[:2] + off, foot[2]]; Q1 = np.r_[top[:2] + off, top[2]]
            lattice_panel(kyc, kyl, P0, P1, Q0, Q1, 6, chord=0.11, lace=0.05)
        zb, zt = zr + Ht - 0.95, zr + Ht + 0.05
        lattice_panel(ktc, ktc, f1(dT, 0.0, zb), f1(dT, F1_LEN, zb), f1(dT, 0.0, zt), f1(dT, F1_LEN, zt), 40, chord=0.16, lace=0.07)
        lattice_panel(kyc, kyl, f1(dT, 15.4, zr + 2.4), f1(dT, 29.6, zr + 2.4), f1(dT, 15.4, zr + 3.2), f1(dT, 29.6, zr + 3.2), 10, chord=0.1, lace=0.05)
        lattice_panel(kyc, kyl, f1(dT, 45.4, zr + 2.4), f1(dT, 59.0, zr + 2.4), f1(dT, 45.4, zr + 3.2), f1(dT, 59.0, zr + 3.2), 10, chord=0.1, lace=0.05)

LEVELS_FRAME = dict(slabs=[(8.6, 9.4), (14.4, 15.2)], roof=(19.0, 19.8), parapet=1.0, spandrel=1.1, col=0.8, bay=6.0, inner=12.0, steel_bay=6.0)

def rc_frame_building(grp, poly_r3, src, conf, rc_top=19.8, steel_top=24.5, state='frame', core_rects=(), stair=None, note=''):
    P = ccw(list(poly_r3)); n = len(P)
    shp = sg.Polygon(P)
    lv = dict(LEVELS_FRAME); roof0, roof1 = rc_top - 0.8, rc_top
    if state == 'clad':
        kw = L(grp, 'Cladding (clad state)', 'CTX_CLADDING_RIB', '', 'low', note='')
        prism(kw, P, 0.0, steel_top, top=False, bottom=False)
        kr = L(grp, 'Roof', 'CTX_ROOF_METAL', '', 'low')
        prism(kr, P, steel_top - 0.3, steel_top, bottom=False, sides=False)
        return
    kc = L(grp, 'RC columns', 'CTX_RC_BARE', '', conf)
    ks = L(grp, 'RC slabs + spandrel beams', 'CTX_RC_BARE', '', conf)
    col_pts = []
    for i in range(n):
        a, b = P[i], P[(i + 1) % n]; ln = np.linalg.norm(b - a)
        m = max(1, int(round(ln / lv['bay'])))
        for j in range(m):
            col_pts.append(a + (b - a) * j / m)
    inward = []
    for c in col_pts:
        best = c
        for dxy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            q = c + np.array(dxy) * lv['col'] * 0.5
            if shp.contains(sg.Point(q)): best = q; break
        inward.append(best)
    for c in inward:
        obox(kc, c, (1, 0), lv['col'] / 2, lv['col'] / 2, 0.0, roof0)
    minx, miny, maxx, maxy = shp.bounds
    for x in np.arange(minx + lv['inner'], maxx - 2.0, lv['inner']):
        for y in np.arange(miny + lv['inner'], maxy - 2.0, lv['inner']):
            if shp.buffer(-2.0).contains(sg.Point(x, y)):
                obox(kc, (x, y), (1, 0), 0.4, 0.4, 0.0, roof0)
    inner = shp.buffer(-0.35, join_style=2)
    IP = list(np.asarray(inner.exterior.coords)[:-1]) if inner.geom_type == 'Polygon' else P
    for (z0, z1) in lv['slabs'] + [(roof0, roof1)]:
        prism(ks, P, z1 - 0.3, z1)
        for i in range(n):
            a, b = P[i], P[(i + 1) % n]
            nrm = perp(unit(b - a)) * 0.15
            seg_box(ks, a + nrm, b + nrm, 0.3, z1 - lv['spandrel'], z1 - 0.3)
    for i in range(n):
        a, b = P[i], P[(i + 1) % n]; nrm = perp(unit(b - a)) * 0.1
        seg_box(ks, a + nrm, b + nrm, 0.2, roof1, roof1 + lv['parapet'])
    kk = L(grp, 'RC cores', 'CTX_RC_BARE', '', conf)
    for rect in core_rects:
        prism(kk, rect, 0.0, roof1 + 1.2)
    ky = L(grp, 'Yellow steel roof storey (open, under erection)', 'CTX_SAFETY_YELLOW', '', 'low (member layout assumed)')
    mrr = shp.minimum_rotated_rectangle; R = np.asarray(mrr.exterior.coords)[:4]
    e1, e2 = R[1] - R[0], R[2] - R[1]
    ulong = unit(e1) if np.linalg.norm(e1) >= np.linalg.norm(e2) else unit(e2)
    ushort = perp(ulong)
    cen = np.asarray(mrr.centroid.coords[0])
    Llong = max(np.linalg.norm(e1), np.linalg.norm(e2)); Lshort = min(np.linalg.norm(e1), np.linalg.norm(e2))
    z_col = steel_top - 0.5
    for t in np.arange(-Llong / 2 + 0.6, Llong / 2 - 0.5, lv['steel_bay']):
        a = cen + ulong * t - ushort * (Lshort / 2 - 0.6); b = cen + ulong * t + ushort * (Lshort / 2 - 0.6)
        if not (shp.contains(sg.Point(a)) and shp.contains(sg.Point(b))): continue
        mid = (a + b) / 2
        member(ky, np.r_[a, roof1], np.r_[a, z_col], 0.35, 0.45)
        member(ky, np.r_[b, roof1], np.r_[b, z_col], 0.35, 0.45)
        member(ky, np.r_[a, z_col], np.r_[mid, steel_top - 0.28], 0.3, 0.55)
        member(ky, np.r_[mid, steel_top - 0.28], np.r_[b, z_col], 0.3, 0.55)
    for s_ in (-(Lshort / 2 - 0.6), 0.0, Lshort / 2 - 0.6):
        zz = steel_top - 0.2 if s_ == 0 else z_col
        a = cen + ushort * s_ - ulong * (Llong / 2 - 0.6); b = cen + ushort * s_ + ulong * (Llong / 2 - 0.6)
        seg = sg.LineString([a, b]).intersection(shp.buffer(-0.3))
        for part in ([seg] if seg.geom_type == 'LineString' else list(getattr(seg, 'geoms', []))):
            if part.is_empty or part.length < 1.0: continue
            q = np.asarray(part.coords)
            member(ky, np.r_[q[0], zz], np.r_[q[-1], zz], 0.25, 0.4)
    if stair is not None:
        kst = L(grp, 'External steel stair', 'CTX_STEEL_GREY', '', 'low (position assumed)')
        base, along, out = stair
        along = unit(along); out = unit(out); w = 1.4; run = 5.2
        levels = [0.0] + [z1 for (_, z1) in lv['slabs']] + [roof1]
        for i in range(len(levels) - 1):
            z0, z1 = levels[i], levels[i + 1]
            for half in (0, 1):
                za, zb = z0 + (z1 - z0) * half / 2, z0 + (z1 - z0) * (half + 1) / 2
                sgn = 1 if half == 0 else -1
                o = base + out * (0.9 + w * (0.5 if half == 0 else 1.5))
                A3 = np.r_[o - along * sgn * run / 2, max(za, 0.15)]; B3 = np.r_[o + along * sgn * run / 2, zb]
                member(kst, A3, B3, w, 0.25)
                obox(kst, base + out * (0.9 + w) + along * sgn * (run / 2 + 0.7), along, 0.7, w, zb - 0.2, zb)
        for dx in (-run / 2 - 1.4, run / 2 + 1.4):
            for dy in (0.9, 0.9 + 2 * w):
                c = base + along * dx + out * dy
                member(kst, np.r_[c, 0.0], np.r_[c, levels[-1] + 1.1], 0.15)

def build_west_factory():
    g = group('Factory 2-storey west', label='2-storey factory W of the shed (drawing roof level, 24.5 m above the yard)',
              source='',
              state=WEST_FACTORY_STATE)
    xw = -163000.0
    src = 'survey DXF factory walls + layout-plan roof level'
    cores_dxf = [((-121950, 14272), (-121950, 16710), (-132999, 16710), (-132999, 14272)),
                 ((-121950, -45484), (-133755, -45484), (-133755, -48020), (-121950, -48020))]
    cores = [[dxf(x, y) for x, y in c] for c in cores_dxf]
    GROUP_META[g].update(states={'frame': 'bare RC frame + yellow steel roof storey (default)', 'clad': 'closed 24.5 m box'},
                         state_switch='WEST_FACTORY_STATE / env MOCKUP_WEST_FACTORY_STATE')
    if WEST_FACTORY_STATE not in ('frame', 'clad'):
        raise ValueError('MOCKUP_WEST_FACTORY_STATE must be frame | clad')
    pts = [(-112120, -45484), (-112120, 14272), (-121950, 14272), (-121950, 16710), (-132999, 16710), (-132999, 14272),
           (xw, 14272), (xw, -45484), (-133755, -45484), (-133755, -48020), (-121950, -48020), (-121950, -45484)]
    rc_frame_building(g, [dxf(x, y) for x, y in pts], '', 'medium (outline), low (state/levels)', rc_top=WEST_FACTORY_RC_TOP,
                      steel_top=WEST_TALL_BLOCK_TOP, state=WEST_FACTORY_STATE, core_rects=cores)
    return dict(state=WEST_FACTORY_STATE)







def build_north_block():
    g = group('Factory 2 north block', label='2-storey factory N of the fire-engine accessway (bare RC frame + yellow steel, Q6)',
              source='',
              state=Q6_NORTH_BLOCK_STATE)
    px0, px1, py0, py1 = 694.0, 960.0, -60.0, 235.4
    P = [pg(px0, py1), pg(px1, py1), pg(px1, py0), pg(px0, py0)]
    base = pg(px0, py1 - 14.0 / S_PT)
    stair = (base, pg(px0, 0) - pg(px0, 1), pg(0, 0) - pg(1, 0)) if NORTH_BLOCK_STAIR == 'ssw_face' else None
    GROUP_META[g].update(
        stair=dict(state=NORTH_BLOCK_STAIR, page_x=[676.3, 694.0],
                   note=''),
        view_check='')
    rc_frame_building(g, P, '', 'low (extent), medium (look)', rc_top=19.8, steel_top=24.5,
                      state=Q6_NORTH_BLOCK_STATE, stair=stair)

def build_accessway_canopy():
    x0, x1, y0, y1 = ACCESSWAY_CANOPY_PAGE
    g = group('Accessway truss canopy', label='grey steel-truss canopy over the fire-engine accessway NNE of the shed end (photo)',
              source='',
              page_rect=list(ACCESSWAY_CANOPY_PAGE), top=ACCESSWAY_CANOPY_TOP,
              caveat='')
    src = 'site photos; dimensions estimated'
    conf = 'low (extent/height estimated from photos)'
    kP = L(g, 'Steel posts (H-section)', 'CTX_STEEL_GREY', '', conf)
    kT = L(g, 'Lattice girders + trusses', 'CTX_STEEL_GREY', '', conf, note='')
    kR = L(g, 'Roof sheet (profiled metal)', 'CTX_ROOF_METAL', '', conf)
    kU = L(g, 'Roof underside (dark)', 'CTX_BAY_VOID', '', conf)
    kW = L(g, 'ESE end tarp (dark)', 'CTX_BAY_VOID', '', 'low')
    kX = L(g, 'ESE end red panel', 'CTX_STILLAGE_RED', '', 'low')
    XA, XB = x0 * S_PT, x1 * S_PT
    YA, YB = -y1 * S_PT, -y0 * S_PT
    H = ACCESSWAY_CANOPY_TOP; dg = 1.3; zb = H - 0.25 - dg
    nb = max(2, int(round((XB - XA) / 5.5)))
    xs = np.linspace(XA + 0.3, XB - 0.3, nb + 1)
    for xx in xs:
        for yy in (YA + 0.3, YB - 0.3):
            obox(kP, (xx, yy), (1, 0), 0.15, 0.13, 0.0, zb)
            obox(kP, (xx, yy), (1, 0), 0.3, 0.3, 0.0, 0.05)
        lattice_panel(kT, kT, (xx, YA + 0.3, zb), (xx, YB - 0.3, zb), (xx, YA + 0.3, H - 0.25), (xx, YB - 0.3, H - 0.25), 6, chord=0.14, lace=0.06)
    for yy in (YA + 0.3, YB - 0.3):
        lattice_panel(kT, kT, (xs[0], yy, zb), (xs[-1], yy, zb), (xs[0], yy, H - 0.25), (xs[-1], yy, H - 0.25), 4 * nb, chord=0.14, lace=0.06)
    for yy in np.linspace(YA + 0.3, YB - 0.3, 7):
        seg_box(kT, (XA, yy), (XB, yy), 0.1, H - 0.25, H - 0.12)
    obox(kR, ((XA + XB) / 2, (YA + YB) / 2), (1, 0), (XB - XA) / 2 + 0.4, (YB - YA) / 2 + 0.4, H - 0.08, H, bottom=False)
    obox(kU, ((XA + XB) / 2, (YA + YB) / 2), (1, 0), (XB - XA) / 2 + 0.4, (YB - YA) / 2 + 0.4, H - 0.12, H - 0.08, top=False)
    xm = XB - 3.3
    obox(kW, ((xm + XB - 0.3) / 2, YA + 0.2), (1, 0), (XB - 0.3 - xm) / 2, 0.02, 2.2, zb)
    obox(kX, ((xm + XB - 0.3) / 2 + 0.3, YA + 0.5), (1, 0), (XB - 0.3 - xm) / 2 - 0.3, 0.04, 0.0, 2.2)
    return dict(page_rect=list(ACCESSWAY_CANOPY_PAGE), top=H, bays=nb, size_m=[round(XB - XA, 2), round(YB - YA, 2)],
                underside_of_girders=round(zb, 2))

def build_chainlink(g, pts, yard_pt):
    src = 'DXF fence_centreline label "south 1.8m chain-link fence (on lot boundary)" + site photos (no solid wall on the SSW side)'
    kp = L(g, 'SSW chain-link fence - posts + top rail', 'STEEL_HDG', '', 'medium (line/height), low (post spacing assumed 2.5 m)')
    km = L(g, 'SSW chain-link fence - mesh panel', 'CTX_FENCE_MESH', '', 'medium (type/height from the DXF label)',
           uv=f'u = metres along / {CHAINLINK_DIAMOND_M}, v = height / {CHAINLINK_DIAMOND_M} (one chain-link tile per {CHAINLINK_DIAMOND_M} m)',
           note='')
    Hc = CHAINLINK_H; out = []
    pts = [np.asarray(p, float) for p in pts]
    for a, b in zip(pts[:-1], pts[1:]):
        u = unit(b - a); ln = np.linalg.norm(b - a); nrm = perp(u)
        if (yard_pt - a) @ nrm < 0: nrm = -nrm
        m = max(1, int(math.ceil(ln / CHAINLINK_POST_SPACING)))
        for j in range(m + 1):
            c = a + u * ln * j / m + nrm * 0.05
            end = j in (0, m)
            cyl(kp, c, 0.045 if end else 0.030, 0.045 if end else 0.030, -0.2, Hc + 0.05, n=8)
            if end:
                s_ = 1 if j == 0 else -1
                member(kp, np.r_[c + u * s_ * 1.6, -0.1], np.r_[c + u * s_ * 0.05, Hc * 0.7], 0.04)
        member(kp, np.r_[a + nrm * 0.05, Hc + 0.02], np.r_[b + nrm * 0.05, Hc + 0.02], 0.042)
        member(kp, np.r_[a + nrm * 0.05, 0.08], np.r_[b + nrm * 0.05, 0.08], 0.012)
        V = np.array([np.r_[a, 0.03], np.r_[b, 0.03], np.r_[b, Hc], np.r_[a, Hc]])
        k_ = CHAINLINK_DIAMOND_M
        uvq = np.array([[0.0, 0.03 / k_], [ln / k_, 0.03 / k_], [ln / k_, Hc / k_], [0.0, Hc / k_]])
        quad(km, *V, uv=uvq)
        out.append(('south (chain-link 1.8 m)', a.tolist(), b.tolist()))
    return out

def build_hoarding():
    g = group('Boundary hoarding', label='2.4 m grey corrugated metal hoarding on the main road frontage + 16.1 m gate; 1.8 m chain-link on the SSW line',
              source='',
              caveat='',
              south_boundary_type=SOUTH_BOUNDARY_TYPE,
              south_boundary_note='')
    src = 'DXF fence_centreline (boundary layer) + site photos'
    ks = L(g, 'Corrugated sheet', 'CTX_HOARDING', '', 'medium (line), medium (look)', uv='metres along x height, ribs vertical (corrugated_iron_03)')
    kcap = L(g, 'Top capping', 'CTX_HOARDING', '', 'medium')
    kp = L(g, 'Posts + rails (yard side)', 'STEEL_HDG', '', 'low (spacing assumed 2.4 m)')
    fence = {e['label']: np.asarray(e['xy_plan_m']) for e in SITE['features']['fence_centreline']}
    south = [v for kx, v in fence.items() if kx.startswith('south')][0]
    e0 = [v for kx, v in fence.items() if 'part 0' in kx][0]
    e1 = [v for kx, v in fence.items() if 'part 1' in kx][0]
    dsw = unit(south[0] - south[1]); de = unit(e0[1] - e0[0])
    t = np.linalg.solve(np.c_[dsw, -de], e0[0] - south[1])
    se = south[1] + dsw * t[0]
    south_full = [se + dsw * float(SITE['lot_south_line']['length_m']), se]
    north_end = e1[-1] + unit(e1[-1] - e1[-2]) * HOARDING_N_EXTEND_M
    runs = [('south', south_full), ('east A', [se] + list(e0[1:])), ('east B', list(e1[:-1]) + [north_end])]
    GROUP_META[g].update(se_corner_r3m=[round(float(se[0]), 3), round(float(se[1]), 3)])
    yard_pt = pg(520, 560)
    lines_out = []
    for name, pts in runs:
        if name == 'south' and SOUTH_BOUNDARY_TYPE == 'chainlink_1.8':
            lines_out += build_chainlink(g, pts, yard_pt)
            continue
        pts = [np.asarray(p, float) for p in pts]
        for a, b in zip(pts[:-1], pts[1:]):
            u = unit(b - a); ln = np.linalg.norm(b - a); nrm = perp(u)
            if (yard_pt - a) @ nrm < 0: nrm = -nrm
            obox(ks, (a + b) / 2, u, ln / 2, 0.015, -0.25, HOARDING_H)
            obox(kcap, (a + b) / 2 + nrm * 0.02, u, ln / 2, 0.07, HOARDING_H, HOARDING_H + 0.06)
            m = max(1, int(math.ceil(ln / 2.4)))
            for j in range(m + 1):
                c = a + u * ln * j / m + nrm * 0.08
                obox(kp, c, u, 0.05, 0.05, -0.2, HOARDING_H - 0.02)
            for zz in (0.35, 1.25, 2.1):
                obox(kp, (a + b) / 2 + nrm * 0.16, u, ln / 2, 0.03, zz - 0.05, zz + 0.05)
            lines_out.append((name, a.tolist(), b.tolist()))
    ga, gb = e0[-1], e1[0]
    kg = L(g, 'Entrance gate (palisade)', 'CTX_GATE_BROWN', '', 'medium (opening), low (leaf design)')
    u = unit(gb - ga); ln = np.linalg.norm(gb - ga); nrm = perp(u)
    if (yard_pt - ga) @ nrm < 0: nrm = -nrm
    for c in (ga, gb):
        obox(kg, c + u * (0.2 if c is ga else -0.2), u, 0.18, 0.18, -0.2, HOARDING_H + 0.15)
    leaves = [(ga + u * 0.4, ga + u * ln / 2), (ga + u * ln / 2, gb - u * 0.4)]
    if GATE_STATE == 'open':
        leaves = [(ga + u * 0.4, ga + u * 0.4 - u * (ln / 2 - 0.4)), (gb - u * 0.4, gb - u * 0.4 + u * (ln / 2 - 0.4))]
        leaves = [(a_ + nrm * 0.35, b_ + nrm * 0.35) for a_, b_ in leaves]
    for a, b in leaves:
        uu = unit(b - a); l2 = np.linalg.norm(b - a)
        for zz in (0.15, 1.2, 2.25):
            obox(kg, (a + b) / 2, uu, l2 / 2, 0.03, zz - 0.04, zz + 0.04)
        m = int(l2 / 0.13)
        for j in range(m + 1):
            c = a + uu * l2 * j / m
            obox(kg, c, uu, 0.02, 0.02, 0.05, HOARDING_H + 0.05)
    return lines_out, (ga.tolist(), gb.tolist())

def rails_from_ground():
    import re
    gp = os.path.join(ROOT, 'model', 'site_ground.glb')
    if os.path.exists(gp):
        try:
            import struct
            with open(gp, 'rb') as f:
                f.read(12); ln, _ = struct.unpack('<II', f.read(8)); js = json.loads(f.read(ln))
            found = []

            def walk(o, path=''):
                if isinstance(o, dict):
                    for k2, v in o.items(): walk(v, path + '/' + str(k2))
                elif isinstance(o, list):
                    if 'rail' in path.lower() and 'page' in path.lower() and all(isinstance(x, (int, float)) for x in o) and 1 <= len(o) <= 4:
                        found.append((path, [float(x) for x in o]))
                    else:
                        for i, v in enumerate(o): walk(v, path + f'[{i}]')
            walk([js.get('scenes', []), js.get('nodes', [])])
            xs = sorted({round(x, 2) for _, v in found for x in v if 300 < x < 900})
            if len(xs) >= 2: return (xs[0], xs[-1]), 'site_ground.glb extras'
            if len(xs) == 1: return (xs[0], GANTRY_RAILS_PAGE_X[1]), 'site_ground.glb extras (first rail only)'
        except Exception as e:
            pass
    p = os.path.join(HERE, 'build_ground.py')
    if not os.path.exists(p): return None, 'build_ground.py / site_ground.glb not present at build time'
    txt = open(p, encoding='utf-8').read()
    pat = r'^\s*(?:GANTRY_|CRANE_)?RAILS?(?:_CENTRE(?:LINE)?S?)?_PAGE_X\s*=\s*'
    m = re.search(pat + r'[\(\[]\s*([0-9.]+)\s*,\s*([0-9.]+)', txt, re.M)
    if m: return (float(m.group(1)), float(m.group(2))), 'build_ground.py ' + m.group(0).strip()
    m = re.search(pat + r'([0-9.]+)', txt, re.M)
    if m: return (float(m.group(1)), GANTRY_RAILS_PAGE_X[1]), 'build_ground.py (R1 only) ' + m.group(0).strip()
    return None, 'build_ground.py present but no rail page-x constant found'

def gantry_envelope(R1, R2, yc):
    X1, X2 = R1 * S_PT, R2 * S_PT; Y = -yc * S_PT
    half = GANTRY_LEG_SPLAY / 2 + 1.0
    legs = [sg.box(X - 0.55, Y - half, X + 0.55, Y + half) for X in (X1, X2)]
    girder = sg.box(X1 - GANTRY_OVERHANG - 0.6, Y - 1.3, X2 + GANTRY_OVERHANG + 0.6, Y + 1.3)
    return legs, girder

def photo_cameras_r3():
    try:
        ph = json.load(open(os.path.join(SOURCES_DIR, 'camera_poses.json'), encoding='utf-8'))
    except Exception:
        return []
    out = []
    for p in ph if isinstance(ph, list) else ph.get('cameras', []):
        pos = (p.get('pose') or {}).get('pos')
        if pos: out.append((p.get('id'), gltf_xz_to_r3([[pos[0], pos[2]]])[0]))
    return out

PARK_LOG = {}

def solve_park(R1, R2):
    if GANTRY_PARK_PAGE_Y is not None: return GANTRY_PARK_PAGE_Y, 'fixed parameter'
    cams = photo_cameras_r3()
    cands = []; rej = {}
    for yc in np.arange(400.0, 700.0, 0.5):
        legs, girder = gantry_envelope(R1, R2, yc)
        bad = [clear_of_vmus(l, clearance=GANTRY_CLEARANCE)[1] for l in legs if not clear_of_vmus(l, clearance=GANTRY_CLEARANCE)[0]]
        okg, gg = clear_of_vmus(girder, high_only=True, clearance=GANTRY_CLEARANCE)
        if not okg: bad.append(gg + ' (girder, high parts)')
        cam_hit = [i for i, c in cams if any(l.distance(sg.Point(c)) < GANTRY_CAMERA_CLEAR for l in legs)]
        if cam_hit: bad.append('camera ' + ','.join('p%s' % i for i in cam_hit))
        if not bad: cands.append(yc)
        elif abs(yc - GANTRY_PARK_TARGET_Y) <= 30: rej[round(float(yc), 1)] = '; '.join(sorted(set(bad)))
    if not cands: raise RuntimeError('no VMU-clear gantry parking position on the rails')
    yc = min(cands, key=lambda v: abs(v - GANTRY_PARK_TARGET_Y))
    PARK_LOG.update(target=GANTRY_PARK_TARGET_Y, chosen=float(yc), shift_from_target_m=round(float(yc - GANTRY_PARK_TARGET_Y) * S_PT, 2),
                    blocked_near_target={k: v for k, v in sorted(rej.items()) if abs(k - GANTRY_PARK_TARGET_Y) <= abs(yc - GANTRY_PARK_TARGET_Y) + 1},
                    cameras_checked=[i for i, _ in cams], camera_clear_m=GANTRY_CAMERA_CLEAR,
                    camera_to_leg_envelope_m={('p%s' % i): round(float(min(l.distance(sg.Point(c)) for l in gantry_envelope(R1, R2, yc)[0])), 2)
                                              for i, c in cams},
                    clear_window_page_y=[float(min((v for v in cands if abs(v - yc) < 15), default=yc)),
                                         float(max((v for v in cands if abs(v - yc) < 15), default=yc))])
    return yc, (f'solver: nearest clear position to target page y {GANTRY_PARK_TARGET_Y} (VMU hull clearance {GANTRY_CLEARANCE} m, posed '
                f'cameras >= {GANTRY_CAMERA_CLEAR} m from the leg envelopes; {len(cands)} clear candidates)')

def build_gantry(g, R1, R2, yc, src, conf, soffit, depth, gw, twin=False, cabin_end=0, hoist_frac=0.35, platform=True):
    X1, X2 = R1 * S_PT, R2 * S_PT; Y = -yc * S_PT
    kL = L(g, 'A-frame legs (tapered box)', 'CTX_GANTRY_LEG', '', conf)
    kE = L(g, 'End carriages + leg heads', 'CTX_GANTRY_LEG', '', conf)
    kW = L(g, 'Wheels', 'CTX_STEEL_GREY', '', 'low')
    kG = L(g, 'Box girder' + (' (twin)' if twin else ''), 'CTX_GANTRY_GIRDER', '', conf)
    kS = L(g, 'Girder stiffeners + flange lips', 'CTX_GANTRY_GIRDER', '', 'low')
    top_head = soffit - 0.55
    girders_y = [Y - 1.1, Y + 1.1] if twin else [Y]
    for X in (X1, X2):
        obox(kE, (X, Y), (0, 1), GANTRY_LEG_SPLAY / 2 + 0.85, 0.36, 0.12, 0.95)
        for sy in (-1, 1):
            obox(kW, (X, Y + sy * (GANTRY_LEG_SPLAY / 2 + 0.45)), (0, 1), 0.33, 0.14, 0.0, 0.62)
            foot = np.array([X, Y + sy * GANTRY_LEG_SPLAY / 2, 0.95]); head = np.array([X, Y + sy * 0.55, top_head])
            member(kL, foot, head, 0.45, 0.55, 0.72, 0.85, up=(1, 0, 0))
        obox(kE, (X, Y), (0, 1), 1.3 + (1.1 if twin else 0), 0.6, top_head - 0.35, soffit)
    XA, XB = X1 - GANTRY_OVERHANG, X2 + GANTRY_OVERHANG
    for yy in girders_y:
        obox(kG, ((XA + XB) / 2, yy), (1, 0), (XB - XA) / 2, gw / 2, soffit, soffit + depth)
        obox(kS, ((XA + XB) / 2, yy), (1, 0), (XB - XA) / 2 - 0.1, gw / 2 + 0.12, soffit - 0.03, soffit)
        for x in np.arange(XA + 0.75, XB - 0.5, 1.5):
            for sy in (-1, 1):
                obox(kS, (x, yy + sy * (gw / 2 + 0.03)), (1, 0), 0.012, 0.03, soffit + 0.05, soffit + depth - 0.05)
    if twin:
        for X in (X1, X2):
            obox(kG, (X, Y), (0, 1), 1.1 + gw / 2, 0.35, soffit + depth, soffit + depth + 0.5)
    kH = L(g, 'Hoist trolley', 'CTX_STEEL_GREY', '', 'low')
    kC = L(g, 'Hoist maintenance cage', 'STEEL_HDG', '', 'low')
    kR = L(g, 'Wire ropes + festoon cable', 'SEALANT_BLACK', '', 'low')
    kY = L(g, 'Hook block', 'CTX_SAFETY_YELLOW', '', 'low')
    xh = X1 + (X2 - X1) * hoist_frac
    for yy in girders_y[:1]:
        obox(kH, (xh, yy), (1, 0), 0.95, 0.55, soffit - 1.05, soffit - 0.05)
        cyl(kH, (xh + 0.2, yy + 0.62), 0.22, 0.22, soffit - 0.95, soffit - 0.25, n=10, bottom=True)
        zc = soffit - 2.05
        obox(kC, (xh, yy), (1, 0), 1.15, 0.95, zc - 0.05, zc)
        cx = [(xh - 1.1, yy - 0.9), (xh + 1.1, yy - 0.9), (xh + 1.1, yy + 0.9), (xh - 1.1, yy + 0.9)]
        for (x, y_) in cx: member(kC, (x, y_, zc), (x, y_, soffit - 0.05), 0.05)
        for zz in (zc + 0.55, zc + 1.1):
            for i in range(4):
                a, b = cx[i], cx[(i + 1) % 4]; member(kC, (a[0], a[1], zz), (b[0], b[1], zz), 0.04)
        hz = 5.4
        for dx in (-0.12, 0.12):
            member(kR, (xh + dx, yy, soffit - 1.05), (xh + dx, yy, hz + 0.5), 0.025)
        obox(kY, (xh, yy), (1, 0), 0.22, 0.16, hz, hz + 0.55)
        member(kY, (xh, yy, hz), (xh, yy, hz - 0.35), 0.08)
    yf = girders_y[-1] + gw / 2 + 0.25
    member(kR, (XA + 0.3, yf, soffit + 0.15), (XB - 0.3, yf, soffit + 0.15), 0.02)
    xs = np.arange(XA + 0.5, XB - 0.4, 2.2)
    for x0, x1 in zip(xs[:-1], xs[1:]):
        t = np.linspace(0, 1, 7); pts = [(x0 + (x1 - x0) * tt, yf, soffit + 0.1 - 0.55 * 4 * tt * (1 - tt)) for tt in t]
        for a, b in zip(pts[:-1], pts[1:]): member(kR, a, b, 0.035)
    if platform:
        Xp = (X1, X2)[cabin_end]; sgx = -1 if cabin_end == 0 else 1
        kP = L(g, 'Leg-head platform + railing', 'CTX_GANTRY_LEG', '', 'low')
        cxp = Xp + sgx * 1.45
        obox(kP, (cxp, Y), (1, 0), 0.85, 1.2, top_head - 0.5, top_head - 0.42)
        for (x, y_) in ((cxp - 0.8, Y - 1.15), (cxp + 0.8, Y - 1.15), (cxp + 0.8, Y + 1.15), (cxp - 0.8, Y + 1.15)):
            member(kP, (x, y_, top_head - 0.42), (x, y_, top_head + 0.65), 0.05)
        for i, (a, b) in enumerate((((cxp - 0.8, Y - 1.15), (cxp + 0.8, Y - 1.15)), ((cxp + 0.8, Y - 1.15), (cxp + 0.8, Y + 1.15)), ((cxp + 0.8, Y + 1.15), (cxp - 0.8, Y + 1.15)))):
            member(kP, (a[0], a[1], top_head + 0.62), (b[0], b[1], top_head + 0.62), 0.045)
        obox(kH, (cxp + sgx * 0.2, Y + 0.5), (1, 0), 0.3, 0.45, top_head - 0.42, top_head + 0.85)
        kF = L(g, 'Floodlight on leg head', 'CTX_LAMP', '', 'low')
        obox(kH, (Xp + sgx * 0.2, Y - 1.35), (1, 0), 0.08, 0.08, soffit - 0.2, soffit + depth + 0.5)
        lamp = np.array([Xp + sgx * 0.2, Y - 1.45, soffit + depth + 0.45])
        member(kF, lamp, lamp + np.array([0, -0.12, -0.08]), 0.45, 0.35)
    return dict(X1=X1, X2=X2, Y=Y, girder=[XA, XB], soffit=soffit, top=soffit + depth + (0.5 if twin else 0), hoist_x=xh)

def build_gantry_crane():
    rails, rsrc = rails_from_ground() if GANTRY_RAILS_SOURCE == 'ground' else (None, 'GANTRY_RAILS_SOURCE=' + GANTRY_RAILS_SOURCE)
    R1, R2 = rails if rails else GANTRY_RAILS_PAGE_X
    yc, psrc = solve_park(R1, R2)
    X1, X2 = R1 * S_PT, R2 * S_PT; Y = -yc * S_PT
    frac = GANTRY_HOIST_AT
    hoist_target = GANTRY_HOIST_TARGET if GANTRY_HOIST_TARGET is not None else (GANTRY_HOIST_TARGET_PAGE_X - R1) / (R2 - R1)
    if frac is None:
        H5 = vmu_hulls(z_high=5.0)
        def hoist_clear(f):
            pt = sg.Point(X1 + (X2 - X1) * f, Y).buffer(1.4)
            return all(hh is None or pt.distance(hh) >= 0.3 for (_, hh, _) in H5.values())
        fr = [f for f in np.arange(0.12, 0.88, 0.005) if hoist_clear(f)]
        frac = min(fr, key=lambda f: abs(f - hoist_target)) if fr else hoist_target
    g = group('Gantry crane', label='gantry crane (pale-blue A-frame legs, off-white box girder) parked on the rails near VMU-01',
              rails_page_x=[R1, R2], rails_source=rsrc if rails else ('default GANTRY_RAILS_PAGE_X; ' + rsrc),
              span_m=round((R2 - R1) * S_PT, 3), girder_length_m=round((R2 - R1) * S_PT + 2 * GANTRY_OVERHANG, 3),
              park_page_y=float(yc), park_source=psrc, park_target_page_y=GANTRY_PARK_TARGET_Y, park_log=PARK_LOG,
              hoist_target=dict(page_x=GANTRY_HOIST_TARGET_PAGE_X, span_fraction=round(float(hoist_target), 3)))
    info = build_gantry(g, R1, R2, yc, '', 'medium (look), low (rails / park position)',
                        GANTRY_GIRDER_SOFFIT, GANTRY_GIRDER_DEPTH, GANTRY_GIRDER_W, hoist_frac=frac)
    info.update(rails_page_x=[R1, R2], park_page_y=float(yc), hoist_frac=float(frac))
    return info


MASTS_PAGE = [(440.0, 682.0), (668.0, 702.0), (335.0, 410.0)]

def build_masts():
    g = group('High masts', label='3 high-mast floodlights, 14 m, 4 lamps', source='')
    kp = L(g, 'Galvanised poles', 'STEEL_HDG', '', 'medium (form), low (positions)')
    kb = L(g, 'Plinths', 'RC_PLAIN', '', 'low')
    kh = L(g, 'Lamp heads', 'CTX_STEEL_GREY', '', 'medium')
    kl = L(g, 'Lamp lenses', 'CTX_LAMP', '', 'medium')
    out = []
    for px, py in MASTS_PAGE:
        c = pg(px, py); H = 14.0
        obox(kb, c, (1, 0), 0.55, 0.55, 0.0, 0.3)
        obox(kp, c, (1, 0), 0.38, 0.38, 0.3, 0.33)
        cyl(kp, c, 0.19, 0.095, 0.33, H, n=12)
        u = unit(pg(0, 0) - pg(0, 1))
        arm = perp(u)
        member(kh, np.r_[c - arm * 1.0, H - 0.3], np.r_[c + arm * 1.0, H - 0.3], 0.1)
        member(kh, np.r_[c, H - 0.3], np.r_[c, H + 0.1], 0.14)
        for t in (-0.75, -0.25, 0.25, 0.75):
            base = c + arm * t
            face_dir = u if t < 0 else -u
            p0 = np.r_[base + face_dir * 0.05, H - 0.25]; p1 = p0 + np.r_[face_dir * 0.22, -0.12]
            member(kh, p0, p1, 0.46, 0.34)
            lc = p1 + np.r_[face_dir * 0.012, -0.007]
            member(kl, lc, lc + np.r_[face_dir * 0.01, -0.005], 0.40, 0.28)
        out.append(dict(page=[px, py], height=H))
    return out

def container(k_body, k_rib, k_door, c0, c1, xa, xb, h, rib=True):
    obox(k_body, ((xa + xb) / 2, (c0 + c1) / 2), (0, 1), (c1 - c0) / 2, (xb - xa) / 2, 0.0, h)
    if rib:
        for y in np.arange(c0 + 0.35, c1 - 0.3, 0.28):
            for x, sg_ in ((xa, -1), (xb, 1)):
                obox(k_rib, (x + sg_ * 0.02, y), (0, 1), 0.06, 0.02, 0.15, h - 0.12)
    for (x, y) in ((xa, c0), (xb, c0), (xa, c1), (xb, c1)):
        obox(k_door, (x + (0.08 if x == xa else -0.08), y + (0.08 if y == c0 else -0.08)), (0, 1), 0.09, 0.09, 0.0, h + 0.01)
    for xx in np.linspace(xa + 0.35, xb - 0.35, 4):
        obox(k_door, (xx, c1 + 0.03), (1, 0), 0.025, 0.025, 0.2, h - 0.2)

def build_containers():
    g = group('Containers + site office', label='R3 container row (off-white / light grey) with the white 20 ft site office at the main road end',
              source='')
    src = 'layout plan container strip + site photos'
    cx0, cx1, ya, yb = 458.0, 470.0, 420.4, 694.7
    xa, xb = pg(cx0, 0)[0], pg(cx1, 0)[0]
    lens = [12.192, 12.192, 12.192, 12.192, 6.058]
    Ltot = (yb - ya) * S_PT; gap = (Ltot - sum(lens)) / (len(lens) - 1)
    yT = pg(0, ya)[1]; cur = yT; spans = []
    mats = ['CTX_CONTAINER_WHITE', 'CTX_CONTAINER_GREY', 'CTX_CONTAINER_WHITE', 'CTX_CONTAINER_GREY', 'CTX_CONTAINER_WHITE']
    kd = L(g, 'Container corner posts + door bars', 'CTX_STEEL_GREY', '', 'low')
    for i, Lc in enumerate(lens):
        y_hi = cur; y_lo = cur - Lc
        m = mats[i]
        kb = L(g, f'Container {i + 1} body' + (' (site office 20 ft)' if i == 4 else ' (40 ft HC)'), m, '', 'medium (row), low (colours per unit)')
        h = 2.896 if Lc > 7 else 2.591
        container(kb, kb, kd, y_lo, y_hi, xa, xb, h)
        spans.append((y_lo, y_hi, h)); cur = y_lo - gap
    if SHOW_SITE_OFFICE:
        y_lo, y_hi, h = spans[-1]
        kw = L(g, 'Site office window + door', 'CTX_BAY_VOID', '', 'low')
        ka = L(g, 'Site office window AC unit', 'CTX_CONTAINER_WHITE', '', 'medium')
        kdb = L(g, 'Site office DB box', 'CTX_STEEL_GREY', '', 'low')
        ksk = L(g, 'Site office DB sockets', 'CTX_STILLAGE_RED', '', 'low')
        xo = xa - 0.012
        obox(kw, (xo, y_lo + 1.6), (0, 1), 0.6, 0.02, 1.0, 2.0)
        obox(kw, (xo, y_lo + 4.7), (0, 1), 0.45, 0.02, 0.1, 2.15)
        obox(ka, (xa - 0.3, y_lo + 3.1), (0, 1), 0.33, 0.3, 1.8, 2.25)
        obox(kdb, (xa - 0.08, y_lo + 3.9), (0, 1), 0.25, 0.08, 1.1, 1.75)
        for dz in (1.2, 1.4):
            obox(ksk, (xa - 0.17, y_lo + 3.9), (0, 1), 0.06, 0.02, dz, dz + 0.1)
        obox(kd, (xa - 0.45, y_lo + 4.7), (0, 1), 0.55, 0.4, 0.0, 0.2)
    return dict(xa=xa, xb=xb, spans=spans)

PLATFORM_R3_PAGE = (393.48, 406.08, 494.40, 613.20)

def build_platform(ct):
    if PLATFORM_POSITION == 'containers':
        return build_platform_on_containers(ct)
    g = group('Temporary steel viewing platform', label='temporary steel viewing platform on the R3 footprint (2.64 x 24.87 m), 30 m from VMU-01',
              source='',
              note='',
              deck_level=PLATFORM_DECK_H)
    src = 'layout plan viewing-platform rectangle; level + structure assumed (scaffold-type steel)'
    x0, x1, y0, y1 = PLATFORM_R3_PAGE
    A = pg(x0, y1); B = pg(x1, y0)
    xa, xb = A[0], B[0]; ya, yb = A[1], B[1]
    zD = PLATFORM_DECK_H
    kD = L(g, 'Deck (chequer plate)', 'STEEL_HDG', '', 'medium (footprint), low (level)')
    kF = L(g, 'Frame (posts + bracing)', 'STEEL_HDG', '', 'low')
    kG = L(g, 'Guardrails + toe boards', 'CTX_SAFETY_YELLOW', '', 'low')
    kS = L(g, 'Stair', 'STEEL_HDG', '', 'low (position assumed: WSW side, main road end)')
    cx, cy = (xa + xb) / 2, (ya + yb) / 2
    obox(kD, (cx, cy), (0, 1), (yb - ya) / 2, (xb - xa) / 2, zD - 0.12, zD)
    ny = max(2, int(math.ceil((yb - ya) / 2.5)))
    ys = np.linspace(ya + 0.08, yb - 0.08, ny + 1)
    for yy in ys:
        for xx in (xa + 0.08, xb - 0.08):
            obox(kF, (xx, yy), (1, 0), 0.05, 0.05, 0.0, zD - 0.12)
            obox(kF, (xx, yy), (1, 0), 0.12, 0.12, 0.0, 0.02)
        seg_box(kF, (xa + 0.08, yy), (xb - 0.08, yy), 0.08, zD - 0.32, zD - 0.12)
    for xx in (xa + 0.08, xb - 0.08):
        seg_box(kF, (xx, ys[0]), (xx, ys[-1]), 0.06, 0.25, 0.31)
        for i in range(ny):
            A3 = np.array([xx, ys[i], 0.3]); B3 = np.array([xx, ys[i + 1], zD - 0.35])
            if i % 2: A3[1], B3[1] = B3[1], A3[1]
            member(kF, A3, B3, 0.045)
    st_w = 1.0; open_y = (ya + 0.1, ya + 1.3)
    for yy in np.arange(ya + 0.05, yb, 2.0):
        for xx in (xa + 0.03, xb - 0.03):
            if xx < cx and open_y[0] - 0.05 < yy < open_y[1] + 0.05: continue
            obox(kG, (xx, yy), (1, 0), 0.025, 0.025, zD, zD + 1.1)
    for zz, h in ((zD + 1.1, 0.05), (zD + 0.55, 0.04), (zD + 0.15, 0.15)):
        seg_box(kG, (xb - 0.03, ya), (xb - 0.03, yb), 0.05, zz - h, zz)
        seg_box(kG, (xa + 0.03, open_y[1]), (xa + 0.03, yb), 0.05, zz - h, zz)
        for yy in (ya + 0.03, yb - 0.03):
            seg_box(kG, (xa, yy), (xb, yy), 0.05, zz - h, zz)
    nr = int(math.ceil(zD / 0.18)); rise = zD / nr; going = 0.25
    xs0 = xa - st_w - 0.05; y_top = open_y[0] + 0.05
    for k in range(nr):
        z = rise * (k + 1); yy = y_top + (nr - 1 - k) * going
        obox(kS, (xs0 + st_w / 2, yy + going / 2), (0, 1), going / 2, st_w / 2, z - 0.04, z)
    y_bot = y_top + nr * going
    for xx in (xs0, xs0 + st_w):
        member(kS, (xx, y_bot, 0.14), (xx, y_top, zD - 0.02), 0.06, 0.25)
        member(kG, (xx, y_bot, 1.0), (xx, y_top, zD + 1.0), 0.05)
        for yy, zz in ((y_bot, 0.0), (y_top, zD - 0.3)):
            obox(kG, (xx, yy), (1, 0), 0.025, 0.025, zz, zz + 1.05)
    return dict(position='r3', page_rect=list(PLATFORM_R3_PAGE), size_m=[round(float(xb - xa), 3), round(float(yb - ya), 3)], deck=zD,
                stair_page_y=[round(float(-y_top / S_PT), 1), round(float(-y_bot / S_PT), 1)])

def build_platform_on_containers(ct):
    g = group('Temporary steel viewing platform', label='temporary steel viewing platform on containers 2-3 (old model position, contradicts R3)',
              source='')
    src = 'build_context.py geometry (form assumed) + R3 label'
    xa, xb, spans = ct['xa'], ct['xb'], ct['spans']
    py_lo, py_hi = spans[2][0], spans[1][1]
    kD = L(g, 'Deck (chequer plate)', 'STEEL_HDG', '', 'low')
    kG = L(g, 'Guardrails', 'CTX_SAFETY_YELLOW', '', 'low')
    kS = L(g, 'Stair', 'STEEL_HDG', '', 'low')
    obox(kD, ((xa + xb) / 2, (py_lo + py_hi) / 2), (0, 1), (py_hi - py_lo) / 2, (xb - xa) / 2 + 0.6, 2.90, 3.00)
    for yy in np.arange(py_lo, py_hi + 0.01, 2.0):
        for xx in (xa - 0.55, xb + 0.55): obox(kG, (xx, yy), (1, 0), 0.03, 0.03, 3.0, 4.1)
    for xx in (xa - 0.55, xb + 0.55):
        for zz in (3.55, 4.1): seg_box(kG, (xx, py_lo), (xx, py_hi), 0.05, zz - 0.05, zz)
    for yy in (py_lo, py_hi):
        for zz in (3.55, 4.1): seg_box(kG, (xa - 0.55, yy), (xb + 0.55, yy), 0.05, zz - 0.05, zz)
    st_y = py_hi - 1.2
    for k in range(16):
        z = 3.0 * (k + 1) / 16; xx = xa - 0.7 - (15 - k) * 0.25
        obox(kS, (xx - 0.125, st_y - 0.5), (1, 0), 0.125, 0.5, z - 0.05, z)
    seg_box(kS, (xa - 0.7 - 16 * 0.25, st_y - 1.0), (xa - 0.7, st_y - 1.0), 0.06, 0.0, 3.0)
    return dict(position='containers', deck_y=[py_lo, py_hi])

STILLAGES_PAGE = [(322.0, 445.0), (336.0, 445.0), (322.0, 480.0), (336.0, 480.0)]

def build_stillages():
    g = group('Material storage (stillages)', label='4 red-oxide steel stillages with aluminium extrusions (R3 "storage area")',
              source='')
    kS = L(g, 'Red stillages', 'CTX_STILLAGE_RED', '', 'medium (look), low (positions)')
    kA = L(g, 'Aluminium stock (extrusions)', 'AL_MILL', '', 'low')
    out = []
    for i, (px, py) in enumerate(STILLAGES_PAGE):
        c = pg(px, py); u = np.array([0.0, 1.0]); v = perp(u)
        Ls, Ws, Hs = 6.0, 1.2, 1.1
        corners = [c + u * su * Ls / 2 + v * sv * Ws / 2 for su in (-1, 1) for sv in (-1, 1)]
        for q in corners: obox(kS, q, u, 0.05, 0.05, 0.0, Hs)
        for su in (-1, -1 / 3, 1 / 3, 1):
            for sv in (-1, 1):
                q = c + u * su * Ls / 2 + v * sv * Ws / 2
                obox(kS, q, u, 0.04, 0.04, 0.0, Hs)
        for z0 in (0.12, 0.6, Hs - 0.06):
            for sv in (-1, 1):
                seg_box(kS, c - u * Ls / 2 + v * sv * Ws / 2, c + u * Ls / 2 + v * sv * Ws / 2, 0.08, z0 - 0.06, z0 + 0.02)
        for su in (-1, -0.33, 0.33, 1):
            seg_box(kS, c + u * su * Ls / 2 - v * Ws / 2, c + u * su * Ls / 2 + v * Ws / 2, 0.08, 0.14, 0.22)
        nst = 3 + i % 3
        for j in range(nst * 4):
            row, col_ = divmod(j, 4)
            q = c + v * (-0.42 + col_ * 0.28)
            obox(kA, q, u, Ls / 2 + 0.25, 0.1, 0.22 + row * 0.13, 0.22 + row * 0.13 + 0.11)
        out.append(dict(page=[px, py]))
    return out

def normals(G, F):
    N = np.zeros_like(G)
    a, b, c = G[F[:, 0]], G[F[:, 1]], G[F[:, 2]]
    fn = np.cross(b - a, c - a)
    for i in range(3): np.add.at(N, F[:, i], fn)
    ln = np.linalg.norm(N, axis=1); ln[ln < 1e-12] = 1
    return N / ln[:, None]

def sanitize(o):
    if isinstance(o, dict): return {str(k): sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [sanitize(v) for v in o]
    if isinstance(o, np.ndarray): return sanitize(o.tolist())
    if isinstance(o, (np.floating,)): return round(float(o), 4)
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, float): return round(o, 4)
    return o

def write(meta):
    by_group = collections.OrderedDict(); stats = collections.OrderedDict()
    for (grp, layer), p in PARTS.items():
        if not p['V']: continue
        V = np.vstack(p['V']); F = np.vstack(p['F']); UV = np.vstack(p['UV'])
        Gv = r3_to_gltf(V[:, :2], V[:, 2])
        N = normals(Gv, F)
        mat = p['mat']
        mi = M(mat)
        name = f'{grp}|{layer}'
        me = glb.mesh(name, Gv, F, N, mi, uvs=UV)
        ex = dict(group=grp, layer_en=layer, finish=mat, **p['meta'], triangles=int(len(F)), context=True)
        nid = glb.node(name, mesh=me, extras=ex)
        by_group.setdefault(grp, []).append(nid)
        s = stats.setdefault(grp, dict(triangles=0, bbox_min=[1e9] * 3, bbox_max=[-1e9] * 3, layers=0))
        s['triangles'] += int(len(F)); s['layers'] += 1
        s['bbox_min'] = np.minimum(s['bbox_min'], Gv.min(0)).tolist(); s['bbox_max'] = np.maximum(s['bbox_max'], Gv.max(0)).tolist()
    for grp, ch in by_group.items():
        glb.node(grp, children=ch, root=True, extras=dict(group=grp, context=True, **GROUP_META.get(grp, {})))
    meta['groups'] = {k: dict(v, bbox_min=[round(x, 3) for x in v['bbox_min']], bbox_max=[round(x, 3) for x in v['bbox_max']]) for k, v in stats.items()}
    meta['triangles'] = int(sum(v['triangles'] for v in stats.values()))
    meta['materials'] = [m['name'] for m in glb.materials]
    meta = sanitize(meta)
    for n_ in glb.nodes:
        if 'extras' in n_: n_['extras'] = sanitize(n_['extras'])
    glb.save(OUT, extras=meta)
    return meta

YARD_LOT_PAGE = (307.08, 1300.0, 377.40, 780.0)
HAND_GROUPS = ('Factory 1 (1-storey shed)', 'Factory 2-storey west', 'Factory 2 north block', 'Accessway truss canopy')

def hand_footprints():
    from shapely.geometry import MultiPoint
    from shapely.ops import unary_union
    per = collections.defaultdict(list)
    for (grp, layer), p in PARTS.items():
        if grp not in HAND_GROUPS or not p['V']: continue
        V = np.vstack(p['V'])[:, :2]
        h = MultiPoint(V).convex_hull
        if h.area > 0.01: per[grp].append(h)
    x0, x1, y0, y1 = YARD_LOT_PAGE
    polys = {g: unary_union(v) for g, v in per.items()}
    polys['VMU yard lot (ESE of grid P)'] = page_band_r3(y0, y1, x0, x1)
    return dict(union=unary_union(list(polys.values())), polys=polys, groups={g: round(v.area, 1) for g, v in polys.items()})


def main():
    meta = dict(builder='build/build_context2.py', y0='yard slab top', ground_level_assumed=4.5,
                params=dict(Q6_NORTH_BLOCK_STATE=Q6_NORTH_BLOCK_STATE, WEST_FACTORY_STATE=WEST_FACTORY_STATE,
                            WEST_FACTORY_RC_TOP=WEST_FACTORY_RC_TOP, YELLOW_LATTICE_HOST=YELLOW_LATTICE_HOST, INCLUDE_YARD_SLAB=INCLUDE_YARD_SLAB,
                            SHOW_SITE_OFFICE=SHOW_SITE_OFFICE, SHOW_STILLAGES=SHOW_STILLAGES, SHOW_MASTS=SHOW_MASTS, SHOW_MOBILE_PLANT=SHOW_MOBILE_PLANT,
                            HOARDING_H=HOARDING_H, GATE_STATE=GATE_STATE, GANTRY_RAILS_PAGE_X=list(GANTRY_RAILS_PAGE_X),
                            GANTRY_PARK_TARGET_Y=GANTRY_PARK_TARGET_Y, WEST_TALL_BLOCK_TOP=WEST_TALL_BLOCK_TOP,
                            PLATFORM_POSITION=PLATFORM_POSITION, PLATFORM_DECK_H=PLATFORM_DECK_H, F1_BAND_D=F1_BAND_D,
                            F1_FRONT_COL_W=F1_FRONT_COL_W, F1_CORNER_COL_W=F1_CORNER_COL_W, F1_ROOF_TOWER_D=F1_ROOF_TOWER_D,
                            GANTRY_RAILS_SOURCE=GANTRY_RAILS_SOURCE, SOUTH_BOUNDARY_TYPE=SOUTH_BOUNDARY_TYPE, CHAINLINK_H=CHAINLINK_H,
                            ACCESSWAY_CANOPY=ACCESSWAY_CANOPY, ACCESSWAY_CANOPY_PAGE=list(ACCESSWAY_CANOPY_PAGE),
                            ACCESSWAY_CANOPY_TOP=ACCESSWAY_CANOPY_TOP, NORTH_BLOCK_STAIR=NORTH_BLOCK_STAIR, F1_ROOF_MODE=F1_ROOF_MODE),
                not_included='yard slab, drains, crane rails + red lines, main road (build_ground.py); palms / people / cars '
                             '(build_features2.py); mobile plant')
    build_factory1()
    meta['west_factory'] = build_west_factory()
    build_north_block()
    if ACCESSWAY_CANOPY: meta['accessway_canopy'] = build_accessway_canopy()
    meta['hoarding_lines'], meta['gate'] = build_hoarding()
    meta['gantry'] = build_gantry_crane()
    if SHOW_MASTS: meta['masts'] = build_masts()
    ct = build_containers()
    meta['platform'] = build_platform(ct)
    if SHOW_STILLAGES: meta['stillages'] = build_stillages()
    hand = hand_footprints()
    meta['hand_footprint_groups'] = hand['groups']
    meta = write(meta)
    json.dump(meta, open(os.path.join(SCRATCH, 'site_context_summary.json'), 'w'), indent=1, default=float)
    if not os.environ.get('MOCKUP_CONTEXT_OUT'):
        json.dump(meta, open(os.path.join(ROOT, 'model', 'site_context_summary.json'), 'w'), indent=1, default=float)
    print(json.dumps({k: meta[k] for k in ('triangles', 'materials')}, indent=0))
    for k, v in meta['groups'].items(): print(f"  {k:48s} tris {v['triangles']:7d}  bbox {v['bbox_min']} .. {v['bbox_max']}")
    print('gantry:', {k: meta['gantry'][k] for k in ('rails_page_x', 'park_page_y', 'hoist_frac', 'soffit', 'top')})
    print('wrote', OUT, os.path.getsize(OUT), 'bytes')

if __name__ == '__main__':
    main()
