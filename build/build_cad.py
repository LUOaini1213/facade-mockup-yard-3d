"""Builds model/vmu_cad.glb (+ model/vmu_cad_summary.json): the render meshes of the legacy CAD model (all triangles, no
decimation, original normals) for the groups that no other builder replaces - VMU-01 tower (without the canopy),
VMU-03 curved podium sample and the ground-level trellis - placed on the layout plan with the per-group registration,
with per-layer finishes from materials_lib, generated louvre panels and a regenerated trellis ring panel.
Needs the private CAD cache, the registration file and the object-id map in SOURCES_DIR (not included).
"""
import os, sys, json, math, pickle, collections
SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')
_OIDS = None
def _oid(alias):
    global _OIDS
    if _OIDS is None:
        _OIDS = json.load(open(os.path.join(SOURCES_DIR, 'legacy_cad_object_ids.json'), encoding='utf-8'))
    return _OIDS[alias]
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
import numpy as np
from gltfw import GLB
from site_frame import r3_to_gltf, r3_dir_to_gltf, O
import materials_lib as ML

KEEP_GROUPS = ('VMU01', 'VMU03', 'TRELLIS')
DROPPED_GROUPS = {'VMU02': 'model/vmu02.glb (build step build_vmu02.py)', 'VMU04': 'model/vmu04.glb (build step build_vmu04.py)',
                  'VMU05': 'model/vmu05.glb (build step build_vmu05.py)'}
CANOPY_GLB = 'model/vmu01_canopy.glb (build step build_canopy.py)'
CANOPY_Z_MAX = 3.6
CANOPY_X_MAX = 17.5
CANOPY_LAYERS_ALL = ('铝板侧面', '铝板底面', '铁架::150X5圆管')
CANOPY_PLATE_TOL = 0.05
VMU03_BRACE_160 = True
VMU03_BEAM_160 = False
GRILLE_FINISH = os.environ.get('MOCKUP_GRILLE_FINISH', 'AL_WOOD')
GRILLE_CLIP_Y = 0.0
GRILLE_BASE_RAIL_DZ = 0.125
SOFFIT_FINISH = os.environ.get('MOCKUP_SOFFIT_FINISH', 'WHITE')
COPING_FINISH = os.environ.get('MOCKUP_COPING_FINISH', 'AL_RAL9016')
assert COPING_FINISH in ('AL_RAL9016', 'WHITE', 'AL_T02'), COPING_FINISH
assert COPING_FINISH in ML._M, f'COPING_FINISH {COPING_FINISH} is not a canonical material in build/materials_lib.py'
COPING_IDS = {
    _oid('obj_01'): ('coping run, grid-A face (+ upper curved corner part)', 'high'),
    _oid('obj_02'): ('coping run, grid-2 face y 26.330..28.643 (SE mitre)', 'high'),
    _oid('obj_03'): ('coping run, grid-2 face y 28.643..33.243', 'high'),
    _oid('obj_04'): ('coping run, grid-2 face y 33.243..36.425 (NE mitre)', 'high'),
    _oid('obj_05'): ('coping run, grid-C face', 'high'),
    _oid('obj_06'): ('end cap of the grid-C run at x 14.486 (B-B 445 cap)', 'high'),
    _oid('obj_07'): ('end cap of the grid-A run at x 16.286', 'high'),
    _oid('obj_08'): ('upper tier of the curved SW corner (886.4 dev.)', 'medium'),
    _oid('obj_09'): ('101-high lower tier of the curved SW corner (110 dev.)', 'medium'),
    _oid('obj_10'): ('101-high grid-1 top strip y 28.218..32.718 (110 dev., 4487 long)', 'medium'),
}
BALCONY_DZ = -0.503
PLYWOOD_INFILL = {_oid('obj_11'): 4.335,
                  _oid('obj_12'): None}
GL02_SPLIT = {_oid('obj_13'): 7.200,
              _oid('obj_14'): 11.750}
TYPE8_SJ_MID = 9.165
TYPE8_SJ_GAP = 0.005
TYPE8_TOP_OVER = 0.0455
TYPE8_CHAINS = {
    'U17..21': dict(H=4697.5, section=[159.5, 85, 465, 85, 1187.5, 85, 135.5, 75, 1026.5, 50, 1237.5, 106], elevation=[202, 550, 1275, 2625, 45.5]),
    'U27..31': dict(H=6051.0, section=[74.5, 1860.5, 85, 1182.5, 50, 1182.5, 85, 695.5, 50, 679.5, 106], elevation=[1980, 2500, 1525.5, 45.5]),
    'U01..07': dict(H=2715.5, section=[85, 135.5, 75, 1584.5, 50, 679.5, 106], elevation=[45, 2625, 45.5]),
    'U08..14, 22..26, UB10': dict(H=4590.5, section=[74.5, 1003, 85, 465, 85, 762.5, 85, 135.5, 75, 984.5, 50, 679.5, 106],
                                            elevation=[1120, 550, 850, 2025, 45.5]),
    'U15..16': dict(H=3723.0, section=[74.5, 1003, 85, 465, 85, 762.5, 85, 1163], elevation=[1120, 550, 850, 1203]),
}
TYPE8_UB_UP = TYPE8_SJ_MID + TYPE8_SJ_GAP
TYPE8_UB_LO = TYPE8_SJ_MID - (4.6975 - TYPE8_TOP_OVER)
TYPE8_CLOSURE_TOP = round(TYPE8_UB_LO + 0.1595, 4)
TYPE8_CLOSURE_IDS = {_oid('obj_15'): 'grid-C face x 14.487..22.671',
                     _oid('obj_16'): 'grid-2 face y 33.393..36.343'}
TYPE8_LOUVRE_DROP = {_oid('obj_17'): 'U29 grid-C x 20.383..22.671', _oid('obj_18'): 'U30',
                     _oid('obj_19'): 'U31', _oid('obj_20'): 'U27 grid-2 y 33.393..34.118',
                     _oid('obj_21'): 'U28 grid-2 y 34.118..36.343'}
LOUVRE_H, LOUVRE_D, LOUVRE_N, LOUVRE_PITCH = 1.946, 0.1546, 24, 0.075
LOUVRE_MULLION = dict(w=0.075, d=(0.0415, 0.1915))
LOUVRE_TIP0 = 0.0626 + 0.023
LOUVRE_RAIL = (0.0626, 0.0329)
LOUVRE_STILE = 0.030
LOUVRE_BLADE = [(0.004, 0.000), (0.030, 0.040), (0.055, 0.064), (0.076, 0.078), (0.105, 0.066), (0.134, 0.047)]
LOUVRE_BLADE_T = 0.002
LOUVRE_Z0 = round(TYPE8_UB_UP + (0.0745 + 1.935) / 2 - LOUVRE_H / 2, 5)
LOUVRE_TYPES = {'LOUVRE_A': 1.0949, 'LOUVRE_B': 1.0775, 'LOUVRE_E': 0.6908, 'LOUVRE_F': 1.0463, 'LOUVRE_C': 1.1260, 'LOUVRE_D': 1.1260}
LOUVRE_GAP = 0.009
LOUVRE_FACES = {'grid-C': ('x', 'y', 36.3429), 'grid-2': ('y', 'x', 22.6709)}
LOUVRE_LAYOUT = [
    ('U27', 'LOUVRE_E', 'grid-2', 33.3929, 34.1179, None), ('U28', 'LOUVRE_A', 'grid-2', 34.1179, 35.2304, None),
    ('U28', 'LOUVRE_F', 'grid-2', 35.2304, 36.3429, 'hi'), ('U29', 'LOUVRE_B', 'grid-C', 21.5269, 22.6709, 'hi'),
    ('U29', 'LOUVRE_D', 'grid-C', 20.3829, 21.5269, None), ('U30', 'LOUVRE_C', 'grid-C', 19.2389, 20.3829, None),
    ('U30', 'LOUVRE_D', 'grid-C', 18.0949, 19.2389, None), ('U31', 'LOUVRE_C', 'grid-C', 16.9509, 18.0949, None),
    ('U31', 'LOUVRE_D', 'grid-C', 15.8069, 16.9509, None)]
UNIT_WIDTHS = {
    'U17': (818.0, 725.0), 'U27': (818.0, 725.0), 'U18': (2380.8, 2225.0), 'U28': (2380.8, 2225.0), 'U19': (2476.3, 2288.0),
    'U29': (2476.3, 2288.0), 'U20': (2305.5, 2288.0), 'U30': (2305.5, 2288.0), 'U21': (2348.5, 2288.0), 'U31': (2348.5, 2288.0)}
UNIT_WIDTH_DECISIONS = []
TR_RING_C = ((34.1624, 11.5777), (34.1624, 13.8110))
TR_RING_R = (0.950, 1.000)
TR_Z = (2.095, 2.095 + 0.153)
TR_BAR_W = 0.050
TR_BAR_X = tuple(round(34.1624 + (-809.7 + 200 * k - 240.3) / 1000, 4) for k in range(12))
TR_BAR_Y = (10.3545, 15.0345)
TR_CAP = dict(t=0.003, h=0.150)
TR_ZONE_X = (33.09, 35.39)
TR_SUPPORT_ANGLE_X = (33.0424, 35.4324)
TR_SUPPORT_ANGLE_IDS = {_oid('obj_22'): 'south rail y 10.43..10.505', _oid('obj_23'): 'north rail y 14.885..14.96'}
TR_SPLICE_PLATE = dict(R=(0.957, 0.993), half_deg=7.2106, h=0.141)
TR_BRACKET = dict(len=0.140, h=0.120, t=0.003)
RING_FINISH = os.environ.get('MOCKUP_TRELLIS_RING_FINISH', 'AL_T02')
assert RING_FINISH in ('AL_T02', 'AL_RAL7038', 'AL_MILL'), RING_FINISH
UV_MATERIALS = ('STEEL_HDG', 'AL_WOOD', 'GMS_RIBBED')
UV_NOTE = ('TEXCOORD_0 in metres, box projection by the dominant glTF normal axis: |ny| max -> (u,v)=(x,z); '
           '|nx| max -> (u,v)=(z,y); |nz| max -> (u,v)=(x,y). v is vertical (y) on all side faces.')

GEOM_SRC = 'legacy CAD model (Rhino render meshes via legacy_cad_cache_n.pkl, no decimation) placed per the layout plan (group_registration.json)'

C = pickle.load(open('legacy_cad_cache_n.pkl', 'rb'))
R = json.load(open('group_registration.json'))
M = C['meshes']

LAYER_EN = {'玻璃面板': 'Glass panels', '结构': 'Structure', '垫块': 'Setting blocks', '铝板': 'Aluminium panels', '型材': 'Aluminium profiles',
            '码件': 'Brackets', '中横梁': 'Middle transom', '小横梁': 'Minor transoms', '铝背板': 'Aluminium back panel', '收口铝板': 'Closure aluminium panels',
            '铝板侧面': 'Canopy fascia', '铝板底面': 'Canopy soffit', '格栅条方形': 'Square grille bars', '百叶面板': 'Louvre panels', '百叶线条': 'Louvre blades',
            '玻璃单元百叶线条': 'Unit louvre lines', '开启扇': 'Opening vents', '竖向格栅条': 'Ground grille TYPE 11 (L300x300x5 posts)', '竖向格栅条铝板': 'Ground grille TYPE 11 (3 mm rails)',
            '中横梁线': 'Transom lines', '装饰条': 'Decorative fins', '装饰条铝板': 'Fin cover panels', '栏杆': 'Balustrade', '栏杆结构封修板': 'Balcony closure (12 mm plywood)',
            '吊顶': 'Ceiling', '室内完成面': 'Interior finish', '封修板': 'Closure panels', '立柱': 'Mullions', '横梁': 'Transoms', '三角形': 'Triangular profiles',
            '楼梯': 'Steel stair', '楼梯扶手': 'Stair handrail', '地面埋板': 'Base plates', '角码': 'Cleats', '角码1': 'Cleats'}

def layer_en(l):
    out = []
    for p in l.split('::'):
        if p == '铁架':
            out.append('Steel frame'); continue
        if p.startswith('铝板0'):
            out.append('Alu panel type ' + p[-2:]); continue
        if p.startswith('型材0'):
            out.append('Profile type ' + p[-2:]); continue
        out.append(LAYER_EN.get(p, p.replace('方钢', 'SHS ').replace('方通', ' SHS').replace('圆管', ' CHS').replace('角钢', ' angle')))
    return ' / '.join(out)

S_T02 = ''
S_7038_V01 = ''
S_HDG = ''
FINISH_RULES = [
    ('VMU01', '装饰条', 'AL_RAL7038', '', ''),
    ('VMU01', '装饰条铝板', 'AL_RAL7038', '', ''),
    ('VMU01', '玻璃面板', 'GL01_VISION', '',
     ''),
    ('VMU01', '铝背板', 'AL_T01', '', ''),
    ('VMU01', '铝板', 'AL_T02', '', ''),
    ('VMU01', '收口铝板', 'AL_T02', '', ''),
    ('VMU01', '横梁', 'AL_T02', '', ''),
    ('VMU01', '立柱', 'AL_T02', '', ''),
    ('VMU01', '中横梁', 'AL_T02', '', ''),
    ('VMU01', '小横梁', 'AL_T02', '', ''),
    ('VMU01', '百叶面板', 'AL_T02', '', ''),
    ('VMU01', '栏杆结构封修板', 'PLYWOOD', '',
     ''),
    ('VMU01', '竖向格栅条', GRILLE_FINISH, '',
     ''),
    ('VMU01', '竖向格栅条铝板', GRILLE_FINISH, '',
     ''),
    ('VMU01', '栏杆', 'SS_BRUSHED', '', ''),
    ('VMU01', '封修板', 'GMS_RIBBED', '',
     ''),
    ('VMU01', '吊顶', SOFFIT_FINISH, '',
     ''),
    ('VMU01', '室内完成面', 'WHITE', '', ''),
    ('VMU01', '铁架::*', 'STEEL_HDG', '', ''),
    ('VMU01', '垫块', 'STEEL_HDG', '', ''),
    ('VMU03', '铝板::角码*', 'AL_MILL', '',
     ''),
    ('VMU03', '铝板::铝板0*', 'AL_RAL7038', '',
     ''),
    ('VMU03', '型材', 'AL_RAL7038', '', ''),
    ('VMU03', '型材::*', 'AL_RAL7038', '', ''),
    ('VMU03', '码件', 'AL_MILL', '', ''),
    ('VMU03', '铁架::*', 'STEEL_HDG', '', ''),
    ('VMU03', '垫块', 'STEEL_HDG', '', ''),
    ('TRELLIS', '格栅条方形', 'AL_T02', '',
     ''),
    ('TRELLIS', '百叶面板', 'AL_T02', '',
     ''),
    ('TRELLIS', '铁架::*', 'STEEL_HDG', '', ''),
]

def finish_of(g, layer):
    for rg, pat, mat, conf, src in FINISH_RULES:
        if rg != g:
            continue
        if pat == layer or pat == '*' or (pat.endswith('*') and layer.startswith(pat[:-1])):
            return mat, conf, src, pat
    raise KeyError(f'no finish rule for {g} / {layer} - add one to FINISH_RULES (never fall back to a default)')

S_PLY_INFILL = ('')
S_COPING = ('')
_COPING_HEX_CONF = {'AL_RAL9016': 'medium (hex: nominal RAL 9016, no sample / site photo)', 'WHITE': 'medium (hex: WHITE stands in for RAL 9016)',
                    'AL_T02': 'low (AL_T02 is the round-1 category default, not the ordered RAL 9016)'}[COPING_FINISH]
OBJECT_FINISH = {oid: ('PLYWOOD', 'high (material), low (colour: raw plywood, may be finished by others)', S_PLY_INFILL, 'object:PLYWOOD_INFILL', 'PLY')
                 for oid in PLYWOOD_INFILL}
OBJECT_FINISH.update({oid: (COPING_FINISH, 'high (part match: 475x450 runs high, 101 strips medium), '
                                           + _COPING_HEX_CONF, S_COPING, 'object:COPING_IDS', 'COPING')
                      for oid in COPING_IDS})
TAG_NAME = {'GL02': 'Glass panels GL02 (vision)', 'PLY': 'Plywood infill, grid-2 face',
            'COPING': 'Roof coping RAL9016',
            'LOUVRE': 'Louvre panels TYPE 8 (1946 high, 24 blades @75)',
            'REDO_BAR': 'Grille bars redo (153x50)', 'REDO_RING': 'Grille rings redo, bent R975',
            'REDO_CAP': 'Grille bar end caps', 'REDO_BRKT': 'Grille ring brackets (hidden)',
            'REDO_SPLICE': 'Ring splice plates (hidden)', 'REDO_SUPPORT_ANGLE': 'Grille support angles'}
S_TR_REDO = ('')
GEN_INFO = {
    'LOUVRE': ('AL_T02', '',
               '', 'generated:LOUVRE_LAYOUT'),
    'REDO_BAR': ('AL_T02', '',
                 '', 'generated:TR_BAR_X'),
    'REDO_RING': (RING_FINISH, '',
                  '', 'generated:TR_RING_R'),
    'REDO_CAP': ('AL_T02', '',
                 '', 'generated:TR_CAP'),
    'REDO_BRKT': ('AL_MILL', '',
                  '', 'generated:TR_BRACKET'),
    'REDO_SPLICE': ('STEEL_HDG', '',
                  '', 'generated:TR_SPLICE_PLATE'),
    'REDO_SUPPORT_ANGLE': ('STEEL_HDG', '',
                  '', 'split:TR_SUPPORT_ANGLE_X'),
}

def finish_of_obj(g, m):
    if m['id'] in OBJECT_FINISH:
        return OBJECT_FINISH[m['id']]
    return finish_of(g, m['layer']) + (None,)

g2_log = collections.defaultdict(list)

def _clamp_below(V, z0):
    lo = V[:, 2] < z0 - 1e-9
    assert np.allclose(V[lo, 2], V[:, 2].min(), atol=1e-6), 'clamp needs a flat bottom'
    V = V.copy(); V[lo, 2] = z0
    return V

def g2_parts(g, m):
    V, L, oid = m['V'], m['layer'], m['id']
    if g == 'TRELLIS':
        return b3_parts(m)
    if g != 'VMU01':
        return [(V, None, None)]
    if oid in TYPE8_LOUVRE_DROP:
        b1_log['louvre_quads_replaced'].append(dict(id=oid, bay=TYPE8_LOUVRE_DROP[oid], z=[round(float(V[:, 2].min()), 4), round(float(V[:, 2].max()), 4)]))
        return []
    if oid in TYPE8_CLOSURE_IDS:
        top = V[:, 2] > TYPE8_CLOSURE_TOP - 0.0035
        assert np.allclose(np.sort(np.unique(np.round(V[top, 2], 4))), [4.685, 4.688]), 'closure top lip expected at 4.685/4.688'
        dz = TYPE8_CLOSURE_TOP - float(V[:, 2].max())
        V2 = V.copy(); V2[top, 2] += dz
        b1_log['closure_clipped'].append(dict(id=oid, face=TYPE8_CLOSURE_IDS[oid], z_before=[round(float(V[:, 2].min()), 4), round(float(V[:, 2].max()), 4)],
                                              z_after=[round(float(V2[:, 2].min()), 4), round(float(V2[:, 2].max()), 4)], dz_mm=round(dz * 1000, 1)))
        return [(V2, None, f'TYPE 8 closure top {V[:, 2].max():.4f} -> {TYPE8_CLOSURE_TOP:.4f} (underside of transom 1, unit chain 159.5; review B1)')]
    if L in ('竖向格栅条', '竖向格栅条铝板'):
        if V[:, 2].max() <= GRILLE_CLIP_Y + 1e-4:
            V2 = V.copy(); V2[:, 2] += GRILLE_BASE_RAIL_DZ
            g2_log['grille_base_rail_lifted'].append(dict(id=oid, layer=L, z_before=[round(float(V[:, 2].min()), 3), round(float(V[:, 2].max()), 3)],
                                                          z_after=[round(float(V2[:, 2].min()), 3), round(float(V2[:, 2].max()), 3)]))
            return [(V2, None, f'base rail translated {GRILLE_BASE_RAIL_DZ:+.3f} m in z onto the slab (detail detail 2: 25 mm above concrete)')]
        if V[:, 2].min() < GRILLE_CLIP_Y:
            g2_log['grille_clamped'].append(dict(id=oid, z_before=[round(float(V[:, 2].min()), 3), round(float(V[:, 2].max()), 3)]))
            return [(_clamp_below(V, GRILLE_CLIP_Y), None, f'clipped at y={GRILLE_CLIP_Y} (was {V[:, 2].min():.3f})')]
        return [(V, None, None)]
    if L in ('栏杆', '栏杆结构封修板'):
        V2 = V.copy(); V2[:, 2] += BALCONY_DZ
        g2_log['balcony_lowered'].append(dict(id=oid, layer=L, z_before=[round(float(V[:, 2].min()), 3), round(float(V[:, 2].max()), 3)],
                                              z_after=[round(float(V2[:, 2].min()), 3), round(float(V2[:, 2].max()), 3)]))
        return [(V2, None, f'translated {BALCONY_DZ:+.3f} m in z')]
    if oid in PLYWOOD_INFILL and PLYWOOD_INFILL[oid] is not None:
        z0 = PLYWOOD_INFILL[oid]
        V2 = _clamp_below(V, z0)
        g2_log['plywood_infill_clipped'].append(dict(id=oid, z_before=[round(float(V[:, 2].min()), 3), round(float(V[:, 2].max()), 3)],
                                                     z_after=[round(float(V2[:, 2].min()), 3), round(float(V2[:, 2].max()), 3)]))
        return [(V2, None, f'bottom raised {V[:, 2].min():.3f} -> {z0:.3f} (no plywood/GMS drawn below 4.335 in elevation)')]
    if oid in GL02_SPLIT:
        zs = GL02_SPLIT[oid]; z = V[:, 2]
        assert len(V) == 4 and len(m['F']) == 2 and z.min() < zs < z.max() and np.isin(np.round(z, 6), np.round([z.min(), z.max()], 6)).all()
        lo = V.copy(); lo[z > zs, 2] = zs
        hi = V.copy(); hi[z < zs, 2] = zs
        g2_log['gl02_split'].append(dict(id=oid, split_z=zs, gl02=[round(float(z.min()), 3), zs], gl01=[zs, round(float(z.max()), 3)],
                                         width=round(float(np.ptp(V[:, 1])), 3)))
        return [(lo, 'GL02', f'GL02 lite z {z.min():.3f}..{zs:.3f}'), (hi, None, f'GL01 part above the transom z {zs:.3f}..{z.max():.3f}')]
    return [(V, None, None)]

b1_log = collections.defaultdict(list)
b3_log = collections.defaultdict(list)

class _Mesh:
    def __init__(s):
        s.V, s.N, s.F, s.n = [], [], [], 0

    def poly(s, P):
        P = np.asarray(P, float)
        n = np.zeros(3)
        for a, b in zip(P, np.roll(P, -1, 0)):
            n += np.cross(a, b)
        ln = np.linalg.norm(n)
        if ln < 1e-12:
            return
        n /= ln
        s.V.append(P); s.N.append(np.repeat(n[None], len(P), 0))
        s.F.append(np.array([[s.n, s.n + k, s.n + k + 1] for k in range(1, len(P) - 1)]))
        s.n += len(P)

    def arrays(s):
        return np.vstack(s.V), np.vstack(s.F).astype(np.int64), np.vstack(s.N)

def _signed_volume(V, F):
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    return float(np.einsum('ij,ij->i', a, np.cross(b, c)).sum() / 6)

def _prism(ms, loop, a0, a1, emb, caps=True, cap_strips=None):
    e0 = emb(0, 0, 0); es = emb(1, 0, 0) - e0; et = emb(0, 1, 0) - e0; ea = emb(0, 0, 1) - e0
    flip = float(np.dot(np.cross(es, et), ea)) < 0
    L = list(loop)[::-1] if flip else list(loop)
    q = lambda pts, a: [emb(p[0], p[1], a) for p in pts]
    for i in range(len(L)):
        p, r = L[i], L[(i + 1) % len(L)]
        ms.poly([emb(p[0], p[1], a0), emb(r[0], r[1], a0), emb(r[0], r[1], a1), emb(p[0], p[1], a1)])
    if caps:
        strips = cap_strips or [loop]
        for st in strips:
            st = list(st)[::-1] if flip else list(st)
            ms.poly(q(st, a1)); ms.poly(q(st[::-1], a0))

def _box(ms, x0, x1, y0, y1, z0, z1):
    _prism(ms, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z0, z1, lambda s, t, a: np.array([s, t, a]))

def louvre_parts():
    ms = _Mesh(); table = []
    blade_up = LOUVRE_BLADE
    blade_lo = [(w, dz - LOUVRE_BLADE_T) for w, dz in LOUVRE_BLADE]
    blade_loop = blade_lo + blade_up[::-1]
    for unit, typ, face, lo, hi, corner in LOUVRE_LAYOUT:
        along, normal, plane = LOUVRE_FACES[face]
        w = LOUVRE_TYPES[typ]
        if corner == 'hi':
            u0 = lo + LOUVRE_GAP
        else:
            u0 = (lo + hi) / 2 - w / 2
        u1 = u0 + w
        z0 = LOUVRE_Z0

        def emb(u, d, z, _a=along, _pl=plane):
            return np.array([u, _pl - d, z]) if _a == 'x' else np.array([_pl - d, u, z])
        for (ua, ub, za, zb) in ((u0, u0 + LOUVRE_STILE, z0, z0 + LOUVRE_H), (u1 - LOUVRE_STILE, u1, z0, z0 + LOUVRE_H),
                                 (u0 + LOUVRE_STILE, u1 - LOUVRE_STILE, z0, z0 + LOUVRE_RAIL[0]),
                                 (u0 + LOUVRE_STILE, u1 - LOUVRE_STILE, z0 + LOUVRE_H - LOUVRE_RAIL[1], z0 + LOUVRE_H)):
            _prism(ms, [(ua, 0.0), (ub, 0.0), (ub, LOUVRE_D), (ua, LOUVRE_D)], za, zb, lambda s, t, a: emb(s, t, a))
        tips = []
        for k in range(LOUVRE_N):
            zt = z0 + LOUVRE_TIP0 + k * LOUVRE_PITCH; tips.append(round(zt, 5))
            _prism(ms, [(d, zt + dz) for d, dz in blade_loop], u0 + LOUVRE_STILE, u1 - LOUVRE_STILE,
                   lambda s, t, a: emb(a, s, t), caps=False)
        table.append(dict(unit=unit, panel=typ, face=face, width_mm=round(w * 1000, 1), u=[round(u0, 4), round(u1, 4)],
                          z=[round(z0, 5), round(z0 + LOUVRE_H, 5)], blades=LOUVRE_N, pitch_mm=LOUVRE_PITCH * 1000, first_tip=tips[0], last_tip=tips[-1]))
    zb, zt = TYPE8_UB_UP + 0.0745, TYPE8_UB_UP + 0.0745 + 1.8605
    for (ua_, ta_, fa_, loa, hia, _c), (ub_, tb_, fb_, lob, hib, _c2) in zip(LOUVRE_LAYOUT, LOUVRE_LAYOUT[1:]):
        if ua_ != ub_:
            continue
        line = hia if abs(hia - lob) < 1e-6 else (loa if abs(loa - hib) < 1e-6 else None)
        assert line is not None and fa_ == fb_, (ua_, loa, hia, lob, hib)
        along, normal, plane = LOUVRE_FACES[fa_]
        joint = sorted([p for p in table if p['unit'] == ua_], key=lambda p: p['u'][0])
        gap = round((joint[1]['u'][0] - joint[0]['u'][1]) * 1000, 2)

        def emb(u, d, z, _a=along, _pl=plane):
            return np.array([u, _pl - d, z]) if _a == 'x' else np.array([_pl - d, u, z])
        w2 = LOUVRE_MULLION['w'] / 2
        _prism(ms, [(line - w2, LOUVRE_MULLION['d'][0]), (line + w2, LOUVRE_MULLION['d'][0]), (line + w2, LOUVRE_MULLION['d'][1]),
                    (line - w2, LOUVRE_MULLION['d'][1])], zb, zt, lambda s, t, a: emb(s, t, a))
        b1_log['louvre_centre_mullions'].append(dict(unit=ua_, face=fa_, line=line, panels=[joint[0]['panel'], joint[1]['panel']], joint_gap_mm=gap,
                                                     w_mm=LOUVRE_MULLION['w'] * 1000, depth_behind_glass_plane_mm=[round(v * 1000, 1) for v in LOUVRE_MULLION['d']],
                                                     z=[round(zb, 4), round(zt, 4)]))
    assert len(b1_log['louvre_centre_mullions']) == 4, b1_log['louvre_centre_mullions']
    V, F, N = ms.arrays()
    return V, F, N, table

def _simplify_loop(loop):
    P = [p for k, p in enumerate(loop) if k == 0 or abs(p[0] - loop[k - 1][0]) > 1e-12 or abs(p[1] - loop[k - 1][1]) > 1e-12]
    if abs(P[0][0] - P[-1][0]) < 1e-12 and abs(P[0][1] - P[-1][1]) < 1e-12:
        P = P[:-1]
    out = []
    n = len(P)
    for k in range(n):
        a, b, c = np.array(P[k - 1]), np.array(P[k]), np.array(P[(k + 1) % n])
        u, v = b - a, c - b
        if abs(u[0] * v[1] - u[1] * v[0]) > 1e-14:
            out.append(P[k])
    return out

def _bar_intervals(x):
    out = []
    for cx, cy in TR_RING_C:
        d = x - cx
        if abs(d) < TR_RING_R[1] - 1e-9:
            h = math.sqrt(TR_RING_R[1] ** 2 - d * d)
            if h > 1e-7:
                out.append((cy - h, cy + h))
    return sorted(out)

def trellis_redo_parts():
    Z0, Z1 = TR_Z
    bars, rings, caps, brk, curved_plates = _Mesh(), _Mesh(), _Mesh(), _Mesh(), _Mesh()
    ys0, ys1 = TR_BAR_Y[0] + TR_CAP['t'], TR_BAR_Y[1] - TR_CAP['t']
    pieces = []; n_sample = 17
    xyz = lambda s, t, a: np.array([s, t, a])
    for bi, xa in enumerate(TR_BAR_X):
        xb = xa + TR_BAR_W
        xs = np.linspace(xa, xb, n_sample)
        segs = []
        for x in xs:
            iv = _bar_intervals(x); b = [ys0]
            for lo_, hi_ in iv:
                b += [lo_, hi_]
            b.append(ys1); segs.append([(b[j], b[j + 1]) for j in range(0, len(b), 2)])
        npc = max(len(s) for s in segs)
        for j, s in enumerate(segs):
            if len(s) < npc:
                x = xs[j]; cyv = [cy for cx, cy in TR_RING_C if abs(abs(x - cx) - TR_RING_R[1]) < 1e-6]
                b = [ys0] + sorted(sum([[cy, cy] for cy in cyv], []) + sum([[lo_, hi_] for lo_, hi_ in _bar_intervals(x)], [])) + [ys1]
                segs[j] = [(b[k], b[k + 1]) for k in range(0, len(b), 2)]
            assert len(segs[j]) == npc, (bi, j, segs[j])
        for p in range(npc):
            lo = [segs[j][p][0] for j in range(n_sample)]; hi = [segs[j][p][1] for j in range(n_sample)]
            loop = [(xs[j], lo[j]) for j in range(n_sample)] + [(xs[j], hi[j]) for j in range(n_sample - 1, -1, -1)]
            loop = _simplify_loop(loop)
            strips = [[(xs[j], lo[j]), (xs[j + 1], lo[j + 1]), (xs[j + 1], hi[j + 1]), (xs[j], hi[j])] for j in range(n_sample - 1)]
            if all(abs(lo[j] - lo[0]) < 1e-9 and abs(hi[j] - hi[0]) < 1e-9 for j in range(n_sample)):
                strips = None
            _prism(bars, loop, Z0, Z1, xyz, cap_strips=strips)
            L_c = (hi[n_sample // 2] - lo[n_sample // 2])
            pieces.append(dict(bar=bi + 1, piece=p + 1, x=[round(xa, 4), round(xb, 4)], y_centre=[round(lo[n_sample // 2], 4), round(hi[n_sample // 2], 4)],
                               length_m=round(L_c, 4)))
        zc = (Z0 + Z1) / 2
        for y0_, y1_ in ((TR_BAR_Y[0], ys0), (ys1, TR_BAR_Y[1])):
            _box(caps, xa, xb, y0_, y1_, zc - TR_CAP['h'] / 2, zc + TR_CAP['h'] / 2)
        xc = (xa + xb) / 2
        iv = _bar_intervals(xc)
        if npc == 3 and all(abs(xc - cx) < TR_RING_R[0] - TR_BAR_W / 2 for cx, _ in TR_RING_C):
            for lo_, hi_ in iv:
                for yj, sgn in ((lo_, -1), (hi_, +1)):
                    ya, yb = sorted((yj, yj + sgn * TR_BRACKET['len']))
                    _box(brk, xc - TR_BRACKET['t'] / 2, xc + TR_BRACKET['t'] / 2, ya, yb, zc - TR_BRACKET['h'] / 2, zc + TR_BRACKET['h'] / 2)
                    b3_log['brackets'].append(dict(bar=bi + 1, y=round(yj, 4)))
    nseg = 72; ring_len = 0.0
    for ri, (cx, cy) in enumerate(TR_RING_C):
        for half, (t0, t1) in enumerate(((-90.0, 90.0), (90.0, 270.0))):
            th = np.radians(np.linspace(t0, t1, nseg + 1))
            ro, rin = TR_RING_R[1], TR_RING_R[0]
            outer = [(cx + ro * math.cos(t), cy + ro * math.sin(t)) for t in th]
            inner = [(cx + rin * math.cos(t), cy + rin * math.sin(t)) for t in th[::-1]]
            strips = [[(cx + rin * math.cos(th[k]), cy + rin * math.sin(th[k])), (cx + ro * math.cos(th[k]), cy + ro * math.sin(th[k])),
                       (cx + ro * math.cos(th[k + 1]), cy + ro * math.sin(th[k + 1])), (cx + rin * math.cos(th[k + 1]), cy + rin * math.sin(th[k + 1]))]
                      for k in range(nseg)]
            _prism(rings, outer + inner, Z0, Z1, xyz, cap_strips=strips)
            ring_len += math.radians(t1 - t0) * (ro + rin) / 2
        for ang in (90.0, 270.0):
            th = np.radians(np.linspace(ang - TR_SPLICE_PLATE['half_deg'], ang + TR_SPLICE_PLATE['half_deg'], 7))
            ro, rin = TR_SPLICE_PLATE['R'][1], TR_SPLICE_PLATE['R'][0]
            outer = [(cx + ro * math.cos(t), cy + ro * math.sin(t)) for t in th]
            inner = [(cx + rin * math.cos(t), cy + rin * math.sin(t)) for t in th[::-1]]
            strips = [[(cx + rin * math.cos(th[k]), cy + rin * math.sin(th[k])), (cx + ro * math.cos(th[k]), cy + ro * math.sin(th[k])),
                       (cx + ro * math.cos(th[k + 1]), cy + ro * math.sin(th[k + 1])), (cx + rin * math.cos(th[k + 1]), cy + rin * math.sin(th[k + 1]))]
                      for k in range(6)]
            zc = (Z0 + Z1) / 2
            _prism(curved_plates, outer + inner, zc - TR_SPLICE_PLATE['h'] / 2, zc + TR_SPLICE_PLATE['h'] / 2, xyz, cap_strips=strips)
    out = {}
    for tag, ms in (('REDO_BAR', bars), ('REDO_RING', rings), ('REDO_CAP', caps), ('REDO_BRKT', brk), ('REDO_SPLICE', curved_plates)):
        V, F, N = ms.arrays()
        vol = _signed_volume(V, F)
        assert vol > 0, (tag, vol)
        out[tag] = (V, F, N)
    straight = sum(p['length_m'] for p in pieces)
    stats = dict(bars=len(TR_BAR_X), bar_pieces=len(pieces), straight_total_m=round(straight, 3), bent_total_m=round(ring_len, 3),
                 half_rings=4, ring_centreline_R_m=round(sum(TR_RING_R) / 2, 4), caps=len(TR_BAR_X) * 2, brackets=len(b3_log['brackets']),
                 curved_plates=4, pieces=pieces)
    return out, stats

def b3_parts(m):
    V, L, oid = m['V'], m['layer'], m['id']
    if L == '格栅条方形' and TR_ZONE_X[0] <= float(V[:, 0].mean()) <= TR_ZONE_X[1]:
        b3_log['legacy_cad_replaced'].append(dict(id=oid, x=[round(float(V[:, 0].min()), 4), round(float(V[:, 0].max()), 4)],
                                               y=[round(float(V[:, 1].min()), 4), round(float(V[:, 1].max()), 4)], triangles=len(m['F'])))
        return []
    if oid in TR_SUPPORT_ANGLE_IDS:
        xs = np.unique(np.round(V[:, 0], 5))
        assert len(xs) == 2, 'L75X5 rail expected as a straight prism along x'
        lo_end = V[:, 0] < xs.mean()
        parts = []
        for a, b, tag, note in ((xs[0], TR_SUPPORT_ANGLE_X[0], None, 'legacy CAD L75X5 rail, west part'),
                                (TR_SUPPORT_ANGLE_X[0], TR_SUPPORT_ANGLE_X[1], 'REDO_SUPPORT_ANGLE', 'L75x75x5 L2390 support angle, cut from the legacy CAD rail'),
                                (TR_SUPPORT_ANGLE_X[1], xs[1], None, 'legacy CAD L75X5 rail, east part')):
            V2 = V.copy(); V2[lo_end, 0] = a; V2[~lo_end, 0] = b
            parts.append((V2, tag, note))
        b3_log['support_angle_split'].append(dict(id=oid, rail=TR_SUPPORT_ANGLE_IDS[oid], x_before=[round(float(xs[0]), 4), round(float(xs[1]), 4)],
                                         support_angle=[TR_SUPPORT_ANGLE_X[0], TR_SUPPORT_ANGLE_X[1]], support_angle_length_mm=round((TR_SUPPORT_ANGLE_X[1] - TR_SUPPORT_ANGLE_X[0]) * 1000, 1)))
        return parts
    return [(V, None, None)]

def legacy_cat(mi, layer):
    if mi == 0: return 'GLASS'
    if layer == '铁架::150X5圆管': return 'STEEL_DARK'
    if mi == 54: return 'ALU_DARK2'
    if mi in (2, 4, 5, 6, 7, 8, 31, 32, 33, 34, 51, 52, 53, 55, 59): return 'ALU_DARK'
    if mi in (10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 44): return 'ALU_SILVER'
    if mi == 56: return 'ALU_WARMGREY'
    if mi in (39, 50): return 'WOODGRAIN'
    if mi == 24: return 'STAINLESS'
    if mi in (45, 46): return 'WHITE'
    if mi in (1, 40, 47): return 'PAINT_LIGHTGREY'
    if mi == 23: return 'ALU_MILL'
    return 'STEEL_GALV'

def rot_of(g):
    r = R['reg'][g]; a = math.radians(r['rot_deg']); c, s = math.cos(a), math.sin(a)
    return np.array(r['c0']), np.array([[c, s], [-s, c]]), np.array([r['tx'], r['ty']])

def xf_group(g, V, N):
    c0, Rm, t = rot_of(g)
    q = (V[:, :2] - c0) @ Rm + t
    P = r3_to_gltf(q, V[:, 2])
    n2 = r3_dir_to_gltf(N[:, :2] @ Rm)
    n = np.c_[n2[:, 0], N[:, 2], n2[:, 1]]
    return P, n

def box_uv(P, N):
    a = np.abs(N); k = a.argmax(1)
    uv = np.empty((len(P), 2))
    s = k == 1; uv[s] = P[s][:, [0, 2]]
    s = k == 0; uv[s] = P[s][:, [2, 1]]
    s = k == 2; uv[s] = P[s][:, [0, 1]]
    return uv

chs_axes = [m['V'][:, :2].mean(0) for i, m in enumerate(M)
            if R['assign'].get(str(i)) == 'VMU01' and m['layer'] == '铁架::150X5圆管']

def canopy_drop(g, m):
    if g != 'VMU01':
        return None
    L, V = m['layer'], m['V']
    in_area = V[:, 2].max() < CANOPY_Z_MAX and V[:, 0].max() < CANOPY_X_MAX
    if L == '铝板':
        return 'canopy top / edge panels (铝板, z<3.6, x<17.5)' if in_area else None
    if L in CANOPY_LAYERS_ALL:
        assert in_area, f'canopy layer {L} object {m["id"]} outside the canopy area'
        return {'铝板侧面': 'canopy fascia', '铝板底面': 'canopy soffit', '铁架::150X5圆管': 'canopy CHS150x5 column'}[L]
    if L == '铁架::地面埋板':
        c = V[:, :2].mean(0)
        if min(np.hypot(*(c - a)) for a in chs_axes) < CANOPY_PLATE_TOL:
            return 'canopy column base plate 400x400'
    return None

def _inset(s, d=0.010):
    a = np.abs(s)
    return np.where(a >= 2 * d, np.sign(s) * (a - d), 0.5 * s)

def shrink_brace(V, N, F):
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]); ar = np.linalg.norm(fn, axis=1)
    ok = ar > 1e-12; fn[ok] /= ar[ok, None]
    a = np.linalg.svd(V - V.mean(0), full_matrices=False)[2][0]
    for _ in range(3):
        side = ok & (np.abs(fn @ a) < 0.2)
        w_, U_ = np.linalg.eigh((fn[side] * ar[side, None]).T @ fn[side])
        a_new = U_[:, 0]; a = a_new if a_new @ a > 0 else -a_new
    if a[2] < 0: a = -a
    e1 = np.cross(a, [0, 0, 1.0]); e1 /= np.linalg.norm(e1); e2 = np.cross(a, e1)
    sv = np.unique(F[side].ravel()); u0 = V[sv] @ e1; w0 = V[sv] @ e2
    c = (u0.max() + u0.min()) / 2 * e1 + (w0.max() + w0.min()) / 2 * e2 + (V.mean(0) @ a) * a
    t = (V - c) @ a; u = (V - c) @ e1; w = (V - c) @ e2
    info = dict(outer_before=[round(2 * float(np.abs(u).max()), 4), round(2 * float(np.abs(w).max()), 4)])
    V2 = c + np.outer(t, a) + np.outer(_inset(u), e1) + np.outer(_inset(w), e2)
    endf = ok & (np.abs(fn @ a) > 0.2)
    planes = {}
    for f in np.where(endf)[0]:
        n = fn[f]; d = float(n @ V[F[f, 0]])
        key = (tuple(np.round(n, 2)), round(d, 3))
        planes.setdefault(key, (n, d))
    moved = np.zeros(len(V), bool)
    for n, d in planes.values():
        on = np.abs(V @ n - d) < 2e-5
        delta = (d - V2[on] @ n) / (a @ n)
        V2[on] += np.outer(delta, a); moved |= on
    t2 = (V2 - c) @ a
    u2 = (V2 - c) @ e1; w2 = (V2 - c) @ e2
    dev = max(float(np.abs(V2[np.abs(V @ n - d) < 2e-5] @ n - d).max()) for n, d in planes.values())
    info.update(outer_after=[round(2 * float(np.abs(u2).max()), 4), round(2 * float(np.abs(w2).max()), 4)], end_planes=len(planes),
                end_vertices=int(moved.sum()), end_plane_max_dev_m=dev, axis=np.round(a, 4).tolist(),
                length_before=round(float(t.max() - t.min()), 4), length_after=round(float(t2.max() - t2.min()), 4))
    return V2, info

def is_brace(m):
    V = m['V']; c = V.mean(0); a = np.linalg.svd(V - c, full_matrices=False)[2][0]
    return m['layer'] == '铁架::方钢180x180x5mm' and 0.3 < abs(a[2]) < 0.97

buckets = collections.defaultdict(list)
dropped = collections.defaultdict(lambda: collections.defaultdict(lambda: dict(objects=0, triangles=0, reason=None, ids=[])))
before_tris = collections.Counter(); after_tris = collections.Counter(); skipped = collections.Counter()
brace_log = []
for i, m in enumerate(M):
    g = R['assign'].get(str(i))
    if g is None or m['layer'].startswith('SCALE') or m['layer'] == '推拉门标注':
        skipped[m['layer'] if m['layer'].startswith('SCALE') or m['layer'] == '推拉门标注' else 'unassigned'] += len(m['F']); continue
    before_tris[g] += len(m['F'])
    if g not in KEEP_GROUPS:
        d = dropped[g][m['layer']]; d['objects'] += 1; d['triangles'] += len(m['F']); d['reason'] = 'group replaced by ' + DROPPED_GROUPS[g]
        continue
    why = canopy_drop(g, m)
    if why:
        d = dropped[g][m['layer']]; d['objects'] += 1; d['triangles'] += len(m['F']); d['reason'] = why + ' -> ' + CANOPY_GLB
        d['ids'].append(m['id']); continue
    mat, conf, src, rule, tag = finish_of_obj(g, m)
    parts = g2_parts(g, m)
    if not parts:
        continue
    for Vp, ptag, note in parts:
        buckets[(g, m['layer'], mat, ptag or tag or '')].append((i, Vp, note))

assert len(b1_log['louvre_quads_replaced']) == len(TYPE8_LOUVRE_DROP) and len(b1_log['closure_clipped']) == len(TYPE8_CLOSURE_IDS), dict(b1_log)
_Vl, _Fl, _Nl, LOUVRE_TABLE = louvre_parts()
buckets[('VMU01', '百叶面板', GEN_INFO['LOUVRE'][0], 'LOUVRE')].append(
    (None, _Vl, f'{len(LOUVRE_TABLE)} louvre panels 1946 (24 blades @75) + {len(b1_log["louvre_centre_mullions"])} unit centre mullions replace the 5 legacy CAD quads 9.165..11.150 (review B1)', _Fl, _Nl))
TR_PARTS, TR_STATS = trellis_redo_parts()
assert len(b3_log['legacy_cad_replaced']) == 34 and len(b3_log['support_angle_split']) == 2, (len(b3_log['legacy_cad_replaced']), len(b3_log['support_angle_split']))
for _tag, (_V, _F, _N) in TR_PARTS.items():
    _lay = {'REDO_BAR': '格栅条方形', 'REDO_RING': '格栅条方形', 'REDO_CAP': '格栅条方形', 'REDO_BRKT': '格栅条方形', 'REDO_SPLICE': '铁架::part'}[_tag]
    buckets[('TRELLIS', _lay, GEN_INFO[_tag][0], _tag)].append((None, _V, f'{TAG_NAME[_tag]} (review B3 trellis redo)', _F, _N))

chk = dict(vmu01_alu_panel_objects=0, dropped_above_3p6=0, kept_inside_canopy_area=0)
for i, m in enumerate(M):
    if R['assign'].get(str(i)) == 'VMU01' and m['layer'] == '铝板':
        chk['vmu01_alu_panel_objects'] += 1
        dz = m['V'][:, 2].max()
        if canopy_drop('VMU01', m) and dz >= CANOPY_Z_MAX: chk['dropped_above_3p6'] += 1
        if not canopy_drop('VMU01', m) and dz < CANOPY_Z_MAX and m['V'][:, 0].max() < CANOPY_X_MAX: chk['kept_inside_canopy_area'] += 1
assert chk['dropped_above_3p6'] == 0 and chk['kept_inside_canopy_area'] == 0, chk
print('canopy drop check', chk)

DESC = {'VMU01': 'Tower unitised curtain wall + decorative fins + TYPE 11 ground grille + plywood balcony closures + steel frame/stair '
                 '(canopy in vmu01_canopy.glb, build step; checked face by face vs elevation, canopy plan, detail, glass number, unit number: G2_vmu01_tower)',
        'VMU03': 'Curved podium facade with horizontal fins (shop-drawing model, verified 0-8 mm)',
        'TRELLIS': 'Ground-level trellis / ceiling-grille mock-up (SHS frame to 2.0 m; grille bars 2.095-2.245 m). One ring panel is '
                   'regenerated: 153 x 50 bars + bent R975 rings 2.095-2.248, end caps, steel splice plates and support angles'}
glb = GLB()
groups = collections.defaultdict(list); gbb = {}; mapping_rows = []; mats_used = collections.Counter()
for (g, layer, mat, tag), items in sorted(buckets.items()):
    Vs, Ns, Fs, off = [], [], [], 0
    ids = [it[0] for it in items if it[0] is not None]
    n_gen = sum(1 for it in items if it[0] is None)
    for it in items:
        if it[0] is None:
            _, V, note, F0, N0 = it
            P, n = xf_group(g, V, N0); Vs.append(P); Ns.append(n); Fs.append(F0 + off); off += len(P)
            continue
        i, V, note = it
        m = M[i]
        if g == 'VMU03' and VMU03_BRACE_160 and is_brace(m):
            V, inf = shrink_brace(m['V'], m['N'], m['F']); inf['id'] = m['id']; inf['index'] = i; brace_log.append(inf)
        P, n = xf_group(g, V, m['N']); Vs.append(P); Ns.append(n); Fs.append(m['F'] + off); off += len(P)
    V = np.vstack(Vs); N = np.vstack(Ns); F = np.vstack(Fs)
    mi = ML.mat(glb, mat)
    uvs = box_uv(V, N) if mat in UV_MATERIALS else None
    mesh = glb.mesh(f'{g}|{layer}|{mat}' + (f'|{tag}' if tag else ''), V, F, N, mi, uvs=uvs)
    if tag in GEN_INFO:
        _, conf, src, rule = GEN_INFO[tag]
    else:
        _, conf, src, rule = OBJECT_FINISH[M[ids[0]]['id']][:4] if tag in ('PLY', 'COPING') else finish_of(g, layer)
    n_mats_in_layer = len({k[2] for k in buckets if k[0] == g and k[1] == layer and not k[3]})
    name = f'{g}|{TAG_NAME[tag]}' if tag else f'{g}|{layer_en(layer)}' + (f' ({mat})' if n_mats_in_layer > 1 else '')
    legacy = sorted({legacy_cat(M[i]['mat'], layer) for i in ids}) if ids else ['new part (review)']
    lay_en = TAG_NAME[tag] if tag else layer_en(layer)
    geom_src = GEOM_SRC if ids else 'generated by build_cad.py from the unit / part drawings (review), placed with the legacy CAD group transform'
    ex = ML.node_extras(g, lay_en, mat, '', conf,
                        layer=layer, objects=len(ids) + n_gen, triangles=int(len(F)), finish_before='', finish_rule='')
    if tag == 'LOUVRE':
        ex['panels'] = LOUVRE_TABLE
        ex['centre_mullions'] = b1_log['louvre_centre_mullions']
        ex['band'] = dict(unit_bottom=TYPE8_UB_UP, band_top=round(TYPE8_UB_UP + 1.980, 4), panel_z=[LOUVRE_Z0, round(LOUVRE_Z0 + LOUVRE_H, 5)],
                          blades=LOUVRE_N, pitch_mm=LOUVRE_PITCH * 1000, depth_mm=LOUVRE_D * 1000)
    if tag == 'REDO_RING':
        ex['colour_open'] = True
        ex['finish_switch'] = 'MOCKUP_TRELLIS_RING_FINISH = AL_T02 (default, design) | AL_RAL7038 | AL_MILL'
    if tag in ('REDO_BAR', 'REDO_RING'):
        ex['section'] = '153 x 50, wall 3.0, circumscribed Ø161'
    if tag == 'REDO_BAR':
        ex['quantities'] = {k: TR_STATS[k] for k in ('bars', 'bar_pieces', 'straight_total_m')}
    if tag == 'REDO_RING':
        ex['quantities'] = {k: TR_STATS[k] for k in ('half_rings', 'ring_centreline_R_m', 'bent_total_m')}
    if g == 'VMU01' and layer in ('竖向格栅条', '竖向格栅条铝板'):
        ex['finish_code'] = ('')
    if tag == 'COPING':
        ex['finish_code'] = ('')
        ex['parts'] = {M[i]['id']: dict(match=COPING_IDS[M[i]['id']][0], confidence=COPING_IDS[M[i]['id']][1]) for i in ids}
    if tag == 'GL02':
        ex['glass_type'] =('')
    notes = sorted({it[2] for it in items if it[2]})
    if notes: ex['modified'] = ''
    if uvs is not None: ex['uv'] = 'metres, box projection (see scene extras uv_note)'
    if g == 'VMU03' and layer == '铁架::方钢180x180x5mm' and VMU03_BRACE_160:
        ex['modified'] = ('')
    nd = glb.node(name, mesh=mesh, extras=ex)
    groups[g].append(nd); after_tris[g] += len(F); mats_used[mat] += len(F)
    bb = (V.min(0), V.max(0)); gbb[g] = (np.minimum(gbb[g][0], bb[0]), np.maximum(gbb[g][1], bb[1])) if g in gbb else bb
    mapping_rows.append(dict(group=g, layer=layer, layer_en=lay_en, objects=len(ids), triangles=int(len(F)),
                             finish_before='', finish_after=mat, confidence=conf, rule='', source='', **({'part': tag} if tag else {})))

for g in KEEP_GROUPS:
    bb = gbb[g]
    ex = dict(group=g, description=DESC[g], triangles=int(after_tris[g]), bbox_min=bb[0].round(3).tolist(), bbox_max=bb[1].round(3).tolist(),
              size_m=(bb[1] - bb[0]).round(3).tolist(), placement=R['reg'][g], source='', confidence='high (geometry = shop-drawing CAD)')
    if g == 'VMU01':
        ex['dropped'] = {k: dict(objects=v['objects'], triangles=v['triangles'], reason=v['reason']) for k, v in dropped['VMU01'].items()}
        ex['canopy'] = 'not in this file: ' + CANOPY_GLB
    glb.node(g, children=groups[g], extras=ex, root=True)

tot = int(sum(after_tris.values()))
scene_extras = dict(
    title='mock-up off-site VMU yard - CAD (future completed state)', work_package='build step',
    frame='glTF x=East, y=Up, z=-North; metres; origin = layout plan ' + str(O.tolist()) + '; y=0 = yard slab top (C12)',
    source='', material_contract='',
    groups=list(KEEP_GROUPS), dropped_groups=DROPPED_GROUPS, canopy='VMU01 canopy CAD layers and old extension removed -> ' + CANOPY_GLB,
    cad_triangles=tot, uv_note=UV_NOTE)
glb.save('../model/vmu_cad.glb', extras=scene_extras)

G2_CHECKS = []
G2_FINISH_CHANGES = []
G2_OPEN = []

G2_ROUND2 = []
_ID = {m['id'][:8]: m for m in M}
_id8 = lambda a: _oid(a)[:8]   # 8-character id prefix of a legacy CAD object (alias -> private map)
_zr = lambda idp, k: float(_ID[idp]['V'][:, 2].min() if k == 0 else _ID[idp]['V'][:, 2].max())
_cum = lambda L, k: sum(L[:k]) / 1000.0
_SL, _EL = TYPE8_CHAINS['U17..21']['section'], TYPE8_CHAINS['U17..21']['elevation']
_SU, _EU = TYPE8_CHAINS['U27..31']['section'], TYPE8_CHAINS['U27..31']['elevation']
_glass8 = (_id8('obj_24'), _id8('obj_25'), _id8('obj_26'), _id8('obj_27'), _id8('obj_28'))
_clo_after = [r['z_after'] for r in b1_log['closure_clipped']]
G2_TYPE8_ROWS = []

def _t8(fam, band, chain, old, new, after, architect=None, dxf=None, kind='mesh edge'):
    G2_TYPE8_ROWS.append(dict(family=fam, band=band, chain=chain, architect=architect, dxf=dxf, old=None if old is None else round(old, 4), new=round(new, 4),
                              after=None if after is None else round(after, 4), delta_old_new_mm=None if old is None else round((new - old) * 1000, 1),
                              after_minus_new_mm=None if after is None else round((after - new) * 1000, 2), kind=kind))

_LO, _UP = 'U17..21 (4697.5)', 'U27..31 (6051)'
_t8(_LO, 'S.J. line below the unit', 'unit bottom - 5', None, TYPE8_UB_LO - TYPE8_SJ_GAP, None, architect=4.285, kind='level (no mesh)')
_t8(_LO, 'unit bottom (mullion bottoms)', '0', min(_zr(i, 0) for i in (_id8('obj_29'), _id8('obj_30'), _id8('obj_31'), _id8('obj_32'), _id8('obj_33'), _id8('obj_34'))),
    TYPE8_UB_LO, min(_zr(i, 0) for i in (_id8('obj_29'), _id8('obj_30'))), kind='mesh edge (unchanged)')
_t8(_LO, '3 mm closure bottom (below the unit)', 'TYPE 11 top 4.320 + 15 (detail), not a unit chain', 4.335, 4.335, min(a[0] for a in _clo_after), 4.285, 4.285)
_t8(_LO, '3 mm closure top = underside of transom 1', 'section 159.5', 4.688, TYPE8_CLOSURE_TOP, max(a[1] for a in _clo_after), 4.715, 4.670)
_t8(_LO, 'transom 1 (85)', 'section 159.5 .. 244.5', _zr(_id8('obj_35'), 0), TYPE8_UB_LO + _cum(_SL, 1), _zr(_id8('obj_35'), 0), kind='mesh edge (unchanged)')
_t8(_LO, 'glass band bottom sightline', 'elevation 202', min(_zr(i, 0) for i in _glass8), TYPE8_UB_LO + _cum(_EL, 1), min(_zr(i, 0) for i in _glass8), 4.715, 4.670)
_t8(_LO, 'glass intermediate transom centre', 'elevation 752', (_zr(_id8('obj_36'), 0) + _zr(_id8('obj_36'), 1)) / 2, TYPE8_UB_LO + _cum(_EL, 2),
    (_zr(_id8('obj_36'), 0) + _zr(_id8('obj_36'), 1)) / 2, 5.265, kind='mesh (unchanged)')
_t8(_LO, 'glass band top sightline', 'elevation 2027', max(_zr(i, 1) for i in _glass8), TYPE8_UB_LO + _cum(_EL, 3), max(_zr(i, 1) for i in _glass8), 6.540, 6.495)
_t8(_LO, 'S.J. line above (top of the fin band)', 'elevation 4652', None, TYPE8_UB_LO + _cum(_EL, 4), None, architect=9.165, dxf=9.145, kind='level (no mesh)')
_t8(_LO, 'top transom (106) bottom', 'section 4591.5', _zr(_id8('obj_37'), 0), TYPE8_UB_LO + _cum(_SL, 11), _zr(_id8('obj_37'), 0), kind='mesh edge (unchanged)')
_t8(_UP, 'unit bottom = louvre band bottom sightline', 'S.J. 9.165 + 5; elevation 0', 9.165, TYPE8_UB_UP, None, 9.165, 9.175, kind='band edge (quad removed)')
_t8(_UP, 'bottom transom (74.5) top = clear opening bottom', 'section 74.5', _zr(_id8('obj_37'), 1), TYPE8_UB_UP + _cum(_SU, 1), _zr(_id8('obj_37'), 1), kind='mesh edge (unchanged)')
_t8(_UP, 'louvre panel bottom (1946, centred in the opening)', '74.5 + 1860.5 / 2 - 973', None, LOUVRE_Z0, min(p['z'][0] for p in LOUVRE_TABLE), kind='new panels')
_t8(_UP, 'louvre panel top', 'panel bottom + 1946', None, LOUVRE_Z0 + LOUVRE_H, max(p['z'][1] for p in LOUVRE_TABLE), kind='new panels')
_t8(_UP, 'louvre band top sightline', 'elevation 1980', 11.150, TYPE8_UB_UP + _cum(_EU, 1), max(p['z'][1] for p in LOUVRE_TABLE), 11.150, 11.105,
    kind='band edge vs panel top')
_t8(_UP, 'transom above the louvres (85) bottom = clear opening top', 'section 1935', _zr(_id8('obj_38'), 0), TYPE8_UB_UP + _cum(_SU, 2), _zr(_id8('obj_38'), 0),
    kind='mesh edge (unchanged)')
_t8(_UP, 'fin band intermediate transom centre', 'elevation 4480', (_zr(_id8('obj_39'), 0) + _zr(_id8('obj_39'), 1)) / 2, TYPE8_UB_UP + _cum(_EU, 2),
    (_zr(_id8('obj_39'), 0) + _zr(_id8('obj_39'), 1)) / 2, 13.650, kind='mesh (unchanged)')
_t8(_UP, 'top S.J. line (mullion tops)', 'elevation 6005.5', max(_zr(i, 1) for i in (_id8('obj_29'), _id8('obj_30'))), TYPE8_UB_UP + _cum(_EU, 3),
    max(_zr(i, 1) for i in (_id8('obj_29'), _id8('obj_30'))), 15.175, 15.155, kind='mesh edge (unchanged)')
_t8(_UP, 'unit top (106 top transom)', '6051', _zr(_id8('obj_40'), 1), TYPE8_UB_UP + 6.051, _zr(_id8('obj_40'), 1), kind='mesh edge (unchanged)')
_T8_CAD = {
    'lo_t1': (_id8('obj_35'), _id8('obj_41')), 'lo_t2': (_id8('obj_36'), _id8('obj_42')), 'lo_t3': (_id8('obj_43'), _id8('obj_44')), 'lo_75': (_id8('obj_45'), None),
    'lo_75b': (_id8('obj_46'), _id8('obj_47')), 'sj_pair': (_id8('obj_37'), _id8('obj_48')), 'up_t85a': (_id8('obj_38'), _id8('obj_49')), 'up_75a': (_id8('obj_50'), None),
    'up_75b': (_id8('obj_51'), _id8('obj_52')), 'up_t85b': (_id8('obj_39'), _id8('obj_53')), 'up_75c': (_id8('obj_54'), _id8('obj_55')), 'up_75d': (_id8('obj_56'), _id8('obj_57')),
    'top_106': (_id8('obj_40'), _id8('obj_58'))}
_fin_zones = sorted({(round(float(m['V'][:, 2].min()), 4), round(float(m['V'][:, 2].max()), 4)) for i, m in enumerate(M)
                     if R['assign'].get(str(i)) == 'VMU01' and m['layer'] == '装饰条铝板' and m['V'][:, 1].min() > 36.30 and 15.7 < m['V'][:, 0].min()
                     and m['V'][:, 0].max() < 22.8 and np.ptp(m['V'][:, 2]) > 0.1})
_covered = lambda a, b: any(z0 - 1e-4 <= a and b <= z1 + 1e-4 for z0, z1 in _fin_zones)
G2_TYPE8_MEMBERS = []

def _mem(fam, member, chain_lohi, key, end=None, note=''):
    ids = [p for p in _T8_CAD[key] if p]
    zc = [(_zr(p, 0), _zr(p, 1)) for p in ids]
    assert all(abs(z[0] - zc[0][0]) < 2e-4 and abs(z[1] - zc[0][1]) < 2e-4 for z in zc), (key, zc)
    a, b = zc[0]
    ca, cb = chain_lohi
    G2_TYPE8_MEMBERS.append(dict(family=fam, member=member, chain=[None if v is None else round(v, 4) for v in (ca, cb)], cad_ids=ids,
                                 cad=[round(a, 4), round(b, 4)], height_mm=round((b - a) * 1000, 1),
                                 d_bottom_mm=None if ca is None or end == 'top' else round((a - ca) * 1000, 1),
                                 d_top_mm=None if cb is None or end == 'bottom' else round((b - cb) * 1000, 1),
                                 visible='hidden (inside a fin cover-panel zone)' if _covered(a, b) else 'exposed or partly exposed', note=''))

def _chain_member(fam_bottom, section, k):
    return fam_bottom + _cum(section, k), fam_bottom + _cum(section, k + 1)

_mem(_LO, 'transom 1 (85)', _chain_member(TYPE8_UB_LO, _SL, 1), 'lo_t1')
_mem(_LO, 'transom 2 (85)', _chain_member(TYPE8_UB_LO, _SL, 3), 'lo_t2')
_mem(_LO, 'transom 3 above the glass (85)', _chain_member(TYPE8_UB_LO, _SL, 5), 'lo_t3', note='')
_mem(_LO, 'member 75 (after 135.5)', _chain_member(TYPE8_UB_LO, _SL, 7), 'lo_75', note='')
_mem(_LO, 'member 50 (after 1026.5)', _chain_member(TYPE8_UB_LO, _SL, 9), 'lo_75b', note='')
_mem(_LO, 'top transom 106 (+ 5 gap + 74.5 of the upper unit: one merged CAD member)', (TYPE8_UB_LO + _cum(_SL, 11), None), 'sj_pair', end='bottom')
_mem(_UP, 'bottom transom 74.5', (None, TYPE8_UB_UP + _cum(_SU, 1)), 'sj_pair', end='top')
_mem(_UP, 'transom above the louvres (85)', _chain_member(TYPE8_UB_UP, _SU, 2), 'up_t85a', note='')
_mem(_UP, 'member 50 (after 1182.5)', _chain_member(TYPE8_UB_UP, _SU, 4), 'up_75b', note='')
_mem(_UP, 'transom 85 (fin-band sightline)', _chain_member(TYPE8_UB_UP, _SU, 6), 'up_t85b', note='')
_mem(_UP, 'member 50 (after 695.5)', _chain_member(TYPE8_UB_UP, _SU, 8), 'up_75d', note='')
_mem(_UP, 'top transom 106', _chain_member(TYPE8_UB_UP, _SU, 10), 'top_106')
_mem(_UP, 'CAD member with no chain member (75)', (None, None), 'up_75a', note='')
_mem(_UP, 'CAD member with no chain member (75)', (None, None), 'up_75c', note='')
CHAIN_SUMS ={k: dict(H=v['H'], section_sum=round(sum(v['section']), 3), elevation_sum=round(sum(v['elevation']), 3),
                      ok=abs(sum(v['section']) - v['H']) < 1e-9 and abs(sum(v['elevation']) - v['H']) < 1e-9) for k, v in TYPE8_CHAINS.items()}
assert all(c['ok'] for c in CHAIN_SUMS.values()), CHAIN_SUMS
_bays_C = sorted((float(_ID[i]['V'][:, 0].min()), float(_ID[i]['V'][:, 0].max())) for i in (_id8('obj_24'), _id8('obj_27'), _id8('obj_28')))
_bays_2 = sorted((float(_ID[i]['V'][:, 1].min()), float(_ID[i]['V'][:, 1].max())) for i in (_id8('obj_26'), _id8('obj_25')))
_mod = {'U31/21': _bays_C[0], 'U30/20': _bays_C[1], 'U29/19': _bays_C[2], 'U27/17': _bays_2[0], 'U28/18': _bays_2[1]}
UNIT_WIDTH_CHECK = [dict(units=k, module_model_mm=round((b - a) * 1000, 2), module_drawing_mm=UNIT_WIDTHS[k.split('/')[0]][1],
                         delta_mm=round((b - a) * 1000 - UNIT_WIDTHS[k.split('/')[0]][1], 2), overall_schedule_mm=UNIT_WIDTHS[k.split('/')[0]][0])
                    for k, (a, b) in _mod.items()]
G2_TYPE8 = dict(
    package='', scratch='', rule='',
    chains=TYPE8_CHAINS, chain_sums=CHAIN_SUMS, bands=G2_TYPE8_ROWS,
    members=dict(rows=G2_TYPE8_MEMBERS, fin_cover_zones=_fin_zones,
                 note=''),
    unit_widths=dict(check=UNIT_WIDTH_CHECK, decisions=UNIT_WIDTH_DECISIONS,
                     note=''),
    louvre_panels=LOUVRE_TABLE,
    edits={k: v for k, v in b1_log.items()},
    plan_deviation='',
    note='')
_st = TR_STATS
_TR_BLANK, _TR_CLAMPS, _TR_NBLANK = 3.7, (0.25, 0.30), 4
_TR_NET = {c: _TR_NBLANK * (_TR_BLANK - 2 * c) for c in _TR_CLAMPS}
_TR_OUTER = 4 * math.pi * TR_RING_R[1]
_TR_DEV = {c: (round((_st['bent_total_m'] / _TR_NET[c] - 1) * 100, 1), round((_TR_OUTER / _TR_NET[c] - 1) * 100, 1)) for c in _TR_CLAMPS}
_TR_TOL_PCT = 15.0
_TR_PASS = all(abs(v) <= _TR_TOL_PCT for d in _TR_DEV.values() for v in d)
B3_TRELLIS = dict(
    package='', scope='',
    section=dict(profile='153 x 50 x 3 bar', height_mm=153.0, width_mm=50.0, wall_mm=3.0, circumscribed_mm=161.0,
                 model_bar_mm=[round(TR_BAR_W * 1000, 3), round((TR_Z[1] - TR_Z[0]) * 1000, 3)], z=[TR_Z[0], round(TR_Z[1], 4)]),
    rings=dict(centres_rhino=TR_RING_C, R_inner_outer_m=TR_RING_R, centreline_R_m=_st['ring_centreline_R_m'], ring_centreline_design_R_m=0.975,
               delta_mm=round((_st['ring_centreline_R_m'] - 0.975) * 1000, 2), half_rings=4, finish=RING_FINISH, colour_open=True),
    counts=dict(cover_plates=_st['caps'], support_angles=len(b3_log['support_angle_split']), angle_lengths_mm=[r['support_angle_length_mm'] for r in b3_log['support_angle_split']],
                curved_splice_plates=_st['curved_plates'], curved_plate_R_mm=[TR_SPLICE_PLATE['R'][0] * 1000, TR_SPLICE_PLATE['R'][1] * 1000], brackets=_st['brackets'],
                bars=_st['bars'], bar_pieces=_st['bar_pieces']),
    lengths=dict(straight_model_m=_st['straight_total_m'], straight_net_order_m=28.8,
                 straight_dev_pct=round((_st['straight_total_m'] / 28.8 - 1) * 100, 1),
                 bent_model_m=_st['bent_total_m'], bent_net_order_m=14.8, bent_dev_pct=round((_st['bent_total_m'] / 14.8 - 1) * 100, 1),
                 explanation='',
                 bent_net_of_clamps_m=[round(_TR_NET[0.30], 3), round(_TR_NET[0.25], 3)],
                 bent_dev_pct_vs_net_of_clamps=[_TR_DEV[0.30][0], _TR_DEV[0.25][0]],
                 bent_acceptance=''),
    replaced_legacy=b3_log['legacy_cad_replaced'], support_angle_split=b3_log['support_angle_split'], bar_pieces=_st['pieces'],
    finishes={t: GEN_INFO[t][0] for t in ('REDO_BAR', 'REDO_RING', 'REDO_CAP', 'REDO_BRKT', 'REDO_SPLICE', 'REDO_SUPPORT_ANGLE')},
    finish_confidence={t: GEN_INFO[t][1] for t in ('REDO_BAR', 'REDO_RING', 'REDO_CAP', 'REDO_BRKT', 'REDO_SPLICE', 'REDO_SUPPORT_ANGLE')})
B4_WOOD_GRILLE = dict(
    package='', element='VMU01 TYPE 11 ground grille (竖向格栅条 + 竖向格栅条铝板)',
    evidence='',
    rejected='',
    open='',
    out_of_scope='',
    finish=GRILLE_FINISH)
_cop_rows = [r for r in mapping_rows if r.get('part') == 'COPING']
assert len(_cop_rows) == 1, _cop_rows
B2_COPING = dict(
    package='',
    node='VMU01|' + TAG_NAME['COPING'], finish=COPING_FINISH, hex=ML._M[COPING_FINISH]['hex'], roughness=ML._M[COPING_FINISH]['roughness'],
    hex_sci=ML._M[COPING_FINISH].get('hex_sci'), switch='MOCKUP_COPING_FINISH = AL_RAL9016 (default) | WHITE (round-2 stand-in) | AL_T02 (round 1)',
    coping_triangles=_cop_rows[0]['triangles'], coping_objects=_cop_rows[0]['objects'],
    white_triangles_before_b2=5663, white_triangles_after=int(mats_used.get('WHITE', 0)),
    white_after_is='',
    geometry='',
    open='')
summary = dict(
    work_package='build step', output='model/vmu_cad.glb', cad_triangles=tot,
    G2_TYPE8=G2_TYPE8, B2_coping=B2_COPING, B3_trellis_redo=B3_TRELLIS, B4_wood_grille=B4_WOOD_GRILLE,
    pk_b=dict(plan='',
              params=dict(TYPE8_SJ_MID=TYPE8_SJ_MID, TYPE8_SJ_GAP=TYPE8_SJ_GAP, TYPE8_UB_LO=round(TYPE8_UB_LO, 4), TYPE8_UB_UP=round(TYPE8_UB_UP, 4),
                          TYPE8_CLOSURE_TOP=TYPE8_CLOSURE_TOP, LOUVRE_Z0=LOUVRE_Z0, LOUVRE_H=LOUVRE_H, LOUVRE_D=LOUVRE_D, LOUVRE_N=LOUVRE_N,
                          LOUVRE_PITCH=LOUVRE_PITCH, RING_FINISH=RING_FINISH, TR_Z=list(TR_Z), TR_RING_R=list(TR_RING_R)),
              triangles=dict(louvre=int(len(_Fl)), trellis_redo={t: int(len(v[1])) for t, v in TR_PARTS.items()})),
    g2_vmu01_tower=dict(package='', scratch='',
                        checks=[dict(zip(('item', 'drawing', 'cad_before', 'cad_after', 'delta_after_mm', 'verdict'), r)) for r in G2_CHECKS],
                        finish_changes=[dict(zip(('group', 'element', 'before', 'after'), r)) for r in G2_FINISH_CHANGES],
                        geometry_edits={k: v for k, v in g2_log.items()}, open_issues=G2_OPEN, round2=G2_ROUND2,
                        params=dict(GRILLE_FINISH=GRILLE_FINISH, GRILLE_CLIP_Y=GRILLE_CLIP_Y, GRILLE_BASE_RAIL_DZ=GRILLE_BASE_RAIL_DZ,
                                    SOFFIT_FINISH=SOFFIT_FINISH, COPING_FINISH=COPING_FINISH, COPING_IDS=COPING_IDS, BALCONY_DZ=BALCONY_DZ,
                                    PLYWOOD_INFILL=PLYWOOD_INFILL, GL02_SPLIT=GL02_SPLIT)),
    groups={g: dict(triangles=int(after_tris[g]), triangles_before_wp1_cad=int(before_tris[g]), bbox_min=gbb[g][0].round(4).tolist(),
                    bbox_max=gbb[g][1].round(4).tolist(), size_m=(gbb[g][1] - gbb[g][0]).round(4).tolist(), description=DESC[g]) for g in KEEP_GROUPS},
    dropped_groups={g: dict(triangles=int(before_tris[g]), replaced_by=DROPPED_GROUPS[g],
                            layers={k: dict(objects=v['objects'], triangles=v['triangles']) for k, v in dropped[g].items()}) for g in DROPPED_GROUPS},
    vmu01_canopy_dropped={k: dict(v) for k, v in dropped['VMU01'].items()}, canopy_drop_check=chk,
    materials_triangles=dict(mats_used), layer_finish_map=mapping_rows,
    vmu03_braces_160=brace_log, vmu03_beams_160='not done (VMU03_BEAM_160=False): 码件 brackets, 120x60 sub-frames and 铝板02 coping bear on the 180 beam faces',
    skipped_tris=dict(skipped), uv_materials=list(UV_MATERIALS), uv_note=UV_NOTE)
json.dump(summary, open('../model/vmu_cad_summary.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('CAD triangles', tot, dict(after_tris), 'before', dict(before_tris))
print('dropped VMU01', {k: (v['objects'], v['triangles']) for k, v in dropped['VMU01'].items()})
print('materials', dict(mats_used))
print('braces', [(b['outer_before'], b['outer_after'], b['end_planes'], b['end_plane_max_dev_m']) for b in brace_log])
