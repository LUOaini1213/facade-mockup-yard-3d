"""First version of model/site_context.glb (yard, factories from the layout plan, containers + viewing platform, fence,
gantry crane, masts). SUPERSEDED by build_context2.py and kept only as a record; the published model is made by
build_context2.py. The step of this first version that added massing for the surrounding buildings from an external map
extract is not part of this copy.
"""
import os, numpy as np, json, math, collections
import shapely.geometry as sg, shapely.ops as so
import mapbox_earcut as earcut
from gltfw import GLB
from site_frame import r3_to_gltf, r3_dir_to_gltf, page_to_r3, s as S_PT, G
SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')

GL = 4.5
H1 = 18.5 - GL
H2 = 29.0 - GL
GX = [343.2, 414.9, 486.5, 558.2, 629.9]
GY = {'L': 24.6, 'M': 113.7, 'N': 200.4, 'O': 287.1, 'P': 376.2}

glb = GLB()
MAT = {}
def mat(name, rgb, alpha=1, metal=0, rough=0.8, **kw):
    MAT[name] = glb.material(name, rgb, alpha, metal, rough, **kw); return MAT[name]
mat('CTX_CONCRETE_YARD', (0.62, 0.61, 0.58), rough=0.92)
mat('CTX_CONCRETE', (0.72, 0.71, 0.68), rough=0.85)
mat('CTX_ROOF_METAL', (0.66, 0.68, 0.70), metal=0.5, rough=0.5)
mat('CTX_WALL_CLAD', (0.66, 0.68, 0.68), metal=0.25, rough=0.55)
mat('CTX_WALL_DARK', (0.30, 0.33, 0.36), metal=0.2, rough=0.6)
mat('CTX_WINDOW', (0.18, 0.24, 0.28), metal=0.3, rough=0.15)
mat('CTX_YELLOW_STEEL', (0.93, 0.70, 0.10), metal=0.3, rough=0.5)
mat('CTX_GANTRY_BLUE', (0.55, 0.74, 0.84), metal=0.3, rough=0.5)
mat('CTX_STEEL_GALV', (0.70, 0.71, 0.72), metal=0.8, rough=0.45)
mat('CTX_STEEL_DARK', (0.25, 0.26, 0.27), metal=0.5, rough=0.5)
mat('CTX_FENCE_MESH', (0.55, 0.58, 0.55), alpha=0.35, metal=0.6, rough=0.5)
mat('CTX_HOARDING_GREEN', (0.22, 0.42, 0.30), rough=0.7)
mat('CTX_KERB', (0.78, 0.77, 0.74), rough=0.9)
mat('CTX_RED_STEEL', (0.62, 0.16, 0.12), metal=0.3, rough=0.6)
mat('CTX_ALU_STOCK', (0.82, 0.83, 0.84), metal=0.8, rough=0.35)
mat('CTX_TIMBER', (0.62, 0.50, 0.34), rough=0.85)
mat('CTX_LAMP', (1.0, 0.97, 0.85), rough=0.3, emissive=(0.6, 0.58, 0.5))
CONT_COLORS = [(0.93, 0.93, 0.91), (0.20, 0.35, 0.62), (0.62, 0.18, 0.14), (0.45, 0.47, 0.49), (0.21, 0.45, 0.33)]
for k, c in enumerate(CONT_COLORS): mat(f'CTX_CONTAINER_{k}', c, metal=0.4, rough=0.55)

class Builder:
    def __init__(s): s.parts = collections.defaultdict(lambda: [[], [], [], []])
    def add(s, key, V, F, N, UV=None):
        p = s.parts[key]; off = sum(len(v) for v in p[0]); p[0].append(V); p[1].append(F + off); p[2].append(N)
        p[3].append(UV if UV is not None else np.zeros((len(V), 2)))
    def quad(s, key, a, b, c, d, uvscale=None):
        V = np.array([a, b, c, d], dtype=float); n = np.cross(V[1] - V[0], V[2] - V[0]); n /= (np.linalg.norm(n) + 1e-12)
        UV = None
        if uvscale:
            u = V[1] - V[0]; lu = np.linalg.norm(u); u /= lu + 1e-12; w = np.cross(n, u)
            UV = np.c_[(V - V[0]) @ u, (V - V[0]) @ w] / uvscale
        s.add(key, V, np.array([[0, 1, 2], [0, 2, 3]]), np.tile(n, (4, 1)), UV)

B = Builder()
def P(px, py, z=0.0):
    return r3_to_gltf(page_to_r3(px, py)[None, :], z)[0]
def Pm(xy, z=0.0):
    return r3_to_gltf(np.asarray(xy, float)[None, :], z)[0]

def box_m(key, x0, x1, y0, y1, z0, z1, uv=None):
    c = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    lo = [Pm(p, z0) for p in c]; hi = [Pm(p, z1) for p in c]
    B.quad(key, hi[0], hi[1], hi[2], hi[3], uv); B.quad(key, lo[3], lo[2], lo[1], lo[0], uv)
    for i in range(4):
        j = (i + 1) % 4; B.quad(key, lo[i], lo[j], hi[j], hi[i], uv)
def box_p(key, px0, px1, py0, py1, z0, z1, uv=None):
    a = page_to_r3(px0, py0); b = page_to_r3(px1, py1)
    box_m(key, min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1]), z0, z1, uv)
def seg_box(key, A, Bp, w, z0, z1):
    A = np.asarray(A, float); Bp = np.asarray(Bp, float); d = Bp - A; L = np.linalg.norm(d)
    if L < 1e-6: return
    u = d / L; n = np.array([-u[1], u[0]]) * w / 2
    c = [A - n, Bp - n, Bp + n, A + n]; lo = [Pm(p, z0) for p in c]; hi = [Pm(p, z1) for p in c]
    B.quad(key, hi[0], hi[1], hi[2], hi[3]); B.quad(key, lo[3], lo[2], lo[1], lo[0])
    for i in range(4):
        j = (i + 1) % 4; B.quad(key, lo[i], lo[j], hi[j], hi[i])
def member(key, A3, B3, w, h=None):
    A3 = np.asarray(A3, float); B3 = np.asarray(B3, float); d = B3 - A3; L = np.linalg.norm(d); u = d / L
    ref = np.array([0, 1, 0]) if abs(u[1]) < 0.9 else np.array([1, 0, 0])
    v = np.cross(u, ref); v /= np.linalg.norm(v); w2 = np.cross(u, v); h = h or w
    c = [v * w / 2 + w2 * h / 2, -v * w / 2 + w2 * h / 2, -v * w / 2 - w2 * h / 2, v * w / 2 - w2 * h / 2]
    a = [A3 + x for x in c]; b = [B3 + x for x in c]
    for i in range(4):
        j = (i + 1) % 4; B.quad(key, a[i], a[j], b[j], b[i])
    B.quad(key, a[3], a[2], a[1], a[0]); B.quad(key, b[0], b[1], b[2], b[3])
def cyl(key, xy, r, z0, z1, n=16):
    ang = np.linspace(0, 2 * np.pi, n + 1)
    for k in range(n):
        p0 = np.asarray(xy) + r * np.array([math.cos(ang[k]), math.sin(ang[k])]); p1 = np.asarray(xy) + r * np.array([math.cos(ang[k + 1]), math.sin(ang[k + 1])])
        B.quad(key, Pm(p0, z0), Pm(p1, z0), Pm(p1, z1), Pm(p0, z1))
def poly_cap(key, poly, z, up=True, uvscale=None):
    rings = [np.asarray(poly.exterior.coords)[:-1]] + [np.asarray(h.coords)[:-1] for h in poly.interiors]
    v = np.vstack(rings); ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
    t = earcut.triangulate_float64(v, ends).reshape(-1, 3)
    V = r3_to_gltf(v, z); N = np.tile([0, 1 if up else -1, 0], (len(V), 1))
    a, b, c = V[t[:, 0]], V[t[:, 1]], V[t[:, 2]]; bad = (np.cross(b - a, c - a)[:, 1] * (1 if up else -1)) < 0
    t[bad] = t[bad][:, ::-1]
    UV = np.c_[V[:, 0], -V[:, 2]] / uvscale if uvscale else None
    B.add(key, V, t, N, UV)

ROAD_A = np.array([307.08, 693.0]); ROAD_B = np.array([811.8, 738.36]); road_u = (ROAD_B - ROAD_A) / np.linalg.norm(ROAD_B - ROAD_A)
far = ROAD_A + road_u * 1150
yard_pg = [(307.08, -330.0), (307.08, 693.0), tuple(far), (far[0], -330.0)]
yard = sg.Polygon([page_to_r3(*p) for p in yard_pg])
poly_cap(('Yard|Concrete slab', 'CTX_CONCRETE_YARD'), yard, 0.0, uvscale=1.0)
bl = [page_to_r3(307.08, -330.0), page_to_r3(307.08, 693.0), page_to_r3(*far)]
for a, b in zip(bl[:-1], bl[1:]): seg_box(('Yard|Kerb', 'CTX_KERB'), a, b, 0.25, -0.05, 0.15)

k1 = 'Factory 1-storey'
for gx in GX:
    for gy in (247.3, GY['O'], GY['P']):
        c = page_to_r3(gx, gy); box_m((k1 + '|Columns', 'CTX_CONCRETE'), c[0] - 0.4, c[0] + 0.4, c[1] - 0.4, c[1] + 0.4, 0, H1 - 1.2)
roof1 = sg.box(*page_to_r3(310.56, 380.28), *page_to_r3(645.72, 247.3)) if False else sg.Polygon([page_to_r3(310.56, 247.3), page_to_r3(645.72, 247.3), page_to_r3(645.72, 380.28), page_to_r3(310.56, 380.28)])
poly_cap((k1 + '|Roof', 'CTX_ROOF_METAL'), roof1, H1, True, 1.0); poly_cap((k1 + '|Roof', 'CTX_ROOF_METAL'), roof1, H1 - 0.25, False, 1.0)
ex = roof1.exterior.coords
for a, b in zip(ex[:-1], ex[1:]): seg_box((k1 + '|Roof fascia', 'CTX_WALL_DARK'), a, b, 0.15, H1 - 1.2, H1 + 0.1)
for gx in GX:
    a = page_to_r3(gx, 247.3); b = page_to_r3(gx, 380.28); seg_box((k1 + '|Rafters', 'CTX_STEEL_DARK'), a, b, 0.35, H1 - 1.2, H1 - 0.25)
for gy in (GY['O'], GY['P']):
    a = page_to_r3(GX[0], gy); b = page_to_r3(GX[-1], gy); seg_box((k1 + '|Crane girders', 'CTX_YELLOW_STEEL'), a, b, 0.6, 9.3, 10.4)
for px in (380, 520):
    a = page_to_r3(px, GY['O']); b = page_to_r3(px, GY['P']); seg_box((k1 + '|Overhead crane', 'CTX_YELLOW_STEEL'), a, b, 1.2, 10.4, 11.4)
a = page_to_r3(310.56, 247.3); b = page_to_r3(310.56, 380.28); seg_box((k1 + '|Side cladding', 'CTX_WALL_CLAD'), a, b, 0.2, 5.0, H1 - 1.2)

k2 = 'Factory 2-storey'
x0, x1, y0, y1 = 343.3, 629.9, GY['L'] - 20, 247.3
zf = 11.5
for gx in GX:
    for gy in (y0, GY['L'], GY['M'], GY['N'], y1):
        c = page_to_r3(gx, gy); box_m((k2 + '|Columns', 'CTX_CONCRETE'), c[0] - 0.5, c[0] + 0.5, c[1] - 0.5, c[1] + 0.5, 0, H2)
box_p((k2 + '|Level 2 slab', 'CTX_CONCRETE'), x0, x1, y0, y1, zf - 0.6, zf)
box_p((k2 + '|Roof', 'CTX_ROOF_METAL'), x0 - 3, x1 + 3, y0, y1 + 3, H2 - 0.4, H2, uv=1.0)
for (ax, ay, bx, by) in ((x0, y0, x0, y1), (x1, y0, x1, y1), (x0, y1, x1, y1)):
    a = page_to_r3(ax, ay); b = page_to_r3(bx, by)
    seg_box((k2 + '|Cladding', 'CTX_WALL_CLAD'), a, b, 0.25, zf, zf + 4.0)
    seg_box((k2 + '|Window band', 'CTX_WINDOW'), a, b, 0.22, zf + 4.0, zf + 6.2)
    seg_box((k2 + '|Cladding', 'CTX_WALL_CLAD'), a, b, 0.25, zf + 6.2, H2 - 0.4)
    seg_box((k2 + '|Cladding', 'CTX_WALL_DARK'), a, b, 0.3, zf - 1.6, zf)
a = page_to_r3(x0, y0); b = page_to_r3(x1, y0); seg_box((k2 + '|Cladding', 'CTX_WALL_CLAD'), a, b, 0.25, 0, H2 - 0.4)
for gx in np.linspace(x0 + 20, x1 - 20, 6):
    a = page_to_r3(gx, y0 + 30); b = page_to_r3(gx, y1 - 20)
    A3 = Pm(a, H2); B3 = Pm(b, H2)
    for t_ in (0.0, 1.0):
        base = A3 + (B3 - A3) * t_; member((k2 + '|Roof yellow frames', 'CTX_YELLOW_STEEL'), base, base + [0, 4.5, 0], 0.35)
    member((k2 + '|Roof yellow frames', 'CTX_YELLOW_STEEL'), A3 + [0, 4.5, 0], B3 + [0, 4.5, 0], 0.5, 0.8)

k3 = 'Factory 2-storey (north block, height assumed)'
box_p((k3 + '|Mass', 'CTX_WALL_CLAD'), 693.84, 840.0, 30.0 - 60, 235.44, 0, H2 - 0.5, uv=1.0)
box_p((k3 + '|Window band', 'CTX_WINDOW'), 693.5, 840.3, 30.0 - 60.3, 235.8, zf + 4.0, zf + 6.2)
box_p((k3 + '|Roof', 'CTX_ROOF_METAL'), 692.0, 842.0, 30.0 - 62, 237.3, H2 - 0.5, H2, uv=1.0)

cx0, cx1 = 458.0, 470.0
ya, yb = 420.4, 694.7
Ltot = (yb - ya) * S_PT
lens = [12.192, 12.192, 12.192, 12.192, 6.058]
gap = (Ltot - sum(lens)) / (len(lens) - 1)
xa, xb = page_to_r3(cx0, ya)[0], page_to_r3(cx1, ya)[0]
yT = page_to_r3(cx0, ya)[1]
cur = yT
spans = []
for k, L in enumerate(lens):
    y_hi = cur; y_lo = cur - L
    key = (f'Containers|40ft/20ft container {k + 1}', f'CTX_CONTAINER_{k % len(CONT_COLORS)}')
    box_m(key, xa + 0.03, xb - 0.03, y_lo, y_hi, 0, 2.896)
    for rr in np.arange(y_lo + 0.3, y_hi - 0.2, 0.28):
        box_m(key, xa - 0.0, xa + 0.03, rr, rr + 0.12, 0.1, 2.8); box_m(key, xb - 0.03, xb, rr, rr + 0.12, 0.1, 2.8)
    spans.append((y_lo, y_hi)); cur = y_lo - gap
ylo, yhi = spans[-1]
box_m(('Containers|Office windows', 'CTX_WINDOW'), xb - 0.02, xb + 0.01, ylo + 1.2, ylo + 2.6, 1.0, 2.1)
box_m(('Containers|AC unit', 'CTX_WALL_CLAD'), xb, xb + 0.35, ylo + 3.3, ylo + 4.1, 1.8, 2.4)
py_lo, py_hi = spans[2][0], spans[1][1]
kp = 'Temporary steel viewing platform'
box_m((kp + '|Deck (chequer plate)', 'CTX_STEEL_GALV'), xa - 0.6, xb + 0.6, py_lo, py_hi, 2.90, 3.00)
for yy in np.arange(py_lo, py_hi + 0.01, 2.0):
    for xx in (xa - 0.55, xb + 0.55): box_m((kp + '|Guardrail', 'CTX_YELLOW_STEEL'), xx - 0.03, xx + 0.03, yy - 0.03, yy + 0.03, 3.0, 4.1)
for xx in (xa - 0.55, xb + 0.55):
    for zz in (3.55, 4.1): seg_box((kp + '|Guardrail', 'CTX_YELLOW_STEEL'), (xx, py_lo), (xx, py_hi), 0.05, zz - 0.05, zz)
for yy in (py_lo, py_hi):
    for zz in (3.55, 4.1): seg_box((kp + '|Guardrail', 'CTX_YELLOW_STEEL'), (xa - 0.55, yy), (xb + 0.55, yy), 0.05, zz - 0.05, zz)
st_y = py_hi - 1.2
for k in range(16):
    z = 3.0 * (k + 1) / 16; xx = xa - 0.7 - (15 - k) * 0.25
    box_m((kp + '|Stair', 'CTX_STEEL_GALV'), xx - 0.25, xx, st_y - 1.0, st_y, z - 0.05, z)
seg_box((kp + '|Stair', 'CTX_STEEL_GALV'), (xa - 0.7 - 16 * 0.25, st_y - 1.0), (xa - 0.7, st_y - 1.0), 0.06, 0, 3.0)

fence_line = [page_to_r3(307.08, -330.0), page_to_r3(307.08, 693.0), page_to_r3(*far)]
for a, b in zip(fence_line[:-1], fence_line[1:]):
    a = np.asarray(a); b = np.asarray(b); L = np.linalg.norm(b - a); u = (b - a) / L
    for t in np.arange(0, L + 0.01, 3.0):
        p = a + u * t; cyl(('Boundary fence|Posts', 'CTX_STEEL_GALV'), p, 0.03, 0, 1.9, 8)
    n = np.array([-u[1], u[0]]) * 0.01
    A = [Pm(a + n, 0.05), Pm(b + n, 0.05), Pm(b + n, 1.8), Pm(a + n, 1.8)]
    B.quad(('Boundary fence|Chain-link mesh', 'CTX_FENCE_MESH'), *A, uvscale=0.06)
    seg_box(('Boundary fence|Top rail', 'CTX_STEEL_GALV'), a, b, 0.04, 1.78, 1.82)

kg = 'Gantry crane (context, position approximate)'
rail_x = (712.0, 800.0)
for rx in rail_x:
    a = page_to_r3(rx, 180.0); b = page_to_r3(rx, 680.0); seg_box((kg + '|Rails', 'CTX_STEEL_DARK'), a, b, 0.25, 0, 0.12)
gy_c = 330.0
span = [page_to_r3(rx, gy_c) for rx in rail_x]
for sp in span:
    for dy in (-3.5, 3.5):
        foot = Pm(sp + [0, dy], 0.4); top = Pm(sp + [0, 0], 11.5)
        member((kg + '|Legs', 'CTX_GANTRY_BLUE'), foot, top, 0.7)
    box_m((kg + '|End carriage', 'CTX_GANTRY_BLUE'), sp[0] - 0.6, sp[0] + 0.6, sp[1] - 4.2, sp[1] + 4.2, 0.0, 0.8)
for dyo in (-0.9, 0.9):
    member((kg + '|Main girder', 'CTX_GANTRY_BLUE'), Pm(span[0] + [-4.0, dyo], 12.0), Pm(span[1] + [4.0, dyo], 12.0), 0.9, 1.6)
tr = (span[0] + span[1]) / 2 + np.array([-3.0, 0])
box_m((kg + '|Trolley + hoist', 'CTX_STEEL_DARK'), tr[0] - 1.2, tr[0] + 1.2, tr[1] - 1.6, tr[1] + 1.6, 12.8, 14.0)
box_m((kg + '|Operator cab', 'CTX_WINDOW'), span[1][0] - 1.0, span[1][0] + 0.6, span[1][1] + 1.2, span[1][1] + 2.8, 9.2, 11.0)

for px_ in (380.0, 560.0, 740.0, 920.0):
    t = (px_ - ROAD_A[0]) / road_u[0]; bp = ROAD_A + road_u * t + np.array([0, -14.0])
    c = page_to_r3(*bp); cyl(('Floodlight masts|Pole', 'CTX_STEEL_GALV'), c, 0.18, 0, 16.0, 12)
    box_m(('Floodlight masts|Head frame', 'CTX_STEEL_DARK'), c[0] - 0.9, c[0] + 0.9, c[1] - 0.15, c[1] + 0.15, 15.8, 16.0)
    for dx in (-0.6, 0.0, 0.6): box_m(('Floodlight masts|Lamps', 'CTX_LAMP'), c[0] + dx - 0.22, c[0] + dx + 0.22, c[1] - 0.25, c[1] + 0.2, 15.35, 15.8)

for k, py_ in enumerate(np.arange(440.0, 680.0, 34.0)):
    a = page_to_r3(318.0, py_); key = ('Material storage|Stillage racks', 'CTX_RED_STEEL')
    x0_, y0_ = a[0], a[1] - 6.0
    for dx in (0, 1.2):
        for dy in (0, 2.0, 4.0, 6.0): box_m(key, x0_ + dx, x0_ + dx + 0.08, y0_ + dy, y0_ + dy + 0.08, 0, 1.6)
    for z in (0.25, 1.55): box_m(key, x0_, x0_ + 1.28, y0_, y0_ + 6.08, z - 0.08, z)
    for j in range(6): box_m(('Material storage|Aluminium stock', 'CTX_ALU_STOCK'), x0_ + 0.12 + j * 0.17, x0_ + 0.25 + j * 0.17, y0_ - 0.2, y0_ + 6.3, 0.25, 0.25 + 0.12 * (1 + j % 3))
    box_m(('Material storage|Timber dunnage', 'CTX_TIMBER'), x0_ + 3.0, x0_ + 4.2, y0_ + 1.0, y0_ + 5.0, 0, 0.35)


nodes = collections.defaultdict(list); tri_count = 0
for (name, mname), (Vs, Fs, Ns, UVs) in B.parts.items():
    V = np.vstack(Vs); F = np.vstack(Fs); N = np.vstack(Ns); UV = np.vstack(UVs)
    grp, part = name.split('|', 1)
    mi = glb.mesh(name, V, F, N, MAT[mname], uvs=UV)
    nodes[grp].append(glb.node(name, mesh=mi, extras=dict(group='CONTEXT', context=grp, part=part, finish=mname, triangles=int(len(F)))))
    tri_count += len(F)
for grp, ch in nodes.items(): glb.node(grp, children=ch, root=True, extras=dict(group='CONTEXT', context=grp))
meta = dict(ground_level_assumed=GL, roof_1storey_m=H1, roof_2storey_m=H2, triangles=tri_count,
            notes='')
glb.save('../model/site_context.glb', extras=meta)
json.dump(meta, open('../model/site_context_summary.json', 'w'), indent=1)
print(meta)
