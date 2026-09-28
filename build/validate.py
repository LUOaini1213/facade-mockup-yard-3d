"""Validation harness for the model (python validate.py [--stages ...] [--skip-render]): camera poses of site photos by a
joint PnP on hand-picked steel-frame points (shared focal length, leave-one-out residuals), column silhouette
residuals, headless renders of the viewer from the solved poses, photo / render composites and colour swatches,
a gantry-girder height check, a layout-plan check of every mock-up footprint (trimmed ICP) and a check of the GLB
materials against the material contract. The photos, the picked points and the contract are private inputs in
SOURCES_DIR and are not included; outputs go to build/_scratch/validation.
"""
import os, sys, json, math, time, base64, asyncio, random, functools, argparse, re, pickle, datetime
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import numpy as np
import cv2
import trimesh
from PIL import Image, ImageDraw, ImageFont
from scipy.optimize import least_squares
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial import ConvexHull, cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODEL = os.path.join(ROOT, 'model')
OUT = os.path.join(HERE, '_scratch', 'validation')
SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')
PHOTO_SRC_DIR = os.path.join(SOURCES_DIR, 'photos')
CAMERA_POSES = os.path.join(SOURCES_DIR, 'camera_poses.json')
_PRIV = json.load(open(os.path.join(SOURCES_DIR, 'photo_correspondences.json'), encoding='utf-8'))
VIEWER_URL = 'http://127.0.0.1:%s/index.html' % os.environ.get('MOCKUP_PORT', '18090')
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, HERE)

PICK_W, PICK_H = 1536, 2048
VIEW_W, VIEW_H = 1050, 1400
SHARED_FOCAL = True
ROBUST_F_SCALE = 4.0
SIL_SEARCH_PX = 14
SIL_STEP_M = 0.20
RESIDUAL_TARGET_M = 0.30
R3_TARGET_M = 0.05
R3_RASTER_M = 0.01
COLOR_TOL_DE = 2.0
PBR_TOL = 0.051
TODAY = time.strftime('%Y-%m-%d')

PHOTOS = {int(k): v for k, v in _PRIV['photos'].items()}
INIT = {int(k): (tuple(v[0]), v[1], v[2], v[3]) for k, v in _PRIV['init'].items()}

def font(sz):
    for f in ('arial.ttf', 'msyh.ttc', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(f, sz)
        except Exception:
            pass
    return ImageFont.load_default()

def srgb_to_lin(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

def lin_to_srgb(c):
    c = np.clip(np.asarray(c, float), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)

def hex_to_rgb(h):
    h = h.strip().lstrip('#'); return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)]) / 255.0

def rgb_to_hex(c):
    c = np.clip(np.round(np.asarray(c) * 255), 0, 255).astype(int); return '#%02X%02X%02X' % tuple(c)

def srgb_to_lab(c):
    l = srgb_to_lin(c)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    X = M @ l / np.array([0.95047, 1.0, 1.08883])
    f = np.where(X > 216 / 24389, np.cbrt(X), (24389 / 27 * X + 16) / 116)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])

@functools.lru_cache(None)
def glb_nodes(fname):
    s = trimesh.load(os.path.join(MODEL, fname))
    out = {}
    for n in s.graph.nodes_geometry:
        T, g = s.graph[n]
        m = s.geometry[g].copy(); m.apply_transform(T)
        out[n] = m
    return out

def sel(fname, pred):
    return {k: v for k, v in glb_nodes(fname).items() if pred(k)}

@functools.lru_cache(None)
def feature_edges(fname, name, angle_deg=25):
    m = glb_nodes(fname)[name].copy()
    m.merge_vertices(digits_vertex=4)
    E = m.face_adjacency_edges[m.face_adjacency_angles > math.radians(angle_deg)]
    ed = np.sort(m.edges, axis=1); u, c = np.unique(ed, axis=0, return_counts=True)
    B = u[c == 1]
    E = np.vstack([E, B]) if len(B) else E
    return m.vertices[E[:, 0]], m.vertices[E[:, 1]]

class Cam:
    def __init__(self, rvec, tvec, f, W, H, cx=None, cy=None):
        self.rvec = np.asarray(rvec, float).reshape(3); self.tvec = np.asarray(tvec, float).reshape(3)
        self.f = float(f); self.W = W; self.H = H
        self.cx = W / 2 if cx is None else cx; self.cy = H / 2 if cy is None else cy
        self.R = cv2.Rodrigues(self.rvec)[0]

    @property
    def C(self):
        return -self.R.T @ self.tvec

    def cam_coords(self, X):
        return (self.R @ np.asarray(X, float).T).T + self.tvec

    def project(self, X):
        P = self.cam_coords(X)
        return P[:, :2] / P[:, 2:3] * self.f + [self.cx, self.cy], P[:, 2]

    @staticmethod
    def from_hpr(C, heading, pitch, roll, f, W, H):
        h, p, r = map(math.radians, (heading, pitch, roll))
        d = np.array([math.sin(h) * math.cos(p), math.sin(p), -math.cos(h) * math.cos(p)])
        right = np.array([math.cos(h), 0, math.sin(h)])
        down = np.cross(d, right); down /= np.linalg.norm(down)
        cr, sr = math.cos(r), math.sin(r)
        R = np.vstack([cr * right + sr * down, -sr * right + cr * down, d])
        return Cam(cv2.Rodrigues(R)[0].ravel(), -R @ np.asarray(C, float), f, W, H)

    def hpr(self):
        d = self.R[2]; right = self.R[0]
        heading = math.degrees(math.atan2(d[0], -d[2])) % 360
        pitch = math.degrees(math.asin(np.clip(d[1], -1, 1)))
        h = math.radians(heading); r0 = np.array([math.cos(h), 0, math.sin(h)])
        down0 = np.cross(d, r0); down0 /= np.linalg.norm(down0)
        return heading, pitch, math.degrees(math.atan2(right @ down0, right @ r0))

    def fov_v(self):
        return math.degrees(2 * math.atan(self.H / 2 / self.f))

    def scaled(self, W, H):
        k = W / self.W
        return Cam(self.rvec, self.tvec, self.f * k, W, H, self.cx * k, self.cy * k)

    def backproject_ground(self, uv, y=0.0):
        uv = np.asarray(uv, float)
        dc = np.c_[(uv[:, 0] - self.cx) / self.f, (uv[:, 1] - self.cy) / self.f, np.ones(len(uv))]
        d = (self.R.T @ dc.T).T; C = self.C
        return C + d * ((y - C[1]) / d[:, 1])[:, None]

    def viewer_pose(self, dist=10.0):
        C = self.C; d = self.R[2]; right = self.R[0]

        def xaxis(a):
            up = np.array([math.sin(a), math.cos(a), 0.0]); x = np.cross(up, -d); return x / np.linalg.norm(x)
        A = np.linspace(-1.2, 1.2, 24001)
        errs = [math.atan2(np.cross(xaxis(a), right) @ d, xaxis(a) @ right) for a in A]
        i = int(np.argmin(np.abs(errs)))
        pose = {'pos': [round(float(v), 4) for v in C], 'target': [round(float(v), 4) for v in C + d * dist],
                'fov': round(self.fov_v(), 4), 'roll': round(float(A[i]), 5)}
        return pose, math.degrees(errs[i])

def threejs_R(pose):
    p = np.array(pose['pos']); t = np.array(pose['target']); r = pose.get('roll', 0)
    z = p - t; z /= np.linalg.norm(z)
    up = np.array([math.sin(r), math.cos(r), 0.0]); x = np.cross(up, z); x /= np.linalg.norm(x); y = np.cross(z, x)
    return np.vstack([x, -y, -z])

U_AX = np.array([0.9377, 0.3475]); V_AX = np.array([0.3475, -0.9377])

def _clusters(V, tol):
    lab = fcluster(linkage(V[:, [0, 2]], 'single'), tol, 'distance')
    return [V[lab == k] for k in np.unique(lab)]

@functools.lru_cache(None)
def model_features():
    F, CORNERS, COLS = {}, {}, {}
    cad = sel('vmu_cad.glb', lambda n: n.startswith('VMU01|Steel'))
    col = [v for k, v in cad.items() if '300X300' in k][0].vertices
    cols = []
    for W in _clusters(col, 0.35):
        c = (W.min(0) + W.max(0)) / 2; cols.append((c[0], c[2], W[:, 1].max(), W))
    assert len(cols) == 6, 'expected 6 SHS300 columns in VMU01|Steel frame, got %d' % len(cols)
    c2 = min(cols, key=lambda c: np.array([c[0], c[1]]) @ (U_AX + V_AX))
    for c in cols:
        p = np.array([c[0], c[1]]) - np.array([c2[0], c2[1]]); uu, vv = p @ U_AX, p @ V_AX
        k = {(0, 0): 'C2', (1, 0): 'C1', (0, 1): 'C4', (1, 1): 'C3', (2, 1): 'C5', (2, 0): 'C6'}[(0 if uu < 0.8 else (1 if uu < 3 else 2), 0 if vv < 2 else 1)]
        x, z, top, W = c
        F[k + '_base'] = np.array([x, 0.0, z]); F[k + '_top'] = np.array([x, top, z])
        Tv = W[W[:, 1] > top - 0.005][:, [0, 2]]; hv = Tv[ConvexHull(Tv).vertices]
        ang = np.arctan2(hv[:, 1] - z, hv[:, 0] - x); cc = np.array([x, z])
        corners = [hv[np.argmax(np.cos(ang - a0) * np.linalg.norm(hv - cc, axis=1))] for a0 in np.radians([20, 110, 200, 290])]
        CORNERS[k + '_top'] = np.array([[q[0], top, q[1]] for q in corners])
        COLS[k] = (np.array(corners), top)
    bp = [v for k, v in cad.items() if 'Base plates' in k][0].vertices
    for W in _clusters(bp, 0.7):
        pc = W.mean(0)
        d = {k: math.hypot(pc[0] - F[k + '_base'][0], pc[2] - F[k + '_base'][2]) for k in COLS}
        k = min(d, key=d.get)
        if d[k] > 0.2:
            F['B' + k[1] + '_foot'] = np.array([pc[0], 0.0, pc[2]])
    for i, (b, t) in enumerate(old_canopy_columns()):
        F['O%d_base' % (i + 1)] = b; F['O%d_top' % (i + 1)] = t
    return F, CORNERS, COLS

def old_canopy_columns():
    cwd = os.getcwd(); os.chdir(HERE)
    try:
        from site_frame import r3_to_gltf
        C = pickle.load(open('legacy_cad_cache_n.pkl', 'rb')); R = json.load(open('group_registration.json'))
    finally:
        os.chdir(cwd)
    r = R['reg']['VMU01']; a = math.radians(r['rot_deg']); c, s_ = math.cos(a), math.sin(a)
    Rm = np.array([[c, s_], [-s_, c]]); c0 = np.array(r['c0']); t = np.array([r['tx'], r['ty']])
    out = []
    for i, m in enumerate(C['meshes']):
        if R['assign'].get(str(i)) == 'VMU01' and m['layer'] == '铁架::150X5圆管':
            V = np.asarray(m['V'])
            P = r3_to_gltf((V[:, :2].mean(0, keepdims=True) - c0) @ Rm + t, 0.0)[0]
            out.append((P.copy(), P + [0, V[:, 2].max(), 0]))
    out.sort(key=lambda bt: (bt[0][0], bt[0][2]))
    return out

def rail_lines():
    out = []
    for n, m in sel('site_ground.glb', lambda n: 'rail head' in n).items():
        m = m.copy(); m.merge_vertices()
        for p in m.split(only_watertight=False):
            V = p.vertices[:, [0, 2]]; c = V.mean(0); _, _, vt = np.linalg.svd(V - c); d = vt[0]
            out.append((c, d / np.linalg.norm(d)))
    return out

def predict(cam, keys):
    F, CORNERS, _ = model_features()
    out = []
    for k in keys:
        if k in CORNERS:
            uv, _ = cam.project(CORNERS[k]); out.append(uv[np.argmin(uv[:, 1])])
        else:
            out.append(cam.project(F[k][None])[0][0])
    return np.array(out)

def depth_of(cam, k):
    F, CORNERS, _ = model_features()
    X = CORNERS[k].mean(0) if k in CORNERS else F[k]
    return float(cam.cam_coords(X[None])[0, 2])

def solve_joint(ids, f0=1430.0, fixed_f=None, exclude=None):
    cams0 = {}
    for i in ids:
        C, h, p, r = INIT[i]; cams0[i] = Cam.from_hpr(C, h, p, r, f0, PICK_W, PICK_H)
    obs = {i: {k: v for k, v in PHOTOS[i]['obs'].items() if (i, k) != exclude} for i in ids}
    W8 = {i: np.array([PHOTOS[i].get('weights', {}).get(k, 1.0) for k in obs[i]]) for i in ids}

    def unpack(x):
        f = fixed_f if fixed_f else x[0]; o = 0 if fixed_f else 1
        return {i: Cam(x[o + 6 * j: o + 6 * j + 3], x[o + 6 * j + 3: o + 6 * j + 6], f, PICK_W, PICK_H) for j, i in enumerate(ids)}

    def res(x):
        cams = unpack(x); r = []
        for i in ids:
            ks = list(obs[i]); uv = np.array([obs[i][k] for k in ks], float)
            r.append(((predict(cams[i], ks) - uv) * W8[i][:, None]).ravel())
        return np.concatenate(r)
    x0 = ([] if fixed_f else [f0]) + [v for i in ids for v in np.r_[cams0[i].rvec, cams0[i].tvec]]
    s = least_squares(res, np.array(x0, float), loss='soft_l1', f_scale=ROBUST_F_SCALE, x_scale='jac', max_nfev=4000)
    cams = unpack(s.x)
    cov = None
    try:
        J = s.jac; dof = max(1, len(s.fun) - len(s.x)); s2 = (s.fun ** 2).sum() / dof
        cov = np.linalg.pinv(J.T @ J) * s2
    except Exception:
        pass
    return cams, s, cov

def pose_sd(cams, cov, ids, fixed_f=None):
    out = {}
    o = 0 if fixed_f else 1
    for j, i in enumerate(ids):
        sl = slice(o + 6 * j, o + 6 * j + 6); Cv = cov[sl, sl]
        cam = cams[i]; p0 = np.r_[cam.rvec, cam.tvec]

        def g(p):
            c = Cam(p[:3], p[3:], cam.f, PICK_W, PICK_H); h, pi, r = c.hpr(); return np.r_[c.C, h, pi]
        J = np.zeros((5, 6)); g0 = g(p0)
        for k in range(6):
            dp = np.zeros(6); dp[k] = 1e-6; J[:, k] = (g(p0 + dp) - g0) / 1e-6
        sd = np.sqrt(np.diag(J @ Cv @ J.T))
        out[i] = {'C_sd_m': sd[:3].round(3).tolist(), 'heading_sd_deg': round(float(sd[3]), 3), 'pitch_sd_deg': round(float(sd[4]), 3)}
    if not fixed_f:
        out['f_sd_px'] = round(float(math.sqrt(cov[0, 0])), 1)
    return out

def stage_photos():
    ids = list(PHOTOS)
    print('== photos: joint PnP over', ids)
    F, CORNERS, COLS = model_features()
    per = {}
    for i in ids:
        cams, s, cov = solve_joint([i])
        per[i] = {'f': round(cams[i].f, 1), 'f_sd': round(float(math.sqrt(cov[0, 0])), 1) if cov is not None else None}
    cams, s, cov = solve_joint(ids)
    f = cams[ids[0]].f
    sd = pose_sd(cams, cov, ids)
    print('   shared focal %.1f px (2048 frame) = %.1f mm equiv. (sd %.1f px); per-photo free focal: %s' % (
        f, f / 1024 * 17.31, sd.get('f_sd_px', float('nan')), {k: v['f'] for k, v in per.items()}))
    R = {'focal_px_2048': round(f, 2), 'focal_sd_px': sd.get('f_sd_px'), 'lens_equiv_mm': round(f / 1024 * 17.31, 2),
         'per_photo_free_focal': per, 'photos': {}}
    rails = rail_lines()
    for i in ids:
        cam = cams[i]; P = PHOTOS[i]; ks = list(P['obs'])
        uv = np.array([P['obs'][k] for k in ks], float); pr = predict(cam, ks)
        fit = np.linalg.norm(pr - uv, axis=1)
        loo = {}
        for k in ks:
            c2, _, _ = solve_joint([i], fixed_f=f, exclude=(i, k))
            e = float(np.linalg.norm(predict(c2[i], [k])[0] - np.array(P['obs'][k])))
            z = depth_of(c2[i], k)
            loo[k] = {'px': round(e, 2), 'm': round(e * z / f, 3), 'depth_m': round(z, 2)}
        chk = {}
        for k, o in P.get('checks', {}).items():
            e = float(np.linalg.norm(predict(cam, [k])[0] - np.array(o))); z = depth_of(cam, k)
            chk[k] = {'px': round(e, 2), 'm': round(e * z / f, 3), 'depth_m': round(z, 2)}
        rail = {}
        for name, pts in P.get('rails', {}).items():
            G = cam.backproject_ground(pts)[:, [0, 2]]
            best = None
            for c, d in rails:
                n = np.array([-d[1], d[0]]); off = (G - c) @ n
                if best is None or abs(off.mean()) < abs(best[0].mean()):
                    best = (off, c, d, n)
            off, c, d, n = best
            ang = math.degrees(math.atan2(*(np.polyfit((G - c) @ d, off, 1)[:1]), 1)) if len(G) > 2 else None
            rail[name] = {'ground_pts': G.round(3).tolist(), 'offset_from_model_rail_m': off.round(3).tolist(),
                          'mean_offset_m': round(float(off.mean()), 3), 'model_rail_point': c.round(3).tolist(),
                          'normal_xz': n.round(4).tolist(), 'angle_deg': None if ang is None else round(ang, 2)}
        pose, roll_res = cam.scaled(VIEW_W, VIEW_H).viewer_pose()
        Rt = threejs_R(pose); dR = cv2.Rodrigues(Rt @ cam.R.T)[0]; rot_err = math.degrees(np.linalg.norm(dR))
        h, p, r = cam.hpr()
        R['photos'][i] = {
            'ref_id': P['ref'], 'src': P['src'], 'n_obs': len(ks),
            'camera_glTF': cam.C.round(3).tolist(), 'heading_deg': round(h, 2), 'pitch_deg': round(p, 2), 'roll_deg': round(r, 2),
            'fov_v_deg_1400': round(cam.scaled(VIEW_W, VIEW_H).fov_v(), 3), 'pose_sd': sd[i],
            'fit_px': {k: round(float(e), 2) for k, e in zip(ks, fit)}, 'fit_rms_px': round(float(np.sqrt((fit ** 2).mean())), 2),
            'loo': loo, 'loo_max_m': max(v['m'] for v in loo.values()), 'loo_median_m': float(np.median([v['m'] for v in loo.values()])),
            'checks': chk, 'rails': rail, 'viewer_pose': pose, 'viewer_rot_err_deg': round(rot_err, 4)}
        print('   p%-3d %s cam %s h %.1f p %.1f r %.1f | fit rms %.1f px | LOO median %.3f max %.3f m | checks %s | viewer rot err %.3f deg' % (
            i, P['ref'], cam.C.round(2), h, p, r, R['photos'][i]['fit_rms_px'], R['photos'][i]['loo_median_m'],
            R['photos'][i]['loo_max_m'], {k: v['m'] for k, v in chk.items()}, rot_err))
        for name, v in rail.items():
            print('        rail %-24s mean offset %.3f m (model rail at %s)' % (name, v['mean_offset_m'], v['model_rail_point']))
    json.dump({'cams': {i: {'rvec': cams[i].rvec.tolist(), 'tvec': cams[i].tvec.tolist(), 'f': cams[i].f} for i in ids}},
              open(os.path.join(OUT, 'cams.json'), 'w'), indent=1)
    return cams, R

def load_cams():
    d = json.load(open(os.path.join(OUT, 'cams.json')))['cams']
    return {int(i): Cam(v['rvec'], v['tvec'], v['f'], PICK_W, PICK_H) for i, v in d.items()}

def update_photos_json(cams, R):
    path = CAMERA_POSES
    L = json.load(open(path, encoding='utf-8'))
    old = {p['id']: p.get('pose') for p in L}
    for p in L:
        i = p['id']
        if i in cams:
            assert (p['w'], p['h']) == (VIEW_W, VIEW_H), p
            ph = R['photos'][i]
            pose = dict(ph['viewer_pose'])
            pose['note'] = ''
            pose['solve'] = {'by': 'build/validate.py %s' % TODAY, 'method': 'PnP, %d VMU-01 steel-frame points, shared focal %.1f px@2048 (%.1f mm equiv.)' % (
                ph['n_obs'], R['focal_px_2048'], R['lens_equiv_mm']), 'fit_rms_px_2048': ph['fit_rms_px'],
                'loo_max_m': ph['loo_max_m'], 'photo_ref': ph['ref_id'],
                'fov_note': 'fov = vertical degrees for this 1050x1400 frame; used as is by window.__poseShot'}
            if old.get(i):
                if str(old[i].get('solve', {}).get('by', '')).startswith('build/validate.py'):
                    if 'previous' in old[i]:
                        pose['previous'] = old[i]['previous']
                else:
                    pose['previous'] = {k: old[i][k] for k in ('pos', 'target', 'note') if k in old[i]}
            p['pose'] = pose
    def _nb(x):
        x = json.loads(json.dumps(x))
        for q in x:
            (q.get('pose') or {}).get('solve', {}).pop('by', None)
        return x
    if _nb(L) == _nb(json.load(open(path, encoding='utf-8'))):
        print('   camera poses unchanged (identical to the stored solve)', sorted(cams))
        return
    json.dump(L, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('   camera poses updated for', sorted(cams))

@functools.lru_cache(None)
def photo_gray(src):
    im = cv2.imdecode(np.fromfile(os.path.join(PHOTO_SRC_DIR, src), np.uint8), cv2.IMREAD_GRAYSCALE)
    return cv2.GaussianBlur(im.astype(np.float32), (0, 0), 1.0)

def stage_silhouette(cams):
    print('== silhouette: column edge residuals')
    from scipy.ndimage import map_coordinates
    F, CORNERS, COLS = model_features()
    out = {}
    for i, cam in cams.items():
        g = photo_gray(PHOTOS[i]['src']); res = {}
        samples = []
        for k, (corners, top) in COLS.items():
            L, Rr, Z = [], [], []
            for h in np.arange(0.5, top - 0.4, SIL_STEP_M):
                P = np.c_[corners[:, 0], np.full(4, h), corners[:, 1]]
                uv, z = cam.project(P)
                if (z <= 0.5).any():
                    continue
                c_uv, _ = cam.project(np.array([[F[k + '_base'][0], h, F[k + '_base'][2]], [F[k + '_base'][0], h + 1, F[k + '_base'][2]]]))
                ax = c_uv[1] - c_uv[0]; ax /= np.linalg.norm(ax); nrm = np.array([-ax[1], ax[0]])
                if nrm[0] < 0:
                    nrm = -nrm
                s = (uv - c_uv[0]) @ nrm
                for side, s0 in (('L', s.min()), ('R', s.max())):
                    p0 = c_uv[0] + nrm * s0
                    if not (SIL_SEARCH_PX + 2 < p0[0] < PICK_W - SIL_SEARCH_PX - 2 and 2 < p0[1] < PICK_H - 2):
                        continue
                    t = np.arange(-SIL_SEARCH_PX, SIL_SEARCH_PX + 0.01, 0.5)
                    pts = p0[None] + t[:, None] * nrm[None]
                    prof = map_coordinates(g, [pts[:, 1], pts[:, 0]], order=1)
                    gr = np.abs(np.gradient(prof))
                    j = int(np.argmax(gr))
                    if gr[j] < 3.0 or j in (0, len(t) - 1):
                        continue
                    (L if side == 'L' else Rr).append(t[j]); samples.append((k, side, p0 + t[j] * nrm, p0))
                Z.append(z.mean())
            def robust(a):
                a = np.array(a)
                if len(a) < 5:
                    return None, len(a)
                m = np.median(a); mad = np.median(np.abs(a - m)) * 1.4826 + 1e-6
                a = a[np.abs(a - m) < 2.5 * mad + 1.0]
                return float(np.median(a)), len(a)
            l, nl = robust(L); r, nr = robust(Rr)
            if l is None or r is None or not Z:
                continue
            zm = float(np.median(Z)); k_m = zm / cam.f
            res[k] = {'left_px': round(l, 2), 'right_px': round(r, 2), 'centre_m': round((l + r) / 2 * k_m, 3),
                      'width_diff_m': round((r - l) * k_m, 3), 'n': [nl, nr], 'depth_m': round(zm, 1)}
        out[i] = {'columns': res, 'max_abs_centre_m': max([abs(v['centre_m']) for v in res.values()] or [None]),
                  'samples': samples}
        print('   p%-3d' % i, {k: (v['centre_m'], v['width_diff_m']) for k, v in res.items()})
    return out

MODE_JS = r"""
(mode) => {
  const S = window.__v.scene;
  if (!window.__visState) { window.__visState = new Map(); S.traverse((o) => window.__visState.set(o, o.visible)); }
  S.traverse((o) => { if (window.__visState.has(o)) o.visible = window.__visState.get(o); });
  if (mode === 'future') return {mode, hidden: 0};
  const chain = (o) => { const s = []; let p = o; while (p) { s.push(p.name || ''); p = p.parent; } return s.join('<'); };
  let hidden = 0, kept = 0;
  S.traverse((o) => {
    if (!(o.isMesh || o.isInstancedMesh || o.isLine || o.isLineSegments || o.isPoints)) return;
    const c = chain(o);
    if (!/(^|<)CAD(<|$)/.test(c)) return;                       // context, ground, vegetation stay
    const keep = /VMU01\|Steel_frame/.test(c);
    if (!keep) { o.visible = false; hidden++; } else kept++;
  });
  return {mode, hidden, kept};
}
"""

async def _render(jobs, timeout=300):
    from playwright.async_api import async_playwright
    from urllib.parse import unquote
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=['--enable-gpu', '--ignore-gpu-blocklist', '--use-angle=d3d11'])
        pg = await (await b.new_context(viewport={'width': 1200, 'height': 750})).new_page()
        errs, pending = [], {}
        pg.on('pageerror', lambda e: errs.append(str(e)))

        async def on_save(route, request):
            name = unquote(request.url.split('name=')[-1]); out = pending.get(name)
            if out:
                open(out, 'wb').write(base64.b64decode((request.post_data or '').split(',', 1)[-1]))
            await route.fulfill(status=200, body='ok')
        await pg.route('**/save?*', on_save)
        t0 = time.time()
        await pg.goto(VIEWER_URL + '?v=%d' % random.randint(0, 10 ** 9))
        while time.time() - t0 < timeout:
            try:
                if await pg.evaluate("(() => { const e = document.getElementById('loading'); return !!e && e.style.display === 'none'; })()"):
                    break
            except Exception:
                pass
            await asyncio.sleep(1)
        rep = await pg.evaluate('window.__ready')
        await asyncio.sleep(2)
        print('   viewer ready in %.0f s (%s triangles, files %s)' % (time.time() - t0, rep.get('triangles'), rep.get('files')))
        info = []
        for pose, out, W, H, mode in jobs:
            name = 'shot_%d.png' % random.randint(0, 10 ** 9); pending[name] = out
            r = await pg.evaluate(MODE_JS, mode)
            await pg.evaluate('([p,n,W,H]) => window.__poseShot(p,n,W,H)', [pose, name, W, H])
            await pg.evaluate(MODE_JS, 'future')
            cam_state = await pg.evaluate("(() => { const c = window.__v.camera; return {fov: c.fov, aspect: c.aspect}; })()")
            info.append({'out': os.path.relpath(out, ROOT), 'mode': r, 'ok': os.path.exists(out)})
            print('   rendered', os.path.relpath(out, ROOT), r)
        for e in errs[:5]:
            print('   PAGEERR', e[:200])
        await b.close()
        return info, rep

def stage_render(cams):
    print('== render: window.__poseShot through', VIEWER_URL)
    jobs = []
    for i, cam in cams.items():
        pose, _ = cam.scaled(VIEW_W, VIEW_H).viewer_pose()
        for mode in ('future', 'frame'):
            jobs.append((pose, os.path.join(OUT, 'p%02d_render_%s.png' % (i, mode)), VIEW_W, VIEW_H, mode))
    return asyncio.run(_render(jobs))

def photo_view(i):
    L = {p['id']: p for p in json.load(open(CAMERA_POSES, encoding='utf-8'))}
    im = Image.open(os.path.join(SOURCES_DIR, L[i]['file'])).convert('RGB')
    assert im.size == (VIEW_W, VIEW_H)
    return im

def check_resize(i):
    a = np.asarray(photo_view(i).convert('L').resize((210, 280)), float)
    o = Image.open(os.path.join(PHOTO_SRC_DIR, PHOTOS[i]['src'])).convert('L').resize((210, 280))
    b = np.asarray(o, float)
    return float(np.corrcoef(a.ravel(), b.ravel())[0, 1])

def draw_edges(im, cam, P0, P1, color, width=1, near=0.3):
    d = ImageDraw.Draw(im)
    A = cam.cam_coords(P0); B = cam.cam_coords(P1)
    for a, b in zip(A, B):
        if a[2] < near and b[2] < near:
            continue
        if a[2] < near:
            a = a + (near - a[2]) / (b[2] - a[2]) * (b - a)
        if b[2] < near:
            b = b + (near - b[2]) / (a[2] - b[2]) * (a - b)
        ua = a[:2] / a[2] * cam.f + [cam.cx, cam.cy]; ub = b[:2] / b[2] * cam.f + [cam.cx, cam.cy]
        if max(np.abs(ua).max(), np.abs(ub).max()) > 1e5:
            continue
        d.line([tuple(ua), tuple(ub)], fill=color, width=width)

def stage_composite(cams, R, SIL):
    print('== composite')
    F, CORNERS, COLS = model_features()
    k = VIEW_W / PICK_W
    sheets = []
    for i, cam in cams.items():
        cv_ = cam.scaled(VIEW_W, VIEW_H); ph = photo_view(i); P = PHOTOS[i]; st = R['photos'][i]
        fr = Image.open(os.path.join(OUT, 'p%02d_render_frame.png' % i)).convert('RGB') if os.path.exists(os.path.join(OUT, 'p%02d_render_frame.png' % i)) else None
        fu = Image.open(os.path.join(OUT, 'p%02d_render_future.png' % i)).convert('RGB') if os.path.exists(os.path.join(OUT, 'p%02d_render_future.png' % i)) else None
        panels = [('photo %s (model id p%d)' % (P['ref'], i), ph)]
        if fu: panels.append(('model, future state', fu))
        if fr: panels.append(('model, VMU-01 steel frame + context (current state)', fr))
        w = 700; h = int(w * VIEW_H / VIEW_W)
        side = Image.new('RGB', (len(panels) * w + (len(panels) - 1) * 8, h + 40), (24, 24, 24)); d = ImageDraw.Draw(side)
        for j, (t, im) in enumerate(panels):
            side.paste(im.resize((w, h), Image.LANCZOS), (j * (w + 8), 40)); d.text((j * (w + 8) + 8, 10), t, fill=(255, 255, 255), font=font(20))
        side.save(os.path.join(OUT, 'p%02d_side.jpg' % i), quality=90)
        if fr: Image.blend(ph, fr, 0.5).save(os.path.join(OUT, 'p%02d_blend_frame.jpg' % i), quality=90)
        if fu: Image.blend(ph, fu, 0.45).save(os.path.join(OUT, 'p%02d_blend_future.jpg' % i), quality=90)
        ov = Image.blend(ph, Image.new('RGB', ph.size, (0, 0, 0)), 0.35)
        for n in sel('vmu_cad.glb', lambda n: n.startswith('VMU01|Steel')):
            draw_edges(ov, cv_, *feature_edges('vmu_cad.glb', n), (255, 225, 0), 1)
        for n in sel('site_ground.glb', lambda n: 'rail head' in n or 'red safety' in n):
            draw_edges(ov, cv_, *feature_edges('site_ground.glb', n, 40), (255, 70, 70), 2)
        d = ImageDraw.Draw(ov); fs = font(14)
        oc = old_canopy_columns()
        for b_, t_ in oc:
            uv, z = cv_.project(np.array([b_, t_]))
            if (z > 0).all(): d.line([tuple(uv[0]), tuple(uv[1])], fill=(255, 150, 0), width=1)
        for kk, o in list(P['obs'].items()) + list(P.get('checks', {}).items()):
            o = np.array(o) * k; pr = predict(cv_, [kk])[0]
            col = (0, 255, 255) if kk in P['obs'] else (255, 150, 0)
            d.line([(o[0] - 7, o[1]), (o[0] + 7, o[1])], fill=(255, 40, 40), width=2); d.line([(o[0], o[1] - 7), (o[0], o[1] + 7)], fill=(255, 40, 40), width=2)
            d.ellipse([pr[0] - 5, pr[1] - 5, pr[0] + 5, pr[1] + 5], outline=col, width=2)
            v = pr + (pr - o) * 4; d.line([tuple(pr), tuple(v)], fill=col, width=1)
            lab = kk.replace('_base', '').replace('_foot', 'f').replace('_top', 't')
            e = st['loo'].get(kk, st['checks'].get(kk, {})).get('m')
            d.text((pr[0] + 7, pr[1] - 16), '%s %s' % (lab, '' if e is None else '%.2f' % e), fill=col, font=fs)
        for name, pts in P.get('rails', {}).items():
            for q in pts:
                q = np.array(q) * k; d.ellipse([q[0] - 4, q[1] - 4, q[0] + 4, q[1] + 4], outline=(255, 255, 255), width=2)
        if SIL and i in SIL:
            for kk, side_, p_edge, p_pred in SIL[i]['samples'][::2]:
                a = p_pred * k; b = p_edge * k
                d.ellipse([b[0] - 1.5, b[1] - 1.5, b[0] + 1.5, b[1] + 1.5], fill=(0, 255, 0))
        box = ['%s  (model id p%d)  %s' % (P['ref'], i, P['src']),
               'camera glTF (%.2f, %.2f, %.2f) m, heading %.1f, pitch %.1f, roll %.1f deg, fov_v %.2f deg (1050x1400)' % (
                   *st['camera_glTF'], st['heading_deg'], st['pitch_deg'], st['roll_deg'], st['fov_v_deg_1400']),
               'PnP: %d VMU-01 frame points, fit rms %.1f px@2048, leave-one-out median %.3f m, max %.3f m (target < %.2f m)' % (
                   st['n_obs'], st['fit_rms_px'], st['loo_median_m'], st['loo_max_m'], RESIDUAL_TARGET_M),
               'red +: picked photo point; cyan o: model projection (label = LOO residual m, line = 4x residual); orange: old canopy columns (check)',
               'yellow: model VMU01 steel frame edges; red lines: model crane rails + safety lines; white o: photo red-line picks; green dots: detected column silhouette edges']
        bw = Image.new('RGB', (VIEW_W, 20 * len(box) + 10), (0, 0, 0)); db = ImageDraw.Draw(bw)
        for j, t in enumerate(box):
            db.text((8, 5 + 20 * j), t, fill=(255, 255, 255), font=font(13))
        full = Image.new('RGB', (VIEW_W, VIEW_H + bw.height)); full.paste(ov, (0, 0)); full.paste(bw, (0, VIEW_H))
        full.save(os.path.join(OUT, 'p%02d_overlay.jpg' % i), quality=90)
        sheets.append(full)
        print('   p%02d side / blend / overlay written' % i)
    tw = 525; th = int(tw * sheets[0].height / sheets[0].width)
    cs = Image.new('RGB', (len(sheets) * tw + (len(sheets) - 1) * 6, th), (20, 20, 20))
    for j, s in enumerate(sheets):
        cs.paste(s.resize((tw, th), Image.LANCZOS), (j * (tw + 6), 0))
    cs.save(os.path.join(OUT, 'photos_contact_sheet.jpg'), quality=88)

def region_masks(cam):
    F, CORNERS, COLS = model_features()
    steel = np.zeros((VIEW_H, VIEW_W), np.uint8)
    for k, (corners, top) in COLS.items():
        P = np.vstack([np.c_[corners[:, 0], np.full(4, h), corners[:, 1]] for h in (2.0, min(12.0, top - 1.0))])
        uv, z = cam.project(P)
        if (z > 0).all():
            cv2.fillConvexPoly(steel, cv2.convexHull(np.round(uv).astype(np.int32)), 255)
    steel = cv2.erode(steel, np.ones((5, 5), np.uint8))
    yy, xx = np.mgrid[0:VIEW_H, 0:VIEW_W]
    uv = np.c_[xx.ravel(), yy.ravel()].astype(float)
    dc = np.c_[(uv[:, 0] - cam.cx) / cam.f, (uv[:, 1] - cam.cy) / cam.f, np.ones(len(uv))]
    d = (cam.R.T @ dc.T).T; t = -cam.C[1] / d[:, 1]
    dist = np.where(t > 0, t * np.linalg.norm(d[:, [0, 2]], axis=1), -1).reshape(VIEW_H, VIEW_W)
    ground = ((dist > 3) & (dist < 25)).astype(np.uint8) * 255
    occ = np.zeros_like(ground)
    for fname, pred in (('vmu_cad.glb', lambda n: n.startswith('VMU01|Steel')), ('vmu01_canopy.glb', lambda n: 'Columns' in n or 'Base plates' in n)):
        for n, m in sel(fname, pred).items():
            uvt, z = cam.project(m.vertices)
            ok = z > 0.3
            for f in m.faces:
                if ok[f].all():
                    cv2.fillConvexPoly(occ, np.round(uvt[f]).astype(np.int32), 255)
    for b_, t_ in old_canopy_columns():
        uvt, z = cam.project(np.array([b_, t_]))
        if (z > 0).all():
            cv2.line(occ, tuple(np.round(uvt[0]).astype(int)), tuple(np.round(uvt[1]).astype(int)), 255, 12)
    occ = cv2.dilate(occ, np.ones((15, 15), np.uint8))
    ground[occ > 0] = 0
    ground[:int(VIEW_H * 0.18), int(VIEW_W * 0.43):] = 0
    return {'steel (STEEL_HDG)': steel, 'yard slab (CTX_CONCRETE_YARD)': ground}

def _robust_median(px):
    m = np.median(px, axis=0); dd = np.linalg.norm(px - m, axis=1)
    return np.median(px[dd <= np.percentile(dd, 80)], axis=0)

def stage_swatch(cams):
    print('== swatch: photo vs render (frame mode) at identical pixels')
    out = {}
    for i, cam in cams.items():
        cv_ = cam.scaled(VIEW_W, VIEW_H)
        rp = os.path.join(OUT, 'p%02d_render_frame.png' % i)
        if not os.path.exists(rp):
            continue
        ph = np.asarray(photo_view(i), float) / 255; rd = np.asarray(Image.open(rp).convert('RGB'), float) / 255
        res = {}
        for name, m in region_masks(cv_).items():
            sel_ = m > 0
            if sel_.sum() < 50:
                continue
            a = _robust_median(ph[sel_]); b = _robust_median(rd[sel_])
            res[name] = {'photo': rgb_to_hex(a), 'render': rgb_to_hex(b), 'dE76': round(float(np.linalg.norm(srgb_to_lab(a) - srgb_to_lab(b))), 1),
                         'dL': round(float(srgb_to_lab(b)[0] - srgb_to_lab(a)[0]), 1), 'px': int(sel_.sum())}
        if len(res) == 2:
            (s1, g1) = res['steel (STEEL_HDG)'], res['yard slab (CTX_CONCRETE_YARD)']
            Ls = lambda h: float(srgb_to_lab(hex_to_rgb(h))[0])
            res['steel minus slab lightness'] = {'photo_dL': round(Ls(s1['photo']) - Ls(g1['photo']), 1), 'render_dL': round(Ls(s1['render']) - Ls(g1['render']), 1)}
        out[i] = res
        print('   p%02d' % i, {k: (v.get('photo'), v.get('render'), v.get('dE76'), v.get('photo_dL'), v.get('render_dL')) for k, v in res.items()})
    rows = [(i, k, v) for i, r in out.items() for k, v in r.items() if 'photo' in v]
    im = Image.new('RGB', (760, 40 + 30 * len(rows)), (250, 250, 250)); d = ImageDraw.Draw(im)
    d.text((8, 8), 'Photo vs render (same pose, same pixels): median sRGB. Photos at dusk / overcast; render = viewer default light.', fill=(0, 0, 0), font=font(13))
    for j, (i, k, v) in enumerate(rows):
        y = 36 + 30 * j
        d.rectangle([8, y, 58, y + 24], fill=v['photo']); d.rectangle([58, y, 108, y + 24], fill=v['render'])
        d.text((118, y + 4), 'p%02d  %-28s photo %s  render %s  dE76 %.1f  dL %+.1f' % (i, k, v['photo'], v['render'], v['dE76'], v['dL']), fill=(0, 0, 0), font=font(13))
    im.save(os.path.join(OUT, 'photo_vs_render_swatches.png'))
    return out

GROUP_FILES = {
    'VMU01': [('vmu_cad.glb', lambda n: n.startswith('VMU01|'))],
    'VMU01_CANOPY': [('vmu01_canopy.glb', lambda n: True)],
    'VMU02': [('vmu02.glb', lambda n: True)],
    'VMU03': [('vmu_cad.glb', lambda n: n.startswith('VMU03|'))],
    'VMU04': [('vmu04.glb', lambda n: True)],
    'VMU05': [('vmu05.glb', lambda n: True)],
    'TRELLIS': [('vmu_cad.glb', lambda n: n.startswith('TRELLIS|'))],
}

def r3_segments_gltf():
    cwd = os.getcwd(); os.chdir(HERE)
    try:
        from site_frame import r3_to_gltf, G
        S = np.load('r3_segs.npy'); s = G['R3_scale_m_per_pt']
    finally:
        os.chdir(cwd)
    A = r3_to_gltf(np.c_[S[:, 0] * s, -S[:, 1] * s])[:, [0, 2]]
    B = r3_to_gltf(np.c_[S[:, 2] * s, -S[:, 3] * s])[:, [0, 2]]
    return A, B, S

def r7_extension_gltf():
    cwd = os.getcwd(); os.chdir(HERE)
    try:
        from site_frame import r3_to_gltf
    finally:
        os.chdir(cwd)
    d = json.load(open(os.path.join(SOURCES_DIR, 'canopy_candidate_a.json')))
    segs = []
    for poly in d['coordinates']:
        for ring in poly:
            P = r3_to_gltf(np.array(ring))[:, [0, 2]]
            segs += [(P[j], P[j + 1]) for j in range(len(P) - 1)]
    return np.array([s[0] for s in segs]), np.array([s[1] for s in segs])

def sample_segments(A, B, step=0.005):
    L = np.linalg.norm(B - A, axis=1); n = np.maximum(1, np.ceil(L / step).astype(int))
    idx = np.repeat(np.arange(len(A)), n + 1)
    t = np.concatenate([np.linspace(0, 1, k + 1) for k in n])
    return A[idx] + (B[idx] - A[idx]) * t[:, None], idx

def footprint(group, pitch=R3_RASTER_M, ymin=None):
    tris = []
    for fname, pred in GROUP_FILES[group]:
        for n, m in sel(fname, pred).items():
            V = m.vertices; Fc = m.faces
            if ymin is not None:
                keep = V[Fc][:, :, 1].max(1) > ymin; Fc = Fc[keep]
            tris.append(V[Fc][:, :, [0, 2]])
    T = np.concatenate(tris)
    lo = T.reshape(-1, 2).min(0) - 0.05; hi = T.reshape(-1, 2).max(0) + 0.05
    W, H = np.ceil((hi - lo) / pitch).astype(int) + 1
    mask = np.zeros((H, W), np.uint8)
    pts = np.round((T - lo) / pitch * 4).astype(np.int32)
    for tri in pts:
        cv2.fillConvexPoly(mask, tri, 255, lineType=cv2.LINE_8, shift=2)
    return mask, lo, pitch, len(T)

R3_DRAWN = {'VMU04': lambda n: 'Precast' in n or 'RC fins' in n}

def plan_edges(group, angle_deg=25.0):
    A, B = [], []
    only = R3_DRAWN.get(group, lambda n: True)
    for fname, pred in GROUP_FILES[group]:
        for n in sel(fname, lambda n: pred(n) and only(n)):
            P0, P1 = feature_edges(fname, n, angle_deg)
            a, b = P0[:, [0, 2]], P1[:, [0, 2]]
            keep = np.linalg.norm(b - a, axis=1) > 0.004
            A.append(a[keep]); B.append(b[keep])
    return np.concatenate(A), np.concatenate(B)

def rigid2d(P, Q, w=None):
    w = np.ones(len(P)) if w is None else w
    cp = (P * w[:, None]).sum(0) / w.sum(); cq = (Q * w[:, None]).sum(0) / w.sum()
    Hm = ((P - cp) * w[:, None]).T @ (Q - cq)
    U, _, Vt = np.linalg.svd(Hm); Rm = (U @ Vt).T
    if np.linalg.det(Rm) < 0:
        Vt[-1] *= -1; Rm = (U @ Vt).T
    return Rm, cq - Rm @ cp

def trimmed_icp(M, tree, Q, taus=(0.30, 0.15, 0.08, 0.05, 0.05, 0.05)):
    Rt, tt = np.eye(2), np.zeros(2); hist = []
    for tau in taus:
        Mc = M @ Rt.T + tt
        d, j = tree.query(Mc)
        ok = d < tau
        if ok.sum() < 50:
            break
        Rm, t = rigid2d(Mc[ok], Q[j[ok]])
        Rt, tt = Rm @ Rt, Rm @ tt + t
        hist.append((tau, int(ok.sum()), float(np.median(d[ok]))))
    return Rt, tt, hist

def canopy_outline_check(tree_r3):
    tris = []
    for n, m in sel('vmu01_canopy.glb', lambda n: re.search(r'Top|Fascia|Chamfer|Soffit', n) is not None).items():
        tris.append(m.vertices[m.faces][:, :, [0, 2]])
    T = np.concatenate(tris); pitch = R3_RASTER_M
    lo = T.reshape(-1, 2).min(0) - 0.05; hi = T.reshape(-1, 2).max(0) + 0.05
    W, H = np.ceil((hi - lo) / pitch).astype(int) + 1
    mask = np.zeros((H, W), np.uint8)
    for tri in np.round((T - lo) / pitch * 4).astype(np.int32):
        cv2.fillConvexPoly(mask, tri, 255, lineType=cv2.LINE_8, shift=2)
    cs, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    cs = [c[:, 0, :] for c in cs if len(c) > 200]
    P = np.concatenate(cs).astype(float) * pitch + lo + pitch / 2
    d, _ = tree_r3.query(P)
    pct = lambda q: round(float(np.percentile(d, q)), 4)
    return {'contour_pts': int(len(P)), 'median': pct(50), 'pct90': pct(90), 'pct95': pct(95), 'pct99': pct(99), 'max': round(float(d.max()), 3),
            'share_le_0.05': round(float((d <= R3_TARGET_M).mean()), 4), 'share_le_0.19': round(float((d <= 0.19).mean()), 4),
            'note': ''}

def stage_r3():
    print('== r3: plan overlay vs build/r3_segs.npy (plan feature edges, two-way nearest distance + trimmed-ICP placement test)')
    A, B, S = r3_segments_gltf()
    EA, EB = r7_extension_gltf()
    res = {}
    for group in GROUP_FILES:
        MA, MB = plan_edges(group)
        M, _ = sample_segments(MA, MB, step=0.01)
        if len(M) > 400000:
            M = M[np.random.default_rng(0).choice(len(M), 400000, replace=False)]
        lo = M.min(0); hi = M.max(0); box = (lo - 1.0, hi + 1.0)
        inb = lambda P: (P[:, 0] > box[0][0]) & (P[:, 0] < box[1][0]) & (P[:, 1] > box[0][1]) & (P[:, 1] < box[1][1])
        s_ = inb(A) | inb(B)
        RA, RB = A[s_], B[s_]
        if group == 'VMU01_CANOPY':
            RA = np.vstack([RA, EA]); RB = np.vstack([RB, EB])
        Q, _ = sample_segments(RA, RB, step=0.01)
        Q = Q[inb(Q)]
        tq = cKDTree(Q); tm = cKDTree(M)
        dm, _ = tq.query(M)
        dr, _ = tm.query(Q)
        Rt, tt, hist = trimmed_icp(M, tq, Q)
        disp = np.linalg.norm(M @ Rt.T + tt - M, axis=1)
        ang = math.degrees(math.atan2(Rt[1, 0], Rt[0, 0]))
        dm2, _ = tq.query(M @ Rt.T + tt)
        inl = dm2 < 0.05
        disp_in = disp[inl] if inl.any() else disp
        pct = lambda a, q: round(float(np.percentile(a, q)), 4)
        st = {'model_edge_samples': int(len(M)), 'r3_samples_in_box': int(len(Q)), 'r3_segments_in_box': int(len(RA)),
              'model_to_r3_m': {'median': pct(dm, 50), 'pct75': pct(dm, 75), 'pct90': pct(dm, 90), 'max': round(float(dm.max()), 3),
                                'share_le_0.05': round(float((dm <= R3_TARGET_M).mean()), 4)},
              'r3_to_model_m': {'median': pct(dr, 50), 'pct75': pct(dr, 75), 'pct90': pct(dr, 90),
                                'share_le_0.05': round(float((dr <= R3_TARGET_M).mean()), 4)},
              'placement_correction': {'dx_east_m': round(float(tt[0] + (Rt @ M.mean(0) - M.mean(0))[0]), 4),
                                       'dz_m': round(float(tt[1] + (Rt @ M.mean(0) - M.mean(0))[1]), 4),
                                       'rot_deg': round(ang, 4), 'max_displacement_m': round(float(disp_in.max()), 4),
                                       'max_displacement_full_extent_m': round(float(disp.max()), 4),
                                       'matched_extent_m': round(float(np.ptp(M[inl], axis=0).max()), 2) if inl.any() else None,
                                       'inliers_last': hist[-1][1] if hist else 0, 'inlier_median_m_last': round(hist[-1][2], 4) if hist else None,
                                       'model_to_r3_median_after_m': pct(dm2, 50)}}
        if group == 'VMU01_CANOPY':
            st['outline'] = canopy_outline_check(tq)
        res[group] = st
        pc = st['placement_correction']
        print('   %-13s model->R3 median %.3f pct90 %.3f (%.0f %% <= 5 cm) | R3->model median %.3f (%.0f %% <= 5 cm) | ICP correction '
              'd=(%.3f, %.3f) m rot %.3f deg -> max displacement %.3f m (inlier median %.3f m)' % (
                  group, st['model_to_r3_m']['median'], st['model_to_r3_m']['pct90'], 100 * st['model_to_r3_m']['share_le_0.05'],
                  st['r3_to_model_m']['median'], 100 * st['r3_to_model_m']['share_le_0.05'], pc['dx_east_m'], pc['dz_m'], pc['rot_deg'],
                  pc['max_displacement_m'], pc['inlier_median_m_last'] or -1))
        sc = float(np.clip(1800.0 / max(box[1] - box[0]), 30, 200))
        W = int((box[1][0] - box[0][0]) * sc); H = int((box[1][1] - box[0][1]) * sc)
        im = Image.new('RGB', (W, H), (255, 255, 255)); d = ImageDraw.Draw(im)
        px = lambda P: np.c_[(P[:, 0] - box[0][0]) * sc, (P[:, 1] - box[0][1]) * sc]
        for a, b in zip(px(RA), px(RB)):
            d.line([tuple(a), tuple(b)], fill=(0, 0, 0), width=1)
        sub = np.random.default_rng(1).choice(len(M), min(len(M), 150000), replace=False)
        P2 = px(M[sub]); dd = dm[sub]
        for (x, y), v in zip(P2, dd):
            d.point((x, y), fill=(0, 170, 0) if v <= 0.02 else ((255, 140, 0) if v <= R3_TARGET_M else (230, 0, 0)))
        d.rectangle([0, 0, W, 50], fill=(255, 255, 255))
        d.text((8, 6), '%s  plan (x east right, north up)   black: R3 vectors%s   model plan edges: green <= 2 cm, orange <= 5 cm, red > 5 cm from R3' % (
            group, ' + R7 red extension' if group == 'VMU01_CANOPY' else ''), fill=(0, 0, 0), font=font(14))
        d.text((8, 26), 'model->R3 median %.3f m, %.0f %% within 5 cm | placement test (trimmed ICP): shift (%.3f, %.3f) m, rot %.3f deg, max displacement %.3f m' % (
            st['model_to_r3_m']['median'], 100 * st['model_to_r3_m']['share_le_0.05'], pc['dx_east_m'], pc['dz_m'], pc['rot_deg'], pc['max_displacement_m']),
            fill=(0, 0, 0), font=font(14))
        im.save(os.path.join(OUT, 'r3_overlay_%s.png' % group))
    return res

def contract_table():
    md = open(os.path.join(SOURCES_DIR, 'material_contract.md'), encoding='utf-8').read()
    sec = md.split('## 4.')[1].split('## 5.')[0]
    T = {}
    for line in sec.splitlines():
        if not line.startswith('| ') or line.startswith('| name') or line.startswith('|---'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        name = cells[0]
        if name.startswith('Context'):
            for m in re.finditer(r'([A-Z_]+) (#[0-9A-Fa-f]{6})', cells[1]):
                T.setdefault('CTX_' + m.group(1), {'hex': m.group(2).upper(), 'metal': None, 'rough': None, 'context': True})
            continue
        h = re.search(r'#[0-9A-Fa-f]{6}', cells[1])
        T[name] = {'hex': h.group(0).upper() if h else None, 'metal': float(cells[2]), 'rough': float(re.findall(r'[\d.]+', cells[3])[-1]) if re.findall(r'[\d.]+', cells[3]) else None,
                   'tint': 'tint' in cells[1], 'rough_range': cells[3]}
    return T

def glb_materials(path):
    import struct
    b = open(path, 'rb').read(); L = struct.unpack('<I', b[12:16])[0]; j = json.loads(b[20:20 + L])
    used = {}
    for m in j.get('meshes', []):
        for p in m.get('primitives', []):
            if 'material' in p:
                used[p['material']] = used.get(p['material'], 0) + 1
    out = []
    for i, m in enumerate(j.get('materials', [])):
        pbr = m.get('pbrMetallicRoughness', {})
        bc = pbr.get('baseColorFactor', [1, 1, 1, 1])
        out.append({'name': m.get('name'), 'srgb': rgb_to_hex(lin_to_srgb(bc[:3])), 'alpha': bc[3],
                    'metal': pbr.get('metallicFactor', 1.0), 'rough': pbr.get('roughnessFactor', 1.0),
                    'extras_srgb': (m.get('extras') or {}).get('srgb'), 'primitives': used.get(i, 0)})
    return out

def stage_materials():
    print('== materials: GLBs + materials.json vs contract section 4')
    T = contract_table()
    MJ = json.load(open(os.path.join(MODEL, 'materials.json'), encoding='utf-8'))
    rows = []
    for name, c in T.items():
        mj = MJ.get(name)
        r = {'where': 'model/materials.json', 'name': name, 'contract_hex': c['hex'], 'contract_metal': c['metal'], 'contract_rough': c['rough']}
        if mj is None:
            r['status'] = 'MISSING'; rows.append(r); continue
        r.update({'hex': mj.get('hex'), 'metal': mj.get('metalness'), 'rough': mj.get('roughness')})
        dE = float(np.linalg.norm(srgb_to_lab(hex_to_rgb(mj['hex'])) - srgb_to_lab(hex_to_rgb(c['hex'])))) if c['hex'] and mj.get('hex') else None
        r['dE'] = None if dE is None else round(dE, 2)
        bad = []
        if dE is not None and dE > COLOR_TOL_DE: bad.append('colour dE %.1f' % dE)
        if c['metal'] is not None and mj.get('metalness') is not None and abs(mj['metalness'] - c['metal']) > PBR_TOL: bad.append('metal')
        if c['rough'] is not None and mj.get('roughness') is not None and abs(mj['roughness'] - c['rough']) > PBR_TOL:
            if not ('–' in (c.get('rough_range') or '') or '-' in (c.get('rough_range') or '')): bad.append('rough')
        r['status'] = 'OK' if not bad else 'DIFF: ' + ', '.join(bad)
        rows.append(r)
    canon = set(T) | {k for k, v in MJ.items() if isinstance(v, dict) and v.get('category') == 'context'}
    glbs = ['vmu_cad.glb', 'vmu01_canopy.glb', 'vmu02.glb', 'vmu04.glb', 'vmu05.glb', 'site_ground.glb', 'site_context.glb']
    glb_rows = []
    red_hits = []
    for g in glbs:
        for m in glb_materials(os.path.join(MODEL, g)):
            nm = m['name'] or ''
            base = re.sub(r'(_noribs|_NORIBS|\.\d+)$', '', nm)
            c = T.get(base) or (T.get('CTX_' + base[4:]) if base.startswith('CTX_') else None)
            r = {'glb': g, 'name': nm, 'srgb': m['srgb'], 'extras_srgb': m['extras_srgb'], 'metal': m['metal'], 'rough': m['rough'],
                 'alpha': m['alpha'], 'primitives': m['primitives'], 'canonical': base in canon}
            ref = (m['extras_srgb'] or m['srgb'])
            if c and c.get('hex') and not c.get('tint'):
                r['dE_vs_contract'] = round(float(np.linalg.norm(srgb_to_lab(hex_to_rgb(ref)) - srgb_to_lab(hex_to_rgb(c['hex'])))), 2)
                if c['metal'] is not None: r['metal_diff'] = round(m['metal'] - c['metal'], 3)
                if c['rough'] is not None: r['rough_diff'] = round(m['rough'] - c['rough'], 3)
            rgb = hex_to_rgb(ref); hsv = cv2.cvtColor(np.uint8([[rgb * 255]]), cv2.COLOR_RGB2HSV)[0, 0]
            is_red = (hsv[0] <= 10 or hsv[0] >= 170) and hsv[1] > 90 and hsv[2] > 60
            r['reddish'] = bool(is_red)
            if is_red and g == 'vmu01_canopy.glb':
                red_hits.append(r)
            glb_rows.append(r)
    for r in rows:
        if r['status'] != 'OK':
            print('   materials.json', r['name'], r['status'], r.get('hex'), 'contract', r['contract_hex'])
    nonc = sorted({(r['glb'], r['name']) for r in glb_rows if not r['canonical']})
    diff = [r for r in glb_rows if r.get('dE_vs_contract', 0) > COLOR_TOL_DE or abs(r.get('metal_diff', 0)) > PBR_TOL]
    print('   %d contract rows, %d OK; %d GLB materials, %d non-canonical names, %d colour/metal deviations, canopy red: %d' % (
        len(rows), sum(r['status'] == 'OK' for r in rows), len(glb_rows), len(nonc), len(diff), len(red_hits)))
    items = [r for r in rows]
    cw, ch = 360, 44; cols = 3; rws = (len(items) + cols - 1) // cols
    im = Image.new('RGB', (cols * cw, rws * ch + 40), (250, 250, 250)); d = ImageDraw.Draw(im)
    d.text((8, 8), 'Material contract (contract section 4) vs model/materials.json: left = contract sRGB, right = materials.json sRGB', fill=(0, 0, 0), font=font(14))
    for j, r in enumerate(items):
        x = (j % cols) * cw; y = 40 + (j // cols) * ch
        if r['contract_hex']: d.rectangle([x + 6, y + 4, x + 46, y + 38], fill=r['contract_hex'])
        if r.get('hex'): d.rectangle([x + 46, y + 4, x + 86, y + 38], fill=r['hex'])
        d.text((x + 92, y + 4), r['name'], fill=(0, 0, 0), font=font(13))
        d.text((x + 92, y + 22), '%s -> %s  %s' % (r['contract_hex'], r.get('hex'), r['status'] if r['status'] == 'OK' else r['status'][:30]),
               fill=(0, 110, 0) if r['status'] == 'OK' else (200, 0, 0), font=font(11))
    im.save(os.path.join(OUT, 'materials_swatches.png'))
    return {'contract_rows': rows, 'glb_materials': glb_rows, 'non_canonical': nonc, 'deviations': diff, 'canopy_red': red_hits}

GIRDER_BOTTOM_EDGE = {int(k): [tuple(p) for p in v] for k, v in _PRIV['girder_bottom_edge'].items()}

def girder_check(cams, heights=(9.5, 10.0, 10.5)):
    mg = sel('site_context.glb', lambda n: n.startswith('Gantry crane') and 'Box girder' in n)
    mb = list(mg.values())[0].bounds if mg else None
    mc = ((mb[0] + mb[1]) / 2)[[0, 2]] if mb is not None else None
    out = {'model_girder_centre_xz': None if mc is None else mc.round(2).tolist(),
           'model_girder_soffit_m': None if mb is None else round(float(mb[0][1]), 2), 'per_height': {}}
    for h in heights:
        L = {}
        for i, pts in GIRDER_BOTTOM_EDGE.items():
            G = cams[i].backproject_ground(pts, y=h)[:, [0, 2]]
            c = G.mean(0); _, _, vt = np.linalg.svd(G - c); L[i] = (c, vt[0], G)
        (c1, d1, G1), (c2, d2, G2) = L[17], L[15]
        n1 = np.array([-d1[1], d1[0]])
        Gall = np.vstack([G1, G2]); c = Gall.mean(0); _, _, vt = np.linalg.svd(Gall - c); d = vt[0]
        out['per_height'][str(h)] = {'view_disagreement_m': round(float(np.abs((G2 - c1) @ n1).mean()), 2),
                                     'axis_point_glTF_xz': c.round(2).tolist(),
                                     'bearing_deg': round(float(math.degrees(math.atan2(d[0], -d[1])) % 180), 1),
                                     'shift_along_rails_m': None if mc is None else round(float((c - mc) @ U_AX), 2)}
    return out

def canopy_overlay(cams):
    for i in (16, 15):
        if i not in cams:
            continue
        cv_ = cams[i].scaled(VIEW_W, VIEW_H)
        im = Image.blend(photo_view(i), Image.new('RGB', (VIEW_W, VIEW_H), (0, 0, 0)), 0.3)
        for n in sel('vmu01_canopy.glb', lambda n: 'GMS' in n):
            draw_edges(im, cv_, *feature_edges('vmu01_canopy.glb', n, 30), (255, 60, 255), 1)
        for n in sel('vmu01_canopy.glb', lambda n: 'Fascia' in n or 'Columns' in n):
            draw_edges(im, cv_, *feature_edges('vmu01_canopy.glb', n, 30), (0, 255, 255), 1)
        d = ImageDraw.Draw(im)
        for b_, t_ in old_canopy_columns():
            uv, z = cv_.project(np.array([b_, t_]))
            if (z > 0).all():
                d.line([tuple(uv[0]), tuple(uv[1])], fill=(255, 150, 0), width=2)
        d.rectangle([0, VIEW_H - 44, VIEW_W, VIEW_H], fill=(0, 0, 0))
        d.text((8, VIEW_H - 40), 'p%d: build step canopy - magenta: GMS primaries (concealed), cyan: fascia + new columns; orange: old legacy CAD canopy columns (existing)' % i,
               fill=(255, 255, 255), font=font(13))
        d.text((8, VIEW_H - 20), 'the extension is not built yet in the photo; the galvanised frame is the existing canopy steel', fill=(255, 255, 255), font=font(13))
        im.save(os.path.join(OUT, 'p%02d_canopy_overlay.jpg' % i), quality=90)






def _glb_json(fname):
    import struct
    try:
        b = open(os.path.join(MODEL, fname), 'rb').read(); L = struct.unpack('<I', b[12:16])[0]
        return json.loads(b[20:20 + L])
    except Exception:
        return {}




def write_report(RES):
    path = os.path.join(OUT, 'validation_summary.md')
    L = ['# Validation summary', '', 'generated %s by build/validate.py; numbers in validation_results.json' % RES.get('generated'), '']
    ph = RES.get('photos', {})
    if ph:
        L.append('- photo poses: shared focal %s px (2048 frame), %d photos' % (ph.get('focal_px_2048'), len(ph.get('photos', {}))))
    if RES.get('r3'):
        L.append('- layout-plan check: %s' % ', '.join(sorted(RES['r3'])))
    if RES.get('materials'):
        L.append('- materials: %d rows checked' % len(RES['materials'].get('rows', RES['materials'])))
    open(path, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('wrote', path)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stages', default='photos,silhouette,render,composite,swatch,girder,r3,materials,report')
    ap.add_argument('--skip-render', action='store_true')
    a = ap.parse_args()
    stages = a.stages.split(',')
    if a.skip_render and 'render' in stages:
        stages.remove('render')
    RES = {'generated': TODAY, 'script': 'build/validate.py'}
    rp = os.path.join(OUT, 'validation_results.json')
    if os.path.exists(rp):
        try:
            RES.update(json.load(open(rp, encoding='utf-8')))
        except Exception:
            pass
    RES['generated'] = TODAY
    if 'photos' in stages:
        cams, R = stage_photos(); RES['photos'] = R
        RES['photo_resize_check'] = {i: round(check_resize(i), 4) for i in cams}
        update_photos_json(cams, R)
    else:
        cams = load_cams(); R = RES['photos']
        R['photos'] = {int(k): v for k, v in R['photos'].items()}
    SIL = None
    if 'silhouette' in stages:
        SIL = stage_silhouette(cams)
        RES['silhouette'] = {i: {k: v for k, v in s.items() if k != 'samples'} for i, s in SIL.items()}
    if 'render' in stages:
        info, rep = stage_render(cams); RES['render'] = {'jobs': info, 'viewer': {k: rep.get(k) for k in ('files', 'triangles', 'hdri', 'canopyScheme')}}
    if 'composite' in stages:
        stage_composite(cams, R, SIL)
    if 'composite' in stages:
        canopy_overlay(cams)
    if 'swatch' in stages:
        RES['swatch'] = stage_swatch(cams)
    if 'girder' in stages:
        RES['girder'] = girder_check(cams); print('== girder', RES['girder'])
    if 'r3' in stages:
        r3 = stage_r3(); RES['r3'] = {k: {kk: vv for kk, vv in v.items() if not kk.startswith('_')} for k, v in r3.items()}
    if 'materials' in stages:
        RES['materials'] = stage_materials()
    json.dump(RES, open(rp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=lambda o: o.tolist() if hasattr(o, 'tolist') else str(o))
    if 'report' in stages:
        RES = json.load(open(rp, encoding='utf-8'))
        write_report(RES)
    print('done ->', os.path.relpath(OUT, ROOT))

if __name__ == '__main__':
    main()
