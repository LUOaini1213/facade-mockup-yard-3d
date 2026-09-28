"""Builds model/site_features.json and model/vegetation_notes.json: instanced vegetation, people, cars and label anchors in
the glTF site frame. Palm and Polyalthia positions are PROCEDURAL: seeded rows along the two road verges of
site_ground.glb (a royal-palm row just outside the hoarding and one on the far verge, about 8 m apart with +-1 m jitter,
none in front of the entrance gate; Polyalthia in some of the gaps of the near row; one Polyalthia and one broad-leaf
tree placed from site photos). The verges are read from the kerb layer of site_ground.glb. Tree bases are ray-sampled on
site_ground.glb; palm crowns are rotated to clear the mock-ups; people and cars are moved off every obstacle of
site_context.glb. No aerial imagery is used. Needs the private survey extract and canopy outline in SOURCES_DIR.
"""
import json, math, os, sys, glob, time
import numpy as np, cv2
from scipy import ndimage as ndi
from scipy.spatial.transform import Rotation
import shapely
from shapely.geometry import Polygon, Point, MultiPoint, LineString, shape, box
from shapely.ops import unary_union
import trimesh
SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
os.chdir(HERE); sys.path.insert(0, HERE)
from site_frame import r3_to_gltf, page_to_r3, r3_dir_to_gltf

T0 = time.time()
SCRATCH_IN = os.path.join(HERE, '_scratch', 'features')
SCRATCH = os.environ.get('MOCKUP_FEATURES_SCRATCH') or SCRATCH_IN
os.makedirs(os.path.join(SCRATCH, 'r2'), exist_ok=True)
P = dict(
    ROW_PITCH=8.0,
    ROW_JITTER=1.0,
    NEAR_ROW_BAND=0.6,
    YOUNG_SHARE=0.1,
    N_POLY=10,
    POLY_MIN_GAP=6.5,
    GATE_CLEAR=3.0,
    FAR_VERGE_W=4.0,
    PALM_MIN_OUT=1.45,
    KERB_CLEAR=0.8,
    PALM_H_TOTAL=(11.5, 16.0),
    YOUNG_H_TOTAL=(6.0, 7.5),
    FAR_H_TOTAL=(10.0, 14.0),
    POLY_H=(6.5, 10.0),
    CROWN_ABOVE_ATTACH=1.9,
    U_RANGE=(-60.0, 198.0),
    PERSON_CLEAR=0.8,
    PERSON_CTX_CLEAR=0.5,
    OBST_Y=1.9,
    OBST_RES=0.05,
    OBST_HOLE_MAX=40.0,
    CAR_NUDGE=(0.5, -0.5, 1.0, -1.0, 1.5, -1.5, 2.0, -2.0),
    CROWN_CLEAR=0.2,
    ROT_STEP_DEG=5.0,
    SEED=7,
    FALLBACK_GROUND_Y=-0.22, VERGE_SINK=0.08,
    PHOTO_POLY=[dict(u=32.6, off=2.3, h=8.5, between_palms=True, src='')],   # u: site-photo cue (behind the site-office container),
                                                                           # snapped to the midpoint of the adjacent procedural palms
    BROADLEAF=[dict(u_range=(34.0, 46.0), h=10.0, r=2.8, min_trunk_gap=2.2,
                    src='')],
)
VPALM = dict(count=(14, 18), len=(3.2, 4.2), leaflet=(0.6, 0.9), droop=(30.0, 50.0), shaftLen=1.6)
rng = np.random.default_rng(P['SEED'])

DWG = json.load(open(os.path.join(SOURCES_DIR, 'site_survey.json'), encoding='utf-8'))
LOT_SOUTH_LEN_M = float(DWG['lot_south_line']['length_m'])
DF = DWG['features']
SE, K1, K2, NC = np.array(DF['lot_boundary_derived'][0]['gltf_xz'], float)[1:5]   # road-side lot corners from the survey extract
dS = (K1 - SE) / np.linalg.norm(K1 - SE); dN = (NC - K2) / np.linalg.norm(NC - K2)
FENCE = np.array([SE - dS * 90, SE, K1, K2, NC, NC + dN * 200])
SEG = np.diff(FENCE, axis=0); SL = np.linalg.norm(SEG, axis=1); ST = SEG / SL[:, None]; CUM = np.r_[0, np.cumsum(SL)]; U0 = CUM[1]
SN = np.stack([-ST[:, 1], ST[:, 0]], -1)
assert SN[1][0] > 0
FENCE_LS = LineString([tuple(q) for q in FENCE])

def to_xz(u, v):
    u = np.asarray(u, float) + U0; v = np.asarray(v, float)
    k = np.clip(np.searchsorted(CUM, u, side='right') - 1, 0, len(ST) - 1)
    return FENCE[k] + ST[k] * (u - CUM[k])[..., None] + SN[k] * v[..., None]

def to_uv(q):
    q = np.asarray(q, float); best = (1e9, 0, 0)
    for k in range(len(ST)):
        t = np.clip(np.dot(q - FENCE[k], ST[k]), 0, SL[k]); p = FENCE[k] + ST[k] * t; d = np.linalg.norm(q - p)
        if d < best[0] - 1e-9: best = (d, CUM[k] + t - U0, np.sign(np.dot(q - p, SN[k])) * d if d > 1e-9 else 0.0)
    return np.array([best[1], best[2]])

_GROUND = []
_gp = os.path.join(ROOT, 'model', 'site_ground.glb')
GROUND_SRC = ('fallback ground: model/site_ground.glb (build step) absent -> flat ground at y %.2f outside the yard slab; '
              'bases at %.2f (sunk %.2f). RE-RUN build/build_features2.py once site_ground.glb exists (ray-sampling path)'
              % (P['FALLBACK_GROUND_Y'], P['FALLBACK_GROUND_Y'] - P['VERGE_SINK'], P['VERGE_SINK']))
if os.path.exists(_gp):
    try:
        _gsc = trimesh.load(_gp, force='scene')
        for _n in _gsc.graph.nodes_geometry:
            _T, _g = _gsc.graph[_n]; _m = _gsc.geometry[_g]
            _V = trimesh.transformations.transform_points(np.asarray(_m.vertices, float), _T); _F = np.asarray(_m.faces)
            if len(_F): _GROUND.append((_n.split('|', 1)[-1], _V[_F]))
        GROUND_SRC = ('vertical rays on model/site_ground.glb (build step, %s; numpy barycentric, highest surface below y 1.0); sunk %.2f m'
                      % (time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(_gp))), P['VERGE_SINK']))
    except Exception as ex: print('site_ground.glb unreadable, using the fallback ground', ex); _GROUND = []
def ground_hit(x, z):
    best = None
    for name, tri in _GROUND:
        A, B, C = tri[:, 0], tri[:, 1], tri[:, 2]
        mn = np.minimum(np.minimum(A, B), C); mx = np.maximum(np.maximum(A, B), C)
        s = (mn[:, 0] <= x) & (mx[:, 0] >= x) & (mn[:, 2] <= z) & (mx[:, 2] >= z) & (mn[:, 1] < 1.0)
        if not s.any(): continue
        a, b, c = A[s], B[s], C[s]
        v0 = b[:, [0, 2]] - a[:, [0, 2]]; v1 = c[:, [0, 2]] - a[:, [0, 2]]; v2 = np.array([x, z]) - a[:, [0, 2]]
        den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]; ok = np.abs(den) > 1e-12
        if not ok.any(): continue
        l1 = np.where(ok, (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / np.where(ok, den, 1), -1)
        l2 = np.where(ok, (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / np.where(ok, den, 1), -1)
        inside = ok & (l1 >= -1e-9) & (l2 >= -1e-9) & (l1 + l2 <= 1 + 1e-9)
        if not inside.any(): continue
        y = a[inside, 1] + l1[inside] * (b[inside, 1] - a[inside, 1]) + l2[inside] * (c[inside, 1] - a[inside, 1])
        y = y[y < 1.0]
        if len(y) and (best is None or y.max() > best[0]): best = (float(y.max()), name)
    return best
def ground_y(x, z):
    h = ground_hit(x, z)
    return round(h[0] - P['VERGE_SINK'], 3) if h else round(P['FALLBACK_GROUND_Y'] - P['VERGE_SINK'], 3)

UA, UB = P['U_RANGE']

def road_profile(step=2.5):
    """near-kerb inner edge and far-kerb outer edge (v, m outside the fence line) per u, from the kerb layer of site_ground.glb."""
    tri = [t for name, T in _GROUND if 'kerbs' in name.lower() for t in T]
    polys = [Polygon(t[:, [0, 2]]) for t in tri]
    K = unary_union([q for q in polys if q.is_valid and q.area > 1e-6])
    out = []
    for u in np.arange(UA - 5.0, UB + 5.01, step):
        a, b = to_xz(u, -2.0), to_xz(u, 80.0); ln = LineString([tuple(a), tuple(b)])
        x = ln.intersection(K)
        parts = [g for g in getattr(x, 'geoms', [x]) if not g.is_empty and g.length > 0.05]
        if len(parts) < 2: continue
        vs = sorted([sorted(float(np.linalg.norm(np.asarray(c) - a)) - 2.0 for c in g.coords) for g in parts])
        out.append((u, vs[0][0], vs[-1][-1]))
    return np.array(out)
ROAD_V = road_profile()
if len(ROAD_V) < 10: raise RuntimeError('no road kerbs found in model/site_ground.glb - build it first (build_ground.py)')
kerbN = lambda u: np.interp(u, ROAD_V[:, 0], ROAD_V[:, 1]); kerbF = lambda u: np.interp(u, ROAD_V[:, 0], ROAD_V[:, 2])
bndF = lambda u: kerbF(u) + P['FAR_VERGE_W']
ROAD_U = (float(ROAD_V[0, 0]), float(ROAD_V[-1, 0]))

def gate_u_range():
    """u range of the entrance gate (site_context.glb) - no palm in front of it."""
    p = os.path.join(ROOT, 'model', 'site_context.glb')
    if not os.path.exists(p): return None
    sc = trimesh.load(p, force='scene'); us = []
    for n in sc.graph.nodes_geometry:
        if 'Entrance gate' not in n: continue
        T, gname = sc.graph[n]
        V = trimesh.transformations.transform_points(np.asarray(sc.geometry[gname].vertices), T)[:, [0, 2]]
        us += [to_uv(q)[0] for q in V[::max(1, len(V) // 400)]]
    return (min(us), max(us)) if us else None
GATE_U = gate_u_range()
def in_gate(u):
    return GATE_U is not None and GATE_U[0] - P['GATE_CLEAR'] <= u <= GATE_U[1] + P['GATE_CLEAR']

palms, trees, rejected = [], [], []
gtf = lambda u, v: [round(float(to_xz(u, v)[0]), 3), 0.0, round(float(to_xz(u, v)[1]), 3)]
SRC_ROW = 'procedural row (seeded)'
for u0 in np.arange(UA + P['ROW_PITCH'] / 2, UB, P['ROW_PITCH']):
    u = float(u0 + rng.uniform(-P['ROW_JITTER'], P['ROW_JITTER']))
    v = float(min(rng.uniform(P['PALM_MIN_OUT'], P['PALM_MIN_OUT'] + P['NEAR_ROW_BAND']), kerbN(u) - P['KERB_CLEAR']))
    young = bool(rng.random() < P['YOUNG_SHARE'])
    H = float(rng.uniform(*(P['YOUNG_H_TOTAL'] if young else P['PALM_H_TOTAL'])))
    lean = round(float(rng.normal(0, 0.015)), 3); rot = round(float(rng.uniform(0, 2 * math.pi)), 3)
    if in_gate(u) or not (ROAD_U[0] <= u <= ROAD_U[1]):
        rejected.append(dict(row='near', u=round(u, 2), why='entrance gate' if in_gate(u) else 'no verge')); continue
    palms.append(dict(p=gtf(u, v), h=round(H, 2), h_crown=round(H - P['CROWN_ABOVE_ATTACH'], 2), lean=lean, rot=rot, type='royal',
                      row='near', age='young' if young else 'mature', u=round(u, 2), off=round(v, 2), conf='low (procedural position)', src=SRC_ROW))
for u0 in np.arange(UA + P['ROW_PITCH'], UB, P['ROW_PITCH']):
    u = float(u0 + rng.uniform(-P['ROW_JITTER'], P['ROW_JITTER']))
    lo, hi = float(kerbF(u)) + 0.8, float(bndF(u)) - 1.0
    v = float(rng.uniform(lo, max(lo, hi)))
    H = float(rng.uniform(*P['FAR_H_TOTAL']))
    lean = round(float(rng.normal(0, 0.02)), 3); rot = round(float(rng.uniform(0, 2 * math.pi)), 3)
    if not (ROAD_U[0] <= u <= ROAD_U[1]): rejected.append(dict(row='far', u=round(u, 2), why='no verge')); continue
    palms.append(dict(p=gtf(u, v), h=round(H, 2), h_crown=round(H - P['CROWN_ABOVE_ATTACH'], 2), lean=lean, rot=rot, type='royal', row='far',
                      u=round(u, 2), off=round(v, 2), conf='low (procedural position)', src=SRC_ROW))
nu = sorted(p_['u'] for p_ in palms if p_['row'] == 'near')
gaps = [(a, b) for a, b in zip(nu[:-1], nu[1:]) if b - a >= P['POLY_MIN_GAP'] and not in_gate((a + b) / 2)]
for k in sorted(rng.choice(len(gaps), size=min(P['N_POLY'], len(gaps)), replace=False).tolist()):
    a, b = gaps[k]; u = (a + b) / 2
    v = float(min(P['PALM_MIN_OUT'] + 0.6 + rng.uniform(0, 0.4), kerbN(u) - P['KERB_CLEAR']))
    H = float(rng.uniform(*P['POLY_H']))
    trees.append(dict(p=gtf(u, v), h=round(H, 2), r=round(float(rng.uniform(0.9, 1.25)), 2), rot=round(float(rng.uniform(0, 2 * math.pi)), 3),
                      type='polyalthia', u=round(u, 2), off=round(v, 2), conf='low (procedural position)', src=SRC_ROW))
for t in P['PHOTO_POLY']:
    t = dict(t)
    if t.get('between_palms'):
        nu = sorted(p_['u'] for p_ in palms if p_['row'] == 'near')
        lo_ = [u_ for u_ in nu if u_ <= t['u']]; hi_ = [u_ for u_ in nu if u_ > t['u']]
        if lo_ and hi_: t['u'] = round((lo_[-1] + hi_[0]) / 2, 2); t['src'] += ' (u %.2f = midpoint of the palms at u %.2f / %.2f)' % (t['u'], lo_[-1], hi_[0])
    q = to_xz(t['u'], t['off'])
    if min(np.linalg.norm(q - np.array(o['p'])[[0, 2]]) for o in palms + trees) < 2.2: rejected.append(dict(t, why='too close')); continue
    trees.append(dict(p=gtf(t['u'], t['off']), h=t['h'], r=1.1, rot=round(float(rng.uniform(0, 2 * math.pi)), 3), type='polyalthia', u=t['u'], off=t['off'],
                      conf='low', src='site photo'))
palms.sort(key=lambda p: (p['row'], p['u'])); trees.sort(key=lambda t: t['u'])

for t in palms + trees:
    h = ground_hit(t['p'][0], t['p'][2])
    t['p'][1] = round(h[0] - P['VERGE_SINK'], 3) if h else round(P['FALLBACK_GROUND_Y'] - P['VERGE_SINK'], 3)
    t['ground'] = h[1] if h else 'fallback'

def ring_xz(poly_r3m):
    return Polygon([tuple(q) for q in r3_to_gltf(np.array(poly_r3m))[:, [0, 2]]])
GROUPS = ('VMU01', 'VMU02', 'VMU03', 'VMU04', 'VMU05', 'TRELLIS')
def group_of(name):
    g = name.split('|')[0]
    if g.startswith('VMU01'): g = 'VMU01'
    return g if g in GROUPS else None
def load_scene(f):
    for attempt in range(3):
        try: return trimesh.load(f, force='scene')
        except Exception as ex: print('retry', os.path.basename(f), type(ex).__name__); time.sleep(3)
    return None
foot, vmu_env, glb_used = {}, [], {}
for f in sorted(glob.glob(os.path.join(ROOT, 'model', '*.glb'))):
    if os.path.basename(f).startswith('site_'): continue
    sc = load_scene(f)
    if sc is None: print('SKIP unreadable', f); continue
    glb_used[os.path.basename(f)] = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(f)))
    for n in sc.graph.nodes_geometry:
        T, gname = sc.graph[n]; g = sc.geometry[gname]
        grp = group_of(n)
        if grp is None: continue
        V = trimesh.transformations.transform_points(np.asarray(g.vertices), T)
        h = MultiPoint([tuple(q) for q in V[::max(1, len(V) // 4000), :][:, [0, 2]]]).convex_hull
        if h.geom_type != 'Polygon': h = h.buffer(0.05)
        foot.setdefault(grp, []).append(h)
        vmu_env.append((grp, n, h, float(V[:, 1].min()), float(V[:, 1].max())))
foot = {k: unary_union(v) for k, v in foot.items()}
src_foot = {k: 'GLB node convex hulls (current model/*.glb)' for k in foot}
cg = json.load(open(os.path.join(SOURCES_DIR, 'canopy_candidate_b.json')))
cfull = shape(cg['full']); cpolys = [cfull] if cfull.geom_type == 'Polygon' else list(cfull.geoms)
foot['VMU01'] = unary_union([foot.get('VMU01', Polygon())] + [ring_xz(np.array(pg.exterior.coords)) for pg in cpolys])
src_foot['VMU01'] += ' + canopy outline'
for k in GROUPS:
    if k not in foot: src_foot[k] = 'missing'
bbox_foot = {}
for k, g in foot.items():
    x0, z0, x1, z1 = g.bounds; bbox_foot[k] = box(x0, z0, x1, z1)
VMU_ALL = unary_union(list(foot.values()))
VMU_BBOX = unary_union(list(bbox_foot.values()))

OX0, OX1, OZ0, OZ1, ORES = -75.0, 75.0, -65.0, 85.0, P['OBST_RES']
OW, OH = int(round((OX1 - OX0) / ORES)), int(round((OZ1 - OZ0) / ORES))
occ = np.zeros((OH, OW), np.uint8); occ_lab = np.full((OH, OW), -1, np.int16); occ_names = []
rail = np.zeros((OH, OW), np.uint8)
CTX_SKIP = ()
def rasterise(path, tag, steep_only=False):
    sc = load_scene(path); n_in = 0
    if sc is None: return None
    for n in sc.graph.nodes_geometry:
        T, gname = sc.graph[n]
        if any(gname.startswith(s) or n.startswith(s) for s in CTX_SKIP): continue
        g = sc.geometry[gname]
        if not hasattr(g, 'faces') or len(g.faces) == 0: continue
        V = trimesh.transformations.transform_points(np.asarray(g.vertices), T)
        if V[:, 1].min() >= P['OBST_Y']: continue
        try: V2, F2 = trimesh.intersections.slice_faces_plane(V, np.asarray(g.faces), plane_normal=[0, -1.0, 0], plane_origin=[0, P['OBST_Y'], 0])
        except Exception: V2, F2 = V, np.asarray(g.faces)[(V[np.asarray(g.faces)][:, :, 1].min(1) < P['OBST_Y'])]
        if F2 is None or len(F2) == 0: continue
        tri = V2[F2]
        ptp = np.ptp(tri[:, :, 1], axis=1)
        keep = ~((ptp < 0.02) & (tri[:, :, 1].max(1) < 0.15))
        if steep_only:
            nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); nl = np.linalg.norm(nrm, axis=1) + 1e-12
            keep &= (np.abs(nrm[:, 1]) / nl < 0.5) & (ptp > 0.05)
        tri = tri[keep]
        if not len(tri): continue
        px = (tri[:, :, 0] - OX0) / ORES; pz = (tri[:, :, 2] - OZ0) / ORES
        w = (px.max(1) >= 0) & (px.min(1) < OW) & (pz.max(1) >= 0) & (pz.min(1) < OH)
        if not w.any(): continue
        m = np.zeros((OH, OW), np.uint8)
        for t in np.round(np.stack([px[w], pz[w]], -1)).astype(np.int32): cv2.fillConvexPoly(m, t, 1)
        occ_names.append(tag + gname); occ_lab[m > 0] = len(occ_names) - 1; np.maximum(occ, m, out=occ); n_in += 1
        if tag == 'ground:' and 'rail' in gname.lower(): np.maximum(rail, m, out=rail)
    return n_in
n_ctx_nodes = rasterise(os.path.join(ROOT, 'model', 'site_context.glb'), '')
n_ground_nodes = rasterise(_gp, 'ground:', steep_only=True) if os.path.exists(_gp) else None
free = occ == 0; lab, nlab = ndi.label(free)
sizes = ndi.sum(free, lab, np.arange(1, nlab + 1)) * ORES ** 2
border = set(np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]]).tolist())
small = np.array([i + 1 for i, s in enumerate(sizes) if s < P['OBST_HOLE_MAX'] and (i + 1) not in border])
if len(small):
    fill = np.isin(lab, small); occ[fill] = 1
    idx = ndi.distance_transform_edt(occ_lab < 0, return_distances=False, return_indices=True)
    occ_lab[fill] = occ_lab[idx[0][fill], idx[1][fill]]
DIST = cv2.distanceTransform((occ == 0).astype(np.uint8), cv2.DIST_L2, 5) * ORES
if rail.any(): rail = cv2.dilate(rail, np.ones((21, 21), np.uint8))
def occ_dist(x, z):
    j, i = int((x - OX0) / ORES), int((z - OZ0) / ORES)
    return float(DIST[i, j]) if 0 <= i < OH and 0 <= j < OW else 99.0
def poly_mask(poly):
    x0, z0, x1, z1 = poly.bounds
    j0, i0 = max(0, int((x0 - OX0) / ORES) - 1), max(0, int((z0 - OZ0) / ORES) - 1)
    j1, i1 = min(OW, int((x1 - OX0) / ORES) + 2), min(OH, int((z1 - OZ0) / ORES) + 2)
    if j1 <= j0 or i1 <= i0: return None
    m = np.zeros((i1 - i0, j1 - j0), np.uint8)
    c = np.array(poly.exterior.coords); pts = np.round(np.c_[(c[:, 0] - OX0) / ORES - j0, (c[:, 1] - OZ0) / ORES - i0]).astype(np.int32)
    cv2.fillPoly(m, [pts], 1)
    return (slice(i0, i1), slice(j0, j1)), m.astype(bool)
def poly_hits(poly, cars_too=False):
    r = poly_mask(poly)
    if r is None: return []
    sl, m = r; o = (occ[sl] > 0) & m
    names = sorted({occ_names[k] for k in np.unique(occ_lab[sl][o]) if k >= 0}) if o.any() else []
    if cars_too and (rail[sl][m] > 0).any(): names.append('crane rail keep-out (site_ground.glb)')
    return names
sc_ctx = load_scene(os.path.join(ROOT, 'model', 'site_context.glb'))
deck, ctx_env, deck_v, ctx_grp = [], [], [], {}
for n in sc_ctx.graph.nodes_geometry:
    T, gname = sc_ctx.graph[n]
    V = trimesh.transformations.transform_points(np.asarray(sc_ctx.geometry[gname].vertices), T)
    ctx_grp.setdefault(gname.split('|')[0], []).append(V)
    if 'Deck' in gname:
        deck.append(MultiPoint([tuple(q) for q in V[:, [0, 2]]]).convex_hull); deck_v.append(V)
DECK = unary_union(deck) if deck else Polygon()
ctx_grp = {k: (np.vstack(v).min(0), np.vstack(v).max(0)) for k, v in ctx_grp.items()}
if deck_v:
    DV = np.vstack(deck_v); DECK_TOP = float(DV[:, 1].max()); dc = DV[:, [0, 2]].mean(0); dd = DV[:, [0, 2]] - dc
    _ang = 0.5 * math.atan2(2 * (dd[:, 0] * dd[:, 1]).sum(), (dd[:, 0] ** 2).sum() - (dd[:, 1] ** 2).sum())
    DAX = np.array([math.cos(_ang), math.sin(_ang)]); DNX = np.array([-DAX[1], DAX[0]])
    DT = dd @ DAX; DW = dd @ DNX; DT0, DT1, DW0, DW1 = DT.min(), DT.max(), DW.min(), DW.max()
    deck_at = lambda f, off=0.0: dc + DAX * (DT0 + f * (DT1 - DT0)) + DNX * ((DW0 + DW1) / 2 + off)
else:
    DECK_TOP, deck_at = 3.0, None

dsw = np.array([-0.9377, -0.3476]); dsw /= np.linalg.norm(dsw); SW = SE + LOT_SOUTH_LEN_M * dsw
NX = NC + dN * ((-155.714 - NC[1]) / dN[1])
YARD = Polygon([tuple(q) for q in (SW, SE, K1, K2, NC, NX)] + [(-200.0, -155.714)]).buffer(0)

def lcg(seed):
    s = [seed]
    def r():
        s[0] = (s[0] * 16807) % 2147483647; return s[0] / 2147483647
    return r
def js_round(x): return math.floor(x + 0.5)
def nrm(v): return v / max(np.linalg.norm(v), 1e-12)
def crown_local(seed, F=VPALM):
    r = lcg(seed); C = np.array([0.0, F['shaftLen'] - 0.05, 0.0]); up = np.array([0.0, 1.0, 0.0]); rad = math.radians
    nF = js_round(F['count'][0] + r() * (F['count'][1] - F['count'][0])); seg = 12
    nOld = 1 + (1 if r() < 0.5 else 0); out = []
    for f in range(nF + nOld):
        isOld = f >= nF; age = 1 if isOld else f / max(1, nF - 1)
        az = f * 2.39996 + r() * 0.4
        if isOld: e0 = -rad(58 + 14 * r()); tipY = -(2.6 + 0.8 * r())
        elif age < 0.28: e0 = rad(48 + 14 * r()); tipY = 0.6 + 0.9 * r()
        elif age < 0.7: e0 = rad(18 + 16 * r()); tipY = -(0.3 + 0.7 * r())
        else: e0 = -rad(15 + 30 * r()); tipY = -(0.9 + 1.3 * r())
        Lf = (F['len'][0] + r() * (F['len'][1] - F['len'][0])) * 1.18
        d = max(0.0, math.sin(e0) - tipY / Lf)
        dirH = np.array([math.cos(az), 0.0, math.sin(az)])
        rach = lambda t: C + dirH * (Lf * t * math.cos(e0) * (1 - 0.1 * t)) + up * (Lf * t * math.sin(e0) - d * Lf * t * t)
        Wl = F['leaflet'][0] + r() * (F['leaflet'][1] - F['leaflet'][0])
        if isOld: r()
        r()
        for side in (-1, 1):
            for layer in (0, 1):
                phi = rad(6 + 12 * r()) if layer else rad(F['droop'][0] + r() * (F['droop'][1] - F['droop'][0]) + (20 if isOld else 0))
                for k in range(seg + 1):
                    t = k / seg; Pt = rach(t); Tt = nrm(rach(min(1, t + 0.02)) - rach(max(0, t - 0.02)))
                    Sr = np.cross(Tt, up)
                    if Sr @ Sr < 1e-6: Sr = np.array([-dirH[2], 0.0, dirH[0]])
                    Sr = nrm(Sr); upL = nrm(np.cross(Sr, Tt))
                    leaf = nrm(Sr * side * math.cos(phi) + upL * (-math.sin(phi)) + Tt * 0.3)
                    W = Wl * (0.78 if layer else 1) * math.sin(math.pi * (0.05 + 0.9 * t)) ** 0.65
                    out.append(Pt); out.append(Pt + leaf * W)
    return np.array(out)
CROWNS = [crown_local(101 + 53 * k) for k in range(4)]
def palm_world(p, i, rot=None, scale_mul=1.0):
    rot = p['rot'] if rot is None else rot; lean = p.get('lean', 0.0)
    hAttach = p['h_crown']; trunkH = max(1.2, hAttach - VPALM['shaftLen']); sc2 = min(1.2, max(0.85, p['h'] / 12.5)) * scale_mul
    q = Rotation.from_euler('XYZ', [lean, rot, lean * 0.7]); top = np.array(p['p']) + q.apply([0, trunkH, 0])
    q2 = Rotation.from_euler('XYZ', [lean * 0.5, rot, lean * 0.35])
    return top + q2.apply(CROWNS[i % 4] * sc2)
palm_xz = np.array([[p['p'][0], p['p'][2]] for p in palms])
def near_verge(hull, reach=9.0):
    return hull.distance(MultiPoint([tuple(q) for q in palm_xz])) < reach
crown_obs = [(g + '|' + n.split('|', 1)[-1], hh.buffer(P['CROWN_CLEAR']), y0, y1) for g, n, hh, y0, y1 in vmu_env if near_verge(hh)]
for g in GROUPS:
    E = [(hh, y0, y1) for gg, n, hh, y0, y1 in vmu_env if gg == g]
    if not E: continue
    bx = unary_union([hh for hh, _, _ in E]).bounds; gb = box(*bx)
    if near_verge(gb): crown_obs.append((g + ' (group bounding box)', gb.buffer(P['CROWN_CLEAR'], join_style=2), min(e[1] for e in E), max(e[2] for e in E)))
for n in sc_ctx.graph.nodes_geometry:
    T, gname = sc_ctx.graph[n]
    if any(gname.startswith(s) for s in CTX_SKIP + ('Boundary hoarding',)): continue
    g = sc_ctx.geometry[gname]; V = trimesh.transformations.transform_points(np.asarray(g.vertices), T)
    if not near_verge(box(V[:, 0].min(), V[:, 2].min(), V[:, 0].max(), V[:, 2].max())): continue
    m = trimesh.Trimesh(V, np.asarray(g.faces), process=False)
    for part in m.split(only_watertight=False):
        hv = part.vertices; hh = MultiPoint([tuple(q) for q in hv[:, [0, 2]]]).convex_hull
        if hh.geom_type != 'Polygon': hh = hh.buffer(0.05)
        if near_verge(hh): crown_obs.append((gname, hh.buffer(P['CROWN_CLEAR']), float(hv[:, 1].min()), float(hv[:, 1].max())))
def crown_clash(W):
    hits = {}
    for name, hb, y0, y1 in crown_obs:
        x0, z0, x1, z1 = hb.bounds
        sel = (W[:, 0] >= x0) & (W[:, 0] <= x1) & (W[:, 2] >= z0) & (W[:, 2] <= z1) & (W[:, 1] >= y0 - P['CROWN_CLEAR']) & (W[:, 1] <= y1 + P['CROWN_CLEAR'])
        if sel.any():
            k = int(shapely.contains_xy(hb, W[sel, 0], W[sel, 2]).sum())
            if k: hits[name] = hits.get(name, 0) + k
    low = W[:, 1] < 2.5 + P['CROWN_CLEAR']
    if low.any():
        k = int((shapely.distance(FENCE_LS, shapely.points(W[low][:, [0, 2]])) < 0.15 + P['CROWN_CLEAR']).sum())
        if k: hits['Boundary hoarding (DXF fence line, 2.4 m)'] = k
    return hits
def crown_min_clear(W):
    best = (99.0, None)
    for name, hb, y0, y1 in crown_obs:
        sel = (W[:, 1] >= y0) & (W[:, 1] <= y1)
        if sel.any():
            d = float(shapely.distance(hb, shapely.points(W[sel][:, [0, 2]])).min()) + P['CROWN_CLEAR']
            if d < best[0]: best = (d, name)
    return best
crown_log = []
for i, p in enumerate(palms):
    W = palm_world(p, i); hits = crown_clash(W)
    if not hits: continue
    ent = dict(i=i, u=p['u'], row=p['row'], h=p['h'], rot0=p['rot'], hits0=hits)
    steps = int(round(360 / P['ROT_STEP_DEG'])); cands = []
    for k in range(1, steps):
        dr = math.radians(P['ROT_STEP_DEG']) * (k if k <= steps // 2 else k - steps)
        rr = (p['rot'] + dr) % (2 * math.pi); hh = crown_clash(palm_world(p, i, rot=rr)); cands.append((sum(hh.values()), abs(dr), rr, hh))
    cands.sort(key=lambda c: (c[0], c[1]))
    n_best, dr_best, rr, hh = cands[0]
    if n_best < sum(hits.values()):
        p['rot'] = round(rr, 3); ent.update(rot=p['rot'], rot_change_deg=round(math.degrees(dr_best), 1), hits=hh)
        p['crown_note'] = 'rot chosen by build step crown-clearance search (fronds on the %s side trained/pruned in reality); seeded rot %.3f' % (
            ', '.join(sorted(hits)), ent['rot0'])
    if n_best:
        sm = 1.0
        while sm > 0.5 and crown_clash(palm_world(p, i, scale_mul=sm)): sm -= 0.02
        p['clash'] = dict(objects=hh, frond_vertices=n_best, note='')
        p['frond_scale'] = round(sm, 2); ent.update(frond_scale=p['frond_scale'])
    ent['min_clear_after'] = crown_min_clear(palm_world(p, i))
    crown_log.append(ent)

def bl_crown_pts(xz, y0, H, R):
    b0 = 2.0; pts = []
    for yy in np.linspace(0.1, 1.0, 12):
        pr = math.sqrt(max(0.0, 1 - ((yy - 0.55) / 0.47) ** 2)) * 1.05 * R
        for a in np.linspace(0, 2 * math.pi, 24, endpoint=False):
            pts.append([xz[0] + pr * math.cos(a), y0 + b0 + yy * (H - b0), xz[1] + pr * math.sin(a)])
    return np.array(pts)
broadleaf, bl_log = [], []
for spec in P['BROADLEAF']:
    best = None
    for u in np.arange(spec['u_range'][0], spec['u_range'][1] + 0.01, 0.5):
        for v in np.arange(P['PALM_MIN_OUT'] + 0.6, float(kerbN(u)) - 1.0 + 0.01, 0.25):
            xz = to_xz(u, v); gap = min(np.linalg.norm(xz - np.array([o['p'][0], o['p'][2]])) for o in palms + trees)
            if gap < spec['min_trunk_gap']: continue
            y0 = ground_y(float(xz[0]), float(xz[1]))
            if crown_clash(bl_crown_pts(xz, y0, spec['h'], spec['r'])): continue
            if best is None or gap > best[0]: best = (gap, u, v, xz, y0)
    if best is None: bl_log.append(dict(spec=spec['src'][:60], placed=False, why='no clash-free spot')); continue
    gap, u, v, xz, y0 = best
    _gh = ground_hit(float(xz[0]), float(xz[1]))
    broadleaf.append(dict(p=[round(float(xz[0]), 3), y0, round(float(xz[1]), 3)], h=spec['h'], r=spec['r'], rot=round(float(rng.uniform(0, 2 * math.pi)), 3),
                          ground=_gh[1] if _gh else 'fallback',
                          type='broadleaf', u=round(float(u), 2), off=round(float(v), 2), conf='low', src=''))
    bl_log.append(dict(placed=True, u=round(float(u), 2), off=round(float(v), 2), min_trunk_gap=round(float(gap), 2)))

old = json.load(open(os.path.join(SCRATCH_IN, 'site_features_before.json'), encoding='utf-8')) if os.path.exists(os.path.join(SCRATCH_IN, 'site_features_before.json')) \
    else json.load(open(os.path.join(ROOT, 'model', 'site_features.json'), encoding='utf-8'))
axis_x = r3_dir_to_gltf(np.array([1.0, 0]))[0]; axis_y = r3_dir_to_gltf(np.array([0, 1.0]))[0]
def car_yaw(c): return math.atan2(-axis_x[1], axis_x[0]) + c['rot']
def car_poly(c, pad=0.15):
    yaw = car_yaw(c); body = box(-2.25 - pad, -0.9 - pad, 2.25 + pad, 0.9 + pad)
    ca, sa = math.cos(yaw), math.sin(yaw)
    return Polygon([(c['p'][0] + x * ca + z * sa, c['p'][2] - x * sa + z * ca) for x, z in body.exterior.coords])
def car_conflicts(c, placed):
    cp = car_poly(c); hit = poly_hits(cp, cars_too=True) + [k for k, g in foot.items() if cp.intersects(g)]
    if cp.intersects(DECK): hit.append('platform deck (+3.0)')
    if not YARD.contains(cp): hit.append('outside the lot')
    if any(cp.intersects(car_poly(o)) for o in placed): hit.append('car')
    return hit
cars, cars_dropped, cars_nudged = [], [], []
for c in old['cars']:
    hit = car_conflicts(c, cars)
    if not hit: cars.append(c); continue
    yaw = car_yaw(c); ax = np.array([math.cos(yaw), -math.sin(yaw)]); ok_c = None
    for d in P['CAR_NUDGE']:
        cc = dict(c); cc['p'] = [round(c['p'][0] + d * ax[0], 3), c['p'][1], round(c['p'][2] + d * ax[1], 3)]
        if not car_conflicts(cc, cars): ok_c = cc; break
    if ok_c: cars.append(ok_c); cars_nudged.append(dict(old=c['p'], new=ok_c['p'], why=hit)); continue
    cars_dropped.append(dict(c, why=hit))

people, moved, pending = [], [], []
CAR_U = unary_union([car_poly(c) for c in cars])
def ok(pt, on_deck=False):
    q = Point(pt)
    if on_deck: return DECK.buffer(-0.4).contains(q) and all(q.distance(Point(o['p'][0], o['p'][2])) > 0.8 for o in people + pending)
    return (not VMU_ALL.buffer(P['PERSON_CLEAR']).contains(q)) and (not VMU_BBOX.buffer(0.3).contains(q)) and occ_dist(*pt) > P['PERSON_CTX_CLEAR'] \
        and (not CAR_U.buffer(0.4).contains(q)) and (not DECK.buffer(0.3).contains(q)) and YARD.contains(q) \
        and all(q.distance(Point(o['p'][0], o['p'][2])) > 0.8 for o in people + pending)
_v01 = [hh for g, n, hh, y0, y1 in vmu_env if g == 'VMU01' and not n.startswith('VMU01_CANOPY')]
TC01 = np.array(unary_union(_v01).centroid.coords[0]) if _v01 else np.zeros(2)
dropped_people = []
deck_off = [i for i, pp in enumerate(old['people']) if pp['p'][1] > 1.0 and not (DECK.buffer(-0.4).contains(Point(pp['p'][0], pp['p'][2])))]
deck_slot = {i: k for k, i in enumerate(deck_off)}
for ip, pp in enumerate(old['people']):
    pending = old['people'][ip + 1:]
    on_deck = pp['p'][1] > 1.0
    xz = (pp['p'][0], pp['p'][2])
    if ok(xz, on_deck): people.append(pp); continue
    best = None
    if on_deck and deck_at is not None:
        k, nd = deck_slot.get(ip, 0), max(1, len(deck_off))
        f0 = 0.5 if nd == 1 else 0.35 + 0.3 * k / (nd - 1); w = DW1 - DW0
        for f in [f0] + [f0 + s * d for d in np.arange(0.02, 0.5, 0.02) for s in (1, -1)]:
            if not 0.08 <= f <= 0.92: continue
            for off in ((0.35 if k % 2 else -0.35) * min(1, w / 2.6), 0.0, (-0.35 if k % 2 else 0.35) * min(1, w / 2.6)):
                cand = tuple(deck_at(f, off))
                if ok(cand, True): best = cand; break
            if best: break
    else:
        for r in np.arange(0.5, 12.01, 0.25):
            for a in np.linspace(0, 2 * math.pi, int(12 + r * 8), endpoint=False):
                cand = (xz[0] + r * math.cos(a), xz[1] + r * math.sin(a))
                if ok(cand, on_deck): best = cand; break
            if best: break
    if best is None: dropped_people.append(dict(pp, why='no free spot')); continue
    npp = dict(pp); npp['p'] = [round(float(best[0]), 3), round(DECK_TOP, 3) if on_deck else 0.0, round(float(best[1]), 3)]
    if on_deck:
        npp['rot'] = round(math.atan2(TC01[0] - best[0], TC01[1] - best[1]), 3)
        npp['note'] = ''
    moved.append(dict(old=pp['p'], new=npp['p'], dist=round(math.dist(xz, best), 2), deck=on_deck)); people.append(npp)

labels = old['labels']
labels['VMU01_EXT'] = dict(zh='VMU-01 雨棚延伸（新增；顶板 Mouse Grey，边带 / 封边 / 斜边 / 底板 T02）',
                           en='VMU-01 canopy extension (new; top Mouse Grey, edge band / fascia / chamfer / soffit T02)', p=None)
labels['TRELLIS'] = dict(zh='Trellis 地面样板（拉弯圆弧吊顶格栅）', en='Trellis ground mock-up (curved ceiling grille)')
road_mid = to_xz(40.0, float(np.mean([kerbN(40.0), kerbF(40.0)])))
ROAD_LABEL = '主路'
ctx_labels = [dict(L) for L in old['ctx_labels'] if L['zh'] != ROAD_LABEL and not L['zh'].startswith('北侧厂房')]
def grp_anchor(key, dy=1.0, y=None):
    if key not in ctx_grp: return None
    lo, hi = ctx_grp[key]; return [round(float((lo[0] + hi[0]) / 2), 3), round(float(hi[1] + dy if y is None else y), 3), round(float((lo[2] + hi[2]) / 2), 3)]
lab_moves = []
for L in ctx_labels:
    newp = None
    if L['zh'].startswith('集装箱'):
        a, b2 = ctx_grp.get('Containers + site office'), ctx_grp.get('Temporary steel viewing platform')
        if a and b2: newp = [round(float((min(a[0][0], b2[0][0]) + max(a[1][0], b2[1][0])) / 2), 3), 5.0, round(float((min(a[0][2], b2[0][2]) + max(a[1][2], b2[1][2])) / 2), 3)]
    elif L['zh'].startswith('材料堆放'): newp = grp_anchor('Material storage (stillages)', y=2.0)
    elif L['zh'].startswith('临时停车') and cars:
        cm = np.mean([[c['p'][0], c['p'][2]] for c in cars], 0)
        cc = sorted([c for c in cars if DECK.distance(Point(c['p'][0], c['p'][2])) > 2.0] or cars, key=lambda c: math.dist(cm, (c['p'][0], c['p'][2])))[0]
        newp = [round(float(cc['p'][0]), 3), 0.5, round(float(cc['p'][2]), 3)]
    if newp and math.dist(newp[::2], L['p'][::2]) > 2.0: lab_moves.append(dict(zh=L['zh'], old=L['p'], new=newp)); L['p'] = newp
ctx_labels.append(dict(zh=ROAD_LABEL, p=[round(float(road_mid[0]), 3), 1.5, round(float(road_mid[1]), 3)]))
_nb = grp_anchor('Factory 2 north block', dy=1.5)
ctx_labels.append(dict(zh='北侧厂房（施工中：裸 RC 框架 + 黄色钢结构屋面层）', p=_nb or [-76.4, 31.0, -71.6]))

lot = [[float(round(q[0])), 0.0, float(round(q[1]))] for q in (SW, SE, K1, K2, NC)]   # published: rounded to 1 m, no extrapolated vertex

out = dict(
    palms=palms, palm_type='Roystonea regia (royal palm); see model/vegetation_notes.json', trees=trees, broadleaf=broadleaf, shrubs=[],
    people=people, cars=cars, axis_x=axis_x.round(4).tolist(), axis_y=axis_y.round(4).tolist(), labels=labels, ctx_labels=ctx_labels,
    lot_boundary=lot,
    meta=dict(
        script='build/build_features2.py', frame='glTF x=E, y=Up, z=-N; y=0 yard slab top',
        palm_h='h = overall palm height above ground (tip of the upper fronds / spear); h_crown = h - %.1f m = frond attachment (top of crownshaft); viewer.js (build step) builds trunk = h_crown - 1.6' % P['CROWN_ABOVE_ATTACH'],
        palm_order='palms[] order sets the viewer crown variant (i % 4); the crown-clearance rot search assumes this order - keep it',
        vegetation_source='procedural seeded rows along the road verges of site_ground.glb (see the module docstring of build/build_features2.py); '
                          'geometry notes in model/vegetation_notes.json',
        broadleaf='1 tree placed from site photos; conf low; viewer.js renders type broadleaf as a round crown',
        shrubs='none (no shrub balls in the site photos) - list left empty',
        lot_boundary='lot line rounded to 1 m: SW, SE, K1, K2, north clip (view placement only)',
        tree_base_y=GROUND_SRC,
        obstacles='people/cars tested against a plan raster of every site_context.glb node below %.1f m%s; VMU footprints = hulls of the current VMU GLB nodes' % (
            P['OBST_Y'], ' + site_ground.glb steep faces' if n_ground_nodes else ''),
        inputs_mtime=dict(glb_used, **{'site_context.glb': time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(os.path.join(ROOT, 'model', 'site_context.glb'))))}),
        params=P,
        ground='tree bases on the site_ground.glb surface (palms[].ground / trees[].ground = hit layer; all must be a road verge), '
               'near-row trunks >= PALM_MIN_OUT outside the survey fence line'),
)
json.dump(out, open(os.path.join(ROOT, 'model', 'site_features.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)

FROND, TRUNK, SHAFT, OLD, DEAD = '#4C5A34', '#9A988E', '#667A40', '#6B6A45', '#8A7A55'
notes = dict(
    about='Geometry + material parameters for instanced vegetation in viewer.js. Positions: model/site_features.json palms[] / '
          'trees[] / broadleaf[]. Royal palm row just outside the hoarding plus a far-verge row; a few columnar Polyalthia '
          'longifolia; one broad-leaf tree; no shrub balls (shrubs = []).',
    viewer_keys='viewer.js vegParams() reads: royal_palm.fronds{colour,count,length,leaflets("a-b m long", "drooping at a-b deg"),colour_variation(hex old, hex dead),spear_leaf{length,width}}, '
                'royal_palm.trunk{radius_base,radius_top,bulge{radius,at_fraction},flare{radius},colour}, royal_palm.crownshaft{colour,roughness,length,radius_base,radius_top}, '
                'polyalthia.crown{colour,roughness,bottom}, polyalthia.trunk{colour,radius}. Other keys are documentation.',
    units='m', frame='instance origin = trunk base on the ground; positions and heights from site_features.json',
    positions_note='',
    royal_palm=dict(
        species='Roystonea regia', json_key='palms (type royal; row near|far; age mature|young)',
        h_meaning='overall palm height to the tip of the upper fronds / spear leaf, JSON palms[].h; JSON h_crown = frond attachment height',
        h_is_trunk=False,
        heights_m=dict(near_row=list(P['PALM_H_TOTAL']), near_row_young=list(P['YOUNG_H_TOTAL']), far_row=list(P['FAR_H_TOTAL'])),
        fronds=dict(colour=FROND, count=list(VPALM['count']), length=list(VPALM['len']),
                    leaflets='pinnate, %.1f-%.1f m long, drooping at %d-%d deg below the rachis, in 2-4 planes (plumose, not a flat blade)' % (
                        VPALM['leaflet'] + tuple(int(x) for x in VPALM['droop'])),
                    colour_variation='old %s, dead %s; +-8 %% lightness per frond' % (OLD, DEAD),
                    spear_leaf=dict(length=1.4, width=0.14, elevation_deg=85),
                    material='CTX_PALM_FROND (%s, rough 0.7, double-sided, alpha-tested leaflets)' % FROND),
        trunk=dict(colour=TRUNK, material='CTX_PALM_TRUNK (%s, rough 0.9, metal 0)' % TRUNK, length='h_crown - crownshaft length',
                   radius_base=0.26, radius_top=0.21, flare=dict(height=0.6, radius=0.34), bulge=dict(at_fraction=0.45, radius=0.28, note=''),
                   texture='smooth pale grey; faint horizontal leaf-scar rings every 0.10-0.15 m; darker grey-brown stain in the lowest 1 m', radial_segments=12),
        crownshaft=dict(colour=SHAFT, roughness=0.45, length=VPALM['shaftLen'], radius_base=0.235, radius_top=0.20,
                        note=''),
        frond_geometry=dict(note='', count=list(VPALM['count']), length=list(VPALM['len']),
                            attach_height='h_crown (= h - %.1f)' % P['CROWN_ABOVE_ATTACH'], rachis_elevation_deg=dict(upper=[50, 68], middle=[20, 35], lower=[-20, -50]),
                            droop='quadratic along the rachis: tip 0.2 m above (young) to 1.5-2.2 m below (old) the attachment height',
                            phyllotaxis='golden angle 137.5 deg', old_fronds='1-2 lowest fronds older %s, occasional dead frond %s hanging along the shaft' % (OLD, DEAD)),
        silhouette='crown diameter 6.5-8 m (viewer scales the crown by clamp(h/12.5, 0.85, 1.2)), crown depth ~4 m; from the yard the fronds overhang the 2.4 m hoarding (photo, photo, photo)',
        per_instance='optional palms[] keys written by build step: crown_note (rot chosen to clear a VMU), clash + frond_scale (only if no rotation clears; frond_scale not read by viewer.js yet)',
        lod='beyond ~150 m: 2 crossed billboards; cast shadows on'),
    polyalthia=dict(
        species='Polyalthia longifolia var. pendula (Indian mast tree)', json_key='trees (type polyalthia)', heights_m=list(P['POLY_H']),
        form='narrow column / slender cone, drooping branchlets from 0.5-1.0 m above ground to the tip; trunk hidden',
        crown=dict(colour='#34482B', core_colour='#26341F', radius='JSON r (0.9-1.25 m)', bottom=0.6, top='h',
                   profile='r at t<0.35 of the height, then tapering linearly to 0.25 r at the tip',
                   roughness=0.65, note=''),
        trunk=dict(colour='#5E5A50', radius=0.08, visible_height=0.6)),
    broadleaf=dict(
        species='unknown broad-leaf roadside tree (site photos)', json_key='broadleaf (type broadleaf)',
        form='round dense crown from ~2 m to h, crown radius JSON r; viewer.js renders it with the Polyalthia foliage colour (no own colour key)',
        crown=dict(colour='#3E5230', note=''), trunk=dict(colour='#5E5A50', radius=0.16)),
    removed=dict(shrubs='empty list: no clipped shrub balls in any photo (site photos G: grass and weeds only)'),
    colours_from='',
)
json.dump(notes, open(os.path.join(ROOT, 'model', 'vegetation_notes.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

def person_clear(pp):
    q = Point(pp['p'][0], pp['p'][2])
    return dict(p=pp['p'], vmu_outline=round(VMU_ALL.distance(q), 2), vmu_bbox=round(VMU_BBOX.distance(q), 2),
                ctx=round(occ_dist(pp['p'][0], pp['p'][2]), 2) if pp['p'][1] < 1 else 'deck', on_deck=bool(DECK.contains(q)) if pp['p'][1] > 1 else None)
near_off = [p['off'] for p in palms if p['row'] == 'near']
rep = dict(
    runtime_s=round(time.time() - T0, 1),
    n_palms_near=sum(p['row'] == 'near' for p in palms), n_palms_young=sum(p.get('age') == 'young' for p in palms),
    n_palms_far=sum(p['row'] == 'far' for p in palms), n_trees=len(trees), n_broadleaf=len(broadleaf), poly_rejected=rejected,
    heights=dict(near_mature=[min(p['h'] for p in palms if p.get('age') == 'mature'), max(p['h'] for p in palms if p.get('age') == 'mature')],
                 near_young=[p['h'] for p in palms if p.get('age') == 'young'], young_u=[p['u'] for p in palms if p.get('age') == 'young'],
                 far=[min(p['h'] for p in palms if p['row'] == 'far'), max(p['h'] for p in palms if p['row'] == 'far')],
                 poly=[min(t['h'] for t in trees), max(t['h'] for t in trees)]),
    near_spacing_m=np.round(np.diff(sorted(p['u'] for p in palms if p['row'] == 'near')), 2).tolist(),
    near_off_m=[min(near_off), max(near_off)],
    near_trunk_to_fence_line=round(float(min(FENCE_LS.distance(Point(p['p'][0], p['p'][2])) for p in palms if p['row'] == 'near')), 2),
    ground_layers={k: sum(1 for t_ in palms + trees + broadleaf if t_.get('ground') == k) for k in sorted({t_.get('ground') for t_ in palms + trees + broadleaf})},
    not_on_verge=[dict(type=t_['type'], row=t_.get('row'), u=t_.get('u'), ground=t_.get('ground')) for t_ in palms + trees + broadleaf if 'verge' not in str(t_.get('ground'))],
    gate_u=GATE_U, rows_rejected=rejected,
    tree_base_y=sorted({t['p'][1] for t in palms + trees + broadleaf}),
    crown_clearance=crown_log, crown_obstacles=len(crown_obs), broadleaf_log=bl_log,
    obstacle_raster=dict(nodes=n_ctx_nodes, ground_nodes=n_ground_nodes, res=ORES, window=[OX0, OX1, OZ0, OZ1], filled_pockets=int(len(small))),
    people_moved=moved, people_dropped=dropped_people, ctx_label_moves=lab_moves, people_clearance=[person_clear(pp) for pp in people], cars_dropped=cars_dropped, cars_nudged=cars_nudged,
    n_people=len(people), n_cars=len(cars), footprint_src=src_foot,
    footprint_bounds={k: [round(x, 2) for x in g.bounds] for k, g in foot.items()},
    road_profile_u_near_far=ROAD_V.round(2).tolist(),
)
json.dump(rep, open(os.path.join(SCRATCH, 'build_report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
np.save(os.path.join(SCRATCH, 'r2', 'occ.npy'), occ)
print('palms near/young/far', rep['n_palms_near'], rep['n_palms_young'], rep['n_palms_far'], 'trees', len(trees), 'broadleaf', len(broadleaf),
      'people', len(people), 'moved', len(moved), 'cars', len(cars), 'nudged', len(cars_nudged), 'dropped', len(cars_dropped),
      'crown fixes', len(crown_log), 'runtime', rep['runtime_s'], 's')
