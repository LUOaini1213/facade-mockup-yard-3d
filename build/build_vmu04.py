"""Builds model/vmu04.glb: VMU-04, the vertical corner mock-up - an architectural precast L-wall with a random-depth rib
formliner (real rib geometry + groove-AO UVs from materials_lib), RC fins, windows (frame, glass, sill, seals), the HDG
steel tower behind it (SHS columns, RHS rails, bracing, base plates, anchor stubs) and the access stair, in the local
frame of the private element spec (mm), placed on the layout plan. Options: MOCKUP_VMU04_* environment variables.
Needs the private element spec in SOURCES_DIR.
"""
import os, sys, json, math
SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.chdir(HERE)
sys.path.insert(0, HERE)
import numpy as np
import shapely
from shapely.geometry import Polygon, MultiPolygon, box as sbox
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
import mapbox_earcut as earcut
from gltfw import GLB
from site_frame import r3_to_gltf, r3_dir_to_gltf
import materials_lib as ML

COLUMN_BASE_Y_M = float(os.environ.get('MOCKUP_VMU04_BASE_Y', '0.0'))
RC_SLAB = os.environ.get('MOCKUP_VMU04_SLAB', 'auto')
SLAB_PROUD_MM = 4.0
SLAB_ELEV_MM = (-5260.0, -530.0, 530.0, 3645.0 + 530.0)
SLAB_STAIR_MARGIN_MM = 300.0
PLAN_ANCHOR = os.environ.get('MOCKUP_VMU04_ANCHOR', 'corner')
ANCHOR_OFFSET_MM = {'corner': (0.0, 0.0), 'fins': (243.4, -167.4)}[PLAN_ANCHOR]
RIB = dict(pitch=ML.FORMLINER['pitch'], depth=max(ML.FORMLINER['depths']), rib_w=ML.FORMLINER['rib_w'], groove_w=ML.FORMLINER['groove_w'],
           depths=tuple(ML.FORMLINER['depths']), first_rib_s=ML.FORMLINER['first_rib_s'], profile='rectangular')
CHAIN_S0 = RIB['first_rib_s']
WIN_FRAME_Y = (40.0, 110.0)
WIN_RECESS = 10.0
CORNER_JOINT = 20.0
JOINT_SEAL = (35.0, 60.0)
STAIR_ON = True
STRINGER_END_PLATE = 10.0
COLUMN_NOTCH = 202.0
STAIR_L2_TIES = True
COL_SHS_TOP = 20.0 + 10067.0
COL_CAP_T = 3.0
PLATE_WASHER = (60.0, 6.0)
ANCHOR_STUB_TOP = 60.0
R3_FIN_CHECK = {'r3_fins_s_from_corner_m': {'S': [[0.954, 1.080], [2.085, 2.210]], 'E': [[1.030, 1.156], [2.161, 2.286]]},
                'model_fins_s_from_corner_m': {'S': [[1.1954, 1.3204], [2.3304, 2.4554]], 'E': [[1.1954, 1.3204], [2.3304, 2.4554]]},
                'offset_m': {'S': 0.243, 'E': 0.167, 'direction': 'R3 fins/windows are CLOSER to the outer corner than the shop drawing'},
                'datum': 's from the virtual arris (tip-plane intersection = R3 corner); shop chain measured from the first-rib flank at s 30.4 (G3 r2)',
                'r3_block_matches': '',
                'r3_sheet': '',
                'shop_drawing': '',
                'newer': '',
                'decision': 'keep the shop-drawing fin positions (PLAN_ANCHOR corner); no change'}

SPEC_PATH = os.path.join(SOURCES_DIR, 'vmu04_spec.json')
OUT_GLB = os.environ.get('MOCKUP_VMU04_OUT') or os.path.join(ROOT, 'model', 'vmu04.glb')
SPEC = json.load(open(SPEC_PATH, encoding='utf-8'))
ORIGIN_R3 = np.array(SPEC['local_frame']['origin_R3_m'], float)
LV = SPEC['levels']

SRC_SHOP = ''
SRC_SPEC = ''
SRC_WIN = ''
SRC_R3 = ''
SRC_RIB = ('')

EX, EY, EZ = np.eye(3)

def _earcut(coords_list):
    verts = np.concatenate(coords_list, 0)
    ends = np.cumsum([len(c) for c in coords_list]).astype(np.uint32)
    tri = np.asarray(earcut.triangulate_float64(verts, ends), np.int64).reshape(-1, 3)
    return verts, tri

def _rings(poly):
    poly = orient(poly, 1.0)
    return [np.asarray(poly.exterior.coords)[:-1]] + [np.asarray(r.coords)[:-1] for r in poly.interiors]

def _polys(geom):
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return [g for g in getattr(geom, 'geoms', []) if isinstance(g, Polygon)]

def _basis(U, V):
    U = np.asarray(U, float); V = np.asarray(V, float)
    return U, V, np.cross(U, V)

def cap(geom, w, O, U, V, up=True):
    U, V, W = _basis(U, V); O = np.asarray(O, float)
    Vs, Ns, Fs, n0 = [], [], [], 0
    for p in _polys(geom):
        if p.area < 1e-3:
            continue
        verts, tri = _earcut(_rings(p))
        if len(tri) == 0:
            continue
        a = verts[tri[:, 1]] - verts[tri[:, 0]]; b = verts[tri[:, 2]] - verts[tri[:, 0]]
        sa = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
        flip = sa < 0 if up else sa > 0
        tri[flip] = tri[flip][:, ::-1]
        tri = tri[np.abs(sa) > 1e-9]
        P = O + verts[:, :1] * U + verts[:, 1:2] * V + w * W
        Vs.append(P); Ns.append(np.tile(W if up else -W, (len(P), 1))); Fs.append(tri + n0); n0 += len(P)
    if not Vs:
        return np.zeros((0, 3)), np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    return np.concatenate(Vs), np.concatenate(Ns), np.concatenate(Fs)

def walls(geom, w0, w1, O, U, V):
    U, V, W = _basis(U, V); O = np.asarray(O, float)
    Vs, Ns, Fs, n0 = [], [], [], 0
    for p in _polys(geom):
        for ring in _rings(p):
            q = np.roll(ring, -1, 0); d = q - ring; L = np.hypot(d[:, 0], d[:, 1]); k = L > 1e-6
            ring, q, d, L = ring[k], q[k], d[k], L[k]
            if len(ring) == 0:
                continue
            n2 = np.c_[d[:, 1], -d[:, 0]] / L[:, None]
            nn = n2[:, :1] * U + n2[:, 1:2] * V
            p3 = O + ring[:, :1] * U + ring[:, 1:2] * V
            q3 = O + q[:, :1] * U + q[:, 1:2] * V
            m = len(ring)
            quad = np.stack([p3 + w0 * W, q3 + w0 * W, q3 + w1 * W, p3 + w1 * W], 1).reshape(-1, 3)
            Vs.append(quad); Ns.append(np.repeat(nn, 4, 0))
            base = n0 + 4 * np.arange(m)[:, None]
            Fs.append(np.concatenate([base + [0, 1, 2], base + [0, 2, 3]], 0)); n0 += 4 * m
    if not Vs:
        return np.zeros((0, 3)), np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    return np.concatenate(Vs), np.concatenate(Ns), np.concatenate(Fs)

def merge(*parts):
    Vs, Ns, Fs, n0 = [], [], [], 0
    for V, N, F in parts:
        if len(V) == 0:
            continue
        Vs.append(V); Ns.append(N); Fs.append(np.asarray(F, np.int64) + n0); n0 += len(V)
    if not Vs:
        return np.zeros((0, 3)), np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    return np.concatenate(Vs), np.concatenate(Ns), np.concatenate(Fs)

def extrude(geom, w0, w1, O=(0, 0, 0), U=EX, V=EY, caps=(True, True)):
    parts = [walls(geom, w0, w1, O, U, V)]
    if caps[0]:
        parts.append(cap(geom, w0, O, U, V, up=False))
    if caps[1]:
        parts.append(cap(geom, w1, O, U, V, up=True))
    return merge(*parts)

def band_stack(bands, O=(0, 0, 0), U=EX, V=EY):
    parts = []
    for w0, w1, g in bands:
        parts.append(walls(g, w0, w1, O, U, V))
    parts.append(cap(bands[0][2], bands[0][0], O, U, V, up=False))
    parts.append(cap(bands[-1][2], bands[-1][1], O, U, V, up=True))
    for (a0, a1, ga), (b0, b1, gb) in zip(bands[:-1], bands[1:]):
        assert abs(a1 - b0) < 1e-9
        parts.append(cap(ga.difference(gb), a1, O, U, V, up=True))
        parts.append(cap(gb.difference(ga), a1, O, U, V, up=False))
    return merge(*parts)

def box(x0, y0, z0, x1, y1, z1):
    return extrude(sbox(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), min(z0, z1), max(z0, z1))

def rrect_profile(w, h, r, nseg=3):
    if r <= 0:
        return np.array([[w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2], [-w / 2, -h / 2]]), None
    pts, nrm = [], []
    for cx, cy, a0 in [(w / 2 - r, -h / 2 + r, -90), (w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180)]:
        for i in range(nseg + 1):
            a = math.radians(a0 + 90.0 * i / nseg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a))); nrm.append((math.cos(a), math.sin(a)))
    return np.array(pts), np.array(nrm)

def circle_profile(d, n=16):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    c = np.c_[np.cos(a), np.sin(a)]
    return c * d / 2, c

def hex_profile(af):
    a = np.radians(np.arange(6) * 60 + 30)
    return np.c_[np.cos(a), np.sin(a)] * af / 2 / math.cos(math.radians(30)), None

def sweep(profile, A, B, up=EZ, caps=True):
    pts, nrm = profile
    A = np.asarray(A, float); B = np.asarray(B, float); L = np.linalg.norm(B - A); t = (B - A) / L
    up = np.asarray(up, float)
    if abs(np.dot(up, t)) > 0.999:
        up = EX if abs(t[0]) < 0.9 else EY
    Q = up - np.dot(up, t) * t; Q /= np.linalg.norm(Q); S = np.cross(Q, t)
    if nrm is None:
        return extrude(Polygon(pts), 0.0, L, A, S, Q, caps=(caps, caps))
    K = len(pts)
    P0 = A + pts[:, :1] * S + pts[:, 1:2] * Q
    nn = nrm[:, :1] * S + nrm[:, 1:2] * Q
    Vw = np.concatenate([P0, P0 + L * t]); Nw = np.concatenate([nn, nn])
    i = np.arange(K); j = (i + 1) % K
    Fw = np.concatenate([np.c_[i, j, K + j], np.c_[i, K + j, K + i]])
    parts = [(Vw, Nw, Fw)]
    if caps:
        parts.append(cap(Polygon(pts), 0.0, A, S, Q, up=False))
        parts.append(cap(Polygon(pts), L, A, S, Q, up=True))
    return merge(*parts)

def mirror_E(part):
    V, N, F = part
    V2 = np.c_[-V[:, 1], -V[:, 0], V[:, 2]]; N2 = np.c_[-N[:, 1], -N[:, 0], N[:, 2]]
    return V2, N2, np.asarray(F)[:, ::-1].copy()

PARTS = []

class Part:
    def __init__(self, layer_en, finish, source, confidence, **extras):
        self.layer_en, self.finish, self.source, self.confidence, self.extras = layer_en, finish, source, confidence, extras
        self.items = []; self.objects = 0
        PARTS.append(self)

    def add(self, geo, count=1):
        if len(geo[0]):
            self.items.append(geo)
        self.objects += count

    def mesh(self):
        return merge(*self.items)

def seg_box(A, B, w, h):
    return A, B, w, h

SF = SPEC['steel_frame']
mem = {m['id']: m for m in SF['members']}
R_SHS200, R_RHS75, R_SHS50 = 20.0, 10.0, 6.0
_LEG_END_S = CHAIN_S0 - next(p for p in SPEC['precast']['panels'] if p['id'] == 'PC_S1')['box'][0]
C18_OVERHANG = -SF['extent_xy'][0] - _LEG_END_S
C18_NOTE = ('')

p_cols = Part('Columns SHS200x200x10', 'STEEL_HDG', '',
              f'high (section, length, c/c 3150 per contractor order); C18: frame far faces {C18_OVERHANG:.1f} beyond the precast leg ends (contractor shop dwg not found)',
              section='SHS 200x200x10, corner r 20 (visual)', c_c_mm=SF['columns_cc'], outer_mm=SF['outer'], z_mm=[20, COL_SHS_TOP],
              top_mm=COL_SHS_TOP + COL_CAP_T,
              cap=f'190x190x3 top closure plate (part "190x190x3mm钢板封口") at z {COL_SHS_TOP:.0f}..{COL_SHS_TOP + COL_CAP_T:.0f}, '
                  f'{LV["ROOF"] - COL_SHS_TOP - COL_CAP_T:.0f} mm below the roof FFL inside the 202 plate notch (column top 10.090 per part; '
                  'spec z1 10110 superseded)',
              not_modelled='D30 through-hole 50 below the column top (part "D30过孔", face not identified)',
              c18_flag=C18_NOTE)
p_bp = Part('Base plates 400x400x20 + anchor bolts', 'STEEL_HDG',
            '',
            'high (plate size/holes/washers), medium (anchor = post-installed M20, chemical ASSUMED as VMU-01; type/supplier not found)',
            bolts_per_plate=8, washer='60x60x6 square plate washer (part) z 20..26', nut='M20 hex 30 AF x 16 z 26..42',
            stub_top_mm=ANCHOR_STUB_TOP, underside_y_m=0.0, grout_mm=0,
            seat='directly on the existing yard hardstanding (y 0); no plinth, no grout (vmu04_base s3; precast supplier detail draws none)')
p_beam = Part('Perimeter beams SHS200x200x10', 'STEEL_HDG', '',
              'high', count_note='12 perimeter = 4 per level x L1/L2/ROOF; top = FFL - 79.5 (75 RHS + 4.5 plate)')
p_beam_i = Part('Interior beams SHS200x200x10 (position inferred)', 'STEEL_HDG', '',
                'low (position inferred at the chequer-plate row joints)')
p_joist = Part('Joists RHS75x50x5', 'STEEL_HDG', '',
               'medium (section/level high; plan run assumed along the top of every beam)')
p_floor = Part('Chequer plate floors L1 L2 roof', 'STEEL_HDG', '',
               'high (plates/levels); chequer (tear-drop) relief not modelled - flat 4.5 mm plate', levels_mm=[LV['L1'], LV['L2'], LV['ROOF']])
p_hr = Part('Handrails CHS48.3x3', 'STEEL_HDG', '',
            'high (frames on the 2 open faces W/N at L1 and L2); N-face frames cut at the stair openings = ASSUMPTION (stair position assumed)')

bolt_xy = [(-150, -150), (0, -150), (150, -150), (150, 0), (150, 150), (0, 150), (-150, 150), (-150, 0)]
for i in range(1, 5):
    c = mem[f'COL{i}']; x, y = c['x'], c['y']
    p_cols.add(sweep(rrect_profile(200, 200, R_SHS200), (x, y, c['z0']), (x, y, COL_SHS_TOP), up=EX))
    p_cols.add(box(x - 95, y - 95, COL_SHS_TOP, x + 95, y + 95, COL_SHS_TOP + COL_CAP_T), 0)
    b = mem[f'BP{i}']['box']; p_bp.add(box(*b))
    _w, _wt = PLATE_WASHER
    for bx, by in bolt_xy:
        X, Y = x + bx, y + by
        p_bp.add(box(X - _w / 2, Y - _w / 2, 20.0, X + _w / 2, Y + _w / 2, 20.0 + _wt), 0)
        p_bp.add(sweep(hex_profile(30), (X, Y, 20.0 + _wt), (X, Y, 36.0 + _wt), up=EX), 0)
        p_bp.add(sweep(circle_profile(20, 10), (X, Y, 36.0 + _wt), (X, Y, ANCHOR_STUB_TOP), up=EX), 0)

def beam_from_box(bx, prof):
    x0, y0, z0, x1, y1, z1 = bx
    zc = (z0 + z1) / 2
    if (x1 - x0) >= (y1 - y0):
        yc = (y0 + y1) / 2; return sweep(prof, (x0, yc, zc), (x1, yc, zc))
    xc = (x0 + x1) / 2; return sweep(prof, (xc, y0, zc), (xc, y1, zc))

beam_boxes = {}
for k in ('L1', 'L2', 'ROOF'):
    for s in ('S', 'N', 'W', 'E'):
        m = mem[f'B_{k}_{s}']; beam_boxes[m['id']] = m['box']; p_beam.add(beam_from_box(m['box'], rrect_profile(200, 200, R_SHS200)))
    for s in ('I1', 'I2'):
        m = mem[f'B_{k}_{s}']; beam_boxes[m['id']] = m['box']; p_beam_i.add(beam_from_box(m['box'], rrect_profile(200, 200, R_SHS200)))
for bid, bx in beam_boxes.items():
    x0, y0, z0, x1, y1, z1 = bx
    jb = [x0, y0, z1, x1, y1, z1 + 75]
    if (x1 - x0) >= (y1 - y0):
        yc = (y0 + y1) / 2; jb[1], jb[4] = yc - 25, yc + 25
    else:
        xc = (x0 + x1) / 2; jb[0], jb[3] = xc - 25, xc + 25
    p_joist.add(beam_from_box(jb, rrect_profile(50, 75, R_RHS75)))

fx0, fy0, fx1, fy1 = SF['extent_xy']
cxm, cym = (fx0 + fx1) / 2, (fy0 + fy1) / 2
xs = [cxm - 1662, cxm, cxm + 1662]
ys = [cym - 1659.5, cym - 1659.5 + 1087, cym - 1659.5 + 1087 + 1145, cym + 1659.5]
_hn = COLUMN_NOTCH / 2.0
col_fp = [sbox(mem[f'COL{i}']['x'] - _hn, mem[f'COL{i}']['y'] - _hn, mem[f'COL{i}']['x'] + _hn, mem[f'COL{i}']['y'] + _hn) for i in range(1, 5)]
for k in ('L1', 'L2', 'ROOF'):
    z = LV[k]
    for i in range(2):
        for j in range(3):
            pl = sbox(xs[i] + (1 if i else 0), ys[j] + (1 if j else 0), xs[i + 1] - (0 if i else 1), ys[j + 1] - (0 if j == 2 else 1))
            for cf in col_fp:
                pl = pl.difference(cf)
            p_floor.add(extrude(pl, z - 4.5, z))
p_floor.extras['plate_grid_mm'] = {'x': [round(v, 1) for v in xs], 'y': [round(v, 1) for v in ys]}
p_floor.extras['column_notch_mm'] = COLUMN_NOTCH

ST_CLEAR, ST_STR_W = 850.0, 48.0
ST_W = ST_CLEAR + 2 * ST_STR_W
ST = dict(y_edge=3650.0,
          xB=(-3435.0, -3435.0 + ST_W),
          xA=(-3435.0 + ST_W, -3435.0 + 2 * ST_W),
          going=204.0, width=ST_W, clear=ST_CLEAR, str_w=ST_STR_W, str_d=100.0, str_web=5.3, str_fl=8.5)
F1_DXF = dict(foot=140.04, top=966.84, run=1087.92, t_risers=(176.92, 376.92, 576.92, 776.92), z_treads=(204.84, 408.84, 612.84, 816.84),
              tread_len=209.0, leg0_bot=15.01, top_plate=(980.92, 984.92, 960.83), plate_t=4.0)
LANDING_Z = 3295.0
Y_LAND = ST['y_edge'] + 9 * ST['going']
Y_FRAME_N = SF['extent_xy'][3]
F_DEF = {'F1': dict(zb=0.0, n=5, r=1020.0 / 5, dirn=-1, x=ST['xB'], part='part', head_face=Y_FRAME_N, plate_top=None),
         'F2': dict(zb=float(LV['L1']), n=10, r=227.5, dirn=+1, x=ST['xA'], part='part', head_face=Y_LAND, plate_top=LANDING_Z - 4.5),
         'F3': dict(zb=3295.0, n=10, r=227.5, dirn=-1, x=ST['xB'], part='part', head_face=Y_FRAME_N, plate_top=None)}
LAND_Y = (Y_LAND, Y_LAND + 1000.0)
POST_X = (-3485.0, -1552.0)
POSTS = [(POST_X[0], Y_LAND + 25), (POST_X[1], Y_LAND + 25), (POST_X[0], LAND_Y[1] - 25), (POST_X[1], LAND_Y[1] - 25)]
POST_TOP = 8.0 + 5575.0
BRACE_L = 3218.0
FEET = []
SPEC_LAYOUT_NOTE = ("REPLACES vmu04_spec.json stair.assumed_layout (landing x -1352.5..-352.5, y 3645..5445 against the tower N face; F2/F3 running along x at y 4070/5020). Reason: in that layout F1 tops out at y 4545 (900 mm off the L1 floor edge, beside the foot of F2) and F3 tops out at x -3445, y 5020 (850 mm outside the tower face): both need connecting platforms that are not in the order list (the spec itself flags the F3 bridge). The build uses a dog-leg perpendicular to the N face instead: F1 and F3 arrive at the N beam face (no bridge needed), F2 leaves it, landing posts tied back to the tower at L2. Both layouts are ASSUMPTIONS (plan position not documented). Not chosen: a W-face stair (elevation detail slab reaches ~1.8 m west, about the 1883 order member length) because the R3 'steel track' runs 1.7-3.3 m west of the frame.")

conf_st = 'position assumed (plan position of the stair not in any document found); members per order'
p_st = Part('Stair flights F1 F2 F3 (position assumed)', 'STEEL_HDG',
            '',
            conf_st, layout=f'dog-leg on the open N face (page +y): F1 ground->L1 and F3 landing->L2 share the west strip x {ST["xB"][0]:.0f}..{ST["xB"][1]:.0f}, '
                            f'F2 L1->landing x {ST["xA"][0]:.0f}..{ST["xA"][1]:.0f} (flange to flange); landing +3295 at y 5486..6486',
            f1_profile=dict(F1_DXF, note=''),
            width_mm=dict(clear=ST_CLEAR, stringer=ST_STR_W, overall=ST_W),
            layout_vs_spec=SPEC_LAYOUT_NOTE,
            reason='W face kept clear: the R3 "steel track" runs 1.7-3.3 m west of the frame; N side is open yard in R3',
            order_qty_note='',
            stringer_heads=f'F1/F3 heads stop at y {Y_FRAME_N + STRINGER_END_PLATE:.0f} with a {STRINGER_END_PLATE:.0f} mm end plate bolted to the N perimeter beam face y {Y_FRAME_N:.0f}; '
                           f'F2 head stops at y {Y_LAND - STRINGER_END_PLATE:.0f} with an end plate (up to the ring-beam top {LANDING_Z - 4.5:.1f}) against the landing edge trimmer face y {Y_LAND:.0f} (connection ASSUMED, not drawn)')
p_land = Part('Stair landing +3295, posts and bracing (position assumed)', 'STEEL_HDG',
              '',
              conf_st, landing_z_mm=LANDING_Z, landing_box_mm=[POST_X[0], LAND_Y[0], POST_X[1], LAND_Y[1]],
              posts_mm=dict(c_c=[round(POST_X[1] - POST_X[0], 1), round(POSTS[2][1] - POSTS[0][1], 1)], z=[8.0, POST_TOP], cap='44x44x3'),
              members_used='landing ring + L2 ring long sides = 1883 (part); short-side X-braces = 3218 (part); '
                           'L2 ties to the tower (ASSUMED, stand-in for the remaining 3218 pieces); part 643 x5 not placed (use unknown)',
              l2_ties=('2 SHS50 ties at the L2 ring level (z 5520..5570) from the near posts back to the tower N face (W tie on COL3, E tie on '
                       'the L2 N perimeter beam) with 80x170x10 end plates - ASSUMED: the posts run base->L2 per order, so they are taken as '
                       'restrained by the tower at L2') if STAIR_L2_TIES else 'off')
p_sthr = Part('Stair handrails CHS42 CHS27 (position assumed)', 'STEEL_HDG', '', conf_st)

def flight(fd, name):
    zb, n, r, dirn, (xa, xb) = fd['zb'], fd['n'], fd['r'], fd['dirn'], fd['x']
    g = ST['going']
    if dirn > 0:
        y0 = ST['y_edge']
    else:
        y0 = ST['y_edge'] + (n - 1) * g
    Y = lambda t: y0 + dirn * t
    geo = []
    tw0, tw1 = xa + ST['str_w'], xb - ST['str_w']
    leg = min(204.0, r - 20.0)
    for k in range(1, n):
        z = zb + k * r; t0, t1 = (k - 1) * g, k * g
        ya, yb = sorted((Y(t0), Y(t1)))
        geo.append(box(tw0, ya, z - 4, tw1, yb, z))
        yn = Y(t0); yf = (yn, yn + dirn * 4)
        geo.append(box(tw0, min(yf), z - leg, tw1, max(yf), z - 4))
    slope = r / g; cth = math.cos(math.atan(slope))
    hv = ST['str_d'] / cth
    c_top = hv / 2 - r / 2
    zt_top = zb + n * r
    y_end = fd['head_face'] - dirn * STRINGER_END_PLATE
    t_heel, t_head = -133.2, (y_end - y0) * dirn
    Ltop = lambda t: zb + r + t * slope + c_top
    band = Polygon([(t_heel - 400, Ltop(t_heel - 400)), (t_head + 400, Ltop(t_head + 400)),
                    (t_head + 400, Ltop(t_head + 400) - hv), (t_heel - 400, Ltop(t_heel - 400) - hv)])
    band = band.intersection(sbox(t_heel, zb, t_head, zt_top))
    fl = ST['str_fl'] / cth
    band_top = band.intersection(Polygon([(t_heel - 500, Ltop(t_heel - 500) - fl), (t_head + 500, Ltop(t_head + 500) - fl),
                                          (t_head + 500, 1e5), (t_heel - 500, 1e5)]))
    band_bot = band.intersection(Polygon([(t_heel - 500, Ltop(t_heel - 500) - hv + fl), (t_head + 500, Ltop(t_head + 500) - hv + fl),
                                          (t_head + 500, -1e5), (t_heel - 500, -1e5)]))
    U = np.array([0, dirn, 0.0]); Vz = EZ; W = np.cross(U, Vz)
    if zb <= 0.0:
        t3 = min(t_head, (SLAB_PROUD_MM - (zb + r + c_top - hv)) / slope)
        fy_ = sorted((Y(t_heel), Y(t3)))
        for xo, xi in ((xa, xa + ST['str_w']), (xb, xb - ST['str_w'])):
            FEET.append(sbox(min(xo, xi), fy_[0], max(xo, xi), fy_[1]))
    for xo, xi in ((xa, xa + ST['str_w']), (xb, xb - ST['str_w'])):
        web = (xi - math.copysign(ST['str_web'], xi - xo), xi)
        for gpoly, (w0x, w1x) in ((band, web), (band_top, (xo, xi)), (band_bot, (xo, xi))):
            wa, wb = sorted(((w0x) * W[0], (w1x) * W[0]))
            geo.append(extrude(gpoly, wa, wb, (0, y0, 0), U, Vz))
        zhi = min(Ltop(t_head), zt_top); zlo = max(Ltop(t_head) - hv, zb)
        pz1 = fd['plate_top'] if fd['plate_top'] is not None else min(zhi + 10.0, zt_top - 10.0)
        ya_, yb_ = sorted((y_end, fd['head_face']))
        geo.append(box(min(xo, xi), ya_, zlo - 10.0, max(xo, xi), yb_, pz1))
    nos = [(Y(0.0), zb + r), (Y((n - 2) * g), zb + (n - 1) * r)]
    return merge(*geo), nos, (xa, xb)

def flight_F1():
    D = F1_DXF; xa, xb = ST['xB']; sw = ST['str_w']; pt = D['plate_t']
    t_cut = D['top_plate'][1]
    y_heel = Y_FRAME_N + STRINGER_END_PLATE + t_cut
    Y = lambda t: y_heel - t
    k = D['top'] / (D['run'] - D['foot'])
    fl = ST['str_fl'] * math.hypot(1.0, k)
    geo = []
    band = Polygon([(0.0, 0.0), (D['foot'], 0.0), (t_cut, (t_cut - D['foot']) * k), (t_cut, D['top']), (D['top'] / k, D['top'])])
    big = 1e5
    band_top = band.intersection(Polygon([(-big, -k * big - fl), (big, k * big - fl), (big, big * 3), (-big, big * 3)]))
    band_bot = band.intersection(Polygon([(-big, k * (-big - D['foot']) + fl), (big, k * (big - D['foot']) + fl), (big, -big * 3), (-big, -big * 3)]))
    U = np.array([0.0, -1.0, 0.0]); Vz = EZ; W = np.cross(U, Vz)
    for xo, xi in ((xa, xa + sw), (xb, xb - sw)):
        web = (xi - math.copysign(ST['str_web'], xi - xo), xi)
        for gpoly, (w0x, w1x) in ((band, web), (band_top, (xo, xi)), (band_bot, (xo, xi))):
            wa, wb = sorted((w0x * W[0], w1x * W[0]))
            geo.append(extrude(gpoly, wa, wb, (0, y_heel, 0), U, Vz))
        geo.append(box(min(xo, xi), Y(t_cut + STRINGER_END_PLATE), (t_cut - D['foot']) * k - 10.0,
                       max(xo, xi), Y(t_cut), D['top'] + 10.0))
        FEET.append(sbox(min(xo, xi), Y(D['foot']), max(xo, xi), Y(0.0)))
    tw0, tw1 = xa + sw, xb - sw
    for i, (tr, zt) in enumerate(zip(D['t_risers'], D['z_treads'])):
        leg_bot = D['leg0_bot'] if i == 0 else D['z_treads'][i - 1]
        t_end = min(tr + D['tread_len'], t_cut)
        geo.append(box(tw0, Y(t_end), zt - pt, tw1, Y(tr), zt))
        geo.append(box(tw0, Y(tr + pt), leg_bot, tw1, Y(tr), zt - pt))
    tp0, tp1, tpz = D['top_plate']
    geo.append(box(tw0, Y(tp1), D['z_treads'][-1], tw1, Y(tp0), tpz))
    nos = [(Y(D['t_risers'][0]), D['z_treads'][0]), (Y(D['t_risers'][-1]), D['z_treads'][-1])]
    return merge(*geo), nos, (xa, xb)

flights = {}
if STAIR_ON:
    for fn in ('F1', 'F2', 'F3'):
        geo, nos, xr = flight_F1() if fn == 'F1' else flight(F_DEF[fn], fn)
        p_st.add(geo, 1); flights[fn] = (nos, xr)
    pl = sbox(POST_X[0], LAND_Y[0], POST_X[1], LAND_Y[1])
    for (px, py) in POSTS:
        pl = pl.difference(sbox(px - 26, py - 26, px + 26, py + 26))
    p_land.add(extrude(pl, LANDING_Z - 4.5, LANDING_Z))
    shs50 = rrect_profile(50, 50, R_SHS50)
    for (px, py) in POSTS:
        p_land.add(box(px - 100, py - 100, 0, px + 100, py + 100, 8))
        FEET.append(sbox(px - 100, py - 100, px + 100, py + 100))
        p_land.add(sweep(shs50, (px, py, 8), (px, py, POST_TOP), up=EX))
        p_land.add(box(px - 22, py - 22, POST_TOP, px + 22, py + 22, POST_TOP + 3.0), 0)
    zr = LANDING_Z - 4.5 - 25
    Z_RING2 = float(LV['L2']) - 25.0
    (xw, yS), (xe, _), (_, yN) = POSTS[0], POSTS[1], POSTS[2]
    for zz in (zr, Z_RING2):
        p_land.add(sweep(shs50, (xw + 25, yS, zz), (xe - 25, yS, zz)))
        p_land.add(sweep(shs50, (xw + 25, yN, zz), (xe - 25, yN, zz)))
        p_land.add(sweep(shs50, (xw, yS + 25, zz), (xw, yN - 25, zz)))
        p_land.add(sweep(shs50, (xe, yS + 25, zz), (xe, yN - 25, zz)))
    _jx = (ST['xB'][1] - 25.0, ST['xA'][0] + 25.0) if ST['xA'][0] - ST['xB'][1] > 60.0 else ((ST['xB'][1] + ST['xA'][0]) / 2.0,)
    for xx in _jx:
        p_land.add(sweep(shs50, (xx, yS + 25, zr), (xx, yN - 25, zr)))
    zb_top = zr - 30.0
    zb_bot = zb_top - math.sqrt(BRACE_L ** 2 - (yN - yS - 50.0) ** 2)
    for xx in (xw, xe):
        p_land.add(sweep(shs50, (xx, yS + 25, zb_bot), (xx, yN - 25, zb_top), up=EX))
        p_land.add(sweep(shs50, (xx, yN - 25, zb_bot), (xx, yS + 25, zb_top), up=EX))
    p_land.extras['x_brace_mm'] = dict(length=BRACE_L, z=[round(zb_bot, 1), round(zb_top, 1)])
    if STAIR_L2_TIES:
        for xx in (xw, xe):
            p_land.add(sweep(shs50, (xx, yS - 25, Z_RING2), (xx, Y_FRAME_N + 10.0, Z_RING2)))
            p_land.add(box(xx - 40, Y_FRAME_N, float(LV['L2']) - 170.0, xx + 40, Y_FRAME_N + 10.0, float(LV['L2'])))
        p_land.extras['l2_tie_length_mm'] = round(yS - 25 - (Y_FRAME_N + 10.0), 1)
    chs42, chs27 = circle_profile(42.4, 12), circle_profile(26.9, 10)
    for fn, (nos, (xa, xb)) in flights.items():
        (ya, za), (yb, zb_) = nos
        for xx in (xa + ST['str_w'] / 2, xb - ST['str_w'] / 2):
            A = np.array([xx, ya, za]); B = np.array([xx, yb, zb_])
            p_sthr.add(sweep(chs42, A + [0, 0, 1068], B + [0, 0, 1068]))
            p_sthr.add(sweep(chs27, A + [0, 0, 534], B + [0, 0, 534]))
            npost = max(2, int(math.ceil(abs(yb - ya) / 900.0)) + 1)
            for f in np.linspace(0, 1, npost):
                P = A + f * (B - A)
                p_sthr.add(sweep(chs42, P + [0, 0, 60], P + [0, 0, 1068 + 21]), 0)
    zl = LANDING_Z
    for A, B in (((xw + 25, yN), (xe - 25, yN)), ((xw, yS + 25), (xw, yN - 25)), ((xe, yS + 25), (xe, yN - 25))):
        p_sthr.add(sweep(chs42, (A[0], A[1], zl + 1068), (B[0], B[1], zl + 1068)))
        p_sthr.add(sweep(chs27, (A[0], A[1], zl + 534), (B[0], B[1], zl + 534)))

chs48 = circle_profile(48.3, 16)
OPEN = {'HR_L1_N': (-3445.0, ST['xA'][1]), 'HR_L2_N': (-3445.0, ST['xB'][1] + 10.0)} if STAIR_ON else {}
hr_log = []
for h in SF['handrails']:
    (x0, y0, z0), (x1, y1, _) = h['line']
    A = np.array([x0, y0, 0.0]); B = np.array([x1, y1, 0.0]); L = np.linalg.norm(B - A); d = (B - A) / L
    posts = [984.0, L - 984.0]
    seg = (0.0, L)
    if h['id'] in OPEN:
        o0, o1 = OPEN[h['id']]
        s_open_end = o1 - x0
        seg = (s_open_end, L)
        posts = [s for s in posts if s > s_open_end + 150] + [s_open_end + 24.15]
    for zc in (h['bottom_rail_z'], h['top_rail_z']):
        p_hr.add(sweep(chs48, A + d * seg[0] + [0, 0, zc], A + d * seg[1] + [0, 0, zc]), 0)
    cut_post = seg[0] + 24.15 if seg[0] > 0 else None
    for s in posts:
        P = A + d * s
        if cut_post is not None and abs(s - cut_post) < 1e-6:
            p_hr.add(box(P[0] - 50, P[1] - 50, z0, P[0] + 50, P[1] + 50, z0 + 8.0), 0)
            p_hr.add(sweep(chs48, P + [0, 0, z0 + 8.0], P + [0, 0, h['top_rail_z']], up=EX), 0)
        else:
            p_hr.add(sweep(chs48, P + [0, 0, h['bottom_rail_z']], P + [0, 0, h['top_rail_z']], up=EX), 0)
    nrm = np.array([-d[1], d[0], 0.0]); ncl = 0
    for s_end, into in ((seg[0], +1.0), (seg[1], -1.0)):
        if s_end > 0 and s_end < L - 1e-6:
            continue
        for zc in (h['bottom_rail_z'], h['top_rail_z']):
            for side in (+1.0, -1.0):
                P0 = A + d * s_end + nrm * side * 24.65 + [0, 0, zc - 15.0]
                P1 = A + d * (s_end + into * 60.0) + nrm * side * 30.65 + [0, 0, zc + 15.0]
                p_hr.add(box(P0[0], P0[1], P0[2], P1[0], P1[1], P1[2]), 0); ncl += 1
    p_hr.objects += 1
    hr_log.append({'id': h['id'], 'kept_mm': [round(seg[0], 1), round(seg[1], 1)], 'posts_mm': [round(s, 1) for s in posts],
                   'cleats': ncl, 'end_post_to_floor': cut_post is not None})
p_hr.extras['frames'] = hr_log
p_hr.extras['fixings'] = ('60x30x6 cleat pairs at the rail ends on the column faces (ASSUMED: part draws no end fixing; part '
                          '60x60x6 D22 = anchor plate washers, not cleats); free ends at the stair openings: end post down to the floor on a '
                          '100x100x8 foot plate (ASSUMED)')

PC = {p['id']: p for p in SPEC['precast']['panels']}
FIN = {f['id']: f for f in SPEC['precast']['fins']['items']}
WIN = {w['id']: w for w in SPEC['windows']}
T = SPEC['precast']['thickness']
LEG_CHAIN = -PC['PC_S1']['box'][0]
LEG = CHAIN_S0 + LEG_CHAIN
fin_x = sorted([(FIN['FIN_S1a']['box'][0] - CHAIN_S0, FIN['FIN_S1a']['box'][3] - CHAIN_S0),
                (FIN['FIN_S1b']['box'][0] - CHAIN_S0, FIN['FIN_S1b']['box'][3] - CHAIN_S0)])
FIN_D = -FIN['FIN_S1a']['box'][1]
op_x = (PC['PC_S1']['opening_xz'][0] - CHAIN_S0, PC['PC_S1']['opening_xz'][2] - CHAIN_S0)
for st in (1, 2):
    bS, bE = PC[f'PC_S{st}']['box'], PC[f'PC_E{st}']['box']
    assert (bE[0], bE[4]) == (-bS[4], -bS[0]) and (bE[2], bE[5]) == (bS[2], bS[5]), 'E panel is not the mirror of S'
    oS, oE = PC[f'PC_S{st}']['opening_xz'], PC[f'PC_E{st}']['opening_yz']
    assert (oE[0], oE[2]) == (-oS[2], -oS[0]) and (oE[1], oE[3]) == (oS[1], oS[3])
    for a, b in (('a', 'b'), ('b', 'a')):
        fs, fin_e = FIN[f'FIN_S{st}{a}']['box'], FIN[f'FIN_E{st}{b}']['box']
        assert (fin_e[1], fin_e[4]) == (-fs[3], -fs[0]) and (fin_e[0], fin_e[3]) == (-fs[4], -fs[1])

def groove_polys(s0, s1, excl):
    p, D, rw = RIB['pitch'], RIB['depth'], RIB['rib_w']
    sf = RIB['first_rib_s']
    out = [sbox(-sf, -1.0, 5.0, D)]
    for k in range(0, int((s1 - sf) // p) + 2):
        a = sf + k * p; b = a + rw; c = a + p
        dk = RIB['depths'][k % len(RIB['depths'])]
        if dk < D - 1e-9:
            out.append(sbox(-b, -1.0, -a, D - dk))
        out.append(sbox(-c, -1.0, -b, D))
    G = unary_union(out)
    for e0, e1 in excl:
        G = G.difference(sbox(-e1, -5.0, -e0, D + 5.0))
    return G

def mitre_half(offset):
    c = offset * math.sqrt(2.0)
    return Polygon([(-LEG - 1000.0, -1000.0), (1000.0 - c, -1000.0), (-1000.0 - c, 1000.0), (-LEG - 1000.0, 1000.0)])

def mirror_poly(p):
    return Polygon([(-y, -x) for x, y in p.exterior.coords], [[(-y, -x) for x, y in r.coords] for r in p.interiors])

fin_excl = [(-x1, -x0) for x0, x1 in fin_x]
LEG_PLAN = sbox(-LEG, 0, 0, T).intersection(mitre_half(CORNER_JOINT / 2.0)).difference(
    groove_polys(0, LEG, fin_excl))
LEG_PLAN = shapely.set_precision(LEG_PLAN, 1e-4)

_AO = ML._PC_TEX['ao_physical']
p_pc = Part('Precast formliner panels', 'PRECAST_FORMLINER',
            '',
            'high (outline, levels, openings; rib profile measured on the vector precast proposal plan +-1 mm), medium (recess form not drawn), '
            'colour low-medium (Q4: design-render evidence #ACA4A5, no sample)',
            panels=4, size_mm=[LEG, 4530, T], size_note='', rib=dict(RIB, geometry='real (outer faces only); inner faces flat', source=''),
            formliner_ribs='REAL GEOMETRY (precast proposal: rectangular ribs 25 / grooves 20, pitch 45, depths 20-15-10 repeating) - the viewer must NOT add the PRECAST_FORMLINER rib normal map on this node',
            rib_shading_note='',
            procedural_ribs=False,
            finish_status=ML.PRECAST_FINISH_NOTE,
            window_recess_mm=WIN_RECESS, recess_interpretation='10 mm rebate on all 4 sides of the 1010x2010 opening over the frame band (y 40..110 from the rib tips)',
            corner_joint_mm=CORNER_JOINT,
            corner_joint=f'45 deg mitre per elevation partial plan 1:25 (inner corner -> outer arris), {CORNER_JOINT:.0f} mm joint square to the mitre, '
                         f'sealant {JOINT_SEAL[0]:.0f}..{JOINT_SEAL[1]:.0f} mm in from the arris along the joint; S and E panels are exact mirror images',
            gap_to_steel_mm=SPEC['precast']['gap_to_steel'],
            not_modelled='precast connection brackets (BRACKET_01a/02a/03a + 150x125x16 / 300x125x15 angles, cast-in inserts): hidden in the 150 gap')
p_fin = Part('RC fins 350x125', 'PRECAST_FORMLINER', '',
             'high (size/position), colour low-medium (Q4, same concrete as the panels)', count=8, size_mm=[125, FIN_D], note='',
             procedural_ribs=False, formliner_ribs='NONE - plain RC fin faces; the viewer must NOT add the rib normal map on this node')
p_joint = Part('Panel joint sealant', 'SEALANT_BLACK', '',
               'medium (L2 horizontal joint and corner mitre joint drawn; sealant set-back and depth assumed)', setback_mm=list(JOINT_SEAL))
p_wf = Part('Window frames AL T02 1000x2000', 'AL_T02', '',
            'high (size/colour code), medium (profile: 30 frame face + 12.5 glazing lips, 70 deep; depth position estimated)',
            count=4, size_mm=[1000, 2000, 70], sightline_mm=42.5, frame_band_y_mm=list(WIN_FRAME_Y))
p_gl = Part('Window glass GL03 939x1939', 'GL03_VISION_B', '', 'high', count=4, size_mm=[939, 1939],
            note='')
p_ws = Part('Window perimeter sealant', 'SEALANT_BLACK', '',
            'medium (5 mm gap between the 1000x2000 frame and the 1010x2010 opening)')

def storey_pieces(st, plan):
    b = PC[f'PC_S{st}']['box']; z0, z1 = b[2], b[5]
    sill, head = PC[f'PC_S{st}']['opening_xz'][1], PC[f'PC_S{st}']['opening_xz'][3]
    O = sbox(op_x[0], -10, op_x[1], T + 10)
    Nr = sbox(op_x[0] - WIN_RECESS, WIN_FRAME_Y[0], op_x[1] + WIN_RECESS, WIN_FRAME_Y[1])
    PN = plan.difference(Nr)
    bands = [(z0, sill - WIN_RECESS, plan), (sill - WIN_RECESS, sill, PN), (sill, head, PN.difference(O)),
             (head, head + WIN_RECESS, PN), (head + WIN_RECESS, z1, plan)]
    panel = band_stack(bands)
    fins = merge(*[box(x0, -FIN_D, z0, x1, 0, z1) for x0, x1 in fin_x])
    w = WIN[f'W_S{st}']; wx0, wx1, wz0, wz1 = w['x0'] - CHAIN_S0, w['x1'] - CHAIN_S0, w['z0'], w['z1']
    cx, cz = (wx0 + wx1) / 2, (wz0 + wz1) / 2
    U, Vv, org = EX, EZ, (0, 0, 0)
    ring = lambda ax, az, bx, bz: sbox(cx - ax / 2, cz - az / 2, cx + ax / 2, cz + az / 2).difference(sbox(cx - bx / 2, cz - bz / 2, cx + bx / 2, cz + bz / 2))
    fy0, fy1 = WIN_FRAME_Y
    frame = merge(extrude(ring(1000, 2000, 940, 1940), -fy1, -fy0, org, U, Vv),
                  extrude(ring(940.5, 1940.5, 915, 1915), -(fy0 + 12), -fy0, org, U, Vv),
                  extrude(ring(940.5, 1940.5, 915, 1915), -fy1, -(fy1 - 18), org, U, Vv))
    seal = extrude(ring(op_x[1] - op_x[0], head - sill, 1000.5, 2000.5), -(fy0 + 10), -fy0, org, U, Vv)
    gy = (fy0 + fy1) / 2
    gl = (np.array([[cx - 469.5, gy, cz - 969.5], [cx + 469.5, gy, cz - 969.5], [cx + 469.5, gy, cz + 969.5], [cx - 469.5, gy, cz + 969.5]]),
          np.tile([0.0, -1.0, 0.0], (4, 1)), np.array([[0, 1, 2], [0, 2, 3]]))
    js = []
    if st == 1:
        jz0, jz1 = z1, PC['PC_S2']['box'][2]
        for x0, x1 in fin_x:
            js.append(box(x0 + 10, -FIN_D + 10, jz0, x1 - 10, JOINT_SEAL[0], jz1))
    return panel, fins, frame, seal, gl, merge(*js)

for st in (1, 2):
    for leg in ('S', 'E'):
        panel, fins, frame, seal, gl, js = storey_pieces(st, LEG_PLAN)
        f = (lambda g: g) if leg == 'S' else mirror_E
        p_pc.add(f(panel)); p_fin.add(f(fins), 2); p_wf.add(f(frame)); p_ws.add(f(seal)); p_gl.add(f(gl))
        if len(js[0]):
            p_joint.add(f(js), 0)
_js = sbox(-LEG, JOINT_SEAL[0], 0, JOINT_SEAL[1]).intersection(mitre_half(0.0))
_jL = shapely.set_precision(unary_union([_js, mirror_poly(_js)]), 1e-4)
p_joint.add(extrude(_jL, PC['PC_S1']['box'][5], PC['PC_S2']['box'][2]), 0)
if CORNER_JOINT > 0:
    _u = np.array([-1.0, 1.0]) / math.sqrt(2.0); _n = np.array([1.0, 1.0]) / math.sqrt(2.0); _h = CORNER_JOINT / 2.0
    _mj = Polygon([JOINT_SEAL[0] * _u - _h * _n, JOINT_SEAL[1] * _u - _h * _n, JOINT_SEAL[1] * _u + _h * _n, JOINT_SEAL[0] * _u + _h * _n])
    for st in (1, 2):
        b = PC[f'PC_S{st}']['box']
        p_joint.add(extrude(_mj, b[2], b[5]), 0)
p_joint.objects = 1 + 4 + (2 if CORNER_JOINT > 0 else 0)

SLAB_OUTLINE = sbox(*SLAB_ELEV_MM)
if STAIR_ON:
    _m = SLAB_STAIR_MARGIN_MM
    SLAB_OUTLINE = unary_union([SLAB_OUTLINE, sbox(POST_X[0] - 100 - _m, fy1, POST_X[1] + 100 + _m, LAND_Y[1] - 25 + 100 + _m)])
SLAB_OUTLINE = orient(SLAB_OUTLINE.simplify(0.01), 1.0)
SRC_SLAB = (f'{SRC_SHOP} elevation detail (grey RC slab under the base plates, ~530 thick, from ~1.84 m W of the S leg end to ~0.53 m '
            f'E of the E precast face; measured at 4.63 mm/px, not dimensioned); elevation partial plan (concrete hatch all round); '
            f'contract section 4 RC_PLAIN "VMU04 slab", C12/Q3, G9')
slab_mode = None
if RC_SLAB not in ('none', 'auto', 'patch'):
    raise SystemExit(f'MOCKUP_VMU04_SLAB must be auto | patch | none, not {RC_SLAB!r}')
if RC_SLAB == 'auto' and COLUMN_BASE_Y_M <= 1e-6:
    slab_mode = 'none (existing yard slab; F5 /  s3: no RC_PLAIN node for VMU-04)'
elif RC_SLAB != 'none':
    if COLUMN_BASE_Y_M > 1e-6:
        slab_mode = 'plinth'
        p_pl = Part('RC plinth (Q3 raised-slab option)', 'RC_PLAIN', '',
                    'low (outline estimated from detail + the assumed stair footprint; access steps up the plinth not modelled)',
                    height_mm=COLUMN_BASE_Y_M * 1000, outline_local_mm=[[round(x, 1), round(y, 1)] for x, y in SLAB_OUTLINE.exterior.coords[:-1]],
                    note='')
        p_pl.add(extrude(SLAB_OUTLINE, -COLUMN_BASE_Y_M * 1000, 0.0))
    else:
        slab_mode = 'flush patch'
        _feet = [sbox(*mem[f'BP{i}']['box'][:2], *mem[f'BP{i}']['box'][3:5]) for i in range(1, 5)] + FEET
        _patch = SLAB_OUTLINE.difference(unary_union(_feet).buffer(1.0, join_style=2))
        p_pl = Part('RC slab patch (flush with yard)', 'RC_PLAIN', '',
                    'low (extent estimated; slab edge not dimensioned, G9); top SLAB_PROUD_MM above the yard only to avoid z-fighting',
                    proud_mm=SLAB_PROUD_MM, outline_local_mm=[[round(x, 1), round(y, 1)] for x, y in SLAB_OUTLINE.exterior.coords[:-1]],
                    cutouts=f'{len(_feet)} cut-outs (+1 mm) round the 4 column base plates, 4 stair post plates and the F1 stringer feet, '
                            f'which stand on the yard level y 0 (Q3 default)',
                    superseded='F5: the drawn grey RC slab is the existing yard slab (vmu04_base s2.5); this patch is only built with MOCKUP_VMU04_SLAB=patch')
        p_pl.add(extrude(_patch, 0.0, SLAB_PROUD_MM))

def to_gltf(V, N):
    Pr = ORIGIN_R3 + (V[:, :2] + np.asarray(ANCHOR_OFFSET_MM)) / 1000.0
    P = r3_to_gltf(Pr, COLUMN_BASE_Y_M + V[:, 2] / 1000.0)
    n2 = r3_dir_to_gltf(N[:, :2])
    Ngl = np.c_[n2[:, 0], N[:, 2], n2[:, 1]]
    Ngl /= np.maximum(np.linalg.norm(Ngl, axis=1, keepdims=True), 1e-12)
    return P, Ngl

def box_uv(P, N):
    a = np.abs(N); k = a.argmax(1)
    uv = np.where((k == 1)[:, None], P[:, [0, 2]], np.where((k == 0)[:, None], P[:, [2, 1]], P[:, [0, 1]]))
    return uv

def precast_uv(V, N, F, ribbed):
    uv = np.zeros((len(V), 2)); uv[:, 0] = ML.FL_AO_TIP_U; uv[:, 1] = V[:, 2] / 1000.0
    stats = {'tip_floor': 0, 'flank': 0, 'plain': int(len(F))}
    if not ribbed or len(F) == 0:
        return uv, stats
    D, P, rw, sf = RIB['depth'], RIB['pitch'], RIB['rib_w'], RIB['first_rib_s']
    dep = np.asarray(RIB['depths']); nd = len(dep); CYC = P * nd; arc0 = np.asarray(ML.FL_RIB_ARC0)
    Vt = V[F]; Nt = N[F].mean(1); Nt /= np.maximum(np.linalg.norm(Nt, axis=1, keepdims=True), 1e-12)
    c = Vt.mean(1)
    legS = (c[:, 0] + c[:, 1]) < 0
    sv = np.where(legS[:, None], -Vt[..., 0], Vt[..., 1]); yv = np.where(legS[:, None], Vt[..., 1], -Vt[..., 0])
    ns = np.where(legS, -Nt[:, 0], Nt[:, 1]); nyy = np.where(legS, Nt[:, 1], -Nt[:, 0]); nz = np.abs(Nt[:, 2])
    sc, yc = sv.mean(1), yv.mean(1)
    arc = np.full(sv.shape, np.nan)
    outw = (nyy < -0.9) & (nz < 0.1) & (yc <= D + 0.01) & (sc >= sf) & ((sv.max(1) - sv.min(1)) <= max(rw, RIB['groove_w']) + 0.01)
    rel = sc - sf; m = np.floor(rel / CYC); w = rel - m * CYC; j = np.clip(np.floor(w / P), 0, nd - 1).astype(int)
    in_rib = (w - j * P) <= rw
    base_s = sf + m * CYC + j * P
    a_tip = m[:, None] * ML.FL_ARC + arc0[j][:, None] + dep[j][:, None] + (sv - base_s[:, None])
    a_flr = m[:, None] * ML.FL_ARC + arc0[j][:, None] + 2 * dep[j][:, None] + rw + (sv - base_s[:, None] - rw)
    arc = np.where((outw & in_rib)[:, None], a_tip, arc)
    arc = np.where((outw & ~in_rib)[:, None], a_flr, arc)
    fl = (np.abs(ns) > 0.9) & (nz < 0.1) & (yv.min(1) >= -0.01) & (yv.max(1) <= D + 0.01) & (sc >= sf - 0.5)
    left = ns < 0
    k = np.where(left, np.round((sc - sf) / P), np.round((sc - sf - rw) / P)).astype(int)
    mk, jk = np.floor_divide(k, nd), np.mod(k, nd)
    h = np.clip(D - yv, 0.0, dep[jk][:, None])
    a_l = mk[:, None] * ML.FL_ARC + arc0[jk][:, None] + h
    a_r = mk[:, None] * ML.FL_ARC + arc0[jk][:, None] + dep[jk][:, None] + rw + (dep[jk][:, None] - h)
    arc = np.where((fl & left)[:, None], a_l, arc)
    arc = np.where((fl & ~left)[:, None], a_r, arc)
    ok = ~np.isnan(arc).any(1)
    uu = uv[:, 0].copy()
    uu[F[ok].ravel()] = (arc[ok] / ML.FL_ARC).ravel()
    uv[:, 0] = uu
    stats = {'tip_floor': int((ok & outw).sum()), 'flank': int((ok & fl).sum()), 'plain': int((~ok).sum())}
    return uv, stats

def main():
    glb = GLB()
    children = []; tri_total = 0; allP = []
    summary = {}
    for p in PARTS:
        V, N, F = p.mesh()
        if len(F) == 0:
            continue
        P, Ngl = to_gltf(V, N)
        uv = box_uv(P, Ngl)
        if ML.resolve(p.finish) == 'PRECAST_FORMLINER':
            uv, uvst = precast_uv(V, N, F, ribbed=p is p_pc)
            p.extras['uv'] = (f'TEXCOORD_0: u = arc length along the precast rib profile / {ML.FL_ARC:.0f} mm (PRECAST_FORMLINER groove-AO atlas, '
                              f'materials.json textures.armMap), v = z m; non-ribbed faces u = {ML.FL_AO_TIP_U:.4f} (AO 1)')
            p.extras['uv_triangles'] = uvst
        m = ML.mat(glb, p.finish)
        if ML.resolve(p.finish) == 'PRECAST_FORMLINER':
            ext = dict(glb.materials[m].get('extras') or {})
            ext.update(procedural_ribs=False, formliner_ribs='REAL GEOMETRY in vmu04.glb (precast proposal: ribs 25 / grooves 20, pitch 45, depths 20-15-10, '
                                                             'outer faces only); do NOT apply the procedural ribs_normal patch to this material instance')
            glb.materials[m]['extras'] = ext
        mi = glb.mesh(f'VMU04|{p.layer_en}', P, F, Ngl, m, uvs=uv)
        ex = ML.node_extras('VMU04', p.layer_en, p.finish, p.source, p.confidence, objects=p.objects, triangles=int(len(F)))
        ex.update(p.extras)
        lo, hi = V.min(0), V.max(0)
        ex['bbox_local_mm'] = [[round(float(v), 1) for v in lo], [round(float(v), 1) for v in hi]]
        children.append(glb.node(f'VMU04|{p.layer_en}', mesh=mi, extras=ex))
        tri_total += len(F); allP.append(P)
        summary[p.layer_en] = dict(finish=p.finish, objects=p.objects, triangles=int(len(F)), bbox_local_mm=ex['bbox_local_mm'])
    allP = np.concatenate(allP)
    bmin, bmax = allP.min(0), allP.max(0)
    root_ex = {'group': 'VMU04', 'description': 'Vertical corner: precast formliner L-wall on HDG steel tower',
               'layer_en': 'VMU04', 'finish': 'PRECAST_FORMLINER + STEEL_HDG + AL_T02 + GL03_VISION_B (+ SEALANT_BLACK' + (', RC_PLAIN slab)' if slab_mode and not slab_mode.startswith('none') else ')'),
               'source': '',
               'confidence': 'high (tower, precast outline, levels, F1 profile, rib profile from the vector precast proposal plan), medium (window depth; base on the existing slab, no plinth), position assumed (stair), precast colour low-medium (Q4 design-render evidence, no sample)',
               'contract': 'Type-11 architectural precast (formliner) corner with windows, 2 storeys',
               'precast_finish_status': ML.PRECAST_FINISH_NOTE,
               'origin_R3_m': ORIGIN_R3.tolist(), 'rotation_vs_R3_deg': SPEC['local_frame']['rotation_vs_R3_deg'],
               'outside_faces': 'precast faces page -y (bearing 110.3) and page +x (bearing 20.3)',
               'levels_local_mm': {'base': LV['base'], 'L1': LV['L1'], 'L2': LV['L2'], 'ROOF': LV['ROOF'], 'column_top': COL_SHS_TOP + COL_CAP_T,
                                   'precast': [[PC['PC_S1']['box'][2], PC['PC_S1']['box'][5]], [PC['PC_S2']['box'][2], PC['PC_S2']['box'][5]]],
                                   'openings': [PC['PC_S1']['opening_xz'][1::2], PC['PC_S2']['opening_xz'][1::2]]},
               'vmu04_base_check': ('F5  vs  (upheld): plate underside y 0 on the existing yard slab, no plinth, '
                                    'no RC slab node; 400x400x20 plates, 8 M20 + 60x60x6 washers; columns to 10.090 (was 10.113); L1 1.020, L2 5.570, '
                                    'roof 10.120; precast hung 1.030-5.560 / 5.580-10.110 (open steel zone below 1.030); openings 2.020-4.030 / '
                                    '6.570-8.580; stair F1 foot y 0, 5 risers to L1 (was 6x170)'),
               'r3_fin_check': R3_FIN_CHECK,
               'params': {'COLUMN_BASE_Y_M (Q3, env MOCKUP_VMU04_BASE_Y)': COLUMN_BASE_Y_M, 'RC_SLAB (env MOCKUP_VMU04_SLAB)': RC_SLAB,
                          'slab_mode': slab_mode, 'SLAB_PROUD_MM': SLAB_PROUD_MM, 'SLAB_ELEV_MM': list(SLAB_ELEV_MM),
                          'PLAN_ANCHOR (env MOCKUP_VMU04_ANCHOR)': PLAN_ANCHOR, 'ANCHOR_OFFSET_MM': list(ANCHOR_OFFSET_MM),
                          'PRECAST_HEX (Q4, materials_lib)': ML.PRECAST_HEX, 'PRECAST_PLACEHOLDER_HEX (§4 row)': ML.PRECAST_PLACEHOLDER_HEX, 'RIB': RIB,
                          'WIN_FRAME_Y': list(WIN_FRAME_Y), 'WIN_RECESS': WIN_RECESS, 'CORNER_JOINT (mitre)': CORNER_JOINT,
                          'JOINT_SEAL': list(JOINT_SEAL), 'STAIR_ON': STAIR_ON, 'STRINGER_END_PLATE': STRINGER_END_PLATE,
                          'COLUMN_NOTCH': COLUMN_NOTCH, 'STAIR_L2_TIES': STAIR_L2_TIES},
               'datum': 'C12: glTF y = COLUMN_BASE_Y_M + local z; drawing FFL L1 +1.55 / L2 +6.10 / ROOF +10.65 -> y 1.02 / 5.57 / 10.12 (column base = drawing +0.53 at yard level, Q3 default). '
                        'The grey band under the base plates (elevation ~480-500, precast supplier detail exactly 500, break lines, undimensioned) is the existing '
                        'yard slab: no separate node (F5,  MOCKUP_VMU04_BASE_Y=0.53 builds the scenario-B raised plinth under the '
                        'tower and the stair; MOCKUP_VMU04_SLAB=patch rebuilds the superseded flush RC_PLAIN patch.',
               'stair_layout': SPEC_LAYOUT_NOTE if STAIR_ON else 'off',
               'r3_plan_deviation_mm': {'outer corner': 0, 'S face line': 0, 'E face line': 25, 'S leg end (R3 symbol 3215 vs shop 3455.4)': 240,
                                        'E leg end (R3 3291 vs 3455.4)': 164, 'S fin/window group (R3 closer to the corner)': 243,
                                        'E fin/window group (R3 closer to the corner)': 167,
                                        'note': ''},
               'c18_flag': C18_NOTE,
               'triangles': int(tri_total), 'bbox_min': [round(float(v), 4) for v in bmin], 'bbox_max': [round(float(v), 4) for v in bmax],
               'size_m': [round(float(v), 4) for v in bmax - bmin], 'uv': 'TEXCOORD_0 in metres, box projection by the dominant glTF normal axis (build_cad.py convention); PRECAST_FORMLINER nodes: groove-AO atlas coordinates (node extras uv)'}
    glb.node('VMU04', children=children, extras=root_ex, root=True)
    glb.save(OUT_GLB, extras={'title': 'mock-up VMU-04 (precast formliner L-wall on HDG steel tower)', 'wp': 'build step',
                              'frame': 'glTF x=East, y=Up, z=-North (build/site_frame.py); y 0 = yard slab top',
                              'builder': 'build/build_vmu04.py', 'spec': SRC_SPEC})
    print(f'wrote {OUT_GLB}  {os.path.getsize(OUT_GLB) / 1e6:.2f} MB  triangles {tri_total}')
    for k, v in summary.items():
        print(f'  {k:55s} {v["finish"]:18s} obj {v["objects"]:3d} tris {v["triangles"]:7d}  {v["bbox_local_mm"]}')
    print('bbox glTF', root_ex['bbox_min'], root_ex['bbox_max'])
    return root_ex, summary

if __name__ == '__main__':
    main()
