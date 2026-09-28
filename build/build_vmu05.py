"""Builds model/vmu05.glb: VMU-05, the low curved balustrade mock-up - an RC parapet (leg + 90 degree arc + leg, chamfered
outer face, block-outs at the posts) with an SS316 flat-bar railing, posts, base plates and anchors, swept along the
plan curve in the local frame of the private element spec (mm) and checked against the layout-plan segments.
MOCKUP_VMU05_BASE=pocket|surface switches the post-base detail. Needs the private spec and segments in SOURCES_DIR.
"""
import os, sys, json, math
import numpy as np
SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.chdir(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from gltfw import GLB
from site_frame import r3_to_gltf, r3_dir_to_gltf
from materials_lib import mat, node_extras
import mapbox_earcut

OUT = os.path.join(ROOT, 'model', 'vmu05.glb')
SEGS = os.path.join(SOURCES_DIR, 'vmu05_layout_segs.npy')
SPEC = os.path.join(SOURCES_DIR, 'vmu05_spec.json')

ORIGIN_R3M = (133.207, -92.858)
ROT_DEG = 0.0
ARC_SEG = 128
BASE_DETAIL = os.environ.get('MOCKUP_VMU05_BASE', 'pocket')
PARAPET_MATERIAL = 'RC_PLAIN'
RAIL_MATERIAL = 'SS_BRUSHED'
assert BASE_DETAIL in ('pocket', 'surface'), BASE_DETAIL
assert ARC_SEG >= 96

LEG_A, LEG_B = 1600.0, 1450.0
R_IN, R_OUT, R_TOP = 1200.0, 1500.0, 1400.0
H, H_CH = 650.0, 500.0
R_C = 1300.0
RAIL_W, RAIL_T = 60.0, 10.0
RAIL_Z = (735.0, 825.0, 915.0, 1005.0, 1095.0)
TOP_Z = 1100.0
POST_ALONG, POST_ACROSS = 10.0, 60.0
FIN = dict(along=30.0, t=3.0, h=15.0, offs=23.5)
BOLT_ALONG = 62.5
if BASE_DETAIL == 'pocket':
    POCKET = dict(along=195.0, across=100.0, depth=50.0)
    PLATE = dict(along=175.0, across=80.0, t=8.0, z0=H - 50.0)
else:
    POCKET = None
    PLATE = dict(along=195.0, across=100.0, t=8.0, z0=H)
POST_Z0 = PLATE['z0'] + PLATE['t']

U_ARC0 = LEG_B
U_ARC1 = LEG_B + R_C * math.pi / 2
U_END = U_ARC1 + LEG_A
POSTS = [('P1', U_ARC0 - 1050.0), ('P2', U_ARC0), ('P3', U_ARC0 + R_C * math.pi / 4), ('P4', U_ARC1), ('P5', U_ARC1 + 1200.0)]
UP = np.array([0.0, 0.0, 1.0])

SRC_PARTS = ''
SRC_R3 = ''

def frame(u):
    if u <= U_ARC0:
        B, n = np.array([0.0, u - U_ARC0]), np.array([1.0, 0.0])
    elif u < U_ARC1:
        th = (u - U_ARC0) / R_C
        B, n = np.zeros(2), np.array([math.cos(th), math.sin(th)])
    else:
        B, n = np.array([-(u - U_ARC1), 0.0]), np.array([0.0, 1.0])
    return B, n, np.array([-n[1], n[0]])

def pos(u, r):
    B, n, _ = frame(u)
    return B + r * n

def s_at(u, r):
    if u <= U_ARC0:
        return u
    if u < U_ARC1:
        return U_ARC0 + r * (u - U_ARC0) / R_C
    return U_ARC0 + r * math.pi / 2 + (u - U_ARC1)

def inv_pos(p):
    x, y = p
    if y <= 0 and x > 0:
        return U_ARC0 + y, x
    if x <= 0 and y > 0:
        return U_ARC1 - x, y
    th = math.atan2(y, x)
    return U_ARC0 + R_C * th, math.hypot(x, y)

ARC_U = U_ARC0 + R_C * np.linspace(0.0, math.pi / 2, ARC_SEG + 1)

def stations(u0, u1):
    return [u0] + [float(u) for u in ARC_U if u0 + 1e-6 < u < u1 - 1e-6] + [u1]

class Mesh:
    def __init__(s):
        s.V, s.N, s.UV, s.F, s.nv, s.parts = [], [], [], [], 0, 0

    def add(s, V, N, UV, F):
        V = np.asarray(V, float)
        s.V.append(V); s.N.append(np.asarray(N, float)); s.UV.append(np.asarray(UV, float))
        s.F.append(np.asarray(F, np.int64).reshape(-1, 3) + s.nv); s.nv += len(V)

    def poly(s, P, n, uv=None):
        P = np.asarray(P, float); k = len(P)
        if uv is None:
            e1 = P[1] - P[0]; e1 /= np.linalg.norm(e1); e2 = np.cross(n, e1)
            uv = np.c_[(P - P[0]) @ e1, (P - P[0]) @ e2]
        s.add(P, np.tile(n, (k, 1)), uv, [[0, i, i + 1] for i in range(1, k - 1)])

    def arrays(s):
        V = np.concatenate(s.V); N = np.concatenate(s.N); UV = np.concatenate(s.UV); F = np.concatenate(s.F)
        N /= np.linalg.norm(N, axis=1, keepdims=True)
        fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
        vn = N[F[:, 0]] + N[F[:, 1]] + N[F[:, 2]]
        flip = (fn * vn).sum(1) < 0
        F[flip] = F[flip][:, [0, 2, 1]]
        return V, N, UV / 1000.0, F

def sweep(m, us, prof, edges, closed_caps=False):
    prof = np.asarray(prof, float); k = len(prof); cen = prof.mean(0)
    fr = [frame(u) for u in us]
    for i in edges:
        a, b = prof[i], prof[(i + 1) % k]
        d = b - a; L = float(np.hypot(*d))
        en = np.array([d[1], -d[0]]) / L
        if np.dot(en, (a + b) / 2 - cen) < 0:
            en = -en
        V, N, UV = [], [], []
        for u, (B, n, t) in zip(us, fr):
            for (r, z), v in ((a, 0.0), (b, L)):
                p = B + r * n
                V.append([p[0], p[1], z]); N.append([en[0] * n[0], en[0] * n[1], en[1]]); UV.append([s_at(u, r), v])
        F = []
        for j in range(len(us) - 1):
            q0, q1, q2, q3 = 2 * j, 2 * j + 1, 2 * j + 3, 2 * j + 2
            F += [[q0, q1, q2], [q0, q2, q3]]
        m.add(V, N, UV, F)
    if closed_caps:
        for u, sgn in ((us[0], -1.0), (us[-1], 1.0)):
            B, n, t = frame(u)
            P = [[*(B + r * n), z] for r, z in prof]
            m.poly(P, np.array([sgn * t[0], sgn * t[1], 0.0]), uv=np.c_[prof[:, 0] - prof[:, 0].min(), prof[:, 1]])

def box(m, C, t, n, a, b, z0, z1):
    C = np.asarray(C, float); t3 = np.array([t[0], t[1], 0.0]); n3 = np.array([n[0], n[1], 0.0])
    c = lambda i, j, z: np.array([C[0], C[1], z]) + i * a * t3 + j * b * n3
    m.poly([c(-1, -1, z1), c(1, -1, z1), c(1, 1, z1), c(-1, 1, z1)], UP)
    m.poly([c(-1, -1, z0), c(-1, 1, z0), c(1, 1, z0), c(1, -1, z0)], -UP)
    m.poly([c(1, -1, z0), c(1, 1, z0), c(1, 1, z1), c(1, -1, z1)], t3)
    m.poly([c(-1, -1, z0), c(-1, -1, z1), c(-1, 1, z1), c(-1, 1, z0)], -t3)
    m.poly([c(-1, 1, z0), c(-1, 1, z1), c(1, 1, z1), c(1, 1, z0)], n3)
    m.poly([c(-1, -1, z0), c(1, -1, z0), c(1, -1, z1), c(-1, -1, z1)], -n3)

def prism(m, C, rad, z0, z1, nseg, phase=0.0, smooth=False):
    ang = phase + np.arange(nseg) * 2 * math.pi / nseg
    ring = np.c_[C[0] + rad * np.cos(ang), C[1] + rad * np.sin(ang)]
    m.poly([[x, y, z1] for x, y in ring], UP)
    m.poly([[x, y, z0] for x, y in ring[::-1]], -UP)
    for i in range(nseg):
        j = (i + 1) % nseg
        if smooth:
            na, nb = np.array([math.cos(ang[i]), math.sin(ang[i]), 0]), np.array([math.cos(ang[j]), math.sin(ang[j]), 0])
            V = [[*ring[i], z0], [*ring[j], z0], [*ring[j], z1], [*ring[i], z1]]
            m.add(V, [na, nb, nb, na], [[0, 0], [1, 0], [1, 1], [0, 1]], [[0, 1, 2], [0, 2, 3]])
        else:
            mid = ang[i] + math.pi / nseg
            m.poly([[*ring[i], z0], [*ring[j], z0], [*ring[j], z1], [*ring[i], z1]], np.array([math.cos(mid), math.sin(mid), 0]))

def post_frames():
    out = []
    for pid, u in POSTS:
        B, n, t = frame(u)
        out.append((pid, u, B + R_C * n, n, t))
    return out

def pocket_rect(C, n, t):
    a, b = POCKET['along'] / 2, POCKET['across'] / 2
    return [C - a * t - b * n, C + a * t - b * n, C + a * t + b * n, C - a * t + b * n]

def build_parapet():
    m = Mesh()
    pu = [u for _, u in POSTS]
    cuts = [(a + b) / 2 for a, b in zip(pu[:-1], pu[1:])]
    us = sorted(set(stations(0.0, U_END)) | set(cuts))
    prof = [(R_IN, 0.0), (R_OUT, 0.0), (R_OUT, H_CH), (R_TOP, H), (R_IN, H)]
    sweep(m, us, prof, edges=[0, 1, 2, 4], closed_caps=True)
    bounds = [0.0] + cuts + [U_END]
    n_top_tri = 0
    for k, (u0, u1) in enumerate(zip(bounds[:-1], bounds[1:])):
        seg = [u for u in us if u0 - 1e-9 <= u <= u1 + 1e-9]
        rings = [[pos(u, R_TOP) for u in seg] + [pos(u, R_IN) for u in seg[::-1]]]
        if POCKET:
            pid, u, C, n, t = post_frames()[k]
            rings.append(pocket_rect(C, n, t)[::-1])
        V2 = np.concatenate([np.asarray(r) for r in rings])
        ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
        tri = np.asarray(mapbox_earcut.triangulate_float64(V2, ends), np.int64).reshape(-1, 3)
        m.add(np.c_[V2, np.full(len(V2), H)], np.tile(UP, (len(V2), 1)), V2.copy(), tri)
        n_top_tri += len(tri)
    if POCKET:
        zb = H - POCKET['depth']
        for pid, u, C, n, t in post_frames():
            R = pocket_rect(C, n, t)
            for i in range(4):
                p, q = R[i], R[(i + 1) % 4]
                mid = (p + q) / 2; inward = np.r_[C - mid, 0.0]; inward /= np.linalg.norm(inward)
                m.poly([[*p, zb], [*q, zb], [*q, H], [*p, H]], inward)
            m.poly([[*R[0], zb], [*R[1], zb], [*R[2], zb], [*R[3], zb]], UP)
    return m, n_top_tri

def build_rails():
    m = Mesh()
    pu = [u for _, u in POSTS]
    half = POST_ALONG / 2
    pieces = []
    for i in range(len(pu) - 1):
        u0, u1 = pu[i] + half, pu[i + 1] - half
        pieces.append((u0, u1))
    for zc in RAIL_Z:
        prof = [(R_C - RAIL_W / 2, zc - RAIL_T / 2), (R_C + RAIL_W / 2, zc - RAIL_T / 2),
                (R_C + RAIL_W / 2, zc + RAIL_T / 2), (R_C - RAIL_W / 2, zc + RAIL_T / 2)]
        for u0, u1 in pieces:
            sweep(m, stations(u0, u1), prof, edges=[0, 1, 2, 3], closed_caps=True)
    return m, pieces

def build_posts():
    m = Mesh()
    for pid, u, C, n, t in post_frames():
        box(m, C, t, n, POST_ALONG / 2, POST_ACROSS / 2, POST_Z0, TOP_Z)
        for sg in (-1, 1):
            box(m, C + sg * FIN['offs'] * n, t, n, FIN['along'] / 2, FIN['t'] / 2, POST_Z0, POST_Z0 + FIN['h'])
    return m

def build_plates():
    m = Mesh()
    for pid, u, C, n, t in post_frames():
        box(m, C, t, n, PLATE['along'] / 2, PLATE['across'] / 2, PLATE['z0'], PLATE['z0'] + PLATE['t'])
    return m

def build_anchors():
    m = Mesh()
    z = PLATE['z0'] + PLATE['t']
    for pid, u, C, n, t in post_frames():
        ang = math.atan2(t[1], t[0])
        for sg in (-1, 1):
            P = C + sg * BOLT_ALONG * t
            prism(m, P, 10.0, z, z + 2.0, 24, smooth=True)
            prism(m, P, 17.0 / math.sqrt(3), z + 2.0, z + 10.0, 6, phase=ang)
            prism(m, P, 5.0, z + 10.0, z + 20.0, 16, smooth=True)
    return m

def _rot(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s], [s, c]])

def r3_check():
    from scipy.optimize import least_squares
    import shapely
    from shapely.geometry import LineString, MultiLineString
    a = np.load(SEGS)
    O = np.array(ORIGIN_R3M); Rm = _rot(math.radians(ROT_DEG))
    S = (a[:, :4].reshape(-1, 2, 2) - O) @ Rm * 1000.0
    near = (np.abs(S) < 2000).all(axis=(1, 2))
    S = S[near]
    L = np.linalg.norm(S[:, 1] - S[:, 0], axis=1)
    lines = []
    arcv = []
    rails = []
    ends = {}
    for (p, q), l in zip(S, L):
        if l > 900 and abs(p[1] - q[1]) < 1 and max(p[0], q[0]) < 5:
            y = (p[1] + q[1]) / 2
            for mv in (R_IN, R_TOP, R_OUT):
                if abs(y - mv) < 30: lines.append((np.linspace(p, q, 20), 1, mv))
            for mv in (R_C - RAIL_W / 2, R_C + RAIL_W / 2):
                if abs(y - mv) < 20: rails.append(('A', mv, y))
        if l > 900 and abs(p[0] - q[0]) < 1 and max(p[1], q[1]) < 5:
            x = (p[0] + q[0]) / 2
            for mv in (R_IN, R_TOP, R_OUT):
                if abs(x - mv) < 30: lines.append((np.linspace(p, q, 20), 0, mv))
            for mv in (R_C - RAIL_W / 2, R_C + RAIL_W / 2):
                if abs(x - mv) < 20: rails.append(('B', mv, x))
        if 250 < l < 350 and abs(p[0] - q[0]) < 1 and p[0] < -1000:
            ends['A'] = (p[0] + q[0]) / 2
        if 250 < l < 350 and abs(p[1] - q[1]) < 1 and p[1] < -1000:
            ends['B'] = (p[1] + q[1]) / 2
    for v in S.reshape(-1, 2):
        th = math.degrees(math.atan2(v[1], v[0])); r = float(np.hypot(*v))
        if 2 < th < 88:
            for mv in (R_IN, R_TOP, R_OUT):
                if abs(r - mv) < 30: arcv.append((v, mv))
    arcv = list({(round(v[0], 3), round(v[1], 3), mv): (v, mv) for v, mv in arcv}.values())

    def resid(prm, with_scale=False):
        dx, dy, dth = prm[:3]; sc = prm[3] if with_scale else 1.0
        Ri = _rot(-dth)
        out = []
        for P, ax, mv in lines:
            Q = ((P - [dx, dy]) @ Ri.T) / sc
            out.append(Q[:, ax] - mv)
        for v, mv in arcv:
            Q = ((v - [dx, dy]) @ Ri.T) / sc
            out.append([np.hypot(*Q) - mv] * 3)
        return np.concatenate([np.atleast_1d(o) for o in out])

    r0 = resid([0, 0, 0])
    fr = least_squares(resid, [0, 0, 0], loss='soft_l1', f_scale=10.0)
    fs = least_squares(lambda p: resid(p, True), [0, 0, 0, 1], loss='soft_l1', f_scale=10.0)
    rr, rs = resid(fr.x), resid(fs.x, True)

    us = stations(0.0, U_END)
    curves = [[pos(u, r) for u in us] for r in (R_IN, R_TOP, R_OUT)]
    curves += [[pos(0, R_IN), pos(0, R_OUT)], [pos(U_END, R_IN), pos(U_END, R_OUT)]]
    pu = [u for _, u in POSTS]
    curves += [[pos(u, r) for u in stations(pu[0], pu[-1])] for r in (R_C - RAIL_W / 2, R_C + RAIL_W / 2)]
    for pid, u, C, n, t in post_frames():
        a_, b_ = 97.5, 50.0
        curves.append([C - a_ * t - b_ * n, C + a_ * t - b_ * n, C + a_ * t + b_ * n, C - a_ * t + b_ * n, C - a_ * t - b_ * n])
    samp = []
    for p, q in S:
        k = max(2, int(np.linalg.norm(q - p) / 10))
        samp.append(np.linspace(p, q, k))
    samp = np.concatenate(samp)
    hyp = {}
    for mir in (False, True):
        for k in range(4):
            T = _rot(k * math.pi / 2) @ (np.diag([1, -1]) if mir else np.eye(2))
            ml = MultiLineString([LineString(np.asarray(c) @ T.T) for c in curves])
            d = shapely.distance(ml, shapely.points(samp[::2]))
            name = ('mirror+' if mir else '') + f'rot{k * 90}'
            hyp[name] = dict(median_mm=round(float(np.median(d)), 1), within_25mm=round(float((d < 25).mean()), 3),
                             trunc_mean_mm=round(float(np.minimum(d, 100).mean()), 1))
    pl = []
    for (p, q), l in zip(S, L):
        if 165 < l < 185:
            u, r = inv_pos((p + q) / 2)
            if 1230 < r < 1380:
                pl.append(u)
    pl = np.sort(np.array(pl)); clusters = []
    for u in pl:
        if clusters and u - clusters[-1][-1] < 60: clusters[-1].append(u)
        else: clusters.append([u])
    post_r3 = []
    for c in clusters:
        uc = float(np.mean(c)); pid, um = min(POSTS, key=lambda x: abs(x[1] - uc))
        post_r3.append(dict(post=pid, r3_u=round(uc, 1), model_u=round(um, 1), delta_mm=round(uc - um, 1)))
    rails_r3 = sorted({(leg, mv): round(v, 1) for leg, mv, v in rails}.items())
    res = dict(
        segments_used=int(near.sum()), line_samples=int(sum(len(p) for p, _, _ in lines)), arc_vertices=len(arcv),
        as_placed=dict(rms_mm=round(float(np.sqrt(np.mean(r0 ** 2))), 1), median_abs_mm=round(float(np.median(np.abs(r0))), 1),
                       max_abs_mm=round(float(np.abs(r0).max()), 1)),
        rigid_fit=dict(dx_mm=round(float(fr.x[0]), 1), dy_mm=round(float(fr.x[1]), 1), rot_deg=round(math.degrees(fr.x[2]), 3),
                       offset_mm=round(float(np.hypot(fr.x[0], fr.x[1])), 1),
                       rms_mm=round(float(np.sqrt(np.mean(rr ** 2))), 1), max_abs_mm=round(float(np.abs(rr).max()), 1)),
        similarity_fit=dict(dx_mm=round(float(fs.x[0]), 1), dy_mm=round(float(fs.x[1]), 1), rot_deg=round(math.degrees(fs.x[2]), 3),
                            scale=round(float(fs.x[3]), 4), rms_mm=round(float(np.sqrt(np.mean(rs ** 2))), 1)),
        r3_dims=dict(legA_len=round(-ends.get('A', float('nan')), 1), legB_len=round(-ends.get('B', float('nan')), 1),
                     lines={f"{'legA_y' if ax else 'legB_x'}_{int(mv)}": round(float(np.mean(P[:, ax])), 1) for P, ax, mv in lines},
                     arc_vertex_mean_r={int(mv): round(float(np.mean([np.hypot(*v) for v, m_ in arcv if m_ == mv])), 1) for mv in (R_IN, R_TOP, R_OUT)},
                     rail_lines={f'{k[0]}_{int(k[1])}': v for k, v in rails_r3}),
        model_dims=dict(legA_len=LEG_A, legB_len=LEG_B, R_in=R_IN, R_top=R_TOP, R_out=R_OUT, rail_edges=[R_C - RAIL_W / 2, R_C + RAIL_W / 2]),
        posts=post_r3,
        orientation_hypotheses=hyp,
        note='',
    )
    best = min(hyp, key=lambda k: hyp[k]['trunc_mean_mm'])
    res['orientation_note'] = ('mirror+rot90 = legs swapped (1600 on -y, 1450 on -x): same arc, differs only at the leg ends '
                               'and post positions; R3 leg along -x = %.0f (A 1600 / B 1450), along -y = %.0f'
                               % (-ends.get('A', float('nan')), -ends.get('B', float('nan'))))
    res['orientation_best'] = best
    return res

def mass_check():
    rho, tube = 7.98e-6, 2 * (60 + 10) * 1 - 4 * 1
    post10, post7, endpl, fins = 60 * 10 * 492, 60 * 7 * 492, 60 * 3 * 484, 2 * 30 * 3 * 15
    parts = {'part (leg A)': (1200, post10, 1, 1, 10.358), 'part (leg B)': (1050, post10, 1, 1, 9.549),
             'part (arc)': (R_C * math.pi / 2, 2 * post7 + post10, 3, 0, 19.509)}
    out = {}
    for k, (L, posts, npl, nend, ref) in parts.items():
        f = lambda pl: (5 * L * tube + posts + npl * (pl[0] * pl[1] * pl[2] + fins) + nend * endpl) * rho
        a, b = f((175, 80, 8)), f((195, 100, 8))
        out[k] = dict(order_ref_kg=ref, model_kg_plate175x80=round(a, 2), dev_pct=round((a / ref - 1) * 100, 1),
                      model_kg_plate195x100=round(b, 2), dev_pct_195=round((b / ref - 1) * 100, 1))
    return out

def to_gltf(V, N):
    Rm = _rot(math.radians(ROT_DEG))
    xy = V[:, :2] @ Rm.T / 1000.0 + np.array(ORIGIN_R3M)
    P = r3_to_gltf(xy, V[:, 2] / 1000.0)
    h = r3_dir_to_gltf(N[:, :2] @ Rm.T)
    Ngl = np.c_[h[:, 0], N[:, 2], h[:, 1]]
    Ngl /= np.linalg.norm(Ngl, axis=1, keepdims=True)
    return P, Ngl

def main():
    spec = json.load(open(SPEC, encoding='utf-8'))
    for (pid, u, C, n, t), it in zip(post_frames(), spec['railing']['posts']['items']):
        assert it['id'] == pid and np.allclose(C, it['xy'], atol=0.1), (pid, C, it['xy'])

    parapet, n_top = build_parapet()
    rails, pieces = build_rails()
    parts = [
        ('RC parapet', '结构', PARAPET_MATERIAL, parapet, 1,
         'medium (geometry high: architect elevation; finish low: not specified)',
         '',
         dict(section='300 x 650, inner face vertical, outside 500 vertical + 100 x 150 chamfer, top 200 (R1200-R1400)',
              plan='leg B 1450 + arc R1200/R1500 90 deg + leg A 1600; 3100 x 2950 overall',
              base_detail=BASE_DETAIL,
              pockets=('5 block-outs 195 x 100 x 50 deep at the posts (elevation plan solid rectangles / section 3-4 recess)' if POCKET else 'none'),
              base='sits on the yard slab at FFL = y 0 (C12); RC footing/slab extent unknown (G9)',
              finish_note='')),
        ('Balustrade rails', '栏杆', RAIL_MATERIAL, rails, len(RAIL_Z) * len(pieces), 'high',
         '',
         dict(section='60 x 10 x 1 SS316 flat tube laid flat, centred on R1300 (R1270-R1330)',
              centres_z_mm=list(RAIL_Z), top_mm=TOP_Z,
              extent='between the end posts P1 (leg B 1050) and P5 (leg A 1200); part lengths 1053 / arc / 1203',
              pieces=[[round(a, 1), round(b, 1)] for a, b in pieces])),
        ('Balustrade posts', '栏杆立柱', RAIL_MATERIAL, build_posts(), len(POSTS), 'high',
         '',
         dict(section='60 x 10 SS flat bar (60 across the wall); P2/P4 = 60x7 bar of the arc piece + 3 mm end plate of the straight piece',
              z_mm=[POST_Z0, TOP_Z], foot_plates='2 x 3 mm x 15 high x 30 long per post (part DWG section B-B)',
              posts={pid: [round(float(v), 1) for v in C] for pid, u, C, n, t in post_frames()})),
        ('Base plates', '底板', RAIL_MATERIAL, build_plates(), len(POSTS), 'medium',
         '',
         dict(size_mm=[PLATE['along'], PLATE['across'], PLATE['t']], z_mm=[PLATE['z0'], PLATE['z0'] + PLATE['t']], grade='SS304')),
        ('Anchors', '锚栓', RAIL_MATERIAL, build_anchors(), 2 * len(POSTS), 'medium',
         '',
         dict(per_plate=2, spacing_mm=2 * BOLT_ALONG)),
    ]

    chk = r3_check()
    glb = GLB()
    kids, tri_total, allP = [], 0, []
    for layer_en, layer, mname, m, nobj, conf, src, extra in parts:
        V, N, UV, F = m.arrays()
        P, Ngl = to_gltf(V, N)
        allP.append(P)
        mi = mat(glb, mname)
        ntri = int(len(F))
        tri_total += ntri
        ex = node_extras('VMU05', layer_en, mname, src, conf, layer=layer, objects=nobj, triangles=ntri, **extra)
        kids.append(glb.node(f'VMU05|{layer_en}', mesh=glb.mesh(f'VMU05|{layer_en}', P, F, Ngl, mi, uvs=UV), extras=ex))
    allP = np.concatenate(allP)
    bmin, bmax = allP.min(0), allP.max(0)
    root_extras = dict(
        group='VMU05', description='RC parapet with SS316 railing',
        triangles=tri_total, bbox_min=[round(float(v), 4) for v in bmin], bbox_max=[round(float(v), 4) for v in bmax],
        size_m=[round(float(v), 4) for v in (bmax - bmin)],
        layer_en='VMU05', finish='RC_PLAIN + SS_BRUSHED', confidence='high (geometry), low (concrete finish)',
        source='',
        placement=dict(origin_R3m=list(ORIGIN_R3M), rot_deg_vs_R3m=ROT_DEG,
                       frame='local x,y = plan metres axes (= contractor elevation plan rotated 180 deg); z = FFL = yard slab top (C12)',
                       outside_faces='leg A outside face normal bearing 290.3 deg (WNW); leg B outside face bearing 20.3 deg (NNE)'),
        params=dict(ARC_SEG=ARC_SEG, BASE_DETAIL=BASE_DETAIL, PARAPET_MATERIAL=PARAPET_MATERIAL, RAIL_MATERIAL=RAIL_MATERIAL),
        r3_check=chk,
        mass_check=mass_check(),
        deviations_from_spec=[
            'rails end at the end posts (1203 / 1053); spec rail_extent 1299.5 / 1159 are frame diagonals',
            ('base plate 175 x 80 x 8 on the floor of a 195 x 100 x 50 block-out (drawing); the specification reads 195 x 100 x 8 on top'
             if POCKET else 'surface mode: 195 x 100 x 8 plate on the parapet top (spec reading)'),
        ],
        builder='build/build_vmu05.py',
    )
    root = glb.node('VMU05', children=kids, extras=root_extras, root=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    glb.save(OUT, dict(title='mock-up VMU-05 (RC parapet + SS316 railing)',
                       frame='glTF x=East, y=Up, z=-North (build/site_frame.py); y 0 = yard slab top'))
    print(f'wrote {OUT}  triangles {tri_total}  bbox {bmin.round(3)} .. {bmax.round(3)}  size {(bmax - bmin).round(3)}')
    print('R3 check:', json.dumps({k: chk[k] for k in ('as_placed', 'rigid_fit', 'similarity_fit', 'orientation_best')}))
    return root_extras

if __name__ == '__main__':
    main()
