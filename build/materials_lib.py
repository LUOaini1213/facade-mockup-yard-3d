"""Canonical material library of the mock-up model: sRGB hex, metalness, roughness, glass recipes, CC0 texture sets,
the generated groove-AO atlas of the ribbed precast formliner, the material extras written into every GLB and
model/materials.json (python materials_lib.py runs a self-test and writes the JSON). The self-test compares the
library with the private material contract table, which is not included.
"""
import os, sys, json, math, copy, re, warnings

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if not os.path.isfile(os.path.join(ROOT, 'build', 'gltfw.py')):
    _p = HERE
    while os.path.dirname(_p) != _p and not os.path.isfile(os.path.join(_p, 'build', 'gltfw.py')):
        _p = os.path.dirname(_p)
    ROOT = _p if os.path.isfile(os.path.join(_p, 'build', 'gltfw.py')) else ROOT
JSON_PATH = os.environ.get('MOCKUP_MATERIALS_JSON') or os.path.join(ROOT, 'model', 'materials.json')
SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')
CONTRACT_MD = os.environ.get('MOCKUP_CONTRACT_MD') or os.path.join(SOURCES_DIR, 'material_contract.md')
for _d in (HERE, os.path.join(ROOT, 'build')):
    if _d not in sys.path:
        sys.path.insert(0, _d)

CANOPY_TOP_OPTIONS = ('AL_MOUSEGREY', 'AL_T02', 'AL_RAL7038')
CANOPY_TOP_MATERIAL = os.environ.get('MOCKUP_CANOPY_TOP', 'AL_MOUSEGREY')
PRECAST_PLACEHOLDER_HEX = '#6E6E6C'
PRECAST_PREVIOUS_HEX = '#B2AAAB'
PRECAST_LAB_SCI = (69.5, 1.2, 6.0)
PRECAST_SPECULAR = 0.005
PRECAST_EVIDENCE_HEX = '#B0A89E'
PRECAST_FINISH_NOTE = ''
PRECAST_RANGE = {'lighter_est': '#C1B8B9', 'darker_est': '#A49C9D'}
PRECAST_HEX = os.environ.get('MOCKUP_PRECAST_HEX', PRECAST_EVIDENCE_HEX).upper()
if CANOPY_TOP_MATERIAL not in CANOPY_TOP_OPTIONS:
    raise ValueError(f'CANOPY_TOP_MATERIAL must be one of {CANOPY_TOP_OPTIONS}, got {CANOPY_TOP_MATERIAL!r} (never red)')
if not re.fullmatch(r'#[0-9A-F]{6}', PRECAST_HEX):
    raise ValueError(f'PRECAST_HEX must look like #RRGGBB, got {PRECAST_HEX!r}')

CONTRACT = 'material contract (colour basis SCE)'

def hex_to_srgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def linear_to_srgb(c):
    c = min(max(c, 0.0), 1.0)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055

def hex_to_linear(h):
    return tuple(srgb_to_linear(c) for c in hex_to_srgb(h))

def linear_to_hex(lin):
    return '#' + ''.join('%02X' % int(round(linear_to_srgb(c) * 255)) for c in lin)

def luminance(lin):
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

def f0_from_ior(ior):
    return ((ior - 1.0) / (ior + 1.0)) ** 2

_M_RGB2XYZ = ((0.4124564, 0.3575761, 0.1804375), (0.2126729, 0.7151522, 0.0721750), (0.0193339, 0.1191920, 0.9503041))
_M_XYZ2RGB = ((3.2404542, -1.5371385, -0.4985314), (-0.9692660, 1.8760108, 0.0415560), (0.0556434, -0.2040259, 1.0572252))
_WHITE_D65 = tuple(sum(r) for r in _M_RGB2XYZ)

def _lab_f(t):
    return t ** (1.0 / 3.0) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29

def _lab_finv(t):
    return t ** 3 if t > 6 / 29 else 3 * (6 / 29) ** 2 * (t - 4 / 29)

def Y_to_L(Y):
    return 116.0 * _lab_f(Y) - 16.0

def L_to_Y(L):
    return _lab_finv((L + 16.0) / 116.0)

def hex_to_lab(h):
    lin = hex_to_linear(h)
    X = [sum(m * c for m, c in zip(row, lin)) / w for row, w in zip(_M_RGB2XYZ, _WHITE_D65)]
    fx, fy, fz = (_lab_f(v) for v in X)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))

def lab_to_hex(L, a, b):
    fy = (L + 16) / 116
    X = (_WHITE_D65[0] * _lab_finv(fy + a / 500), _WHITE_D65[1] * _lab_finv(fy), _WHITE_D65[2] * _lab_finv(fy - b / 200))
    return linear_to_hex([sum(m * c for m, c in zip(row, X)) for row in _M_XYZ2RGB])

def sce_hex(Y_sce, a, b):
    return lab_to_hex(Y_to_L(Y_sce), a, b)

def de2000(lab1, lab2):
    L1, a1, b1 = lab1; L2, a2, b2 = lab2
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2); Cb = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p, h2p = math.degrees(math.atan2(b1, a1p)) % 360, math.degrees(math.atan2(b2, a2p)) % 360
    dLp, dCp, dh = L2 - L1, C2p - C1p, h2p - h1p
    if C1p * C2p == 0: dh = 0
    elif dh > 180: dh -= 360
    elif dh < -180: dh += 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dh / 2))
    Lbp, Cbp, hs = (L1 + L2) / 2, (C1p + C2p) / 2, h1p + h2p
    if C1p * C2p == 0: hbp = hs
    elif abs(h1p - h2p) <= 180: hbp = hs / 2
    elif hs < 360: hbp = (hs + 360) / 2
    else: hbp = (hs - 360) / 2
    T = (1 - 0.17 * math.cos(math.radians(hbp - 30)) + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6)) - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    dth = 30 * math.exp(-((hbp - 275) / 25) ** 2)
    Rc = 2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / math.sqrt(20 + (Lbp - 50) ** 2); Sc = 1 + 0.045 * Cbp; Sh = 1 + 0.015 * Cbp * T
    Rt = -math.sin(math.radians(2 * dth)) * Rc
    return math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))

def _calib(lab_sci, Y_sce, specular_pct, refs, gloss60_GU=None, Y_sci=None, **kw):
    L, a, b = lab_sci
    d = dict(colour_basis='SCE', hex_sci=lab_to_hex(L, a, b), lab_sci=[round(float(v), 2) for v in lab_sci],
             Y_sci=round(Y_sci if Y_sci is not None else L_to_Y(L), 4), Y_sce=round(Y_sce, 4), specular_pct=specular_pct,
             gloss60_GU=gloss60_GU, calib_ref='')
    d.update(kw)
    return d

def _r(x, n=4):
    return [round(float(v), n) for v in x]

_TEX_SRC = 'textures/'
_TEX_DST = 'textures/'
TEXSETS = {
    'brushed_concrete': dict(res='2k', size_m=2.5, license='CC0 Poly Haven brushed_concrete (Dario Barresi, Dimitrios Savva)',
                             map_mean_linear=(0.1485, 0.1274, 0.0996), arm_mean=(0.892, 0.784, 0.007)),
    'clean_asphalt': dict(res='1k', size_m=2.1, license='CC0 Poly Haven clean_asphalt (Dimitrios Savva)',
                          map_mean_linear=(0.0595, 0.0618, 0.0621), arm_mean=(0.891, 0.660, 0.005)),
    'corrugated_iron_03': dict(res='1k', size_m=2.0, license='CC0 Poly Haven corrugated_iron_03 (Charlotte Baglioni)',
                               map_mean_linear=(0.1521, 0.1825, 0.1816), arm_mean=(0.838, 0.757, 0.001)),
    'Metal009': dict(res='1K', size_m=None, license='CC0 ambientCG Metal009', roughness_mean=0.469),
}

def _ph_textures(setname, hexcol, rough, size_m=None, use_map=True, note=None):
    t = TEXSETS[setname]
    res = t['res']
    base_s, base_d = f'{_TEX_SRC}{setname}/{setname}_', f'{_TEX_DST}{setname}/{setname}_'
    tgt = hex_to_linear(hexcol)
    out = {'set': setname, 'license': t['license'], 'size_m': size_m or t['size_m'],
           'uv': 'UVs in metres; repeat = 1/size_m'}
    if use_map:
        out['map'] = {'file': f'{base_d}diff_{res}.jpg', 'src': f'{base_s}diff_{res}.jpg', 'colorSpace': 'srgb'}
        out['map_mean_linear'] = list(t['map_mean_linear'])
        out['color_with_map_linear'] = _r([a / b for a, b in zip(tgt, t['map_mean_linear'])], 3)
    out['normalMap'] = {'file': f'{base_d}nor_gl_{res}.jpg', 'src': f'{base_s}nor_gl_{res}.jpg', 'colorSpace': 'linear', 'convention': 'OpenGL (+Y)'}
    out['armMap'] = {'file': f'{base_d}arm_{res}.jpg', 'src': f'{base_s}arm_{res}.jpg', 'colorSpace': 'linear',
                     'channels': 'R=AO, G=roughness, B=metalness', 'use': 'aoMap (R) + roughnessMap (G); ignore B, metalness comes from the material'}
    out['arm_mean'] = list(t['arm_mean'])
    out['roughness_with_map'] = round(rough / t['arm_mean'][1], 3)
    if note:
        out['note'] = ''
    return out

def _metal009_roughness(rough, size_m):
    t = TEXSETS['Metal009']
    return {'set': 'Metal009', 'license': t['license'], 'size_m': size_m, 'uv': 'UVs in metres; repeat = 1/size_m',
            'roughnessMap': {'file': f'{_TEX_DST}acg/Metal009/Metal009_1K-JPG_Roughness.jpg',
                             'src': f'{_TEX_SRC}acg/Metal009/Metal009_1K-JPG_Roughness.jpg', 'colorSpace': 'linear'},
            'roughness_map_mean': t['roughness_mean'], 'roughness_with_map': round(rough / t['roughness_mean'], 3),
            'note': ''}

FORMLINER = dict(pitch=45.0, rib_w=25.0, groove_w=20.0, depths=(20.0, 15.0, 10.0), first_rib_s=30.4, base=125.0, total=145.0,
                 source='')
FL_CYCLE = FORMLINER['pitch'] * len(FORMLINER['depths'])
FL_RIB_ARC0 = []
_a = 0.0
for _d in FORMLINER['depths']:
    FL_RIB_ARC0.append(_a); _a += 2 * _d + FORMLINER['rib_w'] + FORMLINER['groove_w']
FL_ARC = _a
FL_AO_TIP_U = (FL_RIB_ARC0[0] + FORMLINER['depths'][0] + FORMLINER['rib_w'] / 2) / FL_ARC
VIEWER_AOMAP_INTENSITY = 0.7

def formliner_segments():
    P, rw, gw = FORMLINER['pitch'], FORMLINER['rib_w'], FORMLINER['groove_w']
    out, arc = [], 0.0
    for j, d in enumerate(FORMLINER['depths']):
        a = j * P; b = a + rw
        for seg, n in (((a, 0.0, a, d), (-1.0, 0.0)), ((a, d, b, d), (0.0, 1.0)), ((b, d, b, 0.0), (1.0, 0.0)), ((b, 0.0, (j + 1) * P, 0.0), (0.0, 1.0))):
            out.append(seg + (n, arc)); arc += math.hypot(seg[2] - seg[0], seg[3] - seg[1])
    return out

def formliner_ao(rho, res_mm=1.0, n_dir=1024, tiles=5):
    import numpy as np
    segs = formliner_segments()
    cen, nrm, arcs = [], [], []
    for (s0, h0, s1, h1, n, arc0) in segs:
        L = math.hypot(s1 - s0, h1 - h0); m = max(1, int(round(L / res_mm)))
        for i in range(m):
            f = (i + 0.5) / m
            cen.append((s0 + (s1 - s0) * f, h0 + (h1 - h0) * f)); nrm.append(n); arcs.append(arc0 + L * f)
    C = np.array(cen); Nn = np.array(nrm); A = np.array(arcs); N = len(C)
    u = -1.0 + (2.0 * np.arange(n_dir) + 1.0) / n_dir
    th = np.arcsin(u)
    T = np.c_[Nn[:, 1], -Nn[:, 0]]
    D = np.cos(th)[None, :, None] * Nn[:, None, :] + np.sin(th)[None, :, None] * T[:, None, :]
    O = C[:, None, :] + Nn[:, None, :] * 1e-6
    best = np.full((N, n_dir), np.inf); hit_arc = np.zeros((N, n_dir))
    H = max(FORMLINER['depths'])
    for k in range(-(tiles // 2), tiles // 2 + 1):
        for (s0, h0, s1, h1, n, arc0) in segs:
            p = np.array([s0 + k * FL_CYCLE, h0]); sd = np.array([s1 - s0, h1 - h0]); L = math.hypot(*sd)
            den = D[..., 0] * sd[1] - D[..., 1] * sd[0]
            ok = np.abs(den) > 1e-12
            w0 = p[0] - O[..., 0]; w1 = p[1] - O[..., 1]
            dd = np.where(ok, den, 1.0)
            t = (w0 * sd[1] - w1 * sd[0]) / dd; q = (w0 * D[..., 1] - w1 * D[..., 0]) / dd
            h = ok & (t > 1e-7) & (q >= 0) & (q <= 1) & (t < best)
            best = np.where(h, t, best); hit_arc = np.where(h, arc0 + q * L, hit_arc)
    esc = ~np.isfinite(best)
    Fsky = esc.mean(1)
    F = np.zeros((N, N))
    ha = np.mod(hit_arc, FL_ARC)
    i1 = np.clip(np.searchsorted(A, ha), 1, N - 1)
    idx = np.where(np.abs(A[i1 - 1] - ha) <= np.abs(A[i1] - ha), i1 - 1, i1)
    for i in range(N):
        j = idx[i][~esc[i]]
        if len(j):
            np.add.at(F[i], j, 1.0 / n_dir)
    B = np.linalg.solve(np.eye(N) - rho * F, rho * Fsky)
    return A, B / rho, Fsky

def _png_rgb(rows):
    import zlib, struct
    raw = b''.join(b'\x00' + bytes(v for px in row for v in px) for row in rows)
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    h, w = len(rows), len(rows[0])
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))

def formliner_ao_texture(rho, rough):
    import base64
    import numpy as np
    A, E, Fsky = formliner_ao(rho)
    W = int(round(FL_ARC)); xs = np.arange(W) + 0.5
    e = np.interp(xs, A, E, period=FL_ARC)
    r = np.clip(1.0 - (1.0 - e) / VIEWER_AOMAP_INTENSITY, 0.0, 1.0)
    row = [(int(round(v * 255)), 255, 0) for v in r]
    png = _png_rgb([row] * 4)
    areas = []
    segs = formliner_segments()
    proj = np.zeros_like(A)
    for (s0, h0, s1, h1, n, arc0) in segs:
        L = math.hypot(s1 - s0, h1 - h0)
        k = (A >= arc0) & (A < arc0 + L)
        proj[k] = abs(n[1])
    face_on = float((E * proj).sum() / proj.sum())
    part = {}
    for (s0, h0, s1, h1, n, arc0) in segs:
        L = math.hypot(s1 - s0, h1 - h0); k = (A >= arc0) & (A < arc0 + L)
        key = 'flank' if abs(n[0]) > 0.5 else ('floor' if h0 == 0 else f'tip_{int(h0)}')
        part.setdefault(key, []).append(E[k].mean())
    return {'set': 'formliner_rib_ao (generated by materials_lib.formliner_ao_texture)', 'license': 'generated (project geometry)',
            'size_m': 1.0,
            'uv': 'vmu04.glb TEXCOORD_0: u = arc length along the precast proposal rib profile / 225 mm (one 135 mm cycle = 3 ribs; arc 0 = foot '
                  'of the 20 mm rib left flank), v = z in m; faces off the ribbed field (fins, caps, reveals, inner faces) sit at '
                  f'u = {FL_AO_TIP_U:.4f} (AO 1). Any other user of PRECAST_FORMLINER must put its UVs there too.',
            'armMap': {'file': 'data:image/png;base64,' + base64.b64encode(png).decode('ascii'),
                       'src': 'generated:materials_lib.formliner_ao_texture', 'colorSpace': 'linear', 'size_px': [W, 4],
                       'channels': f'R = groove AO pre-compensated for the viewer aoMapIntensity {VIEWER_AOMAP_INTENSITY} '
                                   '(effective = physical E), G = 255 (roughness x 1), B = 0',
                       'use': 'aoMap (R, indirect light only) + roughnessMap (G)'},
            'arm_mean': [round(float(r.mean()), 4), 1.0, 0.0], 'roughness_with_map': round(rough, 3),
            'ao_physical': {'method': '2D radiosity, deterministic (1024 stratified directions, 1 mm elements), rho = material Y',
                            'rho': round(rho, 4), 'E_min': round(float(E.min()), 3), 'face_on_mean': round(face_on, 3),
                            'by_part': {k: round(float(np.mean(v)), 3) for k, v in part.items()},
                            'sky_view_min': round(float(Fsky.min()), 3)}}

_M = {}

def _add(name, hexcol, metal, rough, category, used_by, confidence, note, source, **kw):
    e = dict(hex=hexcol.upper(), metalness=float(metal), roughness=float(rough), category=category,
             used_by=used_by, confidence=confidence, note='', source='')
    e.update(kw)
    _M[name] = e

_GLASS_FALLBACK_HEX = '#2A3238'

_add('AL_RAL7038', '#A8AAA4', 0, 0.55, 'vmu',
     'VMU01 fins 装饰条 / 装饰条铝板; VMU03 all panels + fins + coping; '
     'VMU01 canopy only as the non-default alternative (build_canopy SCHEME=RAL7038 / CANOPY_TOP_MATERIAL=AL_RAL7038). '
     'Existing Trellis blades / louvres are AL_T02 (G2); Trellis redo rings: colour open, AL_RAL7038 is one '
     'MOCKUP_TRELLIS_RING_FINISH option (AL_T02 | AL_RAL7038 | AL_MILL)',
     '',
     '',
     '',
     codes='', lrv=0.4115,
     **_calib((70.28, -1.85, 2.84), 0.3965, 1.5,
              '',
              Y_sci=0.4115, Y_sce_measured=True, previous_hex='#AAADA6'),
     param={'Q1': 'non-default canopy alternative (build_canopy SCHEME=RAL7038 or CANOPY_TOP_MATERIAL=AL_RAL7038)'})
_add('AL_T02', '#4B5055', 0, 0.50, 'vmu',
     'VMU01 铝板 (non-canopy), 收口铝板, 横梁/立柱/中横梁/小横梁, 百叶; VMU02 exterior bands, caps, skirting; VMU04 window frames; '
     'VMU01 canopy ALL 3 mm parts (150 top perimeter band + oculus band, 100 fascia, 420x205 chamfer, soffit edge strip, soffit trays); '
     'canopy CHS150 columns + base plates (build_canopy COLUMN_FINISH default, inferred: dark-paint colour proxy - '
     'the 6 existing to-be-replaced legacy CAD columns are dark-painted in site photos, no spec for the 11 new columns); '
     'Q1 alternative for the canopy top; existing Trellis blades / louvres (G2); Trellis redo straight bars '
     '+ cover plates; Trellis redo rings only as the colour-open default of MOCKUP_TRELLIS_RING_FINISH '
     '(plan §3 B3)',
     '',
     '',
     '',
     codes='',
     **_calib((36.9, -1.5, -3.3), 0.078, 1.7,
              '',
              gloss60_GU=18.9, gloss60_range=[15.5, 21.2], Y_sce_range=[0.072, 0.0805], hex_range=['#474D51', '#4B5155'],
              specular_range_pct=[1.5, 2.2], hex_kept=True),
     param={'Q1': 'alternative canopy top colour (CANOPY_TOP_MATERIAL=AL_T02)'})
_add('AL_MOUSEGREY', '#707370', 0, 0.50, 'vmu',
     'VMU01 canopy TOP 25 mm aluminium honeycomb field (existing + extension; the extension has no panel order yet -> same scheme); '
     'default of CANOPY_TOP_MATERIAL (Q1)',
     '',
     '',
     '',
     codes='',
     **_calib((49.8, -1.55, 0.82), 0.1675, 1.5,
              '',
              specular_assumed=True, previous_hex='#6C6E6B'),
     param={'Q1': 'default canopy top colour (CANOPY_TOP_MATERIAL); alternatives AL_T02, AL_RAL7038'})
_add('AL_T01', '#414A52', 0, 0.50, 'vmu',
     'interior covers (VMU02 mullions, VMU01 铝背板)',
     '',
     '',
     '',
     codes='',
     **_calib((Y_to_L(0.0881), -1.2, -6.1), 0.0658, 2.23,
              '',
              gloss60_GU=26, Y_sci=0.0881, Y_sce_measured=True, previous_hex='#45494D'))
_add('AL_RAL9016', '#F0F0EB', 0, 0.45, 'vmu',
     'VMU01 roof coping: 475x450 folded coping. Applied through '
     'build_cad.py COPING_FINISH (default AL_RAL9016; the coping carries '
     'AL_RAL9016, 5,503 triangles; WHITE / AL_T02 remain only as env MOCKUP_COPING_FINISH alternatives)',
     '',
     '',
     '',
     codes='',
     **_calib((95.26, -0.76, 2.11), L_to_Y(95.26) - 0.015, 1.5,
              '',
              specular_assumed=True, replaces='WHITE #E8E8E3 (coping stand-in, G2)'))
_add('AL_WOOD', '#D0B282', 0, 0.55, 'vmu',
     'VMU01 TYPE 11 ground grille, L300×300×5 posts ×17 L4420 + rails',
     '',
     '',
     '',
     clearcoat=0.0, codes='',
     **_calib((74.93, 4.16, 28.4), 0.4666, 1.5,
              '',
              Y_sci=0.4816, specular_assumed=True, previous_hex='#A98056', gloss='matte (亚光), no GU value'),
     procedural={'type': 'woodgrain', 'slot': 'map', 'value_amplitude': 0.08, 'value_amplitude_range': [0.06, 0.10],
                 'grain_axis': 'along member (vertical)', 'grain_period_m': [0.004, 0.012],
                 'note': ''})
_add('AL_METBLACK', '#2B2C2E', 0.6, 0.35, 'vmu',
     'VMU01 lift-lobby panel', '',
     '',
     '',
     codes='')
_add('AL_MILL', '#C9CED2', 1, 0.40, 'vmu',
     'concealed brackets (VMU03 码件)', '',
     '',
     '')
_add('STEEL_HDG', '#ADB2B4', 0.85, 0.50, 'vmu',
     'all VMU frames, canopy GMS 150x100x6 primaries (concealed), stairs, handrails, chequer plate, masts; canopy CHS150 columns '
     'only via build_canopy COLUMN_FINISH=STEEL_HDG (site photos show the 6 existing legacy CAD canopy CHS dark-painted)', '',
     '',
     '',
     textures=_metal009_roughness(0.50, 0.5))
_add('SS_BRUSHED', '#C4C6C8', 1, 0.30, 'vmu',
     'VMU01 and VMU05 railings', '',
     '',
     '',
     anisotropy=0.0)

_add('GL01_VISION', '#8B9593', 0, 0.02, 'vmu',
     'VMU01 vision glass (GL01)', '',
     '',
     '',
     glass={'vlt': 0.30, 'rext': 0.18, 'rint': None, 'tint': '#8B9593', 'transmission': 1.0, 'thickness': 0.0, 'ior': 2.33,
            'specularIntensity': 1.0, 'specularColor': [0.80, 0.92, 1.00], 'specularColorSpace': 'linear',
            'envMapIntensity': 1.0, 'side': 'double', 'transparent': False,
            'makeup': '8 clear HS low-E #2 + 12 AS + 6 clear HS / 1.52 PVB / 6 clear HS = 33.52 mm, black structural sealant',
            'measured': {'T_vis': 0.2906, 'reflect_Lab_glass_side': [49.35, -0.99, -5.92], 'reflect_Y': 0.179,
                         'transmit_Lab': [60.8, -3.62, -0.51], 'look': 'cool blue-grey reflection (#6E767F look)'},
            'spec_limits': '',
            'fallback': {'hex': _GLASS_FALLBACK_HEX, 'opacity': 0.70, 'metalness': 0.0, 'roughness': 0.04, 'envMapIntensity': 1.6}})
_add('GL02_SPANDREL', '#2B2F33', 0, 0.05, 'vmu',
     'VMU01 spandrel (GL02)', '',
     '',
     '',
     clearcoat=1.0, clearcoatRoughness=0.02,
     glass={'opaque': True, 'transmission': 0.0, 'ior': 2.2, 'specularIntensity': 1.0, 'specularColor': [0.80, 0.92, 1.00],
            'specularColorSpace': 'linear', 'makeup': '8 HS + 12A + 8 HS, low-E #2, back pan behind'})
_add('GL03_VISION_B', '#ADB2B0', 0, 0.02, 'vmu',
     'VMU02 IGU, VMU04 windows (GL03 podium vision)', '',
     '',
     '',
     glass={'vlt': 0.42, 'rext': 0.14, 'rint': 0.14, 'tint': '#ADB2B0', 'transmission': 1.0, 'thickness': 0.0, 'ior': 2.33,
            'specularIntensity': 1.0, 'specularColor': [0.85, 0.93, 1.00], 'specularColorSpace': 'linear',
            'envMapIntensity': 1.0, 'side': 'double', 'transparent': False,
            'makeup': '8 mm HS #2 + 12 air + 6 HS / 1.52 PVB / 6 HS = 33.52 mm, black Al spacer, black structural sealant',
            'measured': {'solar_T': [0.17, 0.19], 'U': [1.5, 1.6], 'SC': [0.28, 0.30]},
            'fallback': {'hex': _GLASS_FALLBACK_HEX, 'opacity': 0.58, 'metalness': 0.0, 'roughness': 0.04, 'envMapIntensity': 1.6}})
_add('GL_DOOR', '#B4BAB8', 0, 0.02, 'vmu',
     'VMU02 sliding-door leaves', '',
     '',
     '',
     glass={'vlt': 0.48, 'rext': 0.14, 'rint': 0.11, 'tint': '#B4BAB8', 'transmission': 1.0, 'thickness': 0.0, 'ior': 2.2,
            'specularIntensity': 1.0, 'specularColor': [0.85, 0.93, 1.00], 'specularColorSpace': 'linear',
            'envMapIntensity': 1.0, 'side': 'double', 'transparent': False,
            'makeup': '8 clear HS #2 / 1.52 PVB / 8 clear HS', 'measured': {'solar_T': 0.34, 'U': 5.08, 'SC': 0.58},
            'fallback': {'hex': _GLASS_FALLBACK_HEX, 'opacity': 0.52, 'metalness': 0.0, 'roughness': 0.04, 'envMapIntensity': 1.6}})

_add('SEALANT_BLACK', '#141516', 0, 0.70, 'vmu',
     'SSG joints, gaskets, panel joints (incl. canopy 20 mm joints, VMU02 15 mm SSG joints)', '',
     '',
     '')
_add('GMS_RIBBED', '#A7ACAE', 0.8, 0.50, 'vmu',
     'VMU02 end walls + side-B plates, roof', '',
     '',
     '',
     procedural={'type': 'ribs_normal', 'slot': 'normalMap', 'axis': 'vertical', 'pitch_m': 0.210, 'depth_m': 0.025,
                 'profile': 'trapezoidal (estimated)', 'alt_texture': 'corrugated_iron_03 normal (pitch not matched)'})
_PC_TEX = formliner_ao_texture(luminance(hex_to_linear(PRECAST_HEX)), 0.90)
_add('PRECAST_FORMLINER', PRECAST_HEX, 0, 0.90, 'vmu',
     f'VMU04 L-wall + RC fins (Q4: evidence default {PRECAST_EVIDENCE_HEX}, sample pending)',
     '',
     '',
     '',
     **_calib(PRECAST_LAB_SCI, L_to_Y(PRECAST_LAB_SCI[0]) - PRECAST_SPECULAR, PRECAST_SPECULAR * 100,
              '',
              specular_assumed=True, previous_hex=PRECAST_PREVIOUS_HEX, applies_to=PRECAST_EVIDENCE_HEX,
              rejected_area_hex=['#928A81', '#8A837A']),
     procedural={'type': 'ribs_normal', 'slot': 'normalMap', 'axis': 'vertical', 'pitch_m': 0.045, 'depth_m': 0.020,
                 'depths_m': [0.020, 0.015, 0.010], 'rib_w_m': 0.025, 'groove_w_m': 0.020,
                 'profile': 'rectangular ribs 25 / grooves 20, depths 20-15-10 repeating (precast proposal 1:25 vector)',
                 'note': ''},
     range={**PRECAST_RANGE, 'Y': [0.341, 0.491], 'previous_default': PRECAST_PREVIOUS_HEX, 'previous_mid_rule': 'mean of the two L* values',
            'basis': ''},
     textures=_PC_TEX,
     param={'Q4': f'PRECAST_HEX (default {PRECAST_EVIDENCE_HEX} = SCE lit-rib-face value of the precast supplier reference wall; '
                  'the §4 row carries the same value; env MOCKUP_PRECAST_HEX / viewer ?precast= override; '
                  'replace with the Q4 sample value when the mock-up precast sample exists)'})
_add('RC_PLAIN', '#8A8C8A', 0, 0.90, 'vmu',
     'VMU05 parapet (TBC), VMU03 footing patch, VMU04 slab, canopy column plinths', '',
     '',
     '')
_add('PLYWOOD', '#A88760', 0, 0.80, 'vmu',
     'VMU02 floor', '',
     '',
     '')

_P = 'site photos'
_add('CTX_CONCRETE_YARD', '#C4B8A3', 0, 0.90, 'context',
     'yard slab (dry)', '',
     '',
     '',
     textures=_ph_textures('brushed_concrete', '#C4B8A3', 0.90))
_add('CTX_CONCRETE_YARD_DAMP', '#8F8A82', 0, 0.55, 'context',
     'damp patches / puddle surrounds on the yard slab (20-30 % of area)', '',
     '',
     '',
     textures=_ph_textures('brushed_concrete', '#8F8A82', 0.55))
_add('CTX_HOARDING', '#9AA0A0', 0.5, 0.50, 'context',
     'boundary hoarding along main road (2.4 m solid corrugated / profiled metal, light grey zinc)', '',
     '',
     '',
     textures=_ph_textures('corrugated_iron_03', '#9AA0A0', 0.50))
_add('CTX_GANTRY_LEG', '#9FB8C2', 0, 0.50, 'context',
     'gantry A-frame legs (pale blue), leg base blocks', '',
     '',
     '')
_add('CTX_GANTRY_GIRDER', '#DFE3E4', 0, 0.50, 'context',
     'gantry box girder (off-white)', '',
     '',
     '')
_add('CTX_SAFETY_YELLOW', '#D4A630', 0, 0.55, 'context',
     'Factory 1 roof lattice towers, crane bridges, Factory 2 yellow steel roof storey (Q6)', '',
     '',
     '')
_add('CTX_RED_LINE', '#C8504A', 0, 0.80, 'context',
     'painted red safety lines both sides of each crane rail (80-100 mm wide, ±0.8 m off rail centre)', '',
     '',
     '')
_add('CTX_RAIL', '#8B7B63', 0.2, 0.70, 'context',
     'crane rail heads set flush in the slab', '',
     '',
     '')
_add('CTX_FACTORY_RC', '#CFCFC6', 0, 0.90, 'context',
     'Factory 1 exposed RC columns (upper, off-white/cream)', '',
     '',
     '')
_add('CTX_FACTORY_RC_BASE', '#9E9E98', 0, 0.90, 'context',
     'Factory 1 RC column base stain band (lower 1.5 m)', '',
     '',
     '')
_add('CTX_CLADDING_RIB', '#8A9097', 0.3, 0.50, 'context',
     'Factory 1 ribbed metal cladding band above the bays', '',
     '',
     '',
     textures=_ph_textures('corrugated_iron_03', '#8A9097', 0.50))
_add('CTX_BAY_VOID', '#232629', 0, 0.95, 'context',
     'Factory 1 open bays / soffit / interior (reads as black void)', '',
     '',
     '')
_add('CTX_CONTAINER_WHITE', '#D6D8D4', 0, 0.50, 'context',
     'white 20 ft site-office container (6.06 x 2.44 x 2.6 m) incl. window AC unit casing', '',
     '',
     '')
_add('CTX_PALM_FROND', '#4C5A34', 0, 0.70, 'context',
     'Royal palm / Polyalthia foliage', '',
     '',
     '')
_add('CTX_PALM_TRUNK', '#9A988E', 0, 0.90, 'context',
     'Royal palm trunks (smooth pale grey)', '',
     '',
     '')
_add('CTX_STILLAGE_RED', '#8A3A2C', 0, 0.60, 'context',
     'red-oxide steel stillages (a few, Q6)', '',
     '',
     '')
# asphalt: generic aged-asphalt albedo, about 0.15 (weathered asphalt is typically 0.10-0.20); near-neutral grey, not measured
_add('CTX_ASPHALT', '#6E6D6A', 0, 0.90, 'context',
     'main road carriageway', '',
     '',
     '',
     textures=_ph_textures('clean_asphalt', '#6E6D6A', 0.90))
# grass: mean (in linear RGB) of four site-photo samples of the verge weeds and grass, #585341, #74654B, #62655A and #696D5A
_add('CTX_GRASS', '#666351', 0, 0.95, 'context',
     'main road verges, green buffer strip, weeds at the hoarding foot', '',
     '',
     '')

_add('WHITE', '#E8E8E3', 0, 0.80, 'supplementary',
     'VMU01 吊顶 ceiling, 室内完成面 interior finish', '',
     '',
     '')
_add('CTX_RC_BARE', '#979A98', 0, 0.90, 'supplementary',
     'Factory 2 north block bare grey RC frame (Q6 default)', '',
     '',
     '')
_add('CTX_GATE_BROWN', '#3A2E24', 0.3, 0.60, 'supplementary',
     '16.1 m entrance gate / palisade (dark brown/rust vertical bars)', '',
     '',
     '')
_add('CTX_YELLOW_LINE', '#D4A630', 0, 0.80, 'supplementary',
     'yellow painted line(s) near the main road side of the yard', '',
     '',
     '')
_add('CTX_ROAD_MARKING_WHITE', '#D8D8D0', 0, 0.70, 'supplementary',
     'main road lane lines, hatched median chevrons', '',
     '',
     '')
_add('CTX_KERB', '#B9B6AE', 0, 0.85, 'supplementary',
     'main road kerbs, drain covers / IC chamber covers', '',
     '',
     '')
_add('CTX_BLDG_WHITE', '#DCD8CD', 0, 0.85, 'supplementary',
     'neighbouring white blocks', '',
     '',
     '')
# metal roofs: the galvanised profiled-sheet tone of the hoarding (CTX_HOARDING, site photos); the roof surfaces themselves
# are not visible in the site photos
_add('CTX_ROOF_METAL', '#9AA0A0', 0.5, 0.45, 'supplementary',
     'factory metal roofs (long-span profiled sheet)', '',
     '',
     '',
     textures=_ph_textures('corrugated_iron_03', '#9AA0A0', 0.45))

MATERIALS = _M

ALIASES = {n: 'CTX_' + n for n in ('CONCRETE_YARD', 'HOARDING', 'GANTRY_LEG', 'GANTRY_GIRDER', 'SAFETY_YELLOW', 'RED_LINE', 'RAIL',
                                   'FACTORY_RC', 'CLADDING_RIB', 'BAY_VOID', 'CONTAINER_WHITE', 'PALM_FROND', 'PALM_TRUNK',
                                   'STILLAGE_RED', 'ASPHALT', 'GRASS')}
ALIASES.update({'CONCRETE_YARD_DAMP': 'CTX_CONCRETE_YARD_DAMP', 'FACTORY_RC_BASE': 'CTX_FACTORY_RC_BASE'})
LEGACY = {
    'GLASS': 'GL01_VISION', 'ALU_DARK': 'AL_T02', 'ALU_DARK2': 'AL_T01', 'ALU_SILVER': 'AL_RAL7038', 'ALU_WARMGREY': 'AL_RAL7038',
    'WOODGRAIN': 'AL_WOOD', 'STEEL_GALV': 'STEEL_HDG', 'STEEL_DARK': 'STEEL_HDG', 'STAINLESS': 'SS_BRUSHED', 'ALU_MILL': 'AL_MILL',
    'EXT_CANOPY_ALU': 'AL_RAL7038', 'EXT_CANOPY_STEEL': 'STEEL_HDG', 'EXT_CANOPY_COLUMN': 'STEEL_HDG',
    'CTX_STEEL_GALV': 'STEEL_HDG', 'CTX_GANTRY_BLUE': 'CTX_GANTRY_LEG', 'CTX_HOARDING_GREEN': 'CTX_HOARDING',
    'CTX_YELLOW_STEEL': 'CTX_SAFETY_YELLOW', 'CTX_RED_STEEL': 'CTX_STILLAGE_RED', 'CTX_CONTAINER_0': 'CTX_CONTAINER_WHITE',
    'CTX_WALL_CLAD': 'CTX_CLADDING_RIB',
}

CANOPY_MATERIALS = ('AL_MOUSEGREY', 'AL_T02', 'AL_RAL7038', 'STEEL_HDG', 'SEALANT_BLACK', 'RC_PLAIN')

def _derive(e):
    e = copy.deepcopy(e)
    lin = hex_to_linear(e['hex'])
    e['linear'] = _r(lin)
    e['Y'] = round(luminance(lin), 4)
    g = e.get('glass')
    if g and 'tint' in g:
        tl = hex_to_linear(g['tint'])
        g['tint_linear'] = _r(tl)
        g['tint_Y'] = round(luminance(tl), 4)
    if g:
        f0 = f0_from_ior(g['ior'])
        sl = luminance(g['specularColor'])
        g['f0_luminance'] = round(f0 * sl * g.get('specularIntensity', 1.0), 4)
        if g.get('rext') is not None:
            f0t = min(g['rext'] / sl, 0.99)
            s = math.sqrt(f0t)
            g['ior_for_rext'] = round((1 + s) / (1 - s), 3)
        if g.get('vlt') is not None and 'tint' in g:
            g['vlt_effective_threejs'] = round(g['tint_Y'] * (1 - g['f0_luminance']), 4)
            k = g['vlt'] / max(1e-6, g['vlt_effective_threejs'])
            g['tint_for_vlt_threejs'] = linear_to_hex([min(1.0, c * k) for c in g['tint_linear']])
    return e

def resolve(name, warn_legacy=True):
    if name in _M:
        return name
    if name in ALIASES:
        return ALIASES[name]
    if name in LEGACY:
        if warn_legacy:
            warnings.warn(f'materials_lib: legacy material name {name!r} -> {LEGACY[name]!r}; use the canonical name', stacklevel=3)
        return LEGACY[name]
    import difflib
    close = difflib.get_close_matches(name, list(_M) + list(ALIASES), n=4, cutoff=0.5)
    raise KeyError(f'materials_lib: unknown material {name!r}. Canonical names are in the material contract. Close: {close}')

def get(name):
    return _derive(_M[resolve(name)])

def gltf_params(name):
    c = resolve(name, warn_legacy=False)
    e = _M[c]
    g = e.get('glass')
    if g and g.get('transmission', 0) > 0:
        fb = g['fallback']
        return c, hex_to_linear(fb['hex']), float(fb['opacity']), float(fb['metalness']), float(fb['roughness'])
    return c, hex_to_linear(e['hex']), 1.0, e['metalness'], e['roughness']

def material_extras(name):
    c = resolve(name, warn_legacy=False)
    e = _derive(_M[c])
    x = {'srgb': e['hex'], 'linear': e['linear'], 'canonical': c, 'contract': CONTRACT, 'category': e['category'],
         'confidence': e['confidence'], 'source': ''}
    for k in ('clearcoat', 'clearcoatRoughness', 'anisotropy', 'param', 'codes', 'colour_basis', 'hex_sci'):
        if k in e:
            x[k] = e[k]
    if 'glass' in e:
        x['glass'] = e['glass']
        if e['glass'].get('transmission', 0) > 0:
            x['gltf_base'] = f"fallback {e['glass']['fallback']['hex']} alpha {e['glass']['fallback']['opacity']} (1-VLT); viewer upgrades by name"
    if 'textures' in e:
        x['textures'] = e['textures'].get('set')
    if 'procedural' in e:
        x['procedural'] = e['procedural']['type']
    return x

def mat(glb, name, double=True):
    c = resolve(name)
    if c in glb.matidx:
        return glb.matidx[c]
    c, lin, alpha, metal, rough = gltf_params(c)
    return glb.material(c, lin, alpha, metal, rough, double=double, extras=material_extras(c))

def canopy_top(glb):
    return mat(glb, CANOPY_TOP_MATERIAL)

def node_extras(group, layer_en, finish, source, confidence, **kw):
    x = {'group': group, 'layer_en': layer_en, 'finish': resolve(finish), 'source': '', 'confidence': confidence}
    x.update(kw)
    return x

def as_json():
    out = {}
    for n, e in _M.items():
        out[n] = _derive(e)
    for a, c in list(ALIASES.items()) + list(LEGACY.items()):
        if a in out:
            continue
        d = copy.deepcopy(out[c])
        d['alias_of'] = c
        d['legacy'] = a in LEGACY
        d['note'] = ''
        out[a] = d
    return out

def write_json(path=None):
    path = path or JSON_PATH
    d = as_json()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    return path, d

def _parse_contract_table(md_path=None):
    txt = open(md_path or CONTRACT_MD, encoding='utf-8').read()
    sec = txt.split('## 4. Canonical material table', 1)[1].split('\n## 5.', 1)[0]
    rows, ctx = {}, {}
    for line in sec.splitlines():
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) < 4:
            continue
        name = cells[0]
        if re.fullmatch(r'[A-Z0-9_]+', name):
            hx = re.search(r'#[0-9A-Fa-f]{6}', cells[1])
            r = {'hex': hx.group(0).upper() if hx else None, 'metal': float(cells[2]), 'rough': float(cells[3])}
            v = re.search(r'VLT\s+([0-9.]+)', cells[1]); r['vlt'] = float(v.group(1)) if v else None
            v = re.search(r'Rext\s+(?:about\s+)?([0-9.]+)', cells[1]); r['rext'] = float(v.group(1)) if v else None
            v = re.search(r'clearcoat\s+([0-9.]+)(?:\s*/\s*([0-9.]+))?', cells[4] if len(cells) > 4 else '')
            if v:
                r['clearcoat'] = float(v.group(1)); r['clearcoat2'] = float(v.group(2)) if v.group(2) else None
            rows[name] = r
        elif name.startswith('Context materials'):
            for m in re.finditer(r'([A-Z_]+) (#[0-9A-Fa-f]{6})(?: \(([a-z ]+) (#[0-9A-Fa-f]{6})\))?((?: [mr][0-9.]+)*)', cells[1]):
                n, hx, sub, subhx, mr = m.groups()
                d = {'hex': hx.upper()}
                for t in (mr or '').split():
                    d['metal' if t[0] == 'm' else 'rough'] = float(t[1:])
                ctx[n] = d
                if sub:
                    ctx[n + ('_DAMP' if 'damp' in sub else '_BASE')] = {'hex': subhx.upper()}
            if 'ASPHALT' in cells[1] and 'ASPHALT' not in ctx:
                ctx['ASPHALT'] = {'hex': None}
    return rows, ctx

def _measure_textures():
    import numpy as np
    from PIL import Image
    out = []
    for s, t in TEXSETS.items():
        if s == 'Metal009':
            p = os.path.join(ROOT, _TEX_SRC, 'acg', 'Metal009', 'Metal009_1K-JPG_Roughness.jpg')
            a = np.asarray(Image.open(p).convert('L')).astype(float) / 255
            out.append((s, 'roughness_mean', t['roughness_mean'], round(float(a.mean()), 3)))
            continue
        p = os.path.join(ROOT, _TEX_SRC, s, f"{s}_diff_{t['res']}.jpg")
        a = np.asarray(Image.open(p).convert('RGB')).reshape(-1, 3).astype(float) / 255
        lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4).mean(0)
        out.append((s, 'map_mean_linear', t['map_mean_linear'], tuple(round(float(v), 4) for v in lin)))
        p = os.path.join(ROOT, _TEX_SRC, s, f"{s}_arm_{t['res']}.jpg")
        a = np.asarray(Image.open(p).convert('RGB')).reshape(-1, 3).astype(float) / 255
        out.append((s, 'arm_mean', t['arm_mean'], tuple(round(float(v), 3) for v in a.mean(0))))
    return out

def selftest(write=True, quiet=False, glb_out=None):
    import struct
    fails, warns, lines = [], [], []

    def check(ok, msg, warn=False):
        (lines.append(('PASS ' if ok else ('WARN ' if warn else 'FAIL ')) + msg))
        if not ok:
            (warns if warn else fails).append(msg)

    rows, ctx = _parse_contract_table()
    n_exp = 19
    check(len(rows) == n_exp, f'contract table parsed: {len(rows)} named rows (expect {n_exp}), {len(ctx)} context entries')
    for n in ('AL_MOUSEGREY', 'AL_RAL9016'):
        check(n in rows, f'contract has a row for {n}')
    n_bad = 0
    for n, r in rows.items():
        e = _M.get(n)
        if e is None:
            check(False, f'§4 name {n} missing'); n_bad += 1; continue
        exp_hex = r['hex']
        if n == 'PRECAST_FORMLINER' and 'MOCKUP_PRECAST_HEX' in os.environ:
            exp_hex = PRECAST_HEX
        ok = (e['hex'] == exp_hex and abs(e['metalness'] - r['metal']) < 1e-9 and abs(e['roughness'] - r['rough']) < 1e-9)
        g = e.get('glass', {})
        if r.get('vlt') is not None:
            ok &= abs(g.get('vlt', -1) - r['vlt']) < 1e-9
        if r.get('rext') is not None:
            ok &= abs(g.get('rext', -1) - r['rext']) < 1e-9
        if r.get('clearcoat') is not None:
            ok &= abs(e.get('clearcoat', -1) - r['clearcoat']) < 1e-9
            if r.get('clearcoat2') is not None:
                ok &= abs(e.get('clearcoatRoughness', -1) - r['clearcoat2']) < 1e-9
        check(ok, f'§4 {n:18s} {e["hex"]} m{e["metalness"]:.2f} r{e["roughness"]:.2f}  (contract {r["hex"]} m{r["metal"]} r{r["rough"]}'
                  f'{" VLT %s Rext %s" % (r["vlt"], r["rext"]) if r.get("vlt") else ""})')
        n_bad += not ok
    check(n_bad == 0 and 'PRECAST_FORMLINER' in rows, f'§4 contract: {len(rows) - n_bad}/{len(rows)} named rows match materials_lib, '
          f'{n_bad} mismatches (PRECAST_FORMLINER included, no placeholder exemption)')
    for n, r in ctx.items():
        c = 'CTX_' + n
        e = _M.get(c)
        if e is None:
            check(False, f'context {n} -> {c} missing'); continue
        ok = (r['hex'] is None or e['hex'] == r['hex'])
        if 'metal' in r: ok &= abs(e['metalness'] - r['metal']) < 1e-9
        if 'rough' in r: ok &= abs(e['roughness'] - r['rough']) < 1e-9
        check(ok and resolve(n) == c, f'context {c:22s} {e["hex"]} m{e["metalness"]} r{e["roughness"]} (contract {r})')
    for n in ('CTX_ASPHALT', 'CTX_GRASS', 'CTX_CONCRETE_YARD'):
        check(n in _M, f'task-required context material {n} present')

    rec = json.load(open(os.path.join(SOURCES_DIR, 'materials_recipe.json'), encoding='utf-8'))['opaque']
    worst = 0.0
    for k, v in rec.items():
        lin = hex_to_linear(v['hex'])
        worst = max(worst, max(abs(a - b) for a, b in zip(lin, v['linear'])))
    check(worst < 6e-4, f'sRGB->linear matches materials_recipe.json linear values (max err {worst:.2e}, {len(rec)} colours)')
    rt = max(abs(int(e['hex'][i:i + 2], 16) - int(linear_to_hex(hex_to_linear(e['hex']))[i:i + 2], 16)) for e in _M.values() for i in (1, 3, 5))
    check(rt == 0, f'hex -> linear -> hex round trip exact for all {len(_M)} canonical colours')
    Yof = lambda n: luminance(hex_to_linear(_M[n]['hex']))
    y = Yof('AL_RAL7038')
    check(abs(y - 0.3965) <= 0.003, f'AL_RAL7038 Y {y:.4f} vs measured SCE 0.3965 +-0.003 (paint maker LRV SCI 41.15 / SCE 39.65; colour basis SCE)')
    check(abs(luminance(hex_to_linear('#B5B8B1')) - 0.4115) > 0.04, 'rejected nominal #B5B8B1 is indeed too light (Y %.3f)' % luminance(hex_to_linear('#B5B8B1')))

    y = Yof('AL_T01')
    check(abs(y - 0.0658) <= 0.002, f'AL_T01 Y {y:.4f} vs measured SCE 0.0658 +-0.002 (paint maker LRV SCI 8.81 / SCE 6.58)')
    y = Yof('AL_T02')
    check(0.072 <= y <= 0.0805 and _M['AL_T02']['roughness'] == 0.50,
          f'AL_T02 {_M["AL_T02"]["hex"]} Y {y:.4f} in [0.072, 0.0805], roughness {_M["AL_T02"]["roughness"]} (stays 0.50, not 0.42)')
    mg = _M['AL_MOUSEGREY']
    de = de2000(hex_to_lab(mg['hex_sci']), (50.00, -1.55, 0.82))
    check(de <= 1.0 and mg['metalness'] == 0 and mg['roughness'] == 0.5,
          f'AL_MOUSEGREY hex_sci {mg["hex_sci"]} vs RAL 7005 50.00/-1.55/0.82: dE00 {de:.2f} <= 1.0 (hex {mg["hex"]}, '
          f'Y {Yof('AL_MOUSEGREY'):.4f}, m0 r0.5)')
    w = _M['AL_WOOD']
    y = Yof('AL_WOOD')
    check(abs(y - 0.467) <= 0.01 and w['procedural']['value_amplitude'] == 0.08 and w.get('clearcoat', None) == 0,
          f'AL_WOOD {w["hex"]} Y {y:.4f} vs 0.467 +-0.01; procedural.value_amplitude {w["procedural"]["value_amplitude"]} (0.08); '
          f'clearcoat {w.get("clearcoat")} (0, matte)')
    r9 = _M.get('AL_RAL9016')
    de = de2000(hex_to_lab(r9['hex_sci']), (95.26, -0.76, 2.11)) if r9 else 99
    check(r9 is not None and de <= 0.5 and r9['metalness'] == 0 and r9['roughness'] == 0.45 and r9['hex'] == '#F0F0EB',
          f'AL_RAL9016 exists: hex {r9 and r9["hex"]}, hex_sci {r9 and r9["hex_sci"]} vs RAL 9016 95.26/-0.76/2.11 dE00 {de:.2f} <= 0.5, '
          f'm0 r0.45')
    sce = [n for n, e in _M.items() if e.get('colour_basis') == 'SCE']
    check(set(sce) == {'AL_WOOD', 'AL_RAL7038', 'AL_MOUSEGREY', 'AL_RAL9016', 'AL_T02', 'AL_T01', 'PRECAST_FORMLINER'},
          f'colour_basis SCE entries: {sce}')
    for n in sce:
        e = _M[n]
        lab = hex_to_lab(e['hex_sci']); L0, a0, b0 = e['lab_sci']
        ok_sci = abs(lab[0] - L0) <= 0.3 and abs(lab[1] - a0) <= 0.5 and abs(lab[2] - b0) <= 0.5
        hx = PRECAST_EVIDENCE_HEX if n == 'PRECAST_FORMLINER' else e['hex']
        der = sce_hex(e['Y_sce'], a0, b0)
        ok_der = (der == hx) if not e.get('hex_kept') else (0.072 <= luminance(hex_to_linear(hx)) <= 0.0805)
        ok_y = abs(luminance(hex_to_linear(hx)) - e['Y_sce']) <= 0.003 or e.get('hex_kept')
        ok_sp = abs((e['Y_sci'] - e['Y_sce']) * 100 - e['specular_pct']) <= 0.06
        check(ok_sci and ok_der and ok_y and ok_sp,
              f'SCE basis {n:22s} hex {hx} (Y {luminance(hex_to_linear(hx)):.4f}, Y_sce {e["Y_sce"]}) = Lab(L*(Y_sce), card a*/b*) -> {der}'
              f'{" [hex kept, Y in range]" if e.get("hex_kept") else ""}; hex_sci {e["hex_sci"]} -> Lab {lab[0]:.2f}/{lab[1]:+.2f}/{lab[2]:+.2f} '
              f'vs lab_sci {L0}/{a0:+}/{b0:+} (tol 0.3 L*, 0.5 a*b*); Y_sci - Y_sce = {100 * (e["Y_sci"] - e["Y_sce"]):.2f} % = specular_pct {e["specular_pct"]}')
    rejected = {'#37404A': 'T01 SCI-4 %', '#3D454B': 'T02 SCI-4 %', '#A6A8A2': 'RAL 7038 SCI-4 %', '#646764': 'Mouse Grey SCI-4 %',
                '#928A81': 'PRECAST area value', '#8A837A': 'PRECAST area value', '#494951': 'METBLACK m0.5 proposal'}
    used = sorted(f'{n}={e["hex"]} ({rejected[e["hex"]]})' for n, e in _M.items() if e['hex'] in rejected)
    check(not used, f'no rejected colour_cards / area hex is used (plan §7) {used or ""}')
    mb = _M['AL_METBLACK']
    check((mb['hex'], mb['metalness'], mb['roughness']) == ('#2B2C2E', 0.6, 0.35), f'AL_METBLACK unchanged {mb["hex"]} m{mb["metalness"]} r{mb["roughness"]} (note only)')

    for n in ('GL01_VISION', 'GL03_VISION_B', 'GL_DOOR'):
        g = _derive(_M[n])['glass']
        check(abs(g['tint_Y'] - g['vlt']) <= 0.03, f'{n}: tint luminance {g["tint_Y"]:.3f} vs VLT {g["vlt"]}')
        check(abs(g['vlt_effective_threejs'] - g['vlt']) <= 0.03,
              f'{n}: three.js effective VLT tint_Y*(1-F0) = {g["vlt_effective_threejs"]:.3f} vs VLT {g["vlt"]}'
              f' (tint giving VLT exactly: {g["tint_for_vlt_threejs"]})', warn=True)
        ok = abs(g['f0_luminance'] - g['rext']) <= 0.02
        check(ok, f'{n}: F0 = f(ior {g["ior"]}) x specularColor = {g["f0_luminance"]:.3f} vs Rext {g["rext"]}'
                  f' (ior giving Rext exactly: {g["ior_for_rext"]})', warn=True)
        check(abs(g['fallback']['opacity'] - (1 - g['vlt'])) < 0.011, f'{n}: fallback opacity {g["fallback"]["opacity"]} = 1-VLT')

    for n in CANOPY_MATERIALS + (CANOPY_TOP_MATERIAL,):
        r, g, b = hex_to_srgb(_M[n]['hex'])
        mx, mn = max(r, g, b), min(r, g, b)
        sat = 0 if mx == 0 else (mx - mn) / mx
        red = r == mx and sat > 0.25
        check(not red, f'canopy material {n} {_M[n]["hex"]} is not red (sat {sat:.2f})')
    check(CANOPY_TOP_MATERIAL in CANOPY_TOP_OPTIONS, f'Q1 CANOPY_TOP_MATERIAL = {CANOPY_TOP_MATERIAL} (options {CANOPY_TOP_OPTIONS})')
    mg = _M['AL_MOUSEGREY']
    mg_der = sce_hex(L_to_Y((50.00 + 49.6) / 2) - 0.015, -1.55, 0.82)
    check(mg_der == mg['hex'] == '#707370' and mg['hex_sci'] == '#747775',
          f'AL_MOUSEGREY {mg["hex"]} = SCE(RAL 7005 card L* 49.8 = mean of 50.00 and 49.6, -1.55, +0.82) -> {mg_der}; '
          f'hex_sci {mg["hex_sci"]} (Y {luminance(hex_to_linear(mg["hex"])):.3f})')
    check(_M['PRECAST_FORMLINER']['hex'] == PRECAST_HEX, f'Q4 PRECAST_HEX = {PRECAST_HEX}')
    ev = sce_hex(L_to_Y(PRECAST_LAB_SCI[0]) - PRECAST_SPECULAR, *PRECAST_LAB_SCI[1:]); yev = luminance(hex_to_linear(PRECAST_EVIDENCE_HEX))
    check(ev == PRECAST_EVIDENCE_HEX == '#B0A89E' and PRECAST_EVIDENCE_HEX not in (PRECAST_PLACEHOLDER_HEX, PRECAST_PREVIOUS_HEX),
          f'Q4 evidence default {PRECAST_EVIDENCE_HEX} (Y {yev:.3f}) = SCE(card {PRECAST_LAB_SCI}, specular {PRECAST_SPECULAR * 100:.1f} %) -> {ev}; '
          f'previous {PRECAST_PREVIOUS_HEX} (Y {luminance(hex_to_linear(PRECAST_PREVIOUS_HEX)):.3f}) and placeholder {PRECAST_PLACEHOLDER_HEX} replaced')
    ys = [luminance(hex_to_linear(PRECAST_RANGE[k])) for k in ('darker_est', 'lighter_est')]
    check(ys[0] < yev < ys[1], f'Q4 default Y {yev:.3f} inside the design-render range darker {PRECAST_RANGE["darker_est"]} (Y {ys[0]:.3f}) '
                               f'... lighter {PRECAST_RANGE["lighter_est"]} (Y {ys[1]:.3f})')

    bad = [a for a, c in list(ALIASES.items()) + list(LEGACY.items()) if c not in _M]
    check(not bad, f'{len(ALIASES)} aliases + {len(LEGACY)} legacy names all resolve to canonical names {bad or ""}')
    try:
        resolve('EXT_RED'); check(False, 'unknown name EXT_RED rejected')
    except KeyError:
        check(True, 'unknown name EXT_RED rejected (KeyError)')

    from gltfw import GLB
    import numpy as np
    glb = GLB()
    names = list(_M) + list(ALIASES) + list(LEGACY)
    V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32); F = np.array([[0, 1, 2]], np.uint32)
    kids = []
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        for i, n in enumerate(names):
            mi = mat(glb, n)
            kids.append(glb.node(f'SELFTEST|{n}', mesh=glb.mesh(n, V + [i * 1.2, 0, 0], F, None, mi),
                                 extras=node_extras('SELFTEST', n, n, CONTRACT, 'test')))
    glb.node('SELFTEST', children=kids, root=True)
    glb_out = glb_out or os.environ.get('MOCKUP_SELFTEST_GLB') or os.path.join(HERE, '_selftest', 'materials_selftest.glb')
    os.makedirs(os.path.dirname(glb_out), exist_ok=True)
    glb.save(glb_out, {'note': ''})
    b = open(glb_out, 'rb').read()
    n = struct.unpack('<I', b[12:16])[0]
    gj = json.loads(b[20:20 + n])
    gm = {m['name']: m for m in gj['materials']}
    check(set(gm) == set(_M) and len(gj['materials']) == len(_M),
          f'GLB has exactly the {len(_M)} canonical materials (no alias/legacy names leaked): {len(gj["materials"])}')
    err = 0.0
    for c, m in gm.items():
        _, lin, alpha, metal, rough = gltf_params(c)
        bc = m['pbrMetallicRoughness']['baseColorFactor']
        err = max(err, max(abs(a - b2) for a, b2 in zip(bc, list(lin) + [alpha])))
        ok = abs(m['pbrMetallicRoughness']['metallicFactor'] - metal) < 1e-9 and abs(m['pbrMetallicRoughness']['roughnessFactor'] - rough) < 1e-9
        ok &= m['extras']['srgb'] == _M[c]['hex'] and ((alpha < 1) == (m.get('alphaMode') == 'BLEND'))
        if not ok:
            check(False, f'GLB material {c} params mismatch')
    check(err < 1e-6, f'GLB baseColorFactor = linear(sRGB hex) for all materials (max err {err:.1e}); sRGB hex kept in extras')
    finishes = {nd['extras']['finish'] for nd in gj['nodes'] if 'extras' in nd}
    check(finishes <= set(_M), 'node_extras finish values are canonical names')
    try:
        import trimesh
        sc = trimesh.load(glb_out, force='scene')
        check(len(sc.geometry) == len(names), f'trimesh re-loads the self-test GLB ({len(sc.geometry)} geometries)')
    except Exception as ex:
        check(False, f'trimesh load failed: {ex}')

    if write:
        path, d = write_json()
        d2 = json.load(open(path, encoding='utf-8'))
        try:
            shown = os.path.relpath(path, ROOT)
        except ValueError:
            shown = path
        check(d2 == json.loads(json.dumps(d)), f'wrote {shown} ({len(d2)} entries: {len(_M)} canonical + {len(d2) - len(_M)} alias/legacy)')
    else:
        d2 = json.loads(json.dumps(as_json()))
    blob = json.dumps(d2, ensure_ascii=False)
    priv = sorted(set(re.findall(r'(?<![A-Za-z<])[A-Za-z]:\\\\', blob)))
    check(not priv, f'materials.json carries no absolute drive paths {priv or ""}')
    req = ('hex', 'linear', 'metalness', 'roughness', 'note', 'source')
    miss = [k for k, v in d2.items() if any(r not in v for r in req)]
    check(not miss, f'every materials.json entry has {req} {miss or ""}')
    missing_files = []
    for k, v in d2.items():
        t = v.get('textures') or {}
        for slot in ('map', 'normalMap', 'armMap', 'roughnessMap'):
            if slot in t and str(t[slot]['src']).startswith('generated:'):
                continue
            if slot in t and not os.path.isfile(os.path.join(ROOT, t[slot]['src'])):
                missing_files.append(t[slot]['src'])
    check(not missing_files, f'all texture sources exist {sorted(set(missing_files)) or ""}')
    try:
        import base64, io
        import numpy as np
        from PIL import Image
        t = d2['PRECAST_FORMLINER']['textures']
        png = base64.b64decode(t['armMap']['file'].split(',', 1)[1])
        im = np.asarray(Image.open(io.BytesIO(png)).convert('RGB')).astype(float) / 255
        A, E, _ = formliner_ao(luminance(hex_to_linear(_M['PRECAST_FORMLINER']['hex'])))
        xs = np.arange(im.shape[1]) + 0.5
        eff = 1 + VIEWER_AOMAP_INTENSITY * (im[0, :, 0] - 1)
        err = float(np.abs(eff - np.clip(np.interp(xs, A, E, period=FL_ARC), 1 - VIEWER_AOMAP_INTENSITY, 1)).max())
        ti = int(FL_AO_TIP_U * im.shape[1])
        ok = im.shape[:2] == (4, int(round(FL_ARC))) and err < 0.01 and im[0, ti, 0] == 1.0 and np.all(im[..., 1] == 1.0)
        fo = t['ao_physical']['face_on_mean']
        check(ok and 0.7 < fo < 0.9 and abs(t['roughness_with_map'] - _M['PRECAST_FORMLINER']['roughness']) < 1e-9,
              f'PRECAST_FORMLINER groove-AO atlas {im.shape[1]}x{im.shape[0]} px: viewer-effective AO = radiosity E (max err {err:.4f}), '
              f'AO 1 at u {FL_AO_TIP_U:.4f}, face-on mean {fo}, flanks {t["ao_physical"]["by_part"]["flank"]}, floors {t["ao_physical"]["by_part"]["floor"]}')
    except Exception as ex:
        check(False, f'PRECAST_FORMLINER AO atlas check failed: {ex}')
    try:
        tm = _measure_textures()
        worst = max(max(abs(a - b2) for a, b2 in zip(s if isinstance(s, (list, tuple)) else [s], m if isinstance(m, (list, tuple)) else [m])) for _, _, s, m in tm)
        check(worst < 2e-3, f'texture mean constants re-measured (max diff {worst:.4f})')
    except Exception as ex:
        check(False, f'texture measurement failed: {ex}', warn=True)

    for ln in lines:
        if not quiet or not ln.startswith('PASS'):
            print(ln)
    print(f'materials_lib self-test: {len(lines) - len(fails) - len(warns)} pass, {len(warns)} warn, {len(fails)} fail')
    return not fails, lines

if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    ok, _ = selftest(write='--no-write' not in sys.argv, quiet='--quiet' in sys.argv)
    sys.exit(0 if ok else 1)
