"""Builds model/vmu01_canopy.glb: the VMU-01 canopy (existing part + canopy extension) rebuilt parametrically from the
canopy plan (outline with bulges, top / ceiling panel joints, oculus, column set-out) and the 1.5 degree section:
25 mm honeycomb top field + joints, 150 top band, 100 fascia, 420 x 205 chamfer, soffit panels + joints, concealed
primaries, CHS150 columns with base plates, stiffeners and bolts. The canopy is one plane falling to the west.
Finishes come from materials_lib (the canopy is never red). Options: MOCKUP_CANOPY_SLOPE_OPTION, _SCHEME, _TOP,
_CLAD_FINISH, _COLUMN_FINISH, _COLUMNS, _OCULUS_*. Needs the private canopy plan extract, the legacy CAD cache and the
registration file in SOURCES_DIR (not included).
"""
import os, sys, json, math, hashlib, pickle, time, argparse, collections
SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.chdir(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import numpy as np
import shapely
import shapely.geometry as sg
import shapely.ops as so
from shapely.geometry.polygon import orient
import mapbox_earcut as earcut
from gltfw import GLB
from site_frame import r3_to_gltf, r3_dir_to_gltf
import materials_lib as ML

def _env(k, d):
    return os.environ.get('MOCKUP_CANOPY_' + k, d)

def parse_slope(s):
    s = str(s).strip().lower().replace(' ', '').replace('°', 'deg')
    if s.endswith('deg'):
        return math.tan(math.radians(float(s[:-3])))
    if s.startswith('1:'):
        return 1.0 / float(s[2:])
    return float(s)

SLOPE_OPTION = _env('SLOPE_OPTION', _env('SLOPE', '1.5deg'))
SLOPE = parse_slope(SLOPE_OPTION)
CANOPY_SCHEMES = collections.OrderedDict((
    ('ORDERS', dict(top='AL_MOUSEGREY', clad='AL_T02',
                    note='')),
    ('RAL7038', dict(top='AL_RAL7038', clad='AL_RAL7038',
                     note='')),
))
SCHEME = _env('SCHEME', 'ORDERS').strip().upper()
if SCHEME not in CANOPY_SCHEMES:
    raise ValueError('MOCKUP_CANOPY_SCHEME must be one of %s (never red)' % list(CANOPY_SCHEMES))
TOP_FINISH = ML.CANOPY_TOP_MATERIAL if os.environ.get('MOCKUP_CANOPY_TOP') else CANOPY_SCHEMES[SCHEME]['top']
CLAD_OPTIONS = ('AL_T02', 'AL_RAL7038')
CLAD_FINISH = _env('CLAD_FINISH', CANOPY_SCHEMES[SCHEME]['clad'])
if CLAD_FINISH not in CLAD_OPTIONS:
    raise ValueError('MOCKUP_CANOPY_CLAD_FINISH must be one of %s (never red)' % (CLAD_OPTIONS,))
COLUMN_OPTIONS = ('AL_T02', 'STEEL_HDG')
COLUMN_FINISH = _env('COLUMN_FINISH', 'AL_T02')
if COLUMN_FINISH not in COLUMN_OPTIONS:
    raise ValueError('MOCKUP_CANOPY_COLUMN_FINISH must be one of %s' % (COLUMN_OPTIONS,))
COLUMNS_LAYOUTS = ('dwg_cen', 'dwg_asdrawn', 'asbuilt6')
_COL_ALIAS = {'dwg': 'dwg_asdrawn', 'asdrawn': 'dwg_asdrawn', 'legacy_cad_r7': 'asbuilt6', 'cen': 'dwg_cen'}
COLUMNS = _env('COLUMNS', 'dwg_cen').strip().lower()
COLUMNS = _COL_ALIAS.get(COLUMNS, COLUMNS)
if COLUMNS not in COLUMNS_LAYOUTS:
    raise ValueError('MOCKUP_CANOPY_COLUMNS must be one of %s' % (COLUMNS_LAYOUTS,))
TOWER_STRIP_PART = _env('TOWER_STRIP_PART', 'existing')
TOP_AT_HIGH_EDGE = 3.350
FASCIA_H = 0.100
CHAMFER_W = 0.420
DEPTH = 0.306
CHAMFER_DROP = DEPTH - FASCIA_H
TOP_BAND_W = 0.150
SOFFIT_BAND_W = 0.495
JOINT_W = 0.020
JOINT_RECESS = 0.002
OCULUS_VOID_D = float(_env('OCULUS_VOID_D', '2.20'))
OCULUS_BAND_W = float(_env('OCULUS_BAND_W', '0.150'))
OCULUS_RIM = _env('OCULUS_RIM', 'vertical')
if OCULUS_RIM not in ('vertical', 'chamfer'):
    raise ValueError('MOCKUP_CANOPY_OCULUS_RIM must be vertical or chamfer')
PRIMARY_W, PRIMARY_H, PRIMARY_TOP_BELOW = 0.100, 0.150, 0.126
CAP_BELOW_TOP = 0.126
CHS_D, CHS_T, CHS_SEG = 0.150, 0.005, 48
BP = 0.400
BP_T = float(_env('BASEPLATE_T', '0.012'))
STIFF_T = 0.005
STIFF_R0, STIFF_R_DIAG, STIFF_R_ORTH = 0.075, 0.172, 0.110
STIFF_H0, STIFF_H1 = 0.150, 0.030
BOLT_PITCH = 0.150
WASHER, WASHER_T = 0.050, 0.008
NUT_AF, NUT_H, BOLT_D, BOLT_STUB = 0.036, 0.019, 0.024, 0.020
PLINTH, PLINTH_H = 0.650, 0.100
PLINTH_TOP = float(_env('PLINTH_TOP', '0.0'))
ARC_STEP_DEG = 2.5
DENSIFY = 0.05
OUT = _env('OUT', os.path.join(ROOT, 'model', 'vmu01_canopy.glb'))
SCRATCH = _env('SCRATCH', os.path.join(HERE, '_scratch', 'canopy'))
PLAN_JSON = os.path.join(SOURCES_DIR, 'canopy_plan_extract.json')
DXF_PATH = os.path.join(SOURCES_DIR, 'canopy_plan_dxf')
DWG_PATH = os.path.join(SOURCES_DIR, 'canopy_plan_dwg')
SEC_PDF = os.path.join(SOURCES_DIR, 'canopy_section')
EXTRACT_JSON = os.path.join(SCRATCH, 'canopy_dxf_extract.json')
R7_JSON = os.path.join(SOURCES_DIR, 'canopy_candidate_a.json')
JSON_ORIGIN_R3M = np.array([108.43167, -131.65244])
DWG_CEN_BULGE_MM = [
    (8604.9998, 6345.0, 0.0), (8604.9971, 12255.0307, 0.0), (8399.686, 12255.0435, -0.298133), (6294.4727, 13634.4369, 0.0),
    (4511.4897, 11851.454, -0.198912), (3312.9437, 11355.0, 0.0), (2155.8875, 11355.0, -0.198912), (957.3415, 11851.454, 0.0),
    (-301.4897, 13110.2852, 0.668179), (-1505.0, 12611.7749, 0.0), (-1505.0, 10100.0, 0.414214), (-800.0, 9395.0, 0.0),
    (1900.0, 9395.0, -0.414214), (3595.0, 7700.0, 0.0), (3595.0, 6701.8025, -0.244698), (2872.2121, 5313.3398, 0.0),
    (-1204.3714, 2458.8853, 0.244698), (-1505.0, 1881.3831, 0.0), (-1505.0, -600.0, 0.414214), (-800.0, -1305.0, 0.0),
    (248.5281, -1305.0, 0.198912), (747.0384, -1098.5103, 0.0), (2898.5103, 1052.9616, 0.198912), (3105.0, 1551.4719, 0.0),
    (3105.0, 2760.0, -0.414214), (4800.0, 4455.0, 0.0), (6141.0179, 4455.0, -0.363159), (8400.0, 6345.0, 0.0)]
R7_COLUMNS_R3M = [(106.957, -118.455), (106.856, -121.868), (106.957, -129.154), (106.661, -131.091), (107.408, -133.067),
                  (109.558, -132.504), (110.760, -131.206)]
R7_SNAP_TOL = 0.25
INS_2F = np.array([90692.403, 6428.531])
GROUP = 'VMU01_CANOPY'
SRC_S1 = ''
SRC_S2 = ''
SRC_S3 = ''
SRC_DET = ''
SRC_LEGACY_CAD = ''
if SLOPE <= 0 or SLOPE > 0.1:
    raise ValueError('MOCKUP_CANOPY_SLOPE_OPTION must give a fall between 0 and 0.1 (e.g. 1.5deg or 1:100)')
if TOWER_STRIP_PART not in ('existing', 'extension'):
    raise ValueError('MOCKUP_CANOPY_TOWER_STRIP_PART must be existing or extension')

REG = json.load(open('group_registration.json'))
_r = REG['reg']['VMU01']
_a = math.radians(_r['rot_deg'])
C0 = np.array(_r['c0']); RM = np.array([[math.cos(_a), math.sin(_a)], [-math.sin(_a), math.cos(_a)]]); T0 = np.array([_r['tx'], _r['ty']])

def rh2r3(P):
    return (np.atleast_2d(np.asarray(P, float))[:, :2] - C0) @ RM + T0

def r32rh(Q):
    return (np.atleast_2d(np.asarray(Q, float))[:, :2] - T0) @ RM.T + C0

def world(P3):
    P3 = np.asarray(P3, float)
    return r3_to_gltf(rh2r3(P3[:, :2]), P3[:, 2])

def world_n(N3):
    N3 = np.asarray(N3, float)
    n2 = r3_dir_to_gltf(N3[:, :2] @ RM)
    return np.c_[n2[:, 0], N3[:, 2], n2[:, 1]]

print('[build step] loading legacy CAD cache ...'); t0 = time.time()
CACHE = pickle.load(open('legacy_cad_cache_n.pkl', 'rb'))
MESHES = CACHE['meshes']
V01 = [m for i, m in enumerate(MESHES) if REG['assign'].get(str(i)) == 'VMU01']
CANOPY_LAYERS = ('铝板', '铝板侧面', '铝板底面')
TOWER_LAYERS = ('玻璃面板', '立柱', '横梁', '中横梁', '收口铝板')

def is_old_canopy(m):
    return (m['layer'] in CANOPY_LAYERS and m['V'][:, 2].max() < 3.6) or m['layer'] == '铁架::150X5圆管'

def tri_union(ms, pad=0.001):
    polys = []
    for m in ms:
        for f in m['F']:
            p = sg.Polygon(m['V'][f][:, :2])
            if p.is_valid and p.area > 1e-9:
                polys.append(p)
    return so.unary_union(polys).buffer(pad, join_style=2).buffer(-pad, join_style=2)

EXIST_FP = tri_union([m for m in V01 if m['layer'] in CANOPY_LAYERS and m['V'][:, 2].max() < 3.6])
if EXIST_FP.geom_type != 'Polygon':
    EXIST_FP = max(EXIST_FP.geoms, key=lambda g: g.area)
TOWER_FP = tri_union([m for m in V01 if m['layer'] in TOWER_LAYERS], pad=0.002)
TOWER_LOW = tri_union([m for m in V01 if m['layer'] in TOWER_LAYERS and m['V'][:, 2].min() < 3.9], pad=0.002)
_ge = np.concatenate([np.r_[m['V'][m['F']][:, [0, 1], :2], m['V'][m['F']][:, [1, 2], :2], m['V'][m['F']][:, [2, 0], :2]]
                      for m in V01 if m['layer'] == '玻璃面板'])
_ge = np.unique(np.round(_ge[np.linalg.norm(_ge[:, 1] - _ge[:, 0], axis=1) > 1e-4], 5), axis=0)
TOWER_GLASS = sg.MultiLineString([tuple(map(tuple, e)) for e in _ge])
TOWER_INTERIOR = tri_union([m for m in V01 if m['layer'] in ('吊顶', '室内完成面', '中横梁', '横梁', '立柱')], pad=0.002)
FINS_LOW = tri_union([m for m in V01 if m['layer'] == '装饰条' and m['V'][:, 2].min() < 3.6 and m['V'][:, 2].max() < 4.2])
OLD_COLS = [((m['V'][:, :2].min(0) + m['V'][:, :2].max(0)) / 2) for m in V01 if m['layer'] == '铁架::150X5圆管']
TOWER_COLS = [((m['V'][:, :2].min(0) + m['V'][:, :2].max(0)) / 2) for m in V01 if m['layer'] == '铁架::300X300X9方通']
print('[build step] legacy CAD: old canopy %.3f m2, %d old CHS columns, %d tower columns (%.1fs)' % (EXIST_FP.area, len(OLD_COLS), len(TOWER_COLS), time.time() - t0))
PLAN = json.load(open(PLAN_JSON, encoding='utf-8'))

def md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()

def extract_dxf():
    import ezdxf, logging
    from ezdxf import path as ezpath
    import operator
    _dx = operator.attrgetter('dxf')
    logging.disable(logging.WARNING)
    print('[build step] reading DXF', DXF_PATH)
    doc = ezdxf.readfile(DXF_PATH)
    msp = doc.modelspace()
    cols = [(_dx(e).insert.x, _dx(e).insert.y) for e in msp.query('INSERT[name=="钢立柱"]')]
    f1 = [c for c in cols if c[0] < 90000]; f2 = [c for c in cols if c[0] >= 90000]
    grid = dict(g1x_1F=min(c[0] for c in f1), gAy=min(c[1] for c in f1), dx_2F=min(c[0] for c in f2) - min(c[0] for c in f1),
                n_1F=len(f1), n_2F=len(f2), rows_1F=sorted(set(round(c[1], 1) for c in f1)), cols_1F=sorted(set(round(c[0], 1) for c in f1)))
    reg = (86000, 2000, 101000, 23000)
    out = dict(edge=None, circles=[], grid=grid)
    for e in msp:
        t = e.dxftype()
        if t == 'LWPOLYLINE' and _dx(e).layer == 'ALUM' and not e.closed:
            P = np.array([(v.x, v.y) for v in ezpath.make_path(e).flattening(0.5)])
            if len(P) >= 3 and reg[0] <= P[:, 0].mean() <= reg[2] and reg[1] <= P[:, 1].mean() <= reg[3] and np.linalg.norm(np.diff(P, axis=0), axis=1).sum() > 40000:
                out['edge'] = P.tolist()
        elif t == 'CIRCLE' and _dx(e).radius > 500 and reg[0] <= _dx(e).center.x <= reg[2] and reg[1] <= _dx(e).center.y <= reg[3]:
            out['circles'].append(dict(layer=_dx(e).layer, c=list(_dx(e).center)[:2], r=_dx(e).radius))
    out['source'] = dict(dwg_md5=md5(DWG_PATH) if os.path.exists(DWG_PATH) else None)
    os.makedirs(SCRATCH, exist_ok=True)
    json.dump(out, open(EXTRACT_JSON, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    return out

ap = argparse.ArgumentParser()
ap.add_argument('--extract', action='store_true')
ap.add_argument('--no-verify', action='store_true')
ARGS = ap.parse_args()
DX = extract_dxf() if (ARGS.extract or not os.path.exists(EXTRACT_JSON)) else json.load(open(EXTRACT_JSON, encoding='utf-8'))
G = DX['grid']
TC = np.array(TOWER_COLS)
RH_G1X, RH_GAY = TC[:, 0].min(), TC[:, 1].min()

def dxf2rh(P, plan2f=True):
    P = np.atleast_2d(np.asarray(P, float)).copy()
    if plan2f:
        P[:, 0] -= G['dx_2F']
    return np.c_[(P[:, 0] - G['g1x_1F']) / 1000.0 + RH_G1X, (P[:, 1] - G['gAy']) / 1000.0 + RH_GAY]

def blk2rh(P):
    return dxf2rh(np.atleast_2d(np.asarray(P, float))[:, :2] + INS_2F, plan2f=True)

def j2rh(P):
    return blk2rh((np.atleast_2d(np.asarray(P, float))[:, :2] - JSON_ORIGIN_R3M) * 1000.0)

def rh2j(P):
    OCr = blk2rh([[0, 0]])[0]
    return np.atleast_2d(np.asarray(P, float))[:, :2] - OCr + JSON_ORIGIN_R3M

def rh2blk(P):
    P = np.atleast_2d(np.asarray(P, float))[:, :2]
    return np.c_[(P[:, 0] - RH_G1X) * 1000.0 + G['g1x_1F'] + G['dx_2F'] - INS_2F[0], (P[:, 1] - RH_GAY) * 1000.0 + G['gAy'] - INS_2F[1]]

def nearest_on_bulge_ring(VB, p):
    VB = np.asarray(VB, float); p = np.asarray(p, float); n = len(VB); best = (None, 1e18, None)
    for i in range(n):
        a, b, bu = VB[i, :2], VB[(i + 1) % n, :2], VB[i, 2]
        if abs(bu) < 1e-9:
            d = b - a; t = float(np.clip((p - a) @ d / (d @ d), 0.0, 1.0)); q = a + t * d
        else:
            th = 4.0 * math.atan(bu); c = b - a; L = np.linalg.norm(c); nl = np.array([-c[1], c[0]]) / L
            ctr = (a + b) / 2 + nl * (L / 2) / math.tan(th / 2); r = np.linalg.norm(a - ctr)
            a0 = math.atan2(a[1] - ctr[1], a[0] - ctr[0]); ap = math.atan2(p[1] - ctr[1], p[0] - ctr[0])
            s = (ap - a0) % (2 * math.pi) if th > 0 else (a0 - ap) % (2 * math.pi)
            if s <= abs(th):
                q = ctr + r * np.array([math.cos(ap), math.sin(ap)])
            else:
                q = a if np.linalg.norm(p - a) <= np.linalg.norm(p - b) else b
        dq = float(np.linalg.norm(p - q))
        if dq < best[1] - 1e-9:
            vi = i if np.linalg.norm(q - a) < 1e-3 else ((i + 1) % n if np.linalg.norm(q - b) < 1e-3 else None)
            best = (q, dq, vi)
    return best

def bulge_ring(VB, step_deg=ARC_STEP_DEG):
    VB = np.asarray(VB, float); out = []; vidx = []
    n = len(VB)
    for i in range(n):
        p, q, b = VB[i, :2], VB[(i + 1) % n, :2], VB[i, 2]
        vidx.append(len(out)); out.append(p)
        if abs(b) < 1e-9:
            continue
        th = 4.0 * math.atan(b); c = q - p; L = np.linalg.norm(c)
        nl = np.array([-c[1], c[0]]) / L
        ctr = (p + q) / 2 + nl * (L / 2) / math.tan(th / 2)
        r = np.linalg.norm(p - ctr); a0 = math.atan2(p[1] - ctr[1], p[0] - ctr[0])
        k = max(2, int(math.ceil(abs(math.degrees(th)) / step_deg)))
        for j in range(1, k):
            a = a0 + th * j / k
            out.append(ctr + r * np.array([math.cos(a), math.sin(a)]))
    return np.array(out), vidx

RING_BLK, RING_VIDX = bulge_ring(PLAN['outline']['vertices_bulge_mm_blockframe'])
TOWER_SIDE = sg.LineString(blk2rh(RING_BLK[RING_VIDX[1]:RING_VIDX[3] + 1]))
OUTLINE = orient(sg.Polygon(blk2rh(RING_BLK)).buffer(0), 1.0)
OC = blk2rh([[0.0, 0.0]])[0]
CANOPY_SOLID = OUTLINE
OCULUS_HOLE = sg.Point(OC).buffer(OCULUS_VOID_D / 2, quad_segs=36)
CANOPY = orient(CANOPY_SOLID.difference(OCULUS_HOLE), 1.0)
assert CANOPY.geom_type == 'Polygon' and len(CANOPY.interiors) == 1
X_EAST = CANOPY_SOLID.bounds[2]

def circle(r):
    return sg.Point(OC).buffer(r, quad_segs=36)

TOWER_STRIP = CANOPY.intersection(TOWER_FP.buffer(0.60)).intersection(EXIST_FP.buffer(0.60)).difference(EXIST_FP)
EXIST = CANOPY.intersection(EXIST_FP.buffer(0.0005, join_style=2))
if TOWER_STRIP_PART == 'existing':
    EXIST = so.unary_union([EXIST, TOWER_STRIP])
EXT = CANOPY.difference(EXIST)
_sl = [g for g in getattr(EXT, 'geoms', [EXT]) if g.geom_type == 'Polygon' and g.area < 0.05]
if _sl:
    EXIST = so.unary_union([EXIST] + _sl); EXT = CANOPY.difference(EXIST)
EXIST = EXIST.buffer(0); EXT = EXT.buffer(0)

def polys(g):
    if g is None or g.is_empty: return []
    if g.geom_type == 'Polygon': return [g]
    return [x for x in getattr(g, 'geoms', []) if x.geom_type == 'Polygon' and x.area > 1e-9]

def lines(g):
    if g is None or g.is_empty: return []
    if g.geom_type in ('LineString', 'LinearRing'): return [sg.LineString(g.coords)]
    out = []
    for x in getattr(g, 'geoms', []): out += lines(x)
    return out

def strips(ls, w=JOINT_W):
    return so.unary_union([l.buffer(w / 2, cap_style=2, join_style=2) for l in ls if l.length > 1e-4])

def ext_seg(a, b, e=0.012):
    d = (b - a) / np.linalg.norm(b - a)
    return sg.LineString([a - d * e, b + d * e])

FIELD_OUTER = orient(CANOPY_SOLID.buffer(-TOP_BAND_W, quad_segs=36), 1.0)
assert FIELD_OUTER.geom_type == 'Polygon'
FIELD = FIELD_OUTER.difference(circle(OCULUS_VOID_D / 2 + OCULUS_BAND_W))
BAND = CANOPY.difference(FIELD)
TOP_SEGS = [j2rh(s) for s in PLAN['top_panel_joints']['segments_R3m']]
TOP_JOINT_LINES = lines(so.unary_union([ext_seg(s[0], s[1]) for s in TOP_SEGS]).intersection(FIELD))
BAND_LINES = [sg.LineString(FIELD_OUTER.exterior.coords)]
if OCULUS_BAND_W > 1e-6:
    BAND_LINES.append(sg.LineString(circle(OCULUS_VOID_D / 2 + OCULUS_BAND_W).exterior.coords))

def mitre_lines(poly, w):
    c = np.asarray(orient(poly, 1.0).exterior.coords)[:-1]; n = len(c); out = []
    inner = orient(poly.buffer(-w, join_style=2), 1.0)
    for i in range(n):
        a, p, b = c[i - 1], c[i], c[(i + 1) % n]
        u, v = (p - a) / np.linalg.norm(p - a), (b - p) / np.linalg.norm(b - p)
        turn = math.degrees(math.atan2(u[0] * v[1] - u[1] * v[0], u @ v))
        if turn < 15.0:
            continue
        q = np.asarray(inner.exterior.coords)[:-1]
        k = np.argmin(np.linalg.norm(q - p, axis=1))
        if np.linalg.norm(q[k] - p) < 3 * w / max(math.sin(math.radians((180 - turn) / 2)), 0.2):
            out.append(sg.LineString([p, q[k]]))
    return out

BAND_MITRES = mitre_lines(CANOPY_SOLID, TOP_BAND_W)
TOP_JOINTS = strips(TOP_JOINT_LINES + BAND_LINES + BAND_MITRES).intersection(CANOPY)
TOP_FIELD = FIELD.difference(TOP_JOINTS)
TOP_BAND = BAND.difference(TOP_JOINTS)

R_VOID = OCULUS_VOID_D / 2
OUTER_LINE = sg.LineString(CANOPY_SOLID.exterior.coords)

def d_outer(P):
    P = np.atleast_2d(P)
    return shapely.distance(OUTER_LINE, shapely.points(P[:, 0], P[:, 1]))

STAR = None; STAR_T = None; STAR_ANG = None
if OCULUS_RIM == 'chamfer':
    STAR_ANG = np.linspace(0, 2 * math.pi, 144, endpoint=False)
    STAR_T = np.empty(len(STAR_ANG))
    for i, th in enumerate(STAR_ANG):
        u = np.array([math.cos(th), math.sin(th)])
        f = lambda t: (t - R_VOID) - d_outer(OC + t * u)[0]
        lo, hi = R_VOID, R_VOID + CHAMFER_W
        if f(hi) <= 0:
            STAR_T[i] = hi; continue
        for _ in range(40):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
        STAR_T[i] = (lo + hi) / 2
    STAR = sg.Polygon(OC + STAR_T[:, None] * np.c_[np.cos(STAR_ANG), np.sin(STAR_ANG)])
    SOFFIT = CANOPY_SOLID.buffer(-CHAMFER_W, quad_segs=36).difference(STAR)
    CHAMFER_INNER = orient(so.unary_union([CANOPY_SOLID.buffer(-CHAMFER_W, quad_segs=36), STAR]), 1.0)
    CEN_CUT = circle(R_VOID + SOFFIT_BAND_W)
else:
    SOFFIT = CANOPY_SOLID.buffer(-CHAMFER_W, quad_segs=36).difference(OCULUS_HOLE)
    CHAMFER_INNER = orient(CANOPY_SOLID.buffer(-CHAMFER_W, quad_segs=36), 1.0)
    CEN_CUT = OCULUS_HOLE
SOFFIT = orient(SOFFIT, 1.0)
assert SOFFIT.geom_type == 'Polygon' and CHAMFER_INNER.geom_type == 'Polygon', 'chamfer offset split the canopy'
CEN = CANOPY_SOLID.buffer(-SOFFIT_BAND_W, quad_segs=36)
SOFFIT_INNER = CEN.difference(CEN_CUT)
CEIL_SEGS = [j2rh(s) for s in PLAN['ceiling_panel_joints']['segments_R3m']]
SOFFIT_JOINT_LINES = lines(so.unary_union([ext_seg(s[0], s[1]) for s in CEIL_SEGS]).intersection(SOFFIT_INNER))
SOFFIT_JOINT_LINES += lines(sg.LineString(CEN.exterior.coords).difference(CEN_CUT.buffer(0.001)))
if OCULUS_RIM == 'chamfer':
    SOFFIT_JOINT_LINES += lines(sg.LineString(CEN_CUT.exterior.coords).intersection(CEN))
SOFFIT_JOINTS = strips(SOFFIT_JOINT_LINES).intersection(SOFFIT)
SOFFIT_PANELS = SOFFIT.difference(SOFFIT_JOINTS)

_ring_c = R_VOID + (SOFFIT_BAND_W if OCULUS_RIM == 'chamfer' else 0.060)
_fr_in = CEN.buffer(-PRIMARY_W / 2, join_style=2).difference(circle(_ring_c + PRIMARY_W / 2))
_d_ok = (PRIMARY_TOP_BELOW + PRIMARY_H - FASCIA_H) / CHAMFER_DROP * CHAMFER_W + 0.005
FRAME_ZONE = CANOPY_SOLID.buffer(-_d_ok).difference(circle(R_VOID + (_d_ok if OCULUS_RIM == 'chamfer' else 0.003)))
FRAME = so.unary_union([
    CEN.buffer(PRIMARY_W / 2, join_style=2).difference(CEN.buffer(-PRIMARY_W / 2, join_style=2)),
    circle(_ring_c + PRIMARY_W / 2).difference(circle(_ring_c - PRIMARY_W / 2)),
    strips(lines(so.unary_union([sg.LineString(s) for s in TOP_SEGS]).intersection(_fr_in)), PRIMARY_W),
]).intersection(FRAME_ZONE).buffer(0)

def top_z(x):
    return TOP_AT_HIGH_EDGE - SLOPE * (X_EAST - np.asarray(x, float))

def dist_edge(P):
    P = np.atleast_2d(P); d = d_outer(P)
    if OCULUS_RIM == 'chamfer':
        d = np.minimum(d, np.abs(np.linalg.norm(P - OC, axis=1) - R_VOID))
    return d

def underside_z(P):
    P = np.atleast_2d(P); d = dist_edge(P)
    return top_z(P[:, 0]) - FASCIA_H - CHAMFER_DROP * np.minimum(d, CHAMFER_W) / CHAMFER_W

def densify_ring(c, maxlen=DENSIFY):
    c = np.asarray(c, float)
    if np.linalg.norm(c[0] - c[-1]) < 1e-9: c = c[:-1]
    out = []; n = len(c)
    for i in range(n):
        a, b = c[i], c[(i + 1) % n]
        L = np.linalg.norm(b - a); k = max(1, int(math.ceil(L / maxlen)))
        for j in range(k): out.append(a + (b - a) * j / k)
    return np.array(out)

def rings(poly):
    p = orient(poly, 1.0)
    return [np.asarray(p.exterior.coords)[:-1]] + [np.asarray(h.coords)[:-1] for h in p.interiors]

def earcut_poly(poly):
    rs = rings(poly)
    verts = np.vstack(rs); ends = np.cumsum([len(r) for r in rs]).astype(np.uint32)
    return verts, earcut.triangulate_float64(verts, ends).reshape(-1, 3)

class Soup:
    def __init__(s): s.V, s.N = [], []

    def add(s, tris, normals):
        tris = np.asarray(tris, float).reshape(-1, 3, 3); normals = np.asarray(normals, float).reshape(-1, 3, 3)
        if len(tris): s.V.append(tris); s.N.append(normals)

    def arrays(s):
        if not s.V: return np.zeros((0, 3, 3)), np.zeros((0, 3, 3))
        return np.concatenate(s.V), np.concatenate(s.N)

def face_normals(T):
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]); return n, np.linalg.norm(n, axis=1)

def orient_tris(T, want):
    n, L = face_normals(T); keep = L > 1e-12
    T = T[keep].copy(); n = n[keep]
    bad = ~want(T.mean(1), n) if callable(want) else (n @ np.asarray(want, float)) < 0
    T[bad] = T[bad][:, ::-1]
    return T

def auto_smooth(T, angle_deg=35.0):
    fn, L = face_normals(T); fu = fn / np.maximum(L[:, None], 1e-15)
    corners = T.reshape(-1, 3)
    key = np.round(corners * 1e5).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True); inv = inv.ravel()
    face_of = np.repeat(np.arange(len(T)), 3)
    order = np.argsort(inv, kind='stable'); inv_s = inv[order]
    cut = np.flatnonzero(np.diff(inv_s)) + 1
    N = np.zeros_like(corners); c = math.cos(math.radians(angle_deg))
    for g in np.split(order, cut):
        fs = face_of[g]; ns = fu[fs]
        acc = (ns @ ns.T > c).astype(float) @ fn[fs]
        N[g] = acc / np.maximum(np.linalg.norm(acc, axis=1, keepdims=True), 1e-15)
    return N.reshape(-1, 3, 3)

def plane_normal(sign=1.0):
    n = np.array([-SLOPE, 0.0, 1.0]); n /= np.linalg.norm(n); return n * sign

def surface(poly_list, zfun, sign=1.0, normal=None):
    out = []
    for p in poly_list:
        if p.area < 1e-8: continue
        v, t = earcut_poly(p)
        if not len(t): continue
        out.append(np.c_[v, zfun(v[:, 0])][t])
    if not out: return np.zeros((0, 3, 3)), np.zeros((0, 3, 3))
    T = orient_tris(np.concatenate(out), [0, 0, sign])
    n = plane_normal(sign) if normal is None else np.asarray(normal, float)
    return T, np.broadcast_to(n, T.shape).copy()

def walls(poly_list, z0fun, z1fun):
    out = []
    for p in poly_list:
        p = orient(p, 1.0)
        for ring in [p.exterior] + list(p.interiors):
            c = np.asarray(ring.coords); a, b = c[:-1], c[1:]
            d = b - a; L = np.linalg.norm(d, axis=1); k = L > 1e-7; a, b, d, L = a[k], b[k], d[k], L[k]
            nrm = np.c_[d[:, 1], -d[:, 0]] / L[:, None]
            q = np.stack([np.c_[a, z0fun(a[:, 0])], np.c_[b, z0fun(b[:, 0])], np.c_[b, z1fun(b[:, 0])], np.c_[a, z1fun(a[:, 0])]], 1)
            n3 = np.c_[nrm, np.zeros(len(nrm))]
            out += [(q[:, [0, 1, 2]], n3), (q[:, [0, 2, 3]], n3)]
    if not out: return np.zeros((0, 3, 3)), np.zeros((0, 3, 3))
    T = np.concatenate([o[0] for o in out]); Nn = np.concatenate([o[1] for o in out])
    fn, L = face_normals(T); k = L > 1e-12; T, Nn, fn = T[k].copy(), Nn[k], fn[k]
    bad = (fn * Nn).sum(1) < 0; T[bad] = T[bad][:, ::-1]
    return T, np.repeat(Nn[:, None, :], 3, 1)

def prism(poly_list, z0fun, z1fun):
    T1, N1 = surface(poly_list, z1fun, +1); T2, N2 = surface(poly_list, z0fun, -1); T3, N3 = walls(poly_list, z0fun, z1fun)
    return np.concatenate([T1, T2, T3]), np.concatenate([N1, N2, N3])

def loft(P, Q):
    q_ls = sg.LineString(np.vstack([Q[:, :2], Q[:1, :2]]))
    s0 = q_ls.project(sg.Point(P[0, :2]))
    sq = np.r_[0, np.cumsum(np.linalg.norm(np.diff(np.vstack([Q[:, :2], Q[:1, :2]]), axis=0), axis=1))][:-1]
    j0 = int(np.searchsorted(sq, s0, side='right') - 1)
    Qr = np.vstack([Q[j0 + 1:], Q[:j0 + 1]])
    start = np.asarray(q_ls.interpolate(s0).coords)[0]
    _q1 = Q[(j0 + 1) % len(Q)]; _sl = np.linalg.norm(_q1[:2] - Q[j0, :2])
    _t = 0.0 if _sl < 1e-12 else min(1.0, max(0.0, np.linalg.norm(start - Q[j0, :2]) / _sl))
    start = np.r_[start, Q[j0, 2] + (_q1[2] - Q[j0, 2]) * _t]
    Qr = np.vstack([start, Qr])
    sq = np.r_[0, np.cumsum(np.linalg.norm(np.diff(Qr[:, :2], axis=0), axis=1))]
    Lq = sq[-1] + np.linalg.norm(Qr[0, :2] - Qr[-1, :2])
    ls = sg.LineString(np.vstack([Qr[:, :2], Qr[:1, :2]]))
    tp = np.array([ls.project(sg.Point(p)) for p in P[:, :2]]); tp[0] = 0.0
    for i in range(1, len(tp)):
        if tp[i] < tp[i - 1] - Lq / 2: tp[i] += Lq
        tp[i] = max(tp[i], tp[i - 1])
    tp[0] = 0.0; tp = np.minimum(tp, Lq)
    n, m = len(P), len(Qr)
    tpe = np.r_[tp, Lq]; sqe = np.r_[sq, Lq]
    Pe = np.vstack([P, P[:1]]); Qe = np.vstack([Qr, Qr[:1]])
    tris = []; i = j = 0
    while i < n or j < m:
        if j >= m or (i < n and tpe[i + 1] <= sqe[j + 1]):
            tris.append((Pe[i], Pe[i + 1], Qe[j])); i += 1
        else:
            tris.append((Pe[i], Qe[j + 1], Qe[j])); j += 1
    return np.array(tris)

def uv_of(Tc, Nc):
    P = Tc.reshape(-1, 3); N = Nc.reshape(-1, 3)
    ax = np.abs(N).argmax(1)
    return np.where(ax[:, None] == 2, P[:, [0, 1]], np.where(ax[:, None] == 0, P[:, [1, 2]], P[:, [0, 2]]))

def split_polys(g):
    return {'existing': polys(g.intersection(EXIST)), 'extension': polys(g.intersection(EXT))}

EXIST_TEST = EXIST.buffer(0.004)

def split_tris(T, N):
    c = T.mean(1)[:, :2]
    ins = shapely.contains_xy(EXIST_TEST, c[:, 0], c[:, 1])
    return {'existing': (T[ins], N[ins]), 'extension': (T[~ins], N[~ins])}

PARTS = collections.OrderedDict()
t0 = time.time()
for key, geom, zoff in (('top', TOP_FIELD, 0.0), ('band', TOP_BAND, 0.0), ('topjoint', TOP_JOINTS, -JOINT_RECESS)):
    PARTS[key] = {reg: surface(pl, lambda x, o=zoff: top_z(x) + o, +1) for reg, pl in split_polys(geom).items()}
ring_B = [densify_ring(r) for r in rings(CANOPY)]
assert len(ring_B) == 2
fT = []
for ri, r in enumerate(ring_B):
    h = FASCIA_H if (ri == 0 or OCULUS_RIM == 'chamfer') else DEPTH
    a, b = r, np.roll(r, -1, 0)
    q = np.stack([np.c_[a, top_z(a[:, 0])], np.c_[b, top_z(b[:, 0])], np.c_[b, top_z(b[:, 0]) - h], np.c_[a, top_z(a[:, 0]) - h]], 1)
    fT += [q[:, [0, 1, 2]], q[:, [0, 2, 3]]]
fT = np.concatenate(fT)
_hn = lambda n: n[:, :2] / np.maximum(np.hypot(n[:, 0], n[:, 1]), 1e-12)[:, None]
fT = orient_tris(fT, lambda c, n: ~shapely.contains_xy(CANOPY, c[:, 0] + _hn(n)[:, 0] * 0.005, c[:, 1] + _hn(n)[:, 1] * 0.005))
fN = auto_smooth(fT, 35)
fN[:, :, 2] = 0; fN /= np.maximum(np.linalg.norm(fN, axis=2, keepdims=True), 1e-12)
PARTS['fascia'] = split_tris(fT, fN)
cT = []
rq = densify_ring(np.asarray(CHAMFER_INNER.exterior.coords)[:-1])
cT.append(loft(np.c_[ring_B[0], top_z(ring_B[0][:, 0]) - FASCIA_H], np.c_[rq, underside_z(rq)]))
if OCULUS_RIM == 'chamfer':
    sq = OC + STAR_T[:, None] * np.c_[np.cos(STAR_ANG), np.sin(STAR_ANG)]
    zq = top_z(sq[:, 0]) - FASCIA_H - CHAMFER_DROP * np.minimum(STAR_T - R_VOID, CHAMFER_W) / CHAMFER_W
    Q3 = np.c_[sq, zq]
    if sg.LinearRing(sq).is_ccw == sg.LinearRing(ring_B[1]).is_ccw:
        pass
    else:
        Q3 = Q3[::-1]
    cT.append(loft(np.c_[ring_B[1], top_z(ring_B[1][:, 0]) - FASCIA_H], Q3))
cT = orient_tris(np.concatenate(cT), [0, 0, -1])
cN = auto_smooth(cT, 35)
PARTS['chamfer'] = split_tris(cT, cN)
PARTS['soffit'] = {r: surface(pl, lambda x: top_z(x) - DEPTH, -1) for r, pl in split_polys(SOFFIT_PANELS).items()}
PARTS['soffitjoint'] = {r: surface(pl, lambda x: top_z(x) - DEPTH + JOINT_RECESS, -1) for r, pl in split_polys(SOFFIT_JOINTS).items()}
PARTS['frame'] = {r: prism(pl, lambda x: top_z(x) - PRIMARY_TOP_BELOW - PRIMARY_H, lambda x: top_z(x) - PRIMARY_TOP_BELOW)
                  for r, pl in split_polys(FRAME).items()}
print('[build step] surfaces built (%.1fs)' % (time.time() - t0))

def box_tris(x0, x1, y0, y1, z0, z1):
    return prism([sg.box(x0, y0, x1, y1)], lambda x: np.full(len(x), z0), lambda x: np.full(len(x), z1))

def cyl(x, y, r, z0, z1, seg, top_cap=True, bot_cap=False):
    ang = np.linspace(0, 2 * math.pi, seg, endpoint=False)
    ring = np.c_[x + r * np.cos(ang), y + r * np.sin(ang)]
    a = np.c_[ring, np.full(seg, z0)]; b = np.c_[ring, np.full(seg, z1)]
    a2, b2 = np.roll(a, -1, 0), np.roll(b, -1, 0)
    n = np.c_[np.cos(ang), np.sin(ang), np.zeros(seg)]; n2 = np.roll(n, -1, 0)
    T = [np.stack([a, a2, b2], 1), np.stack([a, b2, b], 1)]; N = [np.stack([n, n2, n2], 1), np.stack([n, n2, n], 1)]
    if top_cap:
        T.append(orient_tris(np.stack([np.tile([x, y, z1], (seg, 1)), b, b2], 1), [0, 0, 1])); N.append(np.tile([0, 0, 1.0], (seg, 3, 1)))
    if bot_cap:
        T.append(orient_tris(np.stack([np.tile([x, y, z0], (seg, 1)), a, a2], 1), [0, 0, -1])); N.append(np.tile([0, 0, -1.0], (seg, 3, 1)))
    return np.concatenate(T), np.concatenate(N)

def stiffener(x, y, th, r1, zb):
    prof = sg.Polygon([(STIFF_R0, -STIFF_T / 2), (r1, -STIFF_T / 2), (r1, STIFF_T / 2), (STIFF_R0, STIFF_T / 2)])
    zt = lambda xx: zb + STIFF_H0 + (STIFF_H1 - STIFF_H0) * (np.asarray(xx) - STIFF_R0) / (STIFF_R_DIAG - STIFF_R0)
    zbf = lambda xx: np.full(len(np.atleast_1d(xx)), zb)
    T1, N1 = surface([prof], zt, +1); T2, N2 = surface([prof], zbf, -1); T3, N3 = walls([prof], zbf, zt)
    fn, L = face_normals(T1); N1 = np.repeat((fn / L[:, None])[:, None, :], 3, 1)
    T = np.concatenate([T1, T2, T3]).copy(); Nn = np.concatenate([N1, N2, N3]).copy()
    c, s = math.cos(th), math.sin(th); R = np.array([[c, -s], [s, c]])
    T[..., :2] = T[..., :2] @ R.T + [x, y]; Nn[..., :2] = Nn[..., :2] @ R.T
    return T, Nn

def hex_nut(x, y, z0):
    rc = NUT_AF / 2 / math.cos(math.pi / 6)
    P = [(x + rc * math.cos(math.pi / 6 + k * math.pi / 3), y + rc * math.sin(math.pi / 6 + k * math.pi / 3)) for k in range(6)]
    return prism([sg.Polygon(P)], lambda xx: np.full(len(xx), z0), lambda xx: np.full(len(xx), z0 + NUT_H))

SETOUT_IDS = ('C01', 'C02', 'C03', 'C04', 'C05', 'C06', 'C07', 'C08')

def column_layout():
    dwg = collections.OrderedDict()
    for c in PLAN['columns']:
        dwg[c['id']] = dict(id=c['id'], xy=j2rh([c['xy_plan_m']])[0], json_R3m=c['xy_plan_m'], blk=np.asarray(c['dwg_block_xy_mm'], float))
    out = []
    if COLUMNS in ('dwg_cen', 'dwg_asdrawn'):
        for cid, c in dwg.items():
            q, dq, vi = nearest_on_bulge_ring(DWG_CEN_BULGE_MM, c['blk'])
            d = dict(id=cid, xy=c['xy'], json_R3m=c['json_R3m'], blk_asdrawn=c['blk'], blk_model=c['blk'], moved_mm=0.0,
                     dist_asdrawn_to_dwg_cen_mm=round(dq, 1), status='new (DWG); all 6 legacy CAD columns removed')
            if cid in SETOUT_IDS:
                d.update(rule='as drawn (DWG set-out block 图纸, centre on its CEN 495 polyline)',
                         source='', confidence='high (set-out block, on the CEN 495 beam line)')
            elif COLUMNS == 'dwg_cen':
                d.update(xy=blk2rh([q])[0], blk_model=q, moved_mm=round(dq, 1), cen_vertex=vi,
                         rule='G1 projection: DWG r50 marker centre -> nearest point of the DWG CEN 495 polyline (set-out block layer CEN) '
                              '= CEN vertex %s (perimeter-beam corner), moved %.1f mm' % (vi, dq),
                         source='',
                         confidence='medium (count + beam line from the DWG; position projected, contractor to confirm)')
            else:
                d.update(rule='as drawn (0.150 OUTSIDE the canopy edge, free post)',
                         source='',
                         confidence='low (free post outside the edge; no connecting member in the DWG; S2 E column 542 inside)')
            out.append(d)
    else:
        for k, o in enumerate(OLD_COLS):
            b = rh2blk([o])[0]; q, dq, vi = nearest_on_bulge_ring(DWG_CEN_BULGE_MM, b)
            out.append(dict(id='A%02d' % (k + 1), xy=np.asarray(o, float), json_R3m=None, blk_asdrawn=None, blk_model=b, moved_mm=0.0,
                            dist_asdrawn_to_dwg_cen_mm=round(dq, 1), status='as built (existing legacy CAD CHS150, photographed)',
                            rule='as built: legacy CAD 铁架::150X5圆管 axis', source='',
                            confidence='high (as built; photo check <=0.063 m, validation photo)'))
        for k, q3 in enumerate(R7_COLUMNS_R3M):
            p = r32rh([q3])[0]
            dd = {cid: float(np.linalg.norm(p - dwg[cid]['xy'])) for cid in SETOUT_IDS}
            cid = min(dd, key=dd.get)
            if dd[cid] <= R7_SNAP_TOL:
                xy = dwg[cid]['xy']; b = dwg[cid]['blk']; mv = dd[cid] * 1000.0
                rule = 'R7 circle plan metres %s snapped %.1f mm to DWG set-out column %s (earlier-model rule, tol %.2f m)' % (list(q3), mv, cid, R7_SNAP_TOL)
            else:
                b0 = rh2blk([p])[0]; b, dq, vi = nearest_on_bulge_ring(DWG_CEN_BULGE_MM, b0); xy = blk2rh([b])[0]; mv = dq
                rule = 'R7 circle plan metres %s (no DWG column within %.2f m) moved %.1f mm to the nearest point of the DWG CEN 495 line' % (list(q3), R7_SNAP_TOL, mv)
            out.append(dict(id='R%d' % (k + 1), xy=np.asarray(xy, float), json_R3m=list(q3), blk_asdrawn=None, blk_model=np.asarray(b, float),
                            moved_mm=round(mv, 1), dist_asdrawn_to_dwg_cen_mm=None, status='new (R7 extension column, earlier model)',
                            rule=rule, source='',
                            confidence='medium (layout superseded by the DWG proposal; kept as the as-built alternative)'))
    return out

COLS = column_layout()
col_parts = {k: {'existing': Soup(), 'extension': Soup()} for k in ('chs', 'plate', 'plinth')}
COL_INFO = []
_ang48 = np.linspace(0, 2 * math.pi, 48, endpoint=False)
for cdef in COLS:
    x, y = cdef['xy']
    P = sg.Point(x, y)
    reg = 'existing' if EXIST.buffer(0.01).contains(P) else ('extension' if EXT.buffer(0.01).contains(P) else
                                                             ('existing' if EXIST.distance(P) < EXT.distance(P) else 'extension'))
    disk = sg.Point(x, y).buffer(CHS_D / 2, quad_segs=24)
    inside = CANOPY.buffer(-0.001).contains(disk)
    z_plate = PLINTH_TOP + BP_T
    z_cap = float(top_z(x) - CAP_BELOW_TOP)
    T, N = cyl(x, y, CHS_D / 2, z_plate, z_cap, CHS_SEG, top_cap=True); col_parts['chs'][reg].add(T, N)
    T, N = box_tris(x - BP / 2, x + BP / 2, y - BP / 2, y + BP / 2, PLINTH_TOP, z_plate); col_parts['plate'][reg].add(T, N)
    for k in range(8):
        th = k * math.pi / 4
        T, N = stiffener(x, y, th, STIFF_R_DIAG if k % 2 else STIFF_R_ORTH, z_plate); col_parts['plate'][reg].add(T, N)
    for dx_ in (-BOLT_PITCH, 0.0, BOLT_PITCH):
        for dy_ in (-BOLT_PITCH, 0.0, BOLT_PITCH):
            if dx_ == 0.0 and dy_ == 0.0: continue
            bx, by = x + dx_, y + dy_
            T, N = box_tris(bx - WASHER / 2, bx + WASHER / 2, by - WASHER / 2, by + WASHER / 2, z_plate, z_plate + WASHER_T); col_parts['plate'][reg].add(T, N)
            T, N = hex_nut(bx, by, z_plate + WASHER_T); col_parts['plate'][reg].add(T, N)
            T, N = cyl(bx, by, BOLT_D / 2, z_plate + WASHER_T + NUT_H, z_plate + WASHER_T + NUT_H + BOLT_STUB, 12, top_cap=True); col_parts['plate'][reg].add(T, N)
    if PLINTH_TOP > 1e-3:
        T, N = box_tris(x - PLINTH / 2, x + PLINTH / 2, y - PLINTH / 2, y + PLINTH / 2, PLINTH_TOP - PLINTH_H, PLINTH_TOP); col_parts['plinth'][reg].add(T, N)
    d_edge = float(CANOPY_SOLID.exterior.distance(P)) * (1 if CANOPY_SOLID.contains(P) else -1)
    old_d = [float(np.linalg.norm(np.asarray(o) - (x, y))) for o in OLD_COLS]
    rp = np.c_[x + CHS_D / 2 * np.cos(_ang48), y + CHS_D / 2 * np.sin(_ang48)]
    ring_in = bool(shapely.contains_xy(CANOPY, rp[:, 0], rp[:, 1]).all())
    if ring_in:
        pen = float(z_cap - underside_z(rp).max()); cover = float(top_z(rp[:, 0]).min() - z_cap)
        flat = bool(SOFFIT.buffer(0.002).contains(disk))
    else:
        pen = cover = None; flat = False
    info = collections.OrderedDict(
        id=cdef['id'], layout=COLUMNS, region=reg, xy_plan_m=[round(float(v), 4) for v in rh2r3([[x, y]])[0]],
        R3m_canopy_plan_json_frame=[round(float(v), 4) for v in rh2j([[x, y]])[0]], R3m_source=cdef['json_R3m'],
        dwg_block_xy_mm=[round(float(v), 3) for v in cdef['blk_model']] if cdef['blk_model'] is not None else None,
        dwg_block_xy_mm_asdrawn=[round(float(v), 3) for v in cdef['blk_asdrawn']] if cdef['blk_asdrawn'] is not None else None,
        moved_from_source_mm=cdef['moved_mm'], dist_asdrawn_to_dwg_cen_mm=cdef['dist_asdrawn_to_dwg_cen_mm'], rule=cdef['rule'],
        rh=[round(float(x), 4), round(float(y), 4)], gltf_xz=[round(float(v), 4) for v in world([[x, y, 0]])[0][[0, 2]]],
        base_plate_bottom_y=round(PLINTH_TOP, 4), tube_bottom_y=round(z_plate, 4), cap_y=round(z_cap, 4), tube_length=round(z_cap - z_plate, 4),
        soffit_y_at_column=round(float(top_z(x) - DEPTH), 4), top_y_at_column=round(float(top_z(x)), 4),
        dist_inside_edge_m=round(d_edge, 4), under_canopy=bool(inside),
        tube_in_flat_soffit=flat, tube_penetration_into_canopy_m=round(pen, 4) if pen is not None else None,
        cap_cover_below_top_m=round(cover, 4) if cover is not None else None,
        meets_soffit=bool(ring_in and pen is not None and pen > 0.0 and cover > 0.0),
        nearest_old_column_m=round(min(old_d), 3) if old_d else None,
        status=cdef['status'], source='', confidence=cdef['confidence'])
    if 'cen_vertex' in cdef:
        info['dwg_cen_vertex'] = cdef['cen_vertex']
    COL_INFO.append(info)
if COLUMNS == 'dwg_cen':
    _bad = [c['id'] for c in COL_INFO if not (c['under_canopy'] and c['meets_soffit'] and c['tube_in_flat_soffit']
                                               and c['dist_inside_edge_m'] >= SOFFIT_BAND_W - 0.002)]
    assert not _bad, 'dwg_cen columns outside / not meeting the soffit: %s' % [(c['id'], c['under_canopy'], c['meets_soffit'], c['tube_in_flat_soffit'],
                                                                              c['dist_inside_edge_m']) for c in COL_INFO if c['id'] in _bad]
for k in col_parts:
    PARTS['col_' + k] = {r: s.arrays() for r, s in col_parts[k].items()}
N_COL_NEW = sum(1 for c in COL_INFO if c['status'].startswith('new'))
N_COL_KEPT = len(COL_INFO) - N_COL_NEW
N_COL_REMOVED = 0 if COLUMNS == 'asbuilt6' else len(OLD_COLS)
COL_LAYOUT_TXT = {
    'dwg_cen': ('%d CHS150x5 (COLUMNS dwg_cen, default): C01-C08 = DWG set-out block 图纸 on its CEN 495 line; C09-C11 = the DWG loose '
                'columns projected onto the DWG CEN 495 line (nearest point = beam corners, moved 661 / 661 / 785 mm; G1 rule)' % len(COL_INFO),
                'high (C01-C08) / medium (C09-C11 projected from 150 outside the edge; contractor to confirm)'),
    'dwg_asdrawn': ('%d CHS150x5 (COLUMNS dwg_asdrawn): the  DWG as drawn; C09-C11 stand 0.150 OUTSIDE the canopy edge as free posts' % len(COL_INFO),
                    'high (C01-C08) / low (C09-C11 free posts outside the edge)'),
    'asbuilt6': ('%d CHS150x5 (COLUMNS asbuilt6): the 6 photographed as-built legacy CAD columns + 7 R7 extension columns (earlier model: '
                 '5 snapped to DWG C03/C04/C06/C07/C08, 2 moved to the CEN 495 line)' % len(COL_INFO),
                 'high (6 as-built) / medium (7 R7-based)'),
}[COLUMNS]
print('[build step] %d columns (%s: %d new, %d as-built kept, %d legacy CAD removed)' % (len(COLS), COLUMNS, N_COL_NEW, N_COL_KEPT, N_COL_REMOVED))

_FS_ORDERS_TOP = ('')
_FS_ORDERS_CLAD = ('')
FINISH_SRC = {
    'AL_MOUSEGREY': ('', ML._M['AL_MOUSEGREY']['confidence']),
    'AL_T02': ('', ML._M['AL_T02']['confidence']),
    'AL_RAL7038': ('',
                   'low (not the ordered finish)'),
}
_FS_COL = {'AL_T02': ('',
                      'low-medium (inferred from the 6 existing columns in the photos; no spec for the new columns; hex = T02 proxy)'),
           'STEEL_HDG': ('', 'low')}

def _fin(mat, kind='clad'):
    if kind == 'col':
        s, c = _FS_COL[mat]
    elif mat in FINISH_SRC:
        s, c = FINISH_SRC[mat]
        if mat == 'AL_T02' and kind == 'top':
            s, c = 'Q1 alternative (MOCKUP_CANOPY_TOP=AL_T02); not the ordered top finish (order =  Mouse Grey)', 'low (not the ordered finish)'
    else:
        return {}
    return dict(finish_source='', finish_confidence=c, finish_scheme=SCHEME)

PART_DEF = {
    'top': ('Top 25 mm honeycomb panels (1000 strips)', TOP_FINISH, '', 'high (layout) / see finish_confidence (colour)',
            dict(role='top', param='CANOPY_TOP_MATERIAL', options=list(ML.CANOPY_TOP_OPTIONS), **_fin(TOP_FINISH, 'top'))),
    'band': ('Top edge band 150 (3 mm alu) incl. oculus ring', CLAD_FINISH, '', 'high (outer) / medium (oculus)',
             dict(role='band', param='CLAD_FINISH', **_fin(CLAD_FINISH))),
    'topjoint': ('Top joints 20 mm', 'SEALANT_BLACK', '', 'high (layout) / medium (width)',
                 dict(role='joint', finish_source='')),
    'fascia': ('Fascia 100 vertical', CLAD_FINISH, '', 'high', dict(role='fascia', param='CLAD_FINISH', **_fin(CLAD_FINISH))),
    'chamfer': ('Chamfer 420 x 206 to soffit', CLAD_FINISH, '', 'high (free edges) / medium (oculus, tower side)',
                dict(role='fascia', param='CLAD_FINISH', **_fin(CLAD_FINISH))),
    'soffit': ('Soffit 3 mm alu panels', CLAD_FINISH, '', 'high', dict(role='soffit', param='CLAD_FINISH', **_fin(CLAD_FINISH))),
    'soffitjoint': ('Soffit joints 20 mm', 'SEALANT_BLACK', '', 'high (layout) / medium (width)', dict(role='joint')),
    'frame': ('GMS 150x100x6 primaries (concealed)', 'STEEL_HDG', '', 'medium (perimeter) / low (internal)',
              dict(role='frame', concealed=True, finish_source='')),
    'col_chs': ('Columns CHS150x5', COLUMN_FINISH, '', COL_LAYOUT_TXT[1],
                dict(role='column', param='COLUMN_FINISH', **_fin(COLUMN_FINISH, 'col'))),
    'col_plate': ('Base plates 400x400 + 8 stiffeners + 8 bolts', COLUMN_FINISH, '', 'medium',
                  dict(role='baseplate', param='COLUMN_FINISH', **_fin(COLUMN_FINISH, 'col'))),
    'col_plinth': ('RC pads 650x650', 'RC_PLAIN', '', 'low', dict(role='plinth')),
}
glb = GLB()
children = []; stats = collections.OrderedDict(); tri_total = 0
AREA_SRC = {'top': TOP_FIELD, 'band': TOP_BAND, 'topjoint': TOP_JOINTS, 'soffit': SOFFIT_PANELS, 'soffitjoint': SOFFIT_JOINTS}
for key, (layer_en, matname, src, conf, xx) in PART_DEF.items():
    for reg in ('existing', 'extension'):
        T, Nc = PARTS[key].get(reg, (np.zeros((0, 3, 3)), np.zeros((0, 3, 3))))
        if len(T) == 0: continue
        V = world(T.reshape(-1, 3)); Nw = world_n(Nc.reshape(-1, 3))
        Nw /= np.maximum(np.linalg.norm(Nw, axis=1, keepdims=True), 1e-12)
        F = np.arange(len(V)).reshape(-1, 3)
        fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
        bad = (fn * Nw[F[:, 0]]).sum(1) < 0
        if bad.any(): F[bad] = F[bad][:, ::-1]
        name = '%s|%s|%s' % (GROUP, reg, layer_en)
        mi = glb.mesh(name, V, F, Nw, ML.mat(glb, matname), uvs=uv_of(T, Nc))
        ex = ML.node_extras(GROUP, layer_en, matname, src, conf, part=reg, parent_group='VMU01', triangles=int(len(F)), **xx)
        if key in AREA_SRC:
            ex['plan_area_m2'] = round(float(sum(p.area for p in split_polys(AREA_SRC[key])[reg])), 3)
        if key.startswith('col_'):
            ex['columns'] = [c['id'] for c in COL_INFO if c['region'] == reg]
        if reg == 'extension': ex['highlight'] = 'extension'
        children.append(glb.node(name, mesh=mi, extras=ex))
        stats['%s|%s' % (reg, key)] = int(len(F)); tri_total += len(F)

def area_of(g): return round(float(g.area), 3)

meas = collections.OrderedDict()
meas['existing_area_m2'] = area_of(EXIST)
meas['extension_area_m2'] = area_of(EXT)
meas['total_area_net_m2'] = area_of(CANOPY)
meas['total_area_gross_m2'] = area_of(CANOPY_SOLID)
meas['oculus_void_area_m2'] = area_of(OCULUS_HOLE.intersection(CANOPY_SOLID))
meas['json_area_gross_net_m2'] = [PLAN['outline']['area_gross_m2'], PLAN['outline']['area_net_m2']]
meas['legacy_cad_old_footprint_m2'] = area_of(EXIST_FP)
meas['tower_strip_m2'] = area_of(TOWER_STRIP)
meas['tower_strip_part'] = TOWER_STRIP_PART
meas['existing_area_if_strip_is_extension_m2'] = area_of(CANOPY.intersection(EXIST_FP.buffer(0.0005, join_style=2)))
meas['top_field_m2'] = area_of(TOP_FIELD); meas['top_band_m2'] = area_of(TOP_BAND); meas['top_joints_m2'] = area_of(TOP_JOINTS)
meas['soffit_panels_m2'] = area_of(SOFFIT_PANELS); meas['soffit_joints_m2'] = area_of(SOFFIT_JOINTS)
meas['perimeter_outer_m'] = round(CANOPY.exterior.length, 3)
meas['perimeter_oculus_m'] = round(CANOPY.interiors[0].length, 3)
Pb = np.array(CANOPY_SOLID.exterior.coords)
B3 = rh2r3(Pb); BJ = rh2j(Pb)
meas['bbox_R3m'] = [round(float(v), 4) for v in np.r_[B3.min(0), B3.max(0)]]
meas['bbox_R3m_canopy_plan_json_frame'] = [round(float(v), 4) for v in np.r_[BJ.min(0), BJ.max(0)]]
meas['bbox_rh'] = [round(float(v), 4) for v in CANOPY_SOLID.bounds]
g3 = world(np.c_[Pb, top_z(Pb[:, 0])])
meas['bbox_gltf_xz'] = [round(float(g3[:, 0].min()), 4), round(float(g3[:, 2].min()), 4), round(float(g3[:, 0].max()), 4), round(float(g3[:, 2].max()), 4)]
iW, iE, iS, iN = Pb[:, 0].argmin(), Pb[:, 0].argmax(), Pb[:, 1].argmin(), Pb[:, 1].argmax()
lv = collections.OrderedDict()
lv['formula'] = 'y_top = %.3f - %.6f * (x_east - x), x along drawing +x (R3 +X); soffit = top - %.3f; fascia foot = top - %.3f' % (TOP_AT_HIGH_EDGE, SLOPE, DEPTH, FASCIA_H)
lv['formula_R3m_json_frame'] = 'y_top = %.3f - %.6f * (%.4f - X_R3m)' % (TOP_AT_HIGH_EDGE, SLOPE, float(rh2j([[X_EAST, 0]])[0, 0]))
lv['east_high_edge'] = dict(x_R3m=round(float(B3[iE, 0]), 4), top=round(float(top_z(Pb[iE, 0])), 4), fascia_foot=round(float(top_z(Pb[iE, 0]) - FASCIA_H), 4), soffit=round(float(top_z(Pb[iE, 0]) - DEPTH), 4))
lv['west_low_edge'] = dict(x_R3m=round(float(B3[iW, 0]), 4), top=round(float(top_z(Pb[iW, 0])), 4), fascia_foot=round(float(top_z(Pb[iW, 0]) - FASCIA_H), 4),
                           chamfer_foot=round(float(top_z(Pb[iW, 0] + CHAMFER_W) - DEPTH), 4), soffit_at_edge_line=round(float(top_z(Pb[iW, 0]) - DEPTH), 4))
lv['south_tip'] = dict(xy_plan_m=[round(float(v), 4) for v in B3[iS]], top=round(float(top_z(Pb[iS, 0])), 4))
lv['north_tip'] = dict(xy_plan_m=[round(float(v), 4) for v in B3[iN]], top=round(float(top_z(Pb[iN, 0])), 4))
_oc_ring = np.asarray(OCULUS_HOLE.exterior.coords)
lv['oculus_rim_top_min_max'] = [round(float(top_z(_oc_ring[:, 0]).min()), 4), round(float(top_z(_oc_ring[:, 0]).max()), 4)]
lv['total_fall_m'] = round(float(top_z(Pb[iE, 0]) - top_z(Pb[iW, 0])), 4)
fall_dir = world_n(np.array([[-1.0, 0, 0]]))[0]
lv['fall_direction_gltf_xz'] = [round(float(fall_dir[0]), 5), round(float(fall_dir[2]), 5)]
lv['fall_bearing_deg'] = round(math.degrees(math.atan2(fall_dir[0], -fall_dir[2])) % 360, 2)
meas['levels'] = lv
meas['oculus'] = dict(centre_R3m=[round(float(v), 4) for v in rh2r3([OC])[0]], centre_R3m_json_frame=[round(float(v), 4) for v in rh2j([OC])[0]],
                      centre_gltf_xz=[round(float(v), 4) for v in world([[OC[0], OC[1], 0]])[0][[0, 2]]], void_d=OCULUS_VOID_D, band_w=OCULUS_BAND_W,
                      ring_1600_built=False)

FID = collections.OrderedDict()
_jo = sg.Polygon(PLAN['outline']['xy_plan_m']); _mine = sg.Polygon(rh2j(np.asarray(CANOPY_SOLID.exterior.coords)))
FID['outline_hausdorff_mm'] = round(_jo.exterior.hausdorff_distance(_mine.exterior) * 1000, 2)
FID['top_band_150_hausdorff_mm'] = round(sg.Polygon(PLAN['top_band_inner_150']['xy_plan_m']).exterior.hausdorff_distance(sg.Polygon(rh2j(np.asarray(FIELD_OUTER.exterior.coords))).exterior) * 1000, 2)
FID['soffit_495_hausdorff_mm'] = round(sg.Polygon(PLAN['soffit_band_inner_495']['xy_plan_m']).exterior.hausdorff_distance(sg.Polygon(rh2j(np.asarray(CEN.exterior.coords))).exterior) * 1000, 2)
if DX.get('edge'):
    _dxe = dxf2rh(DX['edge'])
    FID['outline_vs_dxf_edge_extract_max_mm'] = round(max(CANOPY_SOLID.exterior.distance(sg.Point(p)) for p in _dxe) * 1000, 2)
FID['oculus_centre_vs_dxf_alum_circle_mm'] = round(float(np.linalg.norm(OC - dxf2rh([c['c'] for c in DX['circles'] if c['layer'] == 'ALUM'][0])[0])) * 1000, 2) if DX.get('circles') else None
FID['legacy_cad_old_footprint_outside_outline_m2'] = round(EXIST_FP.difference(CANOPY_SOLID).area, 4)
_ob = densify_ring(np.asarray(EXIST_FP.exterior.coords), 0.02)
_dd = np.array([CANOPY_SOLID.exterior.distance(sg.Point(p)) for p in _ob])
FID['legacy_cad_old_edge_on_new_edge_share_(<2mm)'] = round(float((_dd < 0.002).mean()), 3)
FID['legacy_cad_old_east_edge_vs_new_mm'] = round(float(abs(EXIST_FP.bounds[2] - X_EAST)) * 1000, 2)
_pts = {'oculus': OC, 'NE_corner': Pb[np.argmax(Pb[:, 0] + Pb[:, 1])], 'SW': Pb[np.argmin(Pb[:, 0] + Pb[:, 1])]}
FID['frame_offset_vs_canopy_plan_json_m'] = {k: [round(float(v), 4) for v in (rh2r3([p])[0] - rh2j([p])[0])] for k, p in _pts.items()}
meas['drawing_fidelity'] = FID

def tower_join_check():
    res = collections.OrderedDict()
    ring = np.array([TOWER_SIDE.interpolate(t).coords[0] for t in np.linspace(0, TOWER_SIDE.length, int(TOWER_SIDE.length / 0.005) + 1)])
    rp = shapely.points(ring[:, 0], ring[:, 1])
    dglass = shapely.distance(TOWER_GLASS, rp); inglass = shapely.contains_xy(TOWER_INTERIOR, ring[:, 0], ring[:, 1])
    near = np.ones(len(ring), bool)
    res['tower_side_edge_length_m'] = round(float(TOWER_SIDE.length), 3)
    if near.any():
        sd = np.where(inglass, -dglass, dglass)[near]
        res['tower_side_edge_vs_unit_glass_face_mm'] = dict(min=round(float(sd.min() * 1000), 2), median=round(float(np.median(sd) * 1000), 2),
                                                            max=round(float(sd.max() * 1000), 2), p95_abs=round(float(np.percentile(np.abs(sd), 95) * 1000), 2),
                                                            share_within_10mm=round(float((np.abs(sd) <= 0.010).mean()), 4),
                                                            note='')
        dlow = shapely.distance(TOWER_LOW.boundary, rp)[near]; inlow = shapely.contains_xy(TOWER_LOW, ring[near, 0], ring[near, 1])
        res['tower_side_edge_vs_lowest_storey_frame_mm'] = dict(min=round(float(np.where(inlow, -dlow, dlow).min() * 1000), 2),
                                                                max=round(float(np.where(inlow, -dlow, dlow).max() * 1000), 2),
                                                                note='')
        pts = ring[near]
        res['tower_side_top_level_min_max'] = [round(float(top_z(pts[:, 0]).min()), 4), round(float(top_z(pts[:, 0]).max()), 4)]
        res['tower_side_edge_under_fins_share'] = round(float(np.mean(shapely.contains_xy(FINS_LOW.buffer(0.002), pts[:, 0], pts[:, 1]))), 3)
    res['plan_overlap_canopy_x_tower_interior_m2'] = round(float(CANOPY_SOLID.intersection(TOWER_INTERIOR).area), 5)
    res['plan_overlap_canopy_x_lowest_storey_frame_m2'] = round(float(CANOPY_SOLID.intersection(TOWER_LOW).area), 5)
    samples, layer_of = [], []
    W = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [.5, .5, 0], [0, .5, .5], [.5, 0, .5], [1 / 3, 1 / 3, 1 / 3], [.7, .15, .15], [.15, .7, .15], [.15, .15, .7]])
    for m in V01:
        if is_old_canopy(m) or m['layer'] == '铁架::地面埋板': continue
        Tm = m['V'][m['F']]
        keep = ((Tm[:, :, 2] > 2.5) & (Tm[:, :, 2] < 4.3)).any(1)
        if not keep.any(): continue
        S = np.einsum('kj,tjd->tkd', W, Tm[keep]).reshape(-1, 3)
        samples.append(S); layer_of += [m['layer']] * len(S)
    S = np.concatenate(samples); layer_of = np.array(layer_of)
    sel = shapely.contains_xy(CANOPY_SOLID.buffer(0.3), S[:, 0], S[:, 1]); S, layer_of = S[sel], layer_of[sel]
    inplan = shapely.contains_xy(CANOPY, S[:, 0], S[:, 1])
    topS = top_z(S[:, 0]); und = np.full(len(S), np.nan)
    if inplan.any(): und[inplan] = underside_z(S[inplan][:, :2])
    clash = inplan & (S[:, 2] < topS - 1e-4) & (S[:, 2] > und + 1e-4)
    res['tower_samples_near_canopy'] = int(len(S))
    res['clash_samples'] = int(clash.sum())
    if clash.any():
        res['clash_layers'] = dict(collections.Counter(layer_of[clash].tolist()))
        pen = np.minimum(topS[clash] - S[clash, 2], S[clash, 2] - und[clash])
        res['clash_max_penetration_m'] = round(float(pen.max()), 4)
        res['clash_plan_depth_max_m'] = round(float(max(CANOPY.exterior.distance(sg.Point(p)) for p in S[clash][:, :2])), 4)
        res['clash_at_R3m'] = [[round(float(v), 3) for v in q] for q in rh2r3(S[clash][:, :2])[:: max(1, int(clash.sum() // 8))]]
    above = inplan & (S[:, 2] >= topS - 1e-4)
    if above.any():
        gap = S[above, 2] - topS[above]; k = gap.argmin()
        res['min_clearance_above_top_m'] = round(float(gap[k]), 4); res['min_clearance_above_layer'] = str(layer_of[above][k])
        res['min_clearance_above_at_R3m'] = [round(float(v), 3) for v in rh2r3([S[above][k, :2]])[0]]
    below = inplan & (S[:, 2] <= und + 1e-4)
    if below.any():
        g3_ = und[below] - S[below, 2]; k = g3_.argmin()
        res['min_clearance_below_underside_m'] = round(float(g3_[k]), 4); res['min_clearance_below_layer'] = str(layer_of[below][k])
    eo = lines(EXIST_FP.exterior.intersection(TOWER_LOW.buffer(0.8)))
    if eo:
        po = np.vstack([np.asarray(l.coords) for l in eo])
        res['legacy_cad_old_canopy_edge_to_unit_face_m'] = [round(float(min(TOWER_LOW.distance(sg.Point(p)) for p in po)), 4), round(float(max(TOWER_LOW.distance(sg.Point(p)) for p in po)), 4)]
    return res

JOIN = {} if ARGS.no_verify else tower_join_check()

_tv = []
for m in V01:
    if is_old_canopy(m) or m['layer'] == '铁架::地面埋板': continue
    Tm = m['V'][m['F']]
    _tv.append(np.concatenate([m['V'], Tm.mean(1), (Tm[:, 0] + Tm[:, 1]) / 2, (Tm[:, 1] + Tm[:, 2]) / 2, (Tm[:, 2] + Tm[:, 0]) / 2]))
_tv = np.concatenate(_tv)
for c in COL_INFO:
    c['cap_below_top_m'] = round(c['top_y_at_column'] - c['cap_y'], 4)
    d = np.hypot(_tv[:, 0] - c['rh'][0], _tv[:, 1] - c['rh'][1])
    along = (d < CHS_D / 2 + 0.005) & (_tv[:, 2] > 0.05) & (_tv[:, 2] < c['cap_y'])
    above = (d < CHS_D / 2 + 0.05) & (_tv[:, 2] >= c['cap_y'])
    c['tower_points_clashing_tube'] = int(along.sum())
    disk = sg.Point(c['rh']).buffer(CHS_D / 2, quad_segs=8); zs = []
    for m in V01:
        if m['layer'] not in ('装饰条', '装饰条铝板', '中横梁', '横梁', '立柱', '吊顶', '玻璃面板'): continue
        Tm = m['V'][m['F']]
        k = (Tm[:, :, 2].min(1) > c['cap_y'] - 0.01) & (Tm[:, :, 2].min(1) < 6.0) &             (Tm[:, :, 0].min(1) < c['rh'][0] + 0.1) & (Tm[:, :, 0].max(1) > c['rh'][0] - 0.1) & (Tm[:, :, 1].min(1) < c['rh'][1] + 0.1) & (Tm[:, :, 1].max(1) > c['rh'][1] - 0.1)
        for t in Tm[k]:
            g = sg.Polygon(t[:, :2]) if sg.Polygon(t[:, :2]).area > 1e-9 else sg.LineString(t[:, :2])
            if g.intersects(disk): zs.append(float(t[:, 2].min()))
    c['under_tower_fins'] = bool(FINS_LOW.intersects(disk))
    c['tower_clearance_above_cap_m'] = round(min(zs) - c['cap_y'], 4) if zs else None

EVAL = collections.OrderedDict()
try:
    r7 = json.load(open(R7_JSON))
    R7 = so.unary_union([sg.Polygon(r32rh(np.array(p[0]))) for p in r7['coordinates']]).buffer(0)
    ceg = json.load(open(os.path.join(SOURCES_DIR, 'canopy_candidate_b.json')))
    SK = so.unary_union([sg.Polygon(r32rh(np.array(p[0])), [r32rh(np.array(h)) for h in p[1:]]) for p in ceg['extension']['coordinates']]).buffer(0)
    EXT_SOLID = CANOPY_SOLID.difference(EXIST_FP.buffer(0.0005, join_style=2)).buffer(0)
    for name, geo in (('candidate_A_fill', R7), ('candidate_B_extension', SK)):
        EVAL[name] = dict(area_m2=round(geo.area, 3), dwg_extension_area_m2=round(EXT_SOLID.area, 3),
                          hausdorff_m=round(geo.boundary.hausdorff_distance(EXT_SOLID.boundary), 3),
                          sym_diff_m2=round(geo.symmetric_difference(EXT_SOLID).area, 3))
    EVAL['note'] = ''
except Exception as e:
    EVAL['error'] = repr(e)

meas['triangles_total'] = int(tri_total)
meas['triangles_by_part'] = stats
USER_QUESTIONS = [
    dict(q='Q1', param='SCHEME (env MOCKUP_CANOPY_SCHEME) -> TOP_FINISH (env MOCKUP_CANOPY_TOP) + CLAD_FINISH (env MOCKUP_CANOPY_CLAD_FINISH)',
         value=TOP_FINISH, value_clad=CLAD_FINISH, scheme=SCHEME, options=list(ML.CANOPY_TOP_OPTIONS), schemes=list(CANOPY_SCHEMES),
         ask=''),
    dict(q='Q2', param='SLOPE_OPTION (env MOCKUP_CANOPY_SLOPE_OPTION)', value=SLOPE_OPTION, options=['1.5deg', '1:100'],
         ask=''),
    dict(q='Q-C09-C11', param='COLUMNS (env MOCKUP_CANOPY_COLUMNS)', value=COLUMNS, options=list(COLUMNS_LAYOUTS),
         ask=''),
    dict(q='Q-OCULUS', param='OCULUS_VOID_D / OCULUS_BAND_W', value=[OCULUS_VOID_D, OCULUS_BAND_W], options=['2.20 + 150 band outside', '1.90 void (hatch r950-1100 read as the band)'],
         ask=''),
    dict(q='Q-COLFINISH', param='COLUMN_FINISH (env MOCKUP_CANOPY_COLUMN_FINISH)', value=COLUMN_FINISH, options=list(COLUMN_OPTIONS),
         ask=''),
]
summary = collections.OrderedDict(
    title='',
    group=GROUP, parent_group='VMU01',
    frame='glTF x=East, y=Up, z=-North; metres; y=0 yard slab top (C12); plan = DWG -> legacy CAD VMU01 rh (tower grid) -> plan metres (group_registration VMU01) -> site_frame.r3_to_gltf',
    params=collections.OrderedDict(SLOPE_OPTION=SLOPE_OPTION, SLOPE=round(SLOPE, 6), SCHEME=SCHEME, TOP_FINISH=TOP_FINISH, CLAD_FINISH=CLAD_FINISH,
                                   COLUMN_FINISH=COLUMN_FINISH, COLUMNS=COLUMNS,
                                   TOWER_STRIP_PART=TOWER_STRIP_PART, TOP_AT_HIGH_EDGE=TOP_AT_HIGH_EDGE, FASCIA_H=FASCIA_H, CHAMFER_W=CHAMFER_W,
                                   CHAMFER_DROP=round(CHAMFER_DROP, 4), DEPTH=DEPTH, TOP_BAND_W=TOP_BAND_W, SOFFIT_BAND_W=SOFFIT_BAND_W,
                                   JOINT_W=JOINT_W, OCULUS_VOID_D=OCULUS_VOID_D, OCULUS_BAND_W=OCULUS_BAND_W, CAP_BELOW_TOP=CAP_BELOW_TOP,
                                   BP=BP, BP_T=BP_T, PLINTH_TOP=PLINTH_TOP),
    sources=[SRC_S1, SRC_S2, SRC_S3, SRC_DET, SRC_LEGACY_CAD],
    dxf_md5=DX.get('source', {}).get('dwg_md5'),
    user_questions=USER_QUESTIONS,
    measurements=meas, tower_join=JOIN, columns=COL_INFO, old_candidates_eval=EVAL,
    removed=dict(legacy_columns=N_COL_REMOVED, note=''),
    column_layout=collections.OrderedDict(COLUMNS=COLUMNS, options=list(COLUMNS_LAYOUTS), text=COL_LAYOUT_TXT[0], confidence=COL_LAYOUT_TXT[1],
                                          new=N_COL_NEW, as_built_kept=N_COL_KEPT, legacy_removed=N_COL_REMOVED,
                                          dwg_cen_source='',
                                          evidence=''),
)
_HEX = {m: ML.get(m)['hex'] for m in (TOP_FINISH, CLAD_FINISH, COLUMN_FINISH, 'SEALANT_BLACK', 'STEEL_HDG')}
_ZH = {'AL_MOUSEGREY': 'Mouse Grey（≈RAL 7005）', 'AL_T02': 'T02 深灰 PVDF',
       'AL_RAL7038': 'RAL 7038 玛瑙灰（备选，非订货色）', 'STEEL_HDG': '热镀锌', 'SEALANT_BLACK': '黑色密封胶'}
_EN = {'AL_MOUSEGREY': 'Mouse Grey ~RAL 7005', 'AL_T02': 'T02 dark grey PVDF',
       'AL_RAL7038': 'RAL 7038 agate grey, non-default alternative, not the ordered finish', 'STEEL_HDG': 'hot-dip galvanised', 'SEALANT_BLACK': 'black sealant'}
_COL_EN = {'AL_T02': ('AL_T02 %s dark paint proxy (inferred: the 6 existing to-be-replaced legacy CAD columns are dark-painted in photo; no spec for the 11 new columns)' % _HEX.get('AL_T02', '')
                     if COLUMNS != 'asbuilt6' else 'AL_T02 %s dark paint proxy (the 6 kept as-built legacy CAD columns are dark-painted in photo; no spec for the 7 new columns)' % _HEX.get('AL_T02', '')),
           'STEEL_HDG': 'STEEL_HDG %s hot-dip galvanised (alternative; the existing columns in the photos are dark-painted)' % _HEX.get('STEEL_HDG', '')}
_COL_ZH = {'AL_T02': ('深色涂装，按 T02 %s 近似（推断：照片中 6 根待拆除的既有柱为深色涂装，新 11 根柱无涂装规格）' % _HEX.get('AL_T02', '')
                     if COLUMNS != 'asbuilt6' else '深色涂装，按 T02 %s 近似（保留的 6 根既有柱在照片中为深色涂装，新 7 根柱无涂装规格）' % _HEX.get('AL_T02', '')),
           'STEEL_HDG': '热镀锌 STEEL_HDG %s（备选；照片中的既有柱为深色涂装）' % _HEX.get('STEEL_HDG', '')}
_used = {TOP_FINISH, CLAD_FINISH, COLUMN_FINISH, 'SEALANT_BLACK', 'STEEL_HDG'}
FINISH_BLOCK = collections.OrderedDict(
    scheme=SCHEME, top=TOP_FINISH, clad_3mm=CLAD_FINISH, columns=COLUMN_FINISH, joints='SEALANT_BLACK', frame='STEEL_HDG',
    note='', source='',
    top_hex=_HEX[TOP_FINISH], clad_hex=_HEX[CLAD_FINISH], columns_hex=_HEX[COLUMN_FINISH], joints_hex=_HEX['SEALANT_BLACK'], frame_hex=_HEX['STEEL_HDG'],
    parts=collections.OrderedDict((k, PART_DEF[k][1]) for k in ('top', 'band', 'fascia', 'chamfer', 'soffit', 'topjoint', 'soffitjoint', 'frame', 'col_chs', 'col_plate')),
    applies_to='existing + extension (the extension has no panel order yet -> same scheme)',
    schemes=list(CANOPY_SCHEMES), uses_ral7038='AL_RAL7038' in _used, never_red=True,
    columns_confidence=_FS_COL[COLUMN_FINISH][1],
    text_en=('VMU-01 canopy (existing + extension, same scheme) finish scheme %s: 25 mm honeycomb top %s %s (%s); 3 mm top band 150 + oculus band, '
             'fascia 100, chamfer 420x205, soffit edge strip + trays %s %s (%s); CHS150 columns + base plates %s; 20 mm joints SEALANT_BLACK; '
             'concealed GMS primaries STEEL_HDG. Never red%s.') % (
        SCHEME, TOP_FINISH, _HEX[TOP_FINISH], _EN.get(TOP_FINISH, TOP_FINISH), CLAD_FINISH, _HEX[CLAD_FINISH], _EN.get(CLAD_FINISH, CLAD_FINISH),
        _COL_EN[COLUMN_FINISH], '; RAL 7038 not used' if 'AL_RAL7038' not in _used else '; RAL 7038 used (non-default alternative scheme)'),
    text_zh=('VMU-01 雨棚（既有 + 延伸同一配色）饰面方案 %s：25 mm 蜂窝顶板 %s %s；3 mm 顶面边带 150 + 圆孔边带 / 封边 100 / 斜边 420x205 / 底板 %s %s；'
             'CHS150 柱及底板 %s；20 mm 缝黑色密封胶；隐藏 GMS 主梁热镀锌。不用红色%s。') % (
        SCHEME, _ZH.get(TOP_FINISH, TOP_FINISH), _HEX[TOP_FINISH], _ZH.get(CLAD_FINISH, CLAD_FINISH), _HEX[CLAD_FINISH], _COL_ZH[COLUMN_FINISH],
        '，无 RAL 7038' if 'AL_RAL7038' not in _used else '，含 RAL 7038（备选方案）'),
)
summary['finish'] = FINISH_BLOCK
scene_x = collections.OrderedDict(
    SLOPE='%s (1:%.1f)' % (SLOPE_OPTION.replace('deg', '°'), 1 / SLOPE), SLOPE_TAN=round(SLOPE, 6), SLOPE_OPTION=SLOPE_OPTION,
    top_level_m=TOP_AT_HIGH_EDGE, top_at_tower_m=JOIN.get('tower_side_top_level_min_max', TOP_AT_HIGH_EDGE),
    top_low_edge_m=lv['west_low_edge']['top'],
    existing_canopy_area_m2=meas['existing_area_m2'], extension_area_m2=meas['extension_area_m2'], total_area_m2=meas['total_area_net_m2'],
    total_area_gross_m2=meas['total_area_gross_m2'], oculus_diameter_m=OCULUS_VOID_D,
    new_columns=N_COL_NEW, columns_total=len(COL_INFO), columns_removed=N_COL_REMOVED, columns_as_built_kept=N_COL_KEPT, COLUMNS=COLUMNS,
    finish=FINISH_BLOCK,
    canopy=summary)
root = glb.node(GROUP, children=children, root=True,
                extras=ML.node_extras(GROUP, 'Canopy (existing + extension)', CLAD_FINISH, 'see scene extras.canopy.sources', 'high (outline, levels) / medium (joint width, rim, C09-C11 set-out)',
                                      parent_group='VMU01', SLOPE=round(SLOPE, 6), SLOPE_OPTION=SLOPE_OPTION, columns=len(COL_INFO), COLUMNS=COLUMNS, triangles=int(tri_total),
                                      finish_scheme=SCHEME, finish_top=TOP_FINISH, finish_clad=CLAD_FINISH, finish_columns=COLUMN_FINISH,
                                      finish_note=''))
os.makedirs(os.path.dirname(OUT), exist_ok=True)
glb.save(OUT, extras=scene_x)
os.makedirs(SCRATCH, exist_ok=True)
_default_out = os.path.abspath(OUT) == os.path.abspath(os.path.join(ROOT, 'model', 'vmu01_canopy.glb'))
rep = os.path.join(SCRATCH, 'canopy_report.json' if _default_out else os.path.basename(os.path.dirname(os.path.abspath(OUT))) + '_' + os.path.basename(OUT).replace('.glb', '_report.json'))
json.dump(summary, open(rep, 'w', encoding='utf-8'), indent=1, ensure_ascii=False, default=lambda o: o.tolist() if hasattr(o, 'tolist') else str(o))
if _default_out:
    pickle.dump(dict(CANOPY=CANOPY, EXIST=EXIST, EXT=EXT, FIELD=FIELD, TOP_JOINTS=TOP_JOINTS, SOFFIT=SOFFIT, SOFFIT_JOINTS=SOFFIT_JOINTS, FRAME=FRAME,
                     TOWER_FP=TOWER_FP, TOWER_LOW=TOWER_LOW, TOWER_GLASS=TOWER_GLASS, TOWER_INTERIOR=TOWER_INTERIOR, FINS_LOW=FINS_LOW, EXIST_FP=EXIST_FP, OC=OC, COLS=COL_INFO, X_EAST=X_EAST, SLOPE=SLOPE),
                open(os.path.join(SCRATCH, 'canopy_plan.pkl'), 'wb'))
print('[build step] wrote', OUT, '%.2f MB' % (os.path.getsize(OUT) / 1e6), 'triangles', tri_total, 'report', rep)
sys.stdout.reconfigure(encoding='utf-8')
print(json.dumps(dict(measurements=meas, tower_join=JOIN), indent=1, ensure_ascii=False, default=str))
for c in COL_INFO:
    print(c['id'], c['region'], 'xy_plan_m', c['xy_plan_m'], 'blk', c['dwg_block_xy_mm'], 'moved', c['moved_from_source_mm'], 'cap', c['cap_y'], 'tube', c['tube_length'],
          'edge', c['dist_inside_edge_m'], 'under', c['under_canopy'], 'meets_soffit', c['meets_soffit'], 'pen', c['tube_penetration_into_canopy_m'],
          'fins', c.get('under_tower_fins'), 'clr', c.get('tower_clearance_above_cap_m'), 'clash', c.get('tower_points_clashing_tube'))
