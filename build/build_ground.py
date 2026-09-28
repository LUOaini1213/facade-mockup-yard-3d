"""Builds model/site_ground.glb: the yard slab bounded by the surveyed lot line (UVs in metres), damp patches, weed strip,
trench-drain covers + sumps, inspection chambers, fire hydrants, the two crane runways (flush rail heads, grooves, edge
angles, red safety lines) clipped by the mock-up footprints, the yellow buffer line and the main road.

The main road is GENERIC: a dual carriageway laid out along the surveyed road-side lot line with nominal dimensions (near verge,
lane, median and far-verge widths below; 4 lanes per direction), a standard dash and
hatch pattern, 2 % crossfall and a level assumed 0.5 m below the yard slab. Runway R1 is drawn on the layout plan; runway R2
is not, so its NNE rail is placed from a site photo and its SSW rail at the R1 gauge. No aerial imagery, map tiles or
terrain data are used. Needs the private survey extract (site_survey.json) in SOURCES_DIR.
"""
import os, sys, json, math, time, re
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
_cwd = os.getcwd(); os.chdir(HERE)
from site_frame import r3_to_gltf, page_to_r3, s as S_PT
os.chdir(_cwd)
from gltfw import GLB
from materials_lib import mat, node_extras
import shapely.geometry as sg
import shapely.ops as so
import mapbox_earcut as earcut

SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')
OUT_GLB = os.path.join(ROOT, 'model', 'site_ground.glb')
DWG_JSON = os.path.join(SOURCES_DIR, 'site_survey.json')
SCRATCH = os.environ.get('MOCKUP_GROUND_SCRATCH') or os.path.join(HERE, '_scratch', 'ground')

# crane runways (plan x of each rail centreline in layout-plan points; rails run along the plan y axis)
R1_PAGE_X = (354.12, 478.32)          # runway R1: drawn on the layout plan (gauge 124.20 pt = 26.00 m)
R2B_PHOTO_PAGE_X = 617.35             # runway R2, NNE rail: a site photo shows it entering the factory end bay 1.4-1.6 m from the
                                      # end column, i.e. plan x 616.3-618.4 -> mid-range
GANTRY_RAILS_PAGE_X = (493.15, 617.35)   # runway R2 = (R2B_PHOTO_PAGE_X - R1 gauge, R2B_PHOTO_PAGE_X); read by build_context2.py
assert abs(GANTRY_RAILS_PAGE_X[0] - (R2B_PHOTO_PAGE_X - (R1_PAGE_X[1] - R1_PAGE_X[0]))) < 1e-6
R2A_END_PT = 656.0
R2B_END_PT = 608.5
RUNWAYS = {
    'R1': dict(x_pt=R1_PAGE_X, gantry=False, confidence='medium', end_pt=(None, None),
               source='layout plan'),
    'R2': dict(x_pt=GANTRY_RAILS_PAGE_X, gantry=True,
               end_pt=(R2A_END_PT, R2B_END_PT),
               confidence='low-medium - NEEDS SITE CONFIRMATION (position and ESE end)',
               source='NNE rail from a site photo, SSW rail at the R1 gauge; ends clear of the mock-ups (assumed)'),
}
RAIL_INTO_BAY_M = 6.0
GRID_P_PT = 377.40
RAIL_END_LINE_PT = ((354.12, 692.6), (478.32, 695.0))
RAIL_HEAD_W = 0.070
RAIL_GROOVE_W = 0.035
RAIL_EDGE_W = 0.020
RAIL_BED_W = 0.50
RAIL_TOP = 0.003
RED_LINE_OFFSET = 0.80
RED_LINE_W = 0.10
RED_LINE_START_PT = 383.0
KEEP_OUT_SOURCES = [
    ('vmu02.glb', r'^VMU02\|', 'VMU02 platform, skirting, access steps, columns', 'hull'),
    ('vmu04.glb', r'^VMU04\|', 'VMU04 RC slab patch, base plates, stair', 'hull'),
    ('vmu05.glb', r'^VMU05\|', 'VMU05 parapet', 'exact'),
    ('vmu01_canopy.glb', r'Base plates|Columns', 'VMU01 canopy column bases (the open area under the canopy stays)', 'exact'),
    ('vmu_cad.glb', r'^(VMU01|VMU03|TRELLIS)\|', 'VMU01 / VMU03 / TRELLIS footprints (hull of base plates / setting blocks)', 'hull'),
    ('site_context.glb', r'^(Containers \+ site office|Temporary steel viewing platform|Material storage \(stillages\)|High masts)\|',
     'containers + site office, viewing-platform posts, stillages, high-mast plinths', 'exact'),
]
PARKING_KEEP_OUT_EXTRA = [
    ('site_context.glb', r'^(Factory|Accessway truss canopy)', 'factory footprints incl. Factory 2 north block (bare RC frame)', 'hull'),
]
KEEP_OUT_MAX_Y = 0.40
KEEP_OUT_MARGIN = 0.10
EAST_EXT_M = 175.0
DAMP_FRACTION = 0.07
DAMP_SEED = 2026
DAMP_BOX_PT = (312.0, 800.0, 386.0, 702.0)
WEED_STRIP_W = 0.50
YELLOW_LINE_OFFSET = 3.0
YELLOW_LINE_W = 0.10
PARKING_PAINT = 'off'
PARKING_R3_STORAGE_X_PT = 694.0
PARK_LINE_W = 0.10
PAINT_Y = 0.003
DAMP_Y = 0.002
COVER_W_JOINT = 0.02
COVER_LEN = 1.0
HYDRANT_BODY_MAT = 'CTX_STILLAGE_RED'
# --- main road: generic dual carriageway along the surveyed road-side lot line (all widths nominal / assumed) -----------
# road frame: origin = SE lot corner, s along bearing ROAD_FRAME_BRG, t across (away from the yard); offsets d from the near
# kerb centreline along its normal. The near kerb is the lot line moved NEAR_VERGE_W across the road (cubic fit, below).
ROAD_FRAME_BRG = 25.0
ROAD_S_RANGE = (-60.0, 250.0)
ROAD_END_RAMP_M = 8.0
NEAR_VERGE_TO_YARD_END = True
NEAR_VERGE_W = 4.0                 # assumed: lot line -> near kerb centreline
KERB_FIT_DEG = 3
ROAD_MEAN_Y = -0.50                # assumed: carriageway 0.5 m below the yard slab
ROAD_CROSSFALL = 0.02
KERB_H = 0.15
KERB_W = 0.30
VERGE_TOP_Y = -0.05
FAR_VERGE_TOP_Y = -0.05
LANES_PER_DIRECTION = 4            # lane count per carriageway
LANE_W = 3.50                      # nominal lane width
MEDIAN_W = 2.00                    # nominal painted (hatched) median between the two edge lines
FAR_VERGE_W = 4.00                 # nominal far verge
FAR_EXTENT_M = 20.0                # modelled ground beyond the far verge
X_NEAR_KERB = 0.0
X_CW0 = 0.15
X_LANES_NEAR = tuple(round(X_CW0 + LANE_W * k, 3) for k in range(1, LANES_PER_DIRECTION))
X_MEDIAN_EDGES = (round(X_CW0 + LANE_W * LANES_PER_DIRECTION, 3), round(X_CW0 + LANE_W * LANES_PER_DIRECTION + MEDIAN_W, 3))
X_MEDIAN_CTR = (X_MEDIAN_EDGES[0] + X_MEDIAN_EDGES[1]) / 2
X_LANES_FAR = tuple(round(X_MEDIAN_EDGES[1] + LANE_W * k, 3) for k in range(1, LANES_PER_DIRECTION))
X_CW1 = round(X_MEDIAN_EDGES[1] + LANE_W * LANES_PER_DIRECTION, 3)
X_FAR_KERB = X_CW1 + 0.15
X_FAR_BOUNDARY = round(X_FAR_KERB + KERB_W / 2 + FAR_VERGE_W, 3)
X_FAR_END = round(X_FAR_BOUNDARY + FAR_EXTENT_M, 3)
LANE_LINE_W = 0.12
MEDIAN_EDGE_W = 0.20
DASH_LEN = 2.0                     # standard pattern: 2 m dash, 4 m gap
DASH_PERIOD = 6.0
DASH_S = {d: [round(float(c), 2) for c in np.arange(ROAD_S_RANGE[0] + DASH_PERIOD / 2, ROAD_S_RANGE[1], DASH_PERIOD)]
          for d in X_LANES_NEAR + X_LANES_FAR}
HATCH_PERIOD = 5.0                 # median hatch: one 45 deg stripe every 5 m
HATCH_SLOPE = 1.0
HATCH_S = [round(float(c), 2) for c in np.arange(ROAD_S_RANGE[0] + HATCH_PERIOD / 2, ROAD_S_RANGE[1], HATCH_PERIOD)]
HATCH_W = 0.30
NEAR_TAPER = []                    # no lane tapers in the generic road
FAR_TAPER = []
NEAR_TAPER_HATCH = dict(slope=1.0, period=5.0, phase=0.0, d_ref=0.0)
FAR_TAPER_HATCH = dict(slope=1.0, period=5.0, phase=0.0, d_ref=0.0)
TAPER_LINE_W = 0.15
TAPER_HATCH_W = 0.25
ROAD_KERB_POLY = None              # set after the survey is read (fit_kerb)

def pg2xz(px, py):
    px = np.atleast_1d(np.asarray(px, float)); py = np.atleast_1d(np.asarray(py, float))
    g = r3_to_gltf(np.c_[px * S_PT, -py * S_PT]); return g[:, [0, 2]]

def pg2xz1(px, py):
    return pg2xz(px, py)[0]

def xz2pg(x, z):
    o = pg2xz1(0.0, 0.0); ex_ = pg2xz1(1.0, 0.0) - o; ey_ = pg2xz1(0.0, 1.0) - o
    M = np.array([ex_, ey_]).T
    q = np.linalg.solve(M, np.vstack([np.atleast_1d(x) - o[0], np.atleast_1d(z) - o[1]]))
    return q.T

_SE = np.array(json.load(open(DWG_JSON, encoding='utf-8'))['features']['lot_boundary_derived'][0]['gltf_xz'][1], float)   # SE lot corner (survey extract)
_b = math.radians(ROAD_FRAME_BRG)
_U = np.array([math.sin(_b), -math.cos(_b)])
_N0 = np.array([math.cos(_b), math.sin(_b)])

def kerb_t(s):
    return np.polyval(ROAD_KERB_POLY, s)

def kerb_dt(s):
    return np.polyval(np.polyder(ROAD_KERB_POLY), s)

def K(s):
    s = np.asarray(s, float)
    return _SE + s[..., None] * _U + kerb_t(s)[..., None] * _N0

def KN(s):
    s = np.asarray(s, float)
    T = _U + kerb_dt(s)[..., None] * _N0
    Nn = np.stack([-T[..., 1], T[..., 0]], -1)
    return Nn / np.linalg.norm(Nn, axis=-1, keepdims=True)

def P(s, d):
    s = np.asarray(s, float); d = np.asarray(d, float)
    return K(s) + d[..., None] * KN(s)

GUTTER_Y = ROAD_MEAN_Y - ROAD_CROSSFALL * (X_MEDIAN_CTR - X_CW0) / 2.0
CROWN_Y = GUTTER_Y + ROAD_CROSSFALL * (X_MEDIAN_CTR - X_CW0)
KERB_TOP_Y = GUTTER_Y + KERB_H

def road_y(d):
    d = np.asarray(d, float)
    near = CROWN_Y - ROAD_CROSSFALL * (X_MEDIAN_CTR - np.clip(d, X_CW0, X_MEDIAN_CTR))
    far = CROWN_Y - ROAD_CROSSFALL * (np.clip(d, X_MEDIAN_CTR, X_CW1) - X_MEDIAN_CTR)
    return np.where(d <= X_MEDIAN_CTR, near, far)

FLOOR_Y = float(min(road_y(X_CW0), road_y(X_CW1)))

def ramp_w(s, ends=(True, True)):
    s = np.asarray(s, float); w = np.zeros_like(s); s0, s1 = ROAD_S_RANGE; R = ROAD_END_RAMP_M
    if ends[0]:
        u = np.clip((s0 + R - s) / R, 0, 1); w = np.maximum(w, u * u * (3 - 2 * u))
    if ends[1]:
        u = np.clip((s - (s1 - R)) / R, 0, 1); w = np.maximum(w, u * u * (3 - 2 * u))
    return w

def ramp(s, y, ends=(True, True)):
    y = np.asarray(y, float)
    return y + ramp_w(s, ends) * (FLOOR_Y - y)

class Acc:
    def __init__(self):
        self.V = []; self.F = []; self.N = []; self.n = 0

    def add(self, V, F, N):
        V = np.asarray(V, np.float64); F = np.asarray(F, np.int64); N = np.asarray(N, np.float64)
        if len(F) == 0:
            return
        self.V.append(V); self.N.append(N); self.F.append(F + self.n); self.n += len(V)

    def arrays(self):
        if not self.V:
            return None
        return np.vstack(self.V), np.vstack(self.F), np.vstack(self.N)

LAYERS = {}

def layer(key, material, source, confidence, **kw):
    if key not in LAYERS:
        LAYERS[key] = dict(acc=Acc(), material=material,
                           extras=node_extras('SITE_GROUND', key, material, source, confidence, **kw))
    return LAYERS[key]['acc']

def tri_polygon(poly):
    rings = [np.asarray(poly.exterior.coords)[:-1]] + [np.asarray(r.coords)[:-1] for r in poly.interiors]
    rings = [r for r in rings if len(r) >= 3]
    if not rings:
        return np.zeros((0, 2)), np.zeros((0, 3), int)
    V = np.vstack(rings)
    ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
    idx = earcut.triangulate_float64(V, ends)
    F = np.asarray(idx, np.int64).reshape(-1, 3)
    if len(F):
        a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
        cr = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
        flip = cr > 0
        F[flip] = F[flip][:, [0, 2, 1]]
    return V, F

def geoms(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == 'Polygon':
        return [g]
    if hasattr(g, 'geoms'):
        out = []
        for h in g.geoms:
            out += geoms(h)
        return out
    return []

def add_flat(acc, g, y):
    for poly in geoms(g):
        if poly.area < 1e-6:
            continue
        V2, F = tri_polygon(poly)
        if not len(F):
            continue
        yy = y(V2[:, 0], V2[:, 1]) if callable(y) else np.full(len(V2), y)
        V = np.c_[V2[:, 0], yy, V2[:, 1]]
        acc.add(V, F, np.tile([0.0, 1.0, 0.0], (len(V), 1)))

def add_grid(acc, Pxz, Y, flip=False):
    R, C = Y.shape
    V = np.c_[Pxz.reshape(-1, 2)[:, 0], Y.reshape(-1), Pxz.reshape(-1, 2)[:, 1]]
    idx = np.arange(R * C).reshape(R, C)
    a = idx[:-1, :-1].ravel(); b = idx[:-1, 1:].ravel(); c = idx[1:, 1:].ravel(); d = idx[1:, :-1].ravel()
    F = np.vstack([np.c_[a, b, c], np.c_[a, c, d]])
    A, B, Cc = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    n = np.cross(B - A, Cc - A)
    fl = n[:, 1] < 0
    F[fl] = F[fl][:, [0, 2, 1]]
    A, B, Cc = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    n = np.cross(B - A, Cc - A)
    N = np.zeros_like(V)
    for k in range(3):
        np.add.at(N, F[:, k], n)
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    acc.add(V, F, N)

def add_wall(acc, xz_line, y_top, y_bot):
    xz = np.asarray(xz_line, float)
    yt = np.full(len(xz), y_top) if np.isscalar(y_top) else np.asarray(y_top, float)
    yb = np.full(len(xz), y_bot) if np.isscalar(y_bot) else np.asarray(y_bot, float)
    for i in range(len(xz) - 1):
        p0, p1 = xz[i], xz[i + 1]
        dvec = p1 - p0; L = np.linalg.norm(dvec)
        if L < 1e-6:
            continue
        nrm = np.array([dvec[1], 0.0, -dvec[0]]) / L
        V = np.array([[p0[0], yt[i], p0[1]], [p1[0], yt[i + 1], p1[1]], [p1[0], yb[i + 1], p1[1]], [p0[0], yb[i], p0[1]]])
        acc.add(V, [[0, 1, 2], [0, 2, 3]], np.tile(nrm, (4, 1)))

def add_cylinder(acc, cx, cz, y0, y1, r, seg=20, cap=True):
    th = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    ring = np.c_[np.cos(th), np.sin(th)]
    V = []; N = []; F = []
    for i in range(seg):
        j = (i + 1) % seg
        p = [ring[i], ring[j], ring[j], ring[i]]
        ys = [y0, y0, y1, y1]
        base = len(V)
        for q, yy in zip(p, ys):
            V.append([cx + r * q[0], yy, cz + r * q[1]]); N.append([q[0], 0, q[1]])
        F += [[base, base + 2, base + 1], [base, base + 3, base + 2]]
    if cap:
        base = len(V)
        V.append([cx, y1, cz]); N.append([0, 1, 0])
        for i in range(seg):
            V.append([cx + r * ring[i, 0], y1, cz + r * ring[i, 1]]); N.append([0, 1, 0])
        for i in range(seg):
            F.append([base, base + 1 + (i + 1) % seg, base + 1 + i])
    acc.add(np.array(V), np.array(F), np.array(N))

def add_cyl_axis(acc, p0, p1, r, seg=14):
    p0 = np.asarray(p0, float); p1 = np.asarray(p1, float); ax = p1 - p0; L = np.linalg.norm(ax); ax /= L
    up = np.array([0, 1.0, 0]) if abs(ax[1]) < 0.9 else np.array([1.0, 0, 0])
    e1 = np.cross(ax, up); e1 /= np.linalg.norm(e1); e2 = np.cross(ax, e1)
    th = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    V = []; N = []; F = []
    for i in range(seg):
        j = (i + 1) % seg
        for (k, e) in ((i, 0), (j, 0), (j, 1), (i, 1)):
            q = math.cos(th[k]) * e1 + math.sin(th[k]) * e2
            V.append((p0 if e == 0 else p1) + r * q); N.append(q)
        b = 4 * i
        F += [[b, b + 1, b + 2], [b, b + 2, b + 3]]
    base = len(V); V.append(p1); N.append(ax)
    for i in range(seg):
        V.append(p1 + r * (math.cos(th[i]) * e1 + math.sin(th[i]) * e2)); N.append(ax)
    for i in range(seg):
        F.append([base, base + 1 + i, base + 1 + (i + 1) % seg])
    acc.add(np.array(V), np.array(F), np.array(N))

def rect_xz(p0, p1, w):
    p0 = np.asarray(p0, float); p1 = np.asarray(p1, float)
    d = p1 - p0; d /= np.linalg.norm(d); n = np.array([-d[1], d[0]]) * w / 2
    return sg.Polygon([p0 + n, p1 + n, p1 - n, p0 - n])

def line_poly(pts, w):
    return sg.LineString(pts).buffer(w / 2, cap_style='flat', join_style='mitre', mitre_limit=3.0)

DWG = json.load(open(DWG_JSON, encoding='utf-8'))
FEAT = DWG['features']
LOT_SOUTH_LEN_M = float(DWG['lot_south_line']['length_m'])
LOT = np.array(FEAT['lot_boundary_derived'][0]['gltf_xz'])
SE, K1, K2, NCLIP = LOT[1], LOT[2], LOT[3], LOT[4]

def unit(v):
    v = np.asarray(v, float); return v / np.linalg.norm(v)

D_SOUTH = unit(LOT[0] - SE)
SW = SE + D_SOUTH * LOT_SOUTH_LEN_M
D_EAST_N = unit(NCLIP - K2)
NEXT = NCLIP + D_EAST_N * EAST_EXT_M
D_WEST = np.array([-D_SOUTH[1], D_SOUTH[0]])
if (NCLIP - SE) @ D_WEST < 0:
    D_WEST = -D_WEST
DEPTH = float((NEXT - SE) @ D_WEST)
BACK_W = SW + D_WEST * DEPTH
BACK_E = NEXT
YARD_POLY = sg.Polygon([SW, SE, K1, K2, NCLIP, NEXT, BACK_W]).buffer(0)
EAST_LINE = [SE, K1, K2, NCLIP, NEXT]
S_EXT = SE - unit(K1 - SE) * 80.0
LOT_LINE_EXT = np.array([S_EXT] + EAST_LINE)

def lot_line_t(s):
    """t (across the road frame) where the lot line crosses the frame normal at station s."""
    o = _SE + s * _U; best = None
    for i in range(len(LOT_LINE_EXT) - 1):
        a, b = LOT_LINE_EXT[i], LOT_LINE_EXT[i + 1]
        M = np.array([_N0, a - b]).T
        try:
            t, u = np.linalg.solve(M, a - o)
        except np.linalg.LinAlgError:
            continue
        if -1e-6 <= u <= 1 + 1e-6 and (best is None or abs(t) < abs(best)):
            best = t
    return best

def fit_kerb():
    """near kerb line = surveyed lot line + NEAR_VERGE_W across the road, as a cubic t(s) over the modelled road."""
    ss = np.arange(ROAD_S_RANGE[0] - ROAD_END_RAMP_M, ROAD_S_RANGE[1] + 40.0, 1.0)
    tt = np.array([lot_line_t(s) for s in ss], dtype=object)
    ok = np.array([t is not None for t in tt])
    ss, tt = ss[ok], tt[ok].astype(float)
    poly = np.polyfit(ss, tt + NEAR_VERGE_W, KERB_FIT_DEG)
    res = np.polyval(poly, ss) - (tt + NEAR_VERGE_W)
    return [float(c) for c in poly], dict(fit_deg=KERB_FIT_DEG, max_abs_residual_m=round(float(np.abs(res).max()), 3),
                                          s_samples=[float(ss[0]), float(ss[-1])])

ROAD_KERB_POLY, KERB_FIT = fit_kerb()
DIR_PAGE_Y = unit(pg2xz1(400, 600) - pg2xz1(400, 400))
DIR_PAGE_X = unit(pg2xz1(600, 400) - pg2xz1(400, 400))

def load_keep_out(sources):
    import trimesh
    polys = []; rep = []
    cache = {}
    for fn, rx, what, mode in sources:
        path = os.path.join(ROOT, 'model', fn)
        if not os.path.exists(path):
            rep.append(dict(file=fn, what=what, status='missing')); continue
        if fn not in cache:
            cache[fn] = trimesh.load(path, force='scene')
        sc = cache[fn]; n_nodes = 0; parts = []
        for n in sc.graph.nodes_geometry:
            if not re.search(rx, n):
                continue
            T, g = sc.graph[n]; m = sc.geometry[g]
            V = trimesh.transform_points(np.asarray(m.vertices, float), T); F = np.asarray(m.faces)
            if not len(F):
                continue
            low = V[F][:, :, 1].min(1) < KEEP_OUT_MAX_Y
            if not low.any():
                continue
            n_nodes += 1
            tri = V[F[low]][:, :, [0, 2]]
            a = 0.5 * np.abs((tri[:, 1, 0] - tri[:, 0, 0]) * (tri[:, 2, 1] - tri[:, 0, 1]) - (tri[:, 1, 1] - tri[:, 0, 1]) * (tri[:, 2, 0] - tri[:, 0, 0]))
            if mode == 'hull':
                parts.append(sg.MultiPoint(tri.reshape(-1, 2)).convex_hull.buffer(0.02))
                continue
            flat = [sg.Polygon(t) for t in tri[a > 1e-6]]
            edge = [sg.LineString(t[[0, 1, 2]]).buffer(0.02) for t in tri[a <= 1e-6]]
            if flat or edge:
                parts.append(so.unary_union(flat + edge))
        U = so.unary_union(parts) if parts else sg.Polygon()
        if not U.is_empty:
            polys.append(U)
        rep.append(dict(file=fn, regex=rx, what=what, mode=mode, nodes=n_nodes, area_m2=round(float(U.area), 2)))
    raw = so.unary_union(polys) if polys else sg.Polygon()
    KO_RAW_ = raw
    return (raw.buffer(KEEP_OUT_MARGIN) if polys else sg.Polygon()), rep, KO_RAW_

def free_pieces(a, b, KO, half_w):
    ls = sg.LineString([a, b])
    if KO.is_empty or not ls.intersects(KO.buffer(half_w)):
        return [(np.asarray(a, float), np.asarray(b, float))], 0.0
    rest = ls.difference(KO.buffer(half_w))
    out = []
    for g in (rest.geoms if hasattr(rest, 'geoms') else [rest]):
        if g.is_empty or g.length < 0.05:
            continue
        c = np.asarray(g.coords); dvec = np.asarray(b, float) - np.asarray(a, float)
        p0, p1 = (c[0], c[-1]) if (c[-1] - c[0]) @ dvec >= 0 else (c[-1], c[0])
        out.append((p0, p1))
    return out, float(ls.length - sum(np.linalg.norm(q - p) for p, q in out))

def rail_end_y(x_pt):
    (xa, ya), (xb, yb) = RAIL_END_LINE_PT
    return ya + (x_pt - xa) * (yb - ya) / (xb - xa)

RAIL_Y0_PT = GRID_P_PT - RAIL_INTO_BAY_M / S_PT
HOLES = []
PAINT_POLYS = []
RAIL_INFO = []
KO = sg.Polygon(); KO_RAW = sg.Polygon(); KO_REPORT = []

def build_rails():
    acc_head = layer('Crane rails (rail head, flush)', 'CTX_RAIL',
                     '', 'medium (R1) / low-medium (R2, needs site confirmation)',
                     rail_head_w_m=RAIL_HEAD_W, flush_top_m=RAIL_TOP)
    acc_groove = layer('Crane rails (flangeway groove)', 'CTX_BAY_VOID', '', 'low',
                       groove_w_m=RAIL_GROOVE_W)
    acc_edge = layer('Crane rails (edge angle)', 'CTX_RAIL', '', 'low', edge_w_m=RAIL_EDGE_W)
    acc_bed = layer('Crane rails (rail-bed joint)', 'CTX_BAY_VOID', '', 'low', bed_w_m=RAIL_BED_W)
    acc_red = layer('Rail red safety lines', 'CTX_RED_LINE', '', 'medium', offset_m=RED_LINE_OFFSET, width_m=RED_LINE_W)
    nn = DIR_PAGE_X
    off_groove = RAIL_HEAD_W / 2 + RAIL_GROOVE_W / 2
    off_edge = RAIL_HEAD_W / 2 + RAIL_GROOVE_W + RAIL_EDGE_W / 2
    for rw, R in RUNWAYS.items():
        for k, xpt in enumerate(R['x_pt']):
            y1 = R['end_pt'][k] if R['end_pt'][k] is not None else rail_end_y(xpt)
            a0 = pg2xz1(xpt, RAIL_Y0_PT); b0 = pg2xz1(xpt, y1)
            wr = RAIL_HEAD_W + RAIL_GROOVE_W + RAIL_EDGE_W
            mid = nn * (wr / 2 - RAIL_HEAD_W / 2)
            pieces, cut = free_pieces(a0 + mid, b0 + mid, KO_RAW, wr / 2 + 0.01)
            pieces = [(p - mid, q - mid) for p, q in pieces]
            ob = nn * (RAIL_HEAD_W / 2 + RAIL_BED_W)
            for p_, q_ in free_pieces(a0 + ob, b0 + ob, KO_RAW, 0.02)[0]:
                bed = rect_xz(p_, q_, 0.012)
                add_flat(acc_bed, bed, 0.0)
                HOLES.append(bed)
            for a, b in pieces:
                head = rect_xz(a, b, RAIL_HEAD_W)
                groove = rect_xz(a + nn * off_groove, b + nn * off_groove, RAIL_GROOVE_W)
                edge = rect_xz(a + nn * off_edge, b + nn * off_edge, RAIL_EDGE_W)
                add_flat(acc_head, head, RAIL_TOP)
                add_flat(acc_groove, groove, -0.025)
                add_flat(acc_edge, edge, 0.002)
                for sgn in (-1, 1):
                    o = nn * (off_groove + sgn * RAIL_GROOVE_W / 2)
                    add_wall(acc_groove, [a + o, b + o], 0.0, -0.025)
                HOLES.append(so.unary_union([head, groove, edge]).buffer(0))
            r0 = pg2xz1(xpt, max(RED_LINE_START_PT, RAIL_Y0_PT)); r1 = b0 - DIR_PAGE_Y * 0.3
            red_cut = 0.0; red_len = 0.0
            for sgn in (-1, 1):
                o = DIR_PAGE_X * (sgn * RED_LINE_OFFSET)
                rp, c_ = free_pieces(r0 + o, r1 + o, KO, RED_LINE_W / 2 + 0.02)
                red_cut += c_
                for p, q in rp:
                    rl = rect_xz(p, q, RED_LINE_W)
                    add_flat(acc_red, rl, PAINT_Y); PAINT_POLYS.append(rl); red_len += float(np.linalg.norm(q - p))
            L = float(sum(np.linalg.norm(q - p) for p, q in pieces))
            RAIL_INFO.append(dict(runway=rw, rail=k, x_R3pt=xpt, y_from_R3pt=round(RAIL_Y0_PT, 2), y_to_R3pt=round(y1, 2),
                                  ended_early=R['end_pt'][k] is not None, length_m=round(L, 2), n_pieces=len(pieces),
                                  clipped_by_keep_out_m=round(cut, 2), red_lines_total_m=round(red_len, 2), red_lines_clipped_m=round(red_cut, 2),
                                  gltf_from=[round(float(a0[0]), 3), round(float(a0[1]), 3)],
                                  gltf_to=[round(float(b0[0]), 3), round(float(b0[1]), 3)], gantry_runway=R['gantry']))

def page_rect(x0, x1, y0, y1):
    c = pg2xz(np.array([x0, x1, x1, x0]), np.array([y0, y0, y1, y1]))
    return sg.Polygon(c).buffer(0)

DRAIN_STRIPS = []

def build_drains():
    F = FEAT['drains']
    pts = [np.c_[np.array(f['xy_plan_m'])[:, 0] / S_PT, -np.array(f['xy_plan_m'])[:, 1] / S_PT] for f in F]
    x_s_out, x_s_in = float(pts[3][0, 0]), float(pts[0][-1, 0])
    x_n_in, x_n_out = float(pts[0][0, 0]), float(pts[2][0, 0])
    y_f0, y_f1 = float(pts[1][1, 1]), float(pts[0][1, 1])
    y_top = float(pts[3][0, 1])
    y_s_end = float(pts[3][-1, 1])
    y_n_end = float(pts[2][-1, 1])
    strips = [('South boundary drain', (x_s_out, x_s_in, y_top, y_s_end), 'y'),
              ('Factory-1 frontage drain', (x_s_in, x_n_in, y_f0, y_f1), 'x'),
              ('NNE drain', (x_n_in, x_n_out, y_top, y_n_end), 'y')]
    acc_c = layer('Trench drain covers (precast)', 'CTX_KERB', '', 'medium (position), low (cover type)',
                  cover_len_m=COVER_LEN, joint_m=COVER_W_JOINT)
    acc_j = layer('Trench drain cover joints', 'CTX_BAY_VOID', '', 'low')
    rails_u = so.unary_union([h for h in HOLES]) if HOLES else sg.Polygon()
    acc_s = layer('Drain sump gratings', 'STEEL_HDG', '', 'low')
    marks = [np.mean(pts[i], 0) for i in (4, 8, 12)]
    sumps = []
    for m_ in marks:
        c = pg2xz1(*m_); sq = rect_xz(c - DIR_PAGE_Y * 0.3, c + DIR_PAGE_Y * 0.3, 0.6).difference(rails_u)
        add_flat(acc_s, sq, 0.003)
        sumps.append(sq)
    rails_u = so.unary_union([rails_u] + sumps)
    HOLES.extend(sumps)
    for name, (x0, x1, y0, y1), along in strips:
        poly = page_rect(x0, x1, y0, y1).intersection(YARD_POLY)
        poly = poly.difference(rails_u)
        HOLES.append(poly)
        a = pg2xz1(x0, y0)
        if along == 'y':
            dvec = DIR_PAGE_Y; L = (y1 - y0) * S_PT
        else:
            dvec = DIR_PAGE_X; L = (x1 - x0) * S_PT
        joints = []
        for k in range(1, int(L / COVER_LEN) + 1):
            c = a + dvec * (k * COVER_LEN)
            perp = np.array([-dvec[1], dvec[0]])
            joints.append(rect_xz(c - perp * 5, c + perp * 5, COVER_W_JOINT))
        J = so.unary_union(joints).intersection(poly) if joints else sg.Polygon()
        add_flat(acc_c, poly.difference(J), 0.002)
        add_flat(acc_j, J, 0.0)
        DRAIN_STRIPS.append(dict(name=name, x_R3pt=[x0, x1], y_R3pt=[y0, y1], width_m=round((x1 - x0 if along == 'y' else y1 - y0) * S_PT, 3),
                                 length_m=round(L, 1), overlaps_keep_out_m2=round(float(poly.intersection(KO).area), 3)))
    return marks

def build_ic_and_hydrants():
    acc_p = layer('IC chamber covers (cast iron)', 'CTX_RAIL', '', 'medium (position), low (finish)')
    acc_f = layer('IC chamber frames', 'CTX_KERB', '', 'low')
    ic = []
    for f in FEAT['inspection_chambers_and_dashed_drain']:
        if not f['closed']:
            continue
        c = np.array(f['gltf_xz'])[:-1]
        plate = sg.Polygon(c).buffer(0)
        frame = plate.buffer(0.10, join_style='mitre').difference(plate)
        add_flat(acc_p, plate, 0.003); add_flat(acc_f, frame, 0.002)
        HOLES.append(plate.buffer(0.10, join_style='mitre'))
        ic.append(dict(centre_gltf_xz=[round(float(v), 3) for v in np.asarray(plate.centroid.coords)[0]],
                       overlaps_keep_out=bool(plate.intersects(KO))))
    acc_h = layer('Fire hydrants (pillar)', HYDRANT_BODY_MAT, '', 'low (shape)')
    acc_hc = layer('Fire hydrant outlet caps', 'STEEL_HDG', '', 'low')
    acc_hp = layer('Fire hydrant pads', 'CTX_KERB', '', 'low')
    out = []
    for f in FEAT['fire_hydrants']:
        c = np.array(f['gltf_xz']).mean(0)
        add_cylinder(acc_hp, c[0], c[1], 0.0, 0.04, 0.5, seg=28)
        add_cylinder(acc_h, c[0], c[1], 0.04, 0.10, 0.16, seg=20)
        add_cylinder(acc_h, c[0], c[1], 0.10, 0.82, 0.11, seg=20)
        add_cylinder(acc_h, c[0], c[1], 0.82, 0.90, 0.125, seg=20)
        add_cylinder(acc_h, c[0], c[1], 0.90, 0.95, 0.06, seg=12)
        for ang in (0.0, math.pi):
            dvec = np.array([math.cos(ang), 0, math.sin(ang)])
            p0 = np.array([c[0], 0.55, c[1]]) + dvec * 0.09; p1 = p0 + dvec * 0.12
            add_cyl_axis(acc_h, p0, p1, 0.045)
            add_cyl_axis(acc_hc, p1, p1 + dvec * 0.03, 0.05)
        out.append(dict(gltf_xz=[round(float(c[0]), 3), round(float(c[1]), 3)],
                        overlaps_keep_out=bool(sg.Point(c).buffer(0.5).intersects(KO))))
    return out, ic

def merge_parking():
    segs_long = []; segs_short = []
    for f in FEAT['parking_lines']:
        p = np.array(f['gltf_xz'])
        L = np.linalg.norm(np.diff(p, axis=0), axis=1).sum()
        if L >= 1.2:
            segs_long.append(p)
        else:
            for i in range(len(p) - 1):
                if np.linalg.norm(p[i + 1] - p[i]) > 0.05:
                    segs_short.append((p[i], p[i + 1]))
    recs = []
    for a, b in segs_short:
        d = b - a; ang = math.degrees(math.atan2(d[1], d[0])) % 180.0
        u = np.array([math.cos(math.radians(ang)), math.sin(math.radians(ang))]); n = np.array([-u[1], u[0]])
        recs.append((ang, float(a @ n), float(a @ u), float(b @ u), a, b))
    used = [False] * len(recs); merged = []; singles = []
    for i, r in enumerate(recs):
        if used[i]:
            continue
        grp = [i]; used[i] = True
        for j in range(i + 1, len(recs)):
            if used[j]:
                continue
            da = abs((recs[j][0] - r[0] + 90) % 180 - 90)
            if da < 2.0:
                u = np.array([math.cos(math.radians(r[0])), math.sin(math.radians(r[0]))]); n = np.array([-u[1], u[0]])
                if abs(recs[j][4] @ n - r[1]) < 0.12 and abs(recs[j][5] @ n - r[1]) < 0.12:
                    grp.append(j); used[j] = True
        if len(grp) < 3:
            singles += [(recs[k][4], recs[k][5]) for k in grp]
            continue
        u = np.array([math.cos(math.radians(r[0])), math.sin(math.radians(r[0]))]); n = np.array([-u[1], u[0]])
        iv = sorted([tuple(sorted((recs[k][4] @ u, recs[k][5] @ u))) for k in grp])
        cur = list(iv[0])
        for lo, hi in iv[1:]:
            if lo - cur[1] <= 1.3:
                cur[1] = max(cur[1], hi)
            else:
                merged.append((cur[0] * u + r[1] * n, cur[1] * u + r[1] * n)); cur = [lo, hi]
        merged.append((cur[0] * u + r[1] * n, cur[1] * u + r[1] * n))
    return segs_long, merged, singles

def build_paint():
    info = dict(parking_mode=PARKING_PAINT)
    if PARKING_PAINT != 'off':
        acc = layer('Parking lines (faded paint)', 'CTX_ROAD_MARKING_WHITE', '',
                    'low (existence), medium (layout)', width_m=PARK_LINE_W, mode=PARKING_PAINT)
        L, M, S1 = merge_parking()
        polys = [line_poly(p, PARK_LINE_W) for p in L] + [line_poly([a, b], PARK_LINE_W) for a, b in M] + \
                [line_poly([a, b], PARK_LINE_W) for a, b in S1]
        U = so.unary_union(polys).intersection(YARD_POLY.buffer(-0.05)).difference(so.unary_union(HOLES).buffer(0.03))
        KOp, rep, _ = load_keep_out(PARKING_KEEP_OUT_EXTRA)
        U = U.difference(KO).difference(KOp)
        if PAINT_POLYS:
            U = U.difference(so.unary_union(PAINT_POLYS).buffer(0.02))
        if PARKING_PAINT == 'dxf_outside_r3_storage':
            U = U.difference(page_rect(PARKING_R3_STORAGE_X_PT, 2000, -500, 2000))
        add_flat(acc, U, PAINT_Y)
        info.update(parking_long=len(L), parking_merged=len(M), parking_single_dashes=len(S1), parking_area_m2=round(float(U.area), 2),
                    parking_keep_out=rep)
    accy = layer('Yellow line (3 m inside the road boundary)', 'CTX_YELLOW_LINE', '', 'low',
                 offset_m=YELLOW_LINE_OFFSET, width_m=YELLOW_LINE_W)
    east = sg.LineString(EAST_LINE[:4])
    off = east.offset_curve(YELLOW_LINE_OFFSET, join_style='mitre')
    if off.distance(sg.Point(SE + D_WEST * 50)) > east.distance(sg.Point(SE + D_WEST * 50)):
        off = east.offset_curve(-YELLOW_LINE_OFFSET, join_style='mitre')
    yl = off.buffer(YELLOW_LINE_W / 2, cap_style='flat', join_style='mitre')
    yl = yl.intersection(YARD_POLY.buffer(-YELLOW_LINE_OFFSET + 0.2)).difference(page_rect(300, 311.5, 600, 720))
    yl0 = yl.area
    yl = yl.difference(so.unary_union(HOLES).buffer(0.03)).difference(KO)
    yl = yl.difference(so.unary_union(PAINT_POLYS).buffer(0.02))
    add_flat(accy, yl, PAINT_Y); PAINT_POLYS.append(yl)
    info.update(yellow_line_m=round(float(yl.area / YELLOW_LINE_W), 1), yellow_line_clipped_m=round(float((yl0 - yl.area) / YELLOW_LINE_W), 1))
    accw = layer('Weed strip at hoarding foot', 'CTX_GRASS', '', 'low', width_m=WEED_STRIP_W)
    fparts = [np.array(f['gltf_xz']) for f in FEAT['fence_centreline'][1:]]
    fparts[-1] = np.vstack([fparts[-1], NEXT])
    ws = []
    for fp in fparts:
        ls = sg.LineString(fp)
        for sgn in (1, -1):
            o = ls.offset_curve(sgn * WEED_STRIP_W / 2, join_style='mitre')
            if YARD_POLY.contains(o.interpolate(0.5, normalized=True)):
                ws.append(o.buffer(WEED_STRIP_W / 2, cap_style='flat', join_style='mitre'))
                break
    W = so.unary_union(ws).intersection(YARD_POLY)
    W = W.difference(so.unary_union(HOLES)).difference(KO)
    add_flat(accw, W, 0.002)
    HOLES.append(W)
    return info

def build_damp():
    if DAMP_FRACTION <= 0:
        return 0.0
    import cv2
    from scipy.ndimage import gaussian_filter
    x0, x1, y0, y1 = DAMP_BOX_PT
    res = 0.20
    W = int((x1 - x0) * S_PT / res); H = int((y1 - y0) * S_PT / res)
    rng = np.random.default_rng(DAMP_SEED)
    def band(sig, w):
        g = gaussian_filter(rng.standard_normal((H, W)), sig / res); return w * g / g.std()
    f = band(8.0, 1.0) + band(2.0, 0.35) + band(0.5, 0.10)
    thr = np.quantile(f, 1 - DAMP_FRACTION)
    mask = (f > thr).astype(np.uint8)
    cs, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    polys = []
    for i, c in enumerate(cs):
        if hier[0][i][3] != -1 or len(c) < 4:
            continue
        pts = c[:, 0, :].astype(float)
        px = x0 + (pts[:, 0] + 0.5) * res / S_PT; py = y0 + (pts[:, 1] + 0.5) * res / S_PT
        xz = pg2xz(px, py)
        poly = sg.Polygon(xz).buffer(0.15).buffer(-0.15).simplify(0.06)
        ch = hier[0][i][2]
        while ch != -1:
            q = cs[ch][:, 0, :].astype(float)
            if len(q) >= 4:
                hx = pg2xz(x0 + (q[:, 0] + 0.5) * res / S_PT, y0 + (q[:, 1] + 0.5) * res / S_PT)
                poly = poly.difference(sg.Polygon(hx).buffer(0))
            ch = hier[0][ch][0]
        if poly.area > 1.5:
            polys.append(poly)
    U = so.unary_union(polys).intersection(YARD_POLY.buffer(-0.3)).difference(so.unary_union(HOLES)).difference(KO)
    if PAINT_POLYS:
        U = U.difference(so.unary_union(PAINT_POLYS).buffer(0.01))
    acc = layer('Damp patches', 'CTX_CONCRETE_YARD_DAMP', '', 'low (procedural)',
                fraction=DAMP_FRACTION, seed=DAMP_SEED)
    add_flat(acc, U, DAMP_Y)
    box = page_rect(x0, x1, y0, y1).intersection(YARD_POLY)
    return float(U.area / box.area)

def build_slab():
    acc = layer('Yard slab', 'CTX_CONCRETE_YARD', '', 'high (main road + south lot lines), '
                'low (NNE/WNW extent beyond the sheet)', uv='metres (u = x East, v = z)', level_note='')
    holes = so.unary_union([h for h in HOLES if h is not None and not h.is_empty])
    slab = YARD_POLY.difference(holes)
    add_flat(acc, slab, 0.0)
    accs = layer('Yard slab edge skirts', 'CTX_CONCRETE_YARD', '', 'n/a', bottom_y=round(FLOOR_Y, 3))
    add_wall(accs, [NEXT, BACK_W, SW, SE], 0.0, FLOOR_Y)
    add_wall(accs, [SE, K1, K2, NCLIP, NEXT], 0.0, FLOOR_Y)
    return slab

def lot_line_d(s):
    k = K(np.array([s]))[0]; nrm = KN(np.array([s]))[0]
    best = None
    for i in range(len(LOT_LINE_EXT) - 1):
        a, b = LOT_LINE_EXT[i], LOT_LINE_EXT[i + 1]
        M = np.array([nrm, a - b]).T
        try:
            d, t = np.linalg.solve(M, a - k)
        except np.linalg.LinAlgError:
            continue
        if -0.02 <= t <= 1.02 and d < 0 and (best is None or d > best):
            best = d
    return best

def verge_end_s():
    s = ROAD_S_RANGE[1]
    while s < 400 and lot_line_d(s + 0.5) is not None:
        s += 0.5
    return s

def build_road():
    s0, s1 = ROAD_S_RANGE; R = ROAD_END_RAMP_M
    ss = np.unique(np.round(np.r_[np.arange(s0, s1, 1.0), np.arange(s0, s0 + R, 0.25), np.arange(s1 - R, s1, 0.25), s1], 4))
    sv1 = verge_end_s() if NEAR_VERGE_TO_YARD_END else s1
    ssv = np.unique(np.round(np.r_[ss, np.arange(s1, sv1, 1.0), sv1], 4))
    acc = layer('Main road carriageway', 'CTX_ASPHALT', '', 'low (generic cross-section; level assumed)', uv='metres (u = x, v = z)',
                crossfall=ROAD_CROSSFALL, gutter_y=round(GUTTER_Y, 3), crown_y=round(CROWN_Y, 3), mean_y=ROAD_MEAN_Y,
                end_ramp_m=ROAD_END_RAMP_M, end_y=round(FLOOR_Y, 3))
    dd = np.array([X_CW0, X_LANES_NEAR[0], X_LANES_NEAR[1], X_LANES_NEAR[2], X_MEDIAN_EDGES[0], X_MEDIAN_CTR, X_MEDIAN_EDGES[1],
                   X_LANES_FAR[0], X_LANES_FAR[1], X_LANES_FAR[2], X_CW1])
    S_, D_ = np.meshgrid(ss, dd, indexing='ij')
    add_grid(acc, P(S_, D_), ramp(S_, road_y(D_)))
    acck = layer('Main road kerbs', 'CTX_KERB', '', 'low', kerb_h_m=KERB_H, kerb_w_m=KERB_W)
    for (dA, dB, dFace, sk, ends) in ((X_NEAR_KERB - KERB_W / 2, X_CW0, X_CW0, ssv, (True, False)),
                                       (X_CW1, X_FAR_KERB + KERB_W / 2, X_CW1, ss, (True, True))):
        S_, D_ = np.meshgrid(sk, np.array([dA, dB]), indexing='ij')
        add_grid(acck, P(S_, D_), ramp(S_, np.full(S_.shape, KERB_TOP_Y), ends))
        face = P(sk, np.full(len(sk), dFace)); yt = ramp(sk, np.full(len(sk), KERB_TOP_Y), ends)
        if dFace == X_CW0:
            face, yt = face[::-1], yt[::-1]
        add_wall(acck, face, yt, float(road_y(dFace)))
    accv = layer('Main road near verge (grass)', 'CTX_GRASS', '', 'medium (lot line), low (width, levels)',
                 top_y=VERGE_TOP_Y, kerb_top_y=round(KERB_TOP_Y, 3), s_range=[s0, round(sv1, 1)])
    dB = np.array([lot_line_d(s) for s in ssv])
    fr = np.linspace(0, 1, 5)
    Dv = dB[:, None] + (X_NEAR_KERB - KERB_W / 2 - dB[:, None]) * fr[None, :]
    Yv = VERGE_TOP_Y + (KERB_TOP_Y - VERGE_TOP_Y) * np.broadcast_to(fr[None, :], Dv.shape)
    Sv = np.broadcast_to(ssv[:, None], Dv.shape)
    add_grid(accv, P(Sv, Dv), ramp(Sv, Yv, (True, False)))
    accvs = layer('Main road verge edge skirts', 'CTX_GRASS', '', 'n/a')
    m0 = ssv <= 0.0
    add_wall(accvs, P(ssv[m0], dB[m0])[::-1], ramp(ssv[m0], np.full(m0.sum(), VERGE_TOP_Y), (True, False))[::-1], FLOOR_Y)
    prof_d = np.r_[Dv[-1], X_CW0]; prof_y = np.r_[Yv[-1], KERB_TOP_Y]
    add_wall(accvs, P(np.full(len(prof_d), ssv[-1]), prof_d), prof_y, FLOOR_Y)
    accf = layer('Main road far verge (grass)', 'CTX_GRASS', '', 'low (generic)',
                 far_boundary_d_m=X_FAR_BOUNDARY)
    df = np.array([X_FAR_KERB + KERB_W / 2, (X_FAR_KERB + KERB_W / 2 + X_FAR_BOUNDARY) / 2, X_FAR_BOUNDARY, X_FAR_END])
    yf = np.array([KERB_TOP_Y, (KERB_TOP_Y + FAR_VERGE_TOP_Y) / 2, FAR_VERGE_TOP_Y, FAR_VERGE_TOP_Y])
    S_, D_ = np.meshgrid(ss, df, indexing='ij')
    add_grid(accf, P(S_, D_), ramp(S_, np.broadcast_to(yf[None, :], S_.shape).copy()))
    acce = layer('Main road far verge edge skirt', 'CTX_GRASS', '', 'n/a')
    add_wall(acce, P(ss, np.full(len(ss), X_FAR_END))[::-1], ramp(ss, np.full(len(ss), FAR_VERGE_TOP_Y))[::-1], FLOOR_Y)

    accm = layer('Main road lane lines + median markings', 'CTX_ROAD_MARKING_WHITE', '', 'low (standard pattern)',
                 lane_line_w_m=LANE_LINE_W, median_edge_w_m=MEDIAN_EDGE_W, dash_len_m=DASH_LEN, hatch_w_m=HATCH_W)
    DZ = 0.004

    def strip(sA, sB, dA_, dB_):
        n = max(1, int(math.ceil((sB - sA) / 0.25)))
        sl = np.linspace(sA, sB, n + 1)
        S2, D2 = np.meshgrid(sl, np.array([dA_, dB_]), indexing='ij')
        add_grid(accm, P(S2, D2), ramp(S2, road_y(D2)) + DZ)

    def slanted(sc, dA_, dB_, slope, w_s):
        cuts = [dA_, dB_] if not (dA_ < X_MEDIAN_CTR < dB_) else [dA_, X_MEDIAN_CTR, dB_]
        for da, db in zip(cuts[:-1], cuts[1:]):
            dl = np.linspace(da, db, 4)
            sl = sc + slope * (dl - dA_)
            Pq = np.stack([P(sl - w_s, dl), P(sl + w_s, dl)], 1)
            Yq = np.stack([ramp(sl - w_s, road_y(dl)), ramp(sl + w_s, road_y(dl))], 1) + DZ
            add_grid(accm, Pq, Yq)
    n_d = 0
    for dc, lst in DASH_S.items():
        for c in lst:
            a, b = max(c - DASH_LEN / 2, s0 + 0.2), min(c + DASH_LEN / 2, s1 - 0.2)
            if b - a > 0.3:
                strip(a, b, dc - LANE_LINE_W / 2, dc + LANE_LINE_W / 2); n_d += 1
    for dc in X_MEDIAN_EDGES:
        S_, D_ = np.meshgrid(ss, np.array([dc - MEDIAN_EDGE_W / 2, dc + MEDIAN_EDGE_W / 2]), indexing='ij')
        add_grid(accm, P(S_, D_), ramp(S_, road_y(D_)) + DZ)
    dA, dB_ = X_MEDIAN_EDGES[0] + MEDIAN_EDGE_W / 2, X_MEDIAN_EDGES[1] - MEDIAN_EDGE_W / 2
    hw_s = HATCH_W * math.sqrt(1 + HATCH_SLOPE ** 2) / 2
    n_h = 0
    for c in HATCH_S:
        sA = c + HATCH_SLOPE * (dA - X_MEDIAN_CTR); sB = c + HATCH_SLOPE * (dB_ - X_MEDIAN_CTR)
        if min(sA, sB) - hw_s < s0 or max(sA, sB) + hw_s > s1:
            continue
        slanted(sA, dA, dB_, HATCH_SLOPE, hw_s); n_h += 1
    n_t = 0
    for line, kerb_d, H in ((NEAR_TAPER, X_CW0 + 0.05, NEAR_TAPER_HATCH), (FAR_TAPER, X_CW1 - 0.05, FAR_TAPER_HATCH)):
        if len(line) < 2:
            continue
        ls_ = np.array(line); sl = np.arange(max(ls_[0, 0], s0), ls_[-1, 0] + 1e-6, 0.5)
        dl = np.interp(sl, ls_[:, 0], ls_[:, 1])
        Pq = np.stack([P(sl, dl - TAPER_LINE_W / 2), P(sl, dl + TAPER_LINE_W / 2)], 1)
        Yq = np.stack([ramp(sl, road_y(dl - TAPER_LINE_W / 2)), ramp(sl, road_y(dl + TAPER_LINE_W / 2))], 1) + DZ
        add_grid(accm, Pq, Yq)
        hw = TAPER_HATCH_W * math.sqrt(1 + H['slope'] ** 2) / 2
        s_lo, s_hi = max(ls_[0, 0], s0), ls_[-1, 0]
        k0 = int(math.floor((s_lo - H['phase']) / H['period'])) - 3; k1 = int(math.ceil((s_hi - H['phase']) / H['period'])) + 3
        for k in range(k0, k1 + 1):
            sc_ref = H['phase'] + k * H['period']
            d_line = float(np.interp(sc_ref, ls_[:, 0], ls_[:, 1]))
            for _ in range(20):
                d_line = float(np.interp(sc_ref + H['slope'] * (d_line - H['d_ref']), ls_[:, 0], ls_[:, 1]))
            lo, hi = sorted([kerb_d, d_line])
            lo += 0.02 if lo == kerb_d else TAPER_LINE_W / 2 + 0.03
            hi -= 0.02 if hi == kerb_d else TAPER_LINE_W / 2 + 0.03
            if hi - lo < 0.3:
                continue
            sa = sc_ref + H['slope'] * (lo - H['d_ref']); sb = sc_ref + H['slope'] * (hi - H['d_ref'])
            if min(sa, sb) - hw < s_lo or max(sa, sb) + hw > s_hi + 0.5:
                continue
            slanted(sa, lo, hi, H['slope'], hw); n_t += 1
    verge = {f's={s_:.1f}': round(float(-lot_line_d(s_)), 2) for s_ in (-50.0, 0.0, 50.0, 100.0, 150.0, 200.0, 250.0) if lot_line_d(s_) is not None}
    corridor = sg.Polygon(np.r_[P(ss, np.array([lot_line_d(s) for s in ss])), P(ss[::-1], np.full(len(ss), X_FAR_END))])
    return dict(n_dashes=n_d, n_hatch=n_h, n_taper_hatch=n_t, verge_width_m=verge, verge_s_end=round(float(sv1), 1),
                corridor=corridor.buffer(0))



def main():
    global KO, KO_RAW, KO_REPORT
    t0 = time.time()
    glb = GLB()
    KO, KO_REPORT, KO_RAW = load_keep_out(KEEP_OUT_SOURCES)
    build_rails()
    marks = build_drains()
    hyd, ic = build_ic_and_hydrants()
    paint = build_paint()
    damp_frac = build_damp()
    slab = build_slab()
    road = build_road()
    children = []
    summary = {}
    for key, L in LAYERS.items():
        arr = L['acc'].arrays()
        if arr is None:
            continue
        V, F, N = arr
        V32 = V.astype(np.float32)
        uv = np.c_[V[:, 0], V[:, 2]].astype(np.float32)
        mi = mat(glb, L['material'])
        m = glb.mesh('SITE_GROUND|' + key, V32, F, N.astype(np.float32), mi, uvs=uv)
        children.append(glb.node('SITE_GROUND|' + key, mesh=m, extras=L['extras']))
        bb0 = V.min(0); bb1 = V.max(0)
        summary[key] = dict(material=L['material'], vertices=int(len(V)), triangles=int(len(F)),
                            bbox_min=[round(float(x), 3) for x in bb0], bbox_max=[round(float(x), 3) for x in bb1])
    rails_extras = dict(runways={k: dict(x_R3pt=list(v['x_pt']), gauge_m=round((v['x_pt'][-1] - v['x_pt'][0]) * S_PT, 3),
                                                                  gantry=v['gantry'], confidence=v['confidence'], source='',
                                                                  end_R3pt=list(v['end_pt']))
                                                         for k, v in RUNWAYS.items()},
                        lines=RAIL_INFO, into_bay_m=RAIL_INTO_BAY_M, red_line_offset_m=RED_LINE_OFFSET, red_line_w_m=RED_LINE_W,
                        needs_site_confirmation=['R2 position (not drawn on the layout plan; placed from a site photo)',
                                                 'R2 ESE ends (R2A_END_PT / R2B_END_PT assumed)', 'number of runways (R1 + R2)'])
    road_x = dict(frame=dict(origin_gltf_xz=_SE.tolist(), bearing_deg=ROAD_FRAME_BRG, kerb_poly_t_of_s=ROAD_KERB_POLY, s_range=list(ROAD_S_RANGE),
                             kerb='surveyed lot line + %.1f m (nominal verge)' % NEAR_VERGE_W, kerb_fit=KERB_FIT),
                  generic=dict(lanes_per_direction=LANES_PER_DIRECTION, lane_w_m=LANE_W, median_w_m=MEDIAN_W, far_verge_w_m=FAR_VERGE_W,
                               dash_len_m=DASH_LEN, dash_period_m=DASH_PERIOD, hatch_period_m=HATCH_PERIOD,
                               level='carriageway mean %.2f m (assumed)' % ROAD_MEAN_Y),
                  offsets_from_near_kerb_m=dict(near_kerb=X_NEAR_KERB, near_kerb_face=X_CW0, lane_lines_near=list(X_LANES_NEAR),
                                                median_edge_lines=list(X_MEDIAN_EDGES), lane_lines_far=list(X_LANES_FAR),
                                                far_kerb_face=X_CW1, far_kerb=X_FAR_KERB, far_boundary=X_FAR_BOUNDARY),
                  lane_widths_m=dict(near=[round(X_LANES_NEAR[0] - X_CW0, 2), round(X_LANES_NEAR[1] - X_LANES_NEAR[0], 2), round(X_LANES_NEAR[2] - X_LANES_NEAR[1], 2),
                                           round(X_MEDIAN_EDGES[0] - X_LANES_NEAR[2], 2)],
                                     median_hatched=round(X_MEDIAN_EDGES[1] - X_MEDIAN_EDGES[0], 2),
                                     far=[round(X_LANES_FAR[0] - X_MEDIAN_EDGES[1], 2), round(X_LANES_FAR[1] - X_LANES_FAR[0], 2),
                                          round(X_LANES_FAR[2] - X_LANES_FAR[1], 2), round(X_CW1 - X_LANES_FAR[2], 2)],
                                     kerb_to_kerb=round(X_CW1 - X_CW0, 2)),
                  levels_y=dict(gutter=round(GUTTER_Y, 3), crown=round(CROWN_Y, 3), mean=ROAD_MEAN_Y, kerb_top=round(KERB_TOP_Y, 3),
                                verge_at_lot_line=VERGE_TOP_Y, far_verge_top=FAR_VERGE_TOP_Y, model_floor=round(FLOOR_Y, 3),
                                end_ramp_m=ROAD_END_RAMP_M),
                  verge_width_lot_line_to_kerb_centre_m=road['verge_width_m'], near_verge_s_end=road['verge_s_end'],
                  markings=dict(dashes=road['n_dashes'], hatch_stripes=road['n_hatch'], taper_hatch_stripes=road['n_taper_hatch']))
    corridor = road['corridor']
    scene_extras = dict(
        group='SITE_GROUND', builder='build/build_ground.py',
        frame='glTF x=East, y=Up, z=-North; y=0 = yard slab top',
        gantry_rails_page_x=list(GANTRY_RAILS_PAGE_X),
        gantry_rails_note='runway R2: NNE rail from a site photo (plan x 616.3-618.4, mid-range), SSW rail at the R1 gauge',
        crane_runways=rails_extras, road_main=road_x,
        keep_out=dict(sources=KO_REPORT, max_y=KEEP_OUT_MAX_Y, margin_m=KEEP_OUT_MARGIN, area_m2=round(float(KO.area), 1)),
        road_corridor=dict(
            polygon_xz=[[round(float(a), 2), round(float(b), 2)] for a, b in np.asarray(corridor.exterior.coords)[::4]],
            model_floor_y=round(FLOOR_Y, 3)),
        yard=dict(polygon_gltf_xz=[[round(float(a), 3), round(float(b), 3)] for a, b in np.asarray(YARD_POLY.exterior.coords)[:-1]],
                  area_m2=round(YARD_POLY.area, 1), east_ext_m=EAST_EXT_M,
                  damp_fraction_of_vmu_yard=round(damp_frac, 3), sumps_R3pt=[[round(float(a), 2), round(float(b), 2)] for a, b in marks],
                  hydrants=hyd, inspection_chambers=ic, drains=DRAIN_STRIPS, paint=paint),
        params=dict(RAIL_INTO_BAY_M=RAIL_INTO_BAY_M, R2A_END_PT=R2A_END_PT, R2B_END_PT=R2B_END_PT, RED_LINE_OFFSET=RED_LINE_OFFSET,
                    DAMP_FRACTION=DAMP_FRACTION, DAMP_SEED=DAMP_SEED, YELLOW_LINE_OFFSET=YELLOW_LINE_OFFSET, PARKING_PAINT=PARKING_PAINT,
                    ROAD_MEAN_Y=ROAD_MEAN_Y, ROAD_CROSSFALL=ROAD_CROSSFALL, KERB_H=KERB_H, VERGE_TOP_Y=VERGE_TOP_Y, NEAR_VERGE_W=NEAR_VERGE_W,
                    LANES_PER_DIRECTION=LANES_PER_DIRECTION, LANE_W=LANE_W, MEDIAN_W=MEDIAN_W, R2B_PHOTO_PAGE_X=R2B_PHOTO_PAGE_X,
                    ROAD_END_RAMP_M=ROAD_END_RAMP_M, NEAR_VERGE_TO_YARD_END=NEAR_VERGE_TO_YARD_END, HYDRANT_BODY_MAT=HYDRANT_BODY_MAT,
                    KEEP_OUT_MARGIN=KEEP_OUT_MARGIN))
    root = glb.node('SITE_GROUND', children=children, extras=dict(group='SITE_GROUND', layer_en='site ground', finish='various',
                                                                  source='', confidence='see children'), root=True)
    glb.save(OUT_GLB, extras=scene_extras)
    os.makedirs(SCRATCH, exist_ok=True)
    with open(os.path.join(SCRATCH, 'site_ground_summary.json'), 'w', encoding='utf-8') as f:
        json.dump(dict(layers=summary, scene=scene_extras), f, ensure_ascii=False, indent=1)
    print(f'wrote {OUT_GLB}  ({os.path.getsize(OUT_GLB) / 1e6:.2f} MB, {len(children)} nodes, {time.time() - t0:.1f} s)')
    for k, v in summary.items():
        print(f"  {k:45s} {v['material']:24s} tris {v['triangles']:7d}  y {v['bbox_min'][1]:.3f}..{v['bbox_max'][1]:.3f}")
    print('keep-out:', json.dumps(KO_REPORT)[:600])
    return summary, scene_extras

if __name__ == '__main__':
    main()
