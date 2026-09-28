"""Builds model/vmu02.glb: VMU-02, the enclosure sample with auto sliding doors - every element of the private shop-drawing
spec (platform, plywood floor, IGU and door-leaf glass, joints and seals, exterior bands and caps, interior covers,
ribbed GMS walls and roof with fall, SHS columns, roof framing, access steps) in the local frame of the spec (mm),
placed on the layout plan by a least-squares fit of ten drawn lines. Options: MOCKUP_VMU02_* environment variables.
Needs the private element spec and the layout-plan segments in SOURCES_DIR / build/.
"""
import os, sys, json, math
import numpy as np
SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from gltfw import GLB
from materials_lib import mat, node_extras

SPEC_PATH = os.path.join(SOURCES_DIR, 'vmu02_spec.json')
L2G_PATH = os.path.join(SOURCES_DIR, 'vmu02_local_to_gltf.json')
R3_SEGS = os.path.join(HERE, 'r3_segs.npy')
OUT = os.environ.get('MOCKUP_VMU02_OUT', os.path.join(ROOT, 'model', 'vmu02.glb'))

PLACEMENT = os.environ.get('MOCKUP_VMU02_PLACEMENT', 'R3')
ROOF_FALL = float(os.environ.get('MOCKUP_VMU02_ROOF_FALL', '0.03'))
END_BAND_TOP = os.environ.get('MOCKUP_VMU02_END_BAND', 'level')
GLASS_SIZE = os.environ.get('MOCKUP_VMU02_GLASS', 'physical')
GLASS_GEOM = os.environ.get('MOCKUP_VMU02_GLASS_GEOM', 'sheet')
DOOR_OPEN = float(os.environ.get('MOCKUP_VMU02_DOOR_OPEN', '0.0'))
STEPS = os.environ.get('MOCKUP_VMU02_STEPS', '1') != '0'
assert PLACEMENT in ('R3', 'R3_flip180', 'spec') and END_BAND_TOP in ('level', 'sloped') and GLASS_SIZE in ('physical', 'unit')
assert GLASS_GEOM in ('sheet', 'solid')
assert 0.0 <= DOOR_OPEN <= 1.0 and 0.0 <= ROOF_FALL < 0.2

GROUP = 'VMU02'
SD = 'SD=shop document'

SPEC = json.load(open(SPEC_PATH, encoding='utf-8'))
E = {e['id']: e for e in SPEC['elements']}
assert len(E) == 66, len(E)
FR = SPEC['frame']
GX, GY = float(FR['grid_1_2']), float(FR['grid_A_B'])
FFL = float(FR['FFL'])
YA = FR['outer_faces']['sideA_y']
YB = FR['outer_faces']['sideB_y']
XE1, XE2 = FR['outer_faces']['end1_x'], FR['outer_faces']['end2_x']
BASE = FR['base_outline']
ZTOP = FR['roof_top']['sideA']
ZBB = FR['roof_top']['sideB']
PROUD = 1.5
CAP = 88.0
Y_BBAND = GY + 158.0
YB_GLASS = GY + 158.0
DYB = YB_GLASS - YB
EAVE = 250.0
X_EB1, X_EB2 = -158.0 - PROUD, GX + 158.0 + PROUD
X_RF1, X_RF2 = -70.0, GX + 70.0
HJ = 12.0
T_IGU = 33.5
T_LEAF = 17.52
LEAF_D = 208.0
RIB_WALL = dict(pitch=210.0, base=50.0, top=25.0, depth=25.0)
RIB_ROOF = dict(pitch=210.0, base=70.0, top=35.0, depth=25.0)
T_SHEET = 1.5
ZU = lambda y: ZBB + ROOF_FALL * (Y_BBAND - np.asarray(y, float))

S_R3 = 0.20936562216484053
R3_LINES = [
    ((642.000, 647.280, 642.120, 712.080), 'y', 0.0, 'grid A'),
    ((615.240, 647.400, 615.360, 712.200), 'y', GY, 'grid B'),
    ((647.280, 651.480, 612.480, 651.480), 'x', GX, 'grid 2'),
    ((647.280, 708.960, 612.600, 708.960), 'x', 0.0, 'grid 1'),
    ((642.840, 709.680, 642.840, 650.640), 'y', -158.0, 'side-A band face (158)'),
    ((642.360, 651.120, 642.480, 709.320), 'y', -158.0 + CAP, 'side-A cap inner edge (70)'),
    ((613.440, 709.320, 613.320, 651.120), 'y', Y_BBAND + EAVE, 'side-B eave edge (158+250)'),
    ((614.520, 651.120, 614.640, 709.320), 'y', Y_BBAND, 'side-B band face (158)'),
    ((642.360, 651.120, 613.320, 651.120), 'x', X_RF2, 'end-2 cap inner edge (70)'),
    ((642.480, 709.320, 613.440, 709.320), 'x', X_RF1, 'end-1 cap inner edge (70)'),
]

def _r3m(px, py):
    return np.array([px * S_R3, -py * S_R3])

def fit_r3():
    from scipy.optimize import least_squares
    S = np.load(R3_SEGS)
    for (x1, y1, x2, y2), *_ in R3_LINES:
        d = np.minimum(np.abs(S[:, :4] - [x1, y1, x2, y2]).max(1), np.abs(S[:, :4] - [x2, y2, x1, y1]).max(1))
        assert d.min() < 0.01, ('R3 line not found', x1, y1, x2, y2)
    P, K, V = [], [], []
    for (x1, y1, x2, y2), k, v, _ in R3_LINES:
        t = np.linspace(0, 1, 25)[:, None]
        P.append(_r3m(x1, y1) + (_r3m(x2, y2) - _r3m(x1, y1)) * t); K += [k] * 25; V += [v] * 25
    P, K, V = np.vstack(P), np.array(K), np.array(V)

    def loc(par, Q):
        th, ox, oy = par
        ux, uy = np.array([-math.sin(th), math.cos(th)]), np.array([-math.cos(th), -math.sin(th)])
        d = Q - [ox, oy]
        return np.c_[d @ ux, d @ uy] * 1000.0

    def res(par):
        L = loc(par, P)
        return np.where(K == 'x', L[:, 0] - V, L[:, 1] - V)
    o0 = _r3m(642.06, 708.96)
    r = least_squares(res, [0.0, o0[0], o0[1]])
    rr = res(r.x)
    per = {}
    for i, (_, _, _, nm) in enumerate(R3_LINES):
        q = rr[i * 25:(i + 1) * 25]
        per[nm] = round(float(np.abs(q).max()), 1)
    return dict(theta_rad=float(r.x[0]), origin_R3m=[float(r.x[1]), float(r.x[2])], rms_mm=round(float(np.sqrt((rr ** 2).mean())), 1),
                max_mm=round(float(np.abs(rr).max()), 1), per_line_max_mm=per)

def r3m_to_gltf_fn():
    cwd = os.getcwd()
    os.chdir(HERE)
    try:
        import site_frame
    finally:
        os.chdir(cwd)
    return site_frame.r3_to_gltf

def matrix_from_fit(fit):
    th = fit['theta_rad']; o = np.array(fit['origin_R3m'])
    ux, uy = np.array([-math.sin(th), math.cos(th)]), np.array([-math.cos(th), -math.sin(th)])
    to_g = r3m_to_gltf_fn()
    G = to_g(np.array([o, o + ux, o + uy]))
    M = np.eye(4)
    M[:3, 3] = G[0]; M[:3, 0] = (G[1] - G[0]) / 1000.0; M[:3, 1] = (G[2] - G[0]) / 1000.0; M[:3, 2] = [0, 0.001, 0]
    return M

M_SPEC = np.array(json.load(open(L2G_PATH))['M_local_mm_to_gltf_m'], float)
FIT = fit_r3()
M_R3 = matrix_from_fit(FIT)
_R180 = np.diag([-1.0, -1.0, 1.0, 1.0]); _R180[0, 3], _R180[1, 3] = GX, GY
M_FLIP = M_R3 @ _R180
M = {'R3': M_R3, 'R3_flip180': M_FLIP, 'spec': M_SPEC}[PLACEMENT]
assert abs(np.linalg.det(M[:3, :3] * 1000.0) - 1.0) < 1e-9

def _bearing(MM, d_local):
    d = MM[:3, :3] @ np.asarray(d_local, float); return float(np.degrees(math.atan2(d[0], -d[2])) % 360)

def side_a_bearing(MM):
    return _bearing(MM, [0, -1.0, 0])

DOORS = {'D1 (side A, Type 1, 1800)': ('A', 1272.5, 3072.5), 'D2 (side A, Type 9, 2895)': ('A', 6572.5, 9467.5),
         'D3 (side B, Type 10, 2895)': ('B', 4572.0, 7467.0)}

def orientation_report(MM):
    s_pt = 1.0 / (S_R3 * 1000.0)
    to_g = lambda p: (MM @ np.r_[p, 1.0])[:3]
    faces = {k: round(_bearing(MM, d), 2) for k, d in (('side_A', [0, -1, 0]), ('side_B', [0, 1, 0]),
                                                         ('end_1', [-1, 0, 0]), ('end_2', [1, 0, 0]))}
    doors = {}
    for k, (side, x0, x1) in DOORS.items():
        yface = -158.0 if side == 'A' else YB_GLASS
        g = to_g([(x0 + x1) / 2.0, yface, FFL])
        r3 = gltf_to_r3m(g[None])[0]
        doors[k] = dict(face=side, module_x_mm=[x0, x1], centre_gltf_m=[round(float(v), 4) for v in g],
                        centre_R3_page_pt=[round(float(r3[0] / S_R3), 2), round(float(-r3[1] / S_R3), 2)],
                        outward_bearing_deg=faces['side_' + side], width_on_page_pt=round((x1 - x0) * s_pt, 2))
    return dict(face_outward_bearing_deg=faces, doors=doors)

class Acc:
    def __init__(self):
        self.V, self.N, self.F, self.n = [], [], [], 0

    def poly(self, P, hint=None):
        P = np.asarray(P, float)
        n = np.zeros(3)
        for i in range(len(P)):
            a, b = P[i], P[(i + 1) % len(P)]
            n += [(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])]
        ln = np.linalg.norm(n)
        if ln < 1e-12:
            return
        n /= ln
        if hint is not None and np.dot(n, hint) < 0:
            P = P[::-1]; n = -n
        k = self.n
        self.V.append(P); self.N.append(np.repeat(n[None], len(P), 0))
        self.F += [[k, k + i, k + i + 1] for i in range(1, len(P) - 1)]
        self.n += len(P)

    def solid(self, faces, pts):
        pts = np.asarray(pts, float); c = pts.mean(0)
        for f in faces:
            P = pts[f]; self.poly(P, P.mean(0) - c)

    def box(self, x0, x1, y0, y1, z0, z1):
        x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1)); z0, z1 = sorted((z0, z1))
        if min(x1 - x0, y1 - y0, z1 - z0) <= 0:
            return
        p = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]
        self.solid(HEXA_FACES, p)

    def hexa(self, p):
        self.solid(HEXA_FACES, p)

    def arrays(self):
        V = np.vstack(self.V); N = np.vstack(self.N); F = np.array(self.F, np.uint32)
        return V, N, F

    @property
    def tris(self):
        return len(self.F)

HEXA_FACES = [[0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]

def rib_profile(u0, u1, pitch, base, top, depth):
    n = int((u1 - u0) // pitch)
    first = u0 + (u1 - u0 - (n - 1) * pitch) / 2.0
    pts = [(u0, 0.0)]
    for k in range(n):
        c = first + k * pitch
        for u, w in ((c - base / 2, 0.0), (c - top / 2, depth), (c + top / 2, depth), (c + base / 2, 0.0)):
            if u0 < u < u1:
                pts.append((u, w))
    pts.append((u1, 0.0))
    return np.array(pts), n

def ribbed_sheet(acc, prof, v0, v1, fmap, t=T_SHEET):
    U, W = prof[:, 0], prof[:, 1]
    o = lambda v, w: fmap(U, np.full_like(U, v), w)
    Po0, Po1, Pi0, Pi1 = o(v0, W), o(v1, W), o(v0, W - t), o(v1, W - t)
    wdir = fmap(np.array([U.mean()]), np.array([v0]), np.array([1.0]))[0] - fmap(np.array([U.mean()]), np.array([v0]), np.array([0.0]))[0]
    vdir = fmap(np.array([U.mean()]), np.array([v1]), np.array([0.0]))[0] - fmap(np.array([U.mean()]), np.array([v0]), np.array([0.0]))[0]
    udir = fmap(np.array([U[-1]]), np.array([v0]), np.array([0.0]))[0] - fmap(np.array([U[0]]), np.array([v0]), np.array([0.0]))[0]
    for i in range(len(U) - 1):
        seg = Po0[i + 1] - Po0[i]
        nout = np.cross(seg, vdir); nout = nout if np.dot(nout, wdir) > 0 else -nout
        acc.poly([Po0[i], Po0[i + 1], Po1[i + 1], Po1[i]], nout)
        acc.poly([Pi0[i], Pi0[i + 1], Pi1[i + 1], Pi1[i]], -nout)
        acc.poly([Po0[i], Po0[i + 1], Pi0[i + 1], Pi0[i]], -vdir)
        acc.poly([Po1[i], Po1[i + 1], Pi1[i + 1], Pi1[i]], vdir)
    acc.poly([Po0[0], Po1[0], Pi1[0], Pi0[0]], -udir)
    acc.poly([Po0[-1], Po1[-1], Pi1[-1], Pi0[-1]], udir)

PARTS = []
USED = set()

def part(key, layer_en, finish, source, confidence, spec_ids=(), **kw):
    for sid in spec_ids:
        assert sid in E, sid
        USED.add(sid)
    p = dict(name=f'{GROUP}|{key}', layer_en=layer_en, finish=finish, acc=Acc(),
             extras=node_extras(GROUP, layer_en, finish, source, confidence, spec_ids='', **kw))
    PARTS.append(p)
    return p['acc']

def ydep(side, d):
    return YA + d if side == 'A' else YB_GLASS - d

def glass_face(acc, side, x0, x1, d0, d1, z0, z1):
    if GLASS_GEOM == 'solid':
        fbox(acc, side, x0, x1, d0, d1, z0, z1)
        return
    y = ydep(side, d0)
    acc.poly([[x0, y, z0], [x1, y, z0], [x1, y, z1], [x0, y, z1]], np.array([0.0, -1.0 if side == 'A' else 1.0, 0.0]))

def spec_box(k):
    mn, mx = list(E[k]['min']), list(E[k]['max'])
    if mn[1] > GY / 2:
        mn[1] += DYB
        mx[1] += DYB
    return [mn[0], mx[0], mn[1], mx[1], mn[2], mx[2]]

def fbox(acc, side, x0, x1, d0, d1, z0, z1):
    acc.box(x0, x1, ydep(side, d0), ydep(side, d1), z0, z1)

def emin(i):
    return E[i]['min']

def emax(i):
    return E[i]['max']

a = part('Base platform skirting', 'Base platform 350 (3 mm Al skirting on SHS200 frame)', 'AL_T02',
         '',
         'high (geometry), medium (skirting colour T02 assumed, review)', ['base_platform'],
         refined='')
bx0, bx1, by0, by1 = BASE['x0'], BASE['x1'], BASE['y0'], BASE['y1']
a.box(bx0, bx1, by0, YA, 0, FFL)
a.box(bx0, bx1, YB, by1, 0, FFL)
a.box(bx0, XE1, YA, YB, 0, FFL)
a.box(XE2, bx1, YA, YB, 0, FFL)
for fx0, fx1, fy0, fy1 in ((XE1, XE1 + 27.0, YA + CAP - 3.0, YB + 1.0), (XE2 - 27.0, XE2, YA + CAP - 3.0, YB + 1.0),
                           (XE1, 2172.0 - 7.5, YB - 27.0, YB), (9867.0 + 7.5, XE2, YB - 27.0, YB)):
    a.box(fx0, fx1, fy0, fy1, FFL - 1.0, FFL + 1.0)

a = part('Plywood floor', 'Floor 24 mm marine plywood', 'PLYWOOD', '',
         'medium (12 mm legend vs 24 mm detail; FINISHING (BY OTHERS) not modelled)', ['floor_plywood'])
a.box(XE1, XE2, YA, YB, FFL - 24.0, FFL)

PANES = [
    ('A_T1_bay1_lower', 'A', (172.5, 1272.5), 1069, FFL, 3750, 'G01-1', '1069x3514'),
    ('A_T1_bay3_lower', 'A', (3072.5, 4172.5), 1069, FFL, 3750, 'G01-1', '1069x3514'),
    ('A_T1_bay1_upper', 'A', (172.5, 1272.5), 1069, 4050, 4800, 'G01-3', '1069x846'),
    ('A_T1_bay2_upper', 'A', (1272.5, 3072.5), 1769, 4050, 4800, 'G01-2', '1769x846'),
    ('A_T1_bay3_upper', 'A', (3072.5, 4172.5), 1069, 4050, 4800, 'G01-3', '1069x846'),
    ('A_T9_bay4_fixed', 'A', (4172.5, 6572.5), 2369, FFL, 4135, 'G01-4', '2369x3867'),
    ('A_T9_bay6_fixed', 'A', (9467.5, 11867.5), 2369, FFL, 4135, 'G01-4', '2369x3867'),
    ('B_bay2_fixed', 'B', (2172.0, 4572.0), 2369, FFL, 4135, 'G01-4', '2369x3867'),
    ('B_bay4_fixed', 'B', (7467.0, 9867.0), 2369, FFL, 4135, 'G01-4', '2369x3867'),
]
PANE_X = {}
for sid, side, (ma, mb), w, z0, z1, gid, size in PANES:
    if GLASS_SIZE == 'physical':
        c = (ma + mb) / 2.0; x0, x1 = c - w / 2.0, c + w / 2.0
    else:
        x0, x1 = emin(sid)[0], emax(sid)[0]
    PANE_X[sid] = (x0, x1)
    zv0 = z0 + (1.0 if z0 == FFL else HJ / 2)
    zv1 = z1 - HJ / 2
    a = part(f'IGU glass|{sid}', 'IGU glass GL03 (fixed SSG)', 'GL03_VISION_B',
             '',
             'high', [sid], glass_id=gid, glass_size_mm=size, visible_mm=[round(x1 - x0, 1), round(zv1 - zv0, 1)],
             makeup='8 HS #2 + 12 A + 6 HS / 1.52 PVB / 6 HS = 33.52 (C3)', glass_geom=GLASS_GEOM,
             glass_face_from_grid_mm=158.0,
             refined='')
    glass_face(a, side, x0, x1, 0.0, T_IGU, zv0, zv1)

for sid in ('door1_leaf_L', 'door1_leaf_R', 'door2_leaf_L', 'door2_leaf_R', 'door3_leaf_L', 'door3_leaf_R'):
    e = E[sid]; side = 'A' if e['min'][1] < GY / 2 else 'B'
    x0, x1 = e['min'][0], e['max'][0]
    sgn = -1.0 if e['door']['slide_dir'] == '-x' else 1.0
    travel = (x1 - x0) - 23.0
    dx = sgn * travel * DOOR_OPEN
    size = '923x3475' if sid.startswith('door1') else '1471x3850'
    a = part(f'Door leaf|{sid}', 'Auto sliding door leaf (laminated)', 'GL_DOOR',
             '',
             'high (size), medium (depth position)', [sid], slide_dir=e['door']['slide_dir'], travel_mm=round(travel, 1),
             door_open=DOOR_OPEN, glass_geom=GLASS_GEOM, operator='concealed sliding-door operator',
             refined='')
    glass_face(a, side, x0 + dx, x1 + dx, LEAF_D, LEAF_D + T_LEAF, e['min'][2], e['max'][2])

a = part('SSG joints', 'SSG joints (black weather seal / structural sealant)', 'SEALANT_BLACK',
         '',
         'high (vertical), medium (horizontal 12 mm estimated)',
         joint_visible_vertical_mm=31.0 if GLASS_SIZE == 'physical' else 15.0, joint_horizontal_mm=HJ,
         note='')
PX = PANE_X
JD0, JD1 = 3.0, 30.0
J = []
jamb = lambda cl, s: (cl + 7.5, cl + 47.5) if s > 0 else (cl - 47.5, cl - 7.5)
J += [('A', 172.5 - 7.5, PX['A_T1_bay1_lower'][0], FFL, 4806.0),
      ('A', PX['A_T1_bay1_lower'][1], PX['A_T1_bay2_upper'][0], FFL, 4806.0),
      ('A', PX['A_T1_bay2_upper'][1], PX['A_T1_bay3_lower'][0], FFL, 4806.0),
      ('A', PX['A_T1_bay3_lower'][1], PX['A_T9_bay4_fixed'][0], FFL, 4806.0),
      ('A', PX['A_T9_bay4_fixed'][1], jamb(6572.5, +1)[0], FFL, 4141.0),
      ('A', jamb(9467.5, -1)[1], PX['A_T9_bay6_fixed'][0], FFL, 4141.0),
      ('A', PX['A_T9_bay6_fixed'][1], 11867.5 + 7.5, FFL, 4141.0),
      ('B', 2172.0 - 7.5, PX['B_bay2_fixed'][0], FFL, 4141.0),
      ('B', PX['B_bay2_fixed'][1], jamb(4572.0, +1)[0], FFL, 4141.0),
      ('B', jamb(7467.0, -1)[1], PX['B_bay4_fixed'][0], FFL, 4141.0),
      ('B', PX['B_bay4_fixed'][1], 9867.0 + 7.5, FFL, 4141.0)]
for side, x0, x1, z0, z1 in J:
    if x1 - x0 > 0.5:
        fbox(a, side, x0, x1, JD0, JD1, z0, z1)
H = [('A', 172.5, 1272.5, 3750), ('A', 3072.5, 4172.5, 3750), ('A', 172.5, 4172.5, 4050), ('A', 172.5, 4172.5, 4800),
     ('A', 4172.5, 6572.5, 4135), ('A', 9467.5, 11867.5, 4135), ('B', 2172.0, 4572.0, 4135), ('B', 7467.0, 9867.0, 4135)]
for side, x0, x1, z in H:
    fbox(a, side, x0, x1, JD0, JD1, z - HJ / 2, z + HJ / 2)
for sid, side, *_ in PANES:
    if E[sid]['min'][2] <= FFL:
        x0, x1 = PX[sid]; fbox(a, side, x0 - 15.5, x1 + 15.5, -10.0, 0.0, FFL, FFL + 1.0)

a = part('Aluminium bands T02', 'Aluminium bands, parapet caps, corner covers (3 mm T02)', 'AL_T02',
         '',
         'high (sizes), medium (depths)',
         ['A_T1_operator_band', 'A_T1_top_band', 'A_T9_top_band', 'A_corner_left', 'A_corner_right', 'B_top_band',
          'end1_top_band', 'end2_top_band'],
         end_band_top=END_BAND_TOP,
         refined='')
fbox(a, 'A', 172.5, 4172.5, -PROUD, 150.0, 3750 + HJ / 2, 4050 - HJ / 2)
fbox(a, 'A', X_EB1, 4172.5, -PROUD, CAP, 4800 + HJ / 2, ZTOP)
fbox(a, 'A', 4172.5, X_EB2, -PROUD, CAP, 4135 + HJ / 2, ZTOP)
for xa, xb, xr, zt in ((X_EB1, 172.5 - 7.5, X_EB1, 4800 + HJ / 2),
                       (11867.5 + 7.5, X_EB2, X_EB2, 4135 + HJ / 2)):
    fbox(a, 'A', xa, xb, -PROUD, -PROUD + 3.0, FFL + 1.0, zt)
    a.box(xr, xr + (3.0 if xr < 0 else -3.0), ydep('A', -PROUD), ydep('A', -PROUD + 111.0), FFL + 1.0, zt)
a.box(X_EB1, X_EB2, Y_BBAND - CAP, Y_BBAND + PROUD, 4135 + HJ / 2, ZBB)
for xa, xb in ((X_EB1, X_RF1 + 2.0), (X_RF2 - 2.0, X_EB2)):
    y0, y1, z0 = YA + CAP, Y_BBAND, 4195.0
    if END_BAND_TOP == 'level':
        a.box(xa, xb, y0, y1, z0, ZTOP)
    else:
        t0, t1 = float(ZU(y0)) + 52.0, float(ZU(y1)) + 52.0
        a.hexa([[xa, y0, z0], [xb, y0, z0], [xb, y1, z0], [xa, y1, z0], [xa, y0, t0], [xb, y0, t0], [xb, y1, t1], [xa, y1, t1]])

a = part('Door jamb and head covers T02', 'Door jamb covers (40 face + 99 return) and head soffits', 'AL_T02',
         '',
         'medium (flat sizes read as face + return)')
for side, cl, s, ztop in (('A', 1272.5, +1, 3750 + HJ / 2), ('A', 3072.5, -1, 3750 + HJ / 2), ('A', 6572.5, +1, 4135 + HJ / 2),
                          ('A', 9467.5, -1, 4135 + HJ / 2), ('B', 4572.0, +1, 4135 + HJ / 2), ('B', 7467.0, -1, 4135 + HJ / 2)):
    f0, f1 = jamb(cl, s)
    fbox(a, side, f0, f1, -PROUD, PROUD, FFL + 1.0, ztop)
    rx = (f1 - 3.0, f1) if s > 0 else (f0, f0 + 3.0)
    fbox(a, side, rx[0], rx[1], PROUD, 99.0, FFL + 1.0, ztop)
for side, x0, x1, d0 in (('A', jamb(6572.5, 1)[1], jamb(9467.5, -1)[0], -PROUD), ('B', jamb(4572.0, 1)[1], jamb(7467.0, -1)[0], -PROUD)):
    fbox(a, side, x0, x1, d0, 160.0, 4135 + HJ / 2 - 3.0, 4135 + HJ / 2)

ids = [k for k in E if '_mullion_' in k]
a = part('Interior mullions T01', 'Interior mullions (extruded Al cover 50x102 on 115 base, T01)', 'AL_T01',
         '', 'high', ids,
         refined='')
GMS_B_X = ((XE1, 2172.0 - 7.5), (9867.0 + 7.5, XE2))
for k in ids:
    x0, x1, y0, y1, z0, z1 = spec_box(k)
    cuts = [x0, x1]
    if k.startswith('B_'):
        cuts = sorted(set([x0, x1] + [c for g in GMS_B_X for c in g if x0 < c < x1]))
    for xa, xb in zip(cuts[:-1], cuts[1:]):
        behind_gms = k.startswith('B_') and any(g0 <= (xa + xb) / 2 <= g1 for g0, g1 in GMS_B_X)
        a.box(xa, xb, y0, min(y1, YB + 1.0 - RIB_WALL['depth'] - T_SHEET) if behind_gms else y1, z0, z1)

ids = ['A_T1_sill', 'A_T9_sill', 'A_T1_head', 'A_T9_head', 'B_sill', 'B_head']
a = part('Interior transoms T01', 'Interior transoms and sills (T01)', 'AL_T01', '',
         'medium (approximate sections)', ids, refined='')
DOORS_X = {'A': [(1272.5, 3072.5), (6572.5, 9467.5)], 'B': [(4572.0, 7467.0)]}
for k in ids:
    bx_ = spec_box(k); side = 'A' if bx_[2] < GY / 2 else 'B'
    segs = [(bx_[0], bx_[1])]
    if k.endswith('sill'):
        for d0, d1 in DOORS_X[side]:
            segs = [s for a_, b_ in segs for s in ((a_, min(b_, d0)), (max(a_, d1), b_)) if s[1] - s[0] > 1]
    for x0, x1 in segs:
        a.box(x0, x1, *bx_[2:])

ids = ['door1_operator', 'door2_operator', 'door3_operator']
a = part('Door operators', 'Auto sliding door operator headers (concealed)', 'AL_T01',
         '', 'low (header size ~150x150 assumed)', ids,
         refined='')
for k in ids:
    x0, x1, y0, y1, z0, z1 = spec_box(k)
    if k == 'door1_operator':
        y0 = max(y0, ydep('A', 150.0))
    a.box(x0, x1, y0, y1, z0, z1)

ids = ['end1_gms_wall', 'end2_gms_wall', 'B_gms_wall_1', 'B_gms_wall_2']
a = part('GMS ribbed walls', 'Ribbed 1.5 mm G.M.S. plate walls (hot-dip galvanised)', 'GMS_RIBBED',
         '',
         'high (extent), medium (rib profile from graphics +-10 mm; FINISHING (BY OTHERS) may paint it later)', ids,
         ribs_modelled=True, rib=RIB_WALL,
         refined='')
rw = RIB_WALL; dep = rw['depth']
zw1 = 4195.0 + 20.0
zb1 = 4135.0 + HJ / 2 + 14.0
prof, n_end = rib_profile(YA + CAP - 3.0, YB + 1.0, rw['pitch'], rw['base'], rw['top'], dep)
xp1, xp2 = XE1 + dep, XE2 - dep
ribbed_sheet(a, prof, FFL + 1.0, zw1, lambda u, v, w: np.c_[xp1 - w, u, v])
ribbed_sheet(a, prof, FFL + 1.0, zw1, lambda u, v, w: np.c_[xp2 + w, u, v])
yp = YB + 1.0 - dep
for x0, x1 in ((xp1, 2172.0 - 7.5), (9867.0 + 7.5, xp2)):
    pb, _ = rib_profile(x0, x1, rw['pitch'], rw['base'], rw['top'], dep)
    ribbed_sheet(a, pb, FFL + 1.0, zb1, lambda u, v, w: np.c_[u, yp + w, v])
for sx, xc in ((-1, XE1), (1, XE2)):
    a.box(xc - sx * 60.0, xc + sx * 1.5, YB + 1.0, YB + 2.5, FFL + 1.0, zb1)
    a.box(xc, xc + sx * 1.5, YB - 60.0, YB + 2.5, FFL + 1.0, zb1)

a = part('GMS ribbed roof', 'Mono-pitch roof, ribbed 1.5 mm G.M.S. sheet', 'GMS_RIBBED',
         '',
         'high (outline, fall direction), medium (3 % fall vs 4.3 % implied by 5250/4998)', ['roof'], ribs_modelled=True, rib=RIB_ROOF,
         roof_fall=ROOF_FALL, refined='')
rr_ = RIB_ROOF
prof, n_roof = rib_profile(X_RF1, X_RF2, rr_['pitch'], rr_['base'], rr_['top'], rr_['depth'])
ribbed_sheet(a, prof, YA + 58.0, Y_BBAND + EAVE, lambda u, v, w: np.c_[u, v, ZU(v) + T_SHEET + w])

ids = ['col_1A', 'col_2A', 'col_1B', 'col_2B', 'col_centre']
a = part('Steel columns SHS200', 'Columns SHS 200x200x6 G.M.S. (HDG)', 'STEEL_HDG', '',
         'high', ids, refined='')
A_BEAM_TOP = float(ZU(100.0)) - 1.0
B_BEAM_TOP = float(ZU(GY + 100.0)) - 1.0
for k in ids:
    mn, mx = E[k]['min'], E[k]['max']
    if k == 'col_centre':
        top = float(ZU(mx[1])) - 1.0 - 200.0
    else:
        top = (A_BEAM_TOP if mn[1] < GY / 2 else B_BEAM_TOP) - 200.0
    a.box(mn[0], mx[0], mn[1], mx[1], 0.0, top)
a = part('Roof framing', 'Roof framing: SHS200 beams + 50x50 purlins (HDG)', 'STEEL_HDG',
         '', 'medium')
a.box(-100.0, GX + 100.0, -100.0, 100.0, A_BEAM_TOP - 200.0, A_BEAM_TOP)
a.box(-100.0, GX + 100.0, GY - 100.0, GY + 100.0, B_BEAM_TOP - 200.0, B_BEAM_TOP)
for xc in (0.0, 2020.0, 4020.0, 6020.0, 8020.0, 10020.0, GX):
    y0, y1 = 100.0, GY - 100.0; t0, t1 = float(ZU(y0)) - 1.0, float(ZU(y1)) - 1.0
    x0, x1 = xc - 100.0, xc + 100.0
    a.hexa([[x0, y0, t0 - 200], [x1, y0, t0 - 200], [x1, y1, t1 - 200], [x0, y1, t1 - 200], [x0, y0, t0], [x1, y0, t0], [x1, y1, t1], [x0, y1, t1]])
for yc in (802.0, 1602.0, 2402.0, 3202.0, 4002.0, 4802.0):
    top = float(ZU(yc + 25.0)) - 1.0
    a.box(100.0, GX - 100.0, yc - 25.0, yc + 25.0, top - 50.0, top)

if STEPS:
    a = part('Access steps (indicative)', 'Access steps, 2 per door (indicative, not documented)', 'STEEL_HDG',
             '',
             'low (assumed)', indicative=True)
    for side, xa, xb in (('A', 1272.5, 3072.5), ('A', 6572.5, 9467.5), ('B', 4572.0, 7467.0)):
        s = -1.0 if side == 'A' else 1.0
        y_face = by0 if side == 'A' else by1
        for k, (d0, d1, h) in enumerate(((0.0, 300.0, FFL * 2 / 3), (300.0, 600.0, FFL / 3))):
            a.box(xa - 50.0, xb + 50.0, y_face + s * d0, y_face + s * d1, 0.0, h)

missing = sorted(set(E) - USED)
assert not missing, f'spec elements not meshed: {missing}'

def uv_box(V, N):
    a = np.abs(N); k = a.argmax(1)
    U = np.where(k == 2, V[:, 0], np.where(k == 0, V[:, 1], V[:, 0]))
    W = np.where(k == 2, V[:, 1], V[:, 2])
    return np.c_[U, W] / 1000.0

def to_gltf(V, N):
    Lm = M[:3, :3]; R = Lm * 1000.0
    return (V @ Lm.T) + M[:3, 3], N @ R.T

def overlay_check(MM):
    S = np.load(R3_SEGS)
    Rm = np.c_[S[:, 0] * S_R3, -S[:, 1] * S_R3, S[:, 2] * S_R3, -S[:, 3] * S_R3]
    ctr = np.array([6020.0, 2802.5])
    to_r3 = lambda P: gltf_to_r3m((np.c_[P, np.zeros(len(P)), np.ones(len(P))] @ MM.T)[:, :3])
    c = to_r3(ctr[None])[0]
    m = (np.abs((Rm[:, 0] + Rm[:, 2]) / 2 - c[0]) < 6) & (np.abs((Rm[:, 1] + Rm[:, 3]) / 2 - c[1]) < 9)
    Rn = Rm[m]; A = Rn[:, :2]; AB = Rn[:, 2:4] - A; L2 = np.maximum((AB ** 2).sum(1), 1e-12)
    lines = {'side-A band face': ((X_EB1 + PROUD, -158.0), (X_EB2 - PROUD, -158.0)),
             'side-A cap inner': ((X_RF1, -70.0), (X_RF2, -70.0)),
             'side-B band face': ((X_RF1, Y_BBAND), (X_RF2, Y_BBAND)),
             'side-B eave edge': ((X_RF1, Y_BBAND + EAVE), (X_RF2, Y_BBAND + EAVE)),
             'end-1 cap inner': ((X_RF1, -70.0), (X_RF1, Y_BBAND + EAVE)),
             'end-2 cap inner': ((X_RF2, -70.0), (X_RF2, Y_BBAND + EAVE)),
             'grid A': ((-600.0, 0.0), (GX + 600.0, 0.0)), 'grid B': ((-600.0, GY), (GX + 600.0, GY)),
             'grid 1': ((0.0, -1000.0), (0.0, GY + 400.0)), 'grid 2': ((GX, -1000.0), (GX, GY + 400.0))}
    out = {}
    for nm, (p, q) in lines.items():
        t = np.linspace(0, 1, 80)[:, None]; P = to_r3(np.array(p) + (np.array(q) - np.array(p)) * t)
        d = []
        for pt in P:
            tt = np.clip(((pt - A) * AB).sum(1) / L2, 0, 1); d.append(np.sqrt(((A + AB * tt[:, None] - pt) ** 2).sum(1)).min())
        d = np.array(d) * 1000.0
        out[nm] = dict(median_mm=round(float(np.median(d)), 1), max_mm=round(float(d.max()), 1))
    return dict(lines=out, max_mm=max(v['max_mm'] for v in out.values()))

def gltf_to_r3m(G):
    cwd = os.getcwd(); os.chdir(HERE)
    try:
        import site_frame as sf
    finally:
        os.chdir(cwd)
    A2 = np.array([[sf.ex[0], sf.ey[0]], [sf.ex[1], sf.ey[1]]])
    return np.linalg.solve(A2, np.vstack([G[:, 0], -G[:, 2]])).T + sf.O

def build():
    glb = GLB()
    children, report = [], {}
    all_V = []
    for p in PARTS:
        acc = p['acc']
        if acc.n == 0:
            continue
        V, N, F = acc.arrays()
        uv = uv_box(V, N)
        Vg, Ngl = to_gltf(V, N)
        mi = mat(glb, p['finish'])
        mesh = glb.mesh(p['name'], Vg, F, Ngl, mi, uvs=uv)
        ex = dict(p['extras']); ex['triangles'] = int(len(F))
        children.append(glb.node(p['name'], mesh=mesh, extras=ex))
        all_V.append(Vg)
        report[p['name']] = dict(tris=int(len(F)), finish=p['finish'],
                                 bbox_local_mm=[V.min(0).round(1).tolist(), V.max(0).round(1).tolist()])
    Vall = np.vstack(all_V)
    ov_r3 = overlay_check(M_R3); ov_spec = overlay_check(M_SPEC); ov_flip = overlay_check(M_FLIP)
    root_extras = {
        'group': GROUP, 'layer_en': 'VMU-02 enclosure sample (Types 1, 9, 10)', 'description': 'Enclosure sample with auto sliding doors',
        'finish': 'AL_T02', 'source': '',
        'confidence': 'high (shop drawing); future state per drawings',
        'status': 'future state per shop drawing (not yet built)',
        'placement': dict(mode=PLACEMENT, side_A_outward_bearing_deg=round(side_a_bearing(M), 2),
                          matrix_local_mm_to_gltf_m=np.round(M, 12).tolist(),
                          r3_fit=dict(FIT, theta_deg=round(math.degrees(FIT['theta_rad']), 4)),
                          overlay_R3_max_mm=dict(R3=ov_r3['max_mm'], spec=ov_spec['max_mm'], R3_flip180=ov_flip['max_mm']),
                          spec_matrix_side_A_bearing_deg=round(side_a_bearing(M_SPEC), 2),
                          note=''),
        'orientation': dict(orientation_report(M), verdict='side A (Type 1 + Type 9, doors D1 + D2) faces NNE; side B (Type 10, '
                                                          'door D3) faces SSW; grid-1 end wall faces the road (ESE); no 180 deg flip',
                            flip180_overlay_R3_lines=ov_flip['lines'],
                            evidence='',
                            evidence_dir=''),
        'params': dict(PLACEMENT=PLACEMENT, ROOF_FALL=ROOF_FALL, END_BAND_TOP=END_BAND_TOP, GLASS_SIZE=GLASS_SIZE, GLASS_GEOM=GLASS_GEOM,
                       DOOR_OPEN=DOOR_OPEN, STEPS=STEPS),
        'glass_faces_from_grid_mm': dict(A=158.0, B=YB_GLASS - GY, note=''),
        'spec_elements_meshed': len(USED), 'datum': 'glTF y 0 = yard slab top; FFL = y 0.350 (review)',
    }
    root = glb.node(GROUP, children=children, extras=root_extras, root=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    glb.save(OUT, extras=dict(group=GROUP, file='vmu02.glb', builder='build/build_vmu02.py', contract='material contract'))
    return dict(parts=report, bbox_gltf=[Vall.min(0).round(4).tolist(), Vall.max(0).round(4).tolist()],
                tris=int(sum(r['tris'] for r in report.values())), overlay_R3=ov_r3, overlay_spec=ov_spec,
                overlay_flip180=ov_flip, root=root_extras)

if __name__ == '__main__':
    R = build()
    print(f'ribs: roof {n_roof}, each end wall {n_end}')
    print(f'wrote {OUT}  ({os.path.getsize(OUT) / 1024:.0f} kB, {R["tris"]} triangles, {len(R["parts"])} mesh nodes, '
          f'{len(USED)}/66 spec elements)')
    print('placement', PLACEMENT, 'side-A bearing', R['root']['placement']['side_A_outward_bearing_deg'],
          'R3 fit rms/max mm', FIT['rms_mm'], FIT['max_mm'])
    print('bbox glTF', R['bbox_gltf'])
    print('R3 overlay max mm: R3-fit', R['overlay_R3']['max_mm'], ' spec matrix', R['overlay_spec']['max_mm'])
    for k, v in R['overlay_R3']['lines'].items():
        print(f'   {k:20s} R3-fit median {v["median_mm"]:6.1f} max {v["max_mm"]:6.1f} | spec max {R["overlay_spec"]["lines"][k]["max_mm"]:7.1f}'
              f' | flip180 median {R["overlay_flip180"]["lines"][k]["median_mm"]:7.1f} max {R["overlay_flip180"]["lines"][k]["max_mm"]:7.1f}')
    O = R['root']['orientation']
    print('face bearings', O['face_outward_bearing_deg'])
    for k, v in O['doors'].items():
        print(f'   {k:28s} face {v["face"]} bearing {v["outward_bearing_deg"]:6.1f}  layout page {v["centre_R3_page_pt"]}  glTF {v["centre_gltf_m"]}')
    for k, v in R['parts'].items():
        print(f'  {k:45s} {v["finish"]:15s} {v["tris"]:6d}')
    json.dump(R, open(os.environ.get('MOCKUP_VMU02_REPORT', os.devnull), 'w'), indent=1, default=float)
