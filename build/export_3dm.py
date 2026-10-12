"""Exports every model GLB (VMU CAD, canopy, VMU-02, VMU-04, VMU-05, site ground, site context) into one Rhino 8 file,
model/vmu_site_future.3dm: millimetres, X = East, Y = North, Z = Up (glTF (x, y, z) m -> Rhino (x, -z, y) mm); every glTF
primitive becomes one Rhino mesh with its own normals and UVs, layers follow the "<GROUP>|<component>" node names
(root layers MOCKUP_VMU and SITE), layer colours are the sRGB material colours, node extras become object user text
and a few document user strings (MOCKUP.*) summarise the build. The VMU layers are asserted to contain no red colour.
"""
import colorsys, csv, json, os, sys, time
from glb_reader import read_glb, accessor, walk
from rhino_mesh import make_mesh, source_key, component_id
from material_integrity import validate_materials
from prepare_rhino_assets import load_json,validate_glb_materials
import numpy as np
import rhino3dm as r

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.normpath(os.path.join(HERE, '..', 'model'))
OUT = os.environ.get('MOCKUP_3DM_OUT') or os.path.join(MODEL, 'vmu_site_future.3dm')
REPORT = os.environ.get('MOCKUP_3DM_REPORT') or os.path.join(HERE, '_scratch', 'export_3dm_report.json')
INVENTORY = os.environ.get('MOCKUP_3DM_INVENTORY') or os.path.splitext(OUT)[0] + '_inventory.csv'
FILES = [
    ('vmu_cad.glb', 'MOCKUP_VMU', 'VMU01 tower (no canopy) + VMU03 + TRELLIS - legacy CAD meshes, build_cad.py'),
    ('vmu01_canopy.glb', 'MOCKUP_VMU', 'VMU01 canopy, existing + extension, parametric - build_canopy.py'),
    ('vmu02.glb', 'MOCKUP_VMU', 'VMU02 enclosure sample - build_vmu02.py'),
    ('vmu04.glb', 'MOCKUP_VMU', 'VMU04 vertical corner - build_vmu04.py'),
    ('vmu05.glb', 'MOCKUP_VMU', 'VMU05 low curved balustrade - build_vmu05.py'),
    ('site_ground.glb', 'SITE', 'yard slab, drains, rails, main road - build_ground.py'),
    ('site_context.glb', 'SITE', 'factories, hoarding, gantries, masts, containers, platform - build_context2.py'),
]
CANOPY_LAYER = 'Canopy (existing + extension)'
USER_TEXT_KEYS = ('group', 'layer', 'layer_en', 'part', 'role', 'finish', 'finish_code', 'finish_source', 'finish_confidence', 'finish_status',
                  'source', 'confidence', 'highlight', 'param', 'options', 'columns', 'glass_type', 'modified',
                  'note', 'indicative', 'concealed', 'context', 'objects', 'triangles', 'plan_area_m2', 'c18_flag', 'flag', 'flags')

MATDB = validate_materials(load_json(os.path.join(MODEL, 'materials.json')))

def canon(name):
    if name not in MATDB: raise ValueError('Unknown public material: '+str(name))
    n = name
    while MATDB[n].get('alias_of'): n = MATDB[n]['alias_of']
    return n

def lin2srgb(c):
    c = max(0.0, min(1.0, float(c)))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055

def mat_rgb(J, mi):
    if mi is None: raise ValueError('Public mesh has no material assignment')
    m = J['materials'][mi]; name = m.get('name', f'mat{mi}'); cn = canon(name)
    if cn:
        h = MATDB[cn]['hex'].lstrip('#'); return (cn, tuple(int(h[k:k + 2], 16) for k in (0, 2, 4)), MATDB[cn])
    bc = m.get('pbrMetallicRoughness', {}).get('baseColorFactor', [0.63, 0.63, 0.63, 1])
    return (name, tuple(round(lin2srgb(v) * 255) for v in bc[:3]), None)

def is_red(rgb):
    h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
    return (h * 360 < 20 or h * 360 > 340) and s > 0.35 and 0.12 < l < 0.85

out = r.File3dm(); out.Settings.ModelUnitSystem = r.UnitSystem.Millimeters
out.Settings.ModelAbsoluteTolerance = 0.01
layer_idx, layer_rgb, rmat_idx = {}, {}, {}

def safe(s):
    s = str(s).replace('::', ' - ').replace(':', '-').replace('\n', ' ').strip()
    return s[:120] or 'part'

def render_material(cn, rgb, entry):
    if cn in rmat_idx: return rmat_idx[cn]
    m = r.Material(); m.Name = cn; m.DiffuseColor = (*rgb, 255)
    metal = float(entry['metalness']); rough = float(entry['roughness'])
    g = (entry or {}).get('glass')
    m.Reflectivity = 0.08 + 0.6 * metal; m.Shine = (1 - rough) * 255 * 0.8
    if g and not g.get('opaque'): m.Transparency = float(g.get('vlt', 0.4)); m.IndexOfRefraction = 1.52
    m.ToPhysicallyBased(); pb = m.PhysicallyBased
    pb.BaseColor = (rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1.0); pb.Metallic = metal; pb.Roughness = rough
    pb.Clearcoat = float(entry.get('clearcoat',0)); pb.ClearcoatRoughness = float(entry.get('clearcoatRoughness',.3))
    pb.Anisotropic = float(entry.get('anisotropy',0))
    # rhino3dm 8.32 exposes emission as a float tuple and no PBR Alpha;
    # retain baseline alpha in legacy transparency/UserText. Native Rhino
    # explicitly writes and verifies pbr-alpha in the delivery model.
    pb.EmissionColor = (*entry.get('emission_linear',[0.,0.,0.]),1.)
    if 'alpha' in entry:
        m.Transparency = 1-float(entry['alpha'])
        m.SetUserString('canonical_alpha',str(entry['alpha']))
    if g and not g.get('opaque'): pb.Opacity = 1.0 - float(g['vlt']) * 0.85; pb.OpacityIOR = float(g['ior'])
    m.SetUserString('hex', '#%02X%02X%02X' % rgb)
    if entry:
        for k in ('confidence', 'source'):
            if entry.get(k): m.SetUserString(k, str(entry[k])[:1000])
    rmat_idx[cn] = out.Materials.Add(m); return rmat_idx[cn]

def layer(path, rgb=None, mat=None, info=None):
    for k in range(1, len(path) + 1):
        p = path[:k]
        if p in layer_idx: continue
        L = r.Layer(); L.Name = safe(p[-1])
        leaf = k == len(path)
        c = rgb if (leaf and rgb) else (150, 150, 150)
        L.Color = (*c, 255)
        if k > 1: L.ParentLayerId = out.Layers.FindIndex(layer_idx[p[:-1]]).Id
        if leaf and mat is not None: L.RenderMaterialIndex = mat
        if leaf and info:
            for kk, vv in info.items(): L.SetUserString(kk, str(vv)[:2000])
        idx = out.Layers.Add(L)
        assert idx >= 0, ('layer rejected', p)
        layer_idx[p] = idx; layer_rgb[p] = c
    return layer_idx[path]

def add_mesh(V, F, N, uv, lay, name, extras, key):
    m = make_mesh(V, F, N, uv)
    att = r.ObjectAttributes(); att.LayerIndex = lay; att.Name = name[:250]
    att.Id = component_id(key)
    att.SetUserString('component_id', str(att.Id))
    att.SetUserString('source_key', key)
    att.SetUserString('has_uv', 'true' if uv is not None else 'false')
    att.SetUserString('source_triangles', str(len(F)))
    att.SetUserString('culled_degenerate_faces', str(len(F) - len(m.Faces)))
    att.SetUserString('inventory_kind', 'GLB mesh primitive; may aggregate physical parts')
    for k in USER_TEXT_KEYS:
        v = extras.get(k)
        if v is None or v == '': continue
        att.SetUserString(k, (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))[:2000])
    gid = out.Objects.AddMesh(m, att)
    if gid != att.Id:
        raise RuntimeError('Rhino did not preserve component ID: ' + key)
    return gid, len(m.Faces)

def to_rhino(P):
    return np.c_[P[:, 0], -P[:, 2], P[:, 1]] * 1000.0

t0 = time.time()
rep = {'output': OUT, 'units': 'mm, X=E, Y=N, Z=Up', 'files': {}, 'groups': {}, 'layers': 0, 'objects': 0, 'triangles': 0, 'missing': [],
       'red_layers_MOCKUP_VMU': [], 'red_layers_SITE': [], 'uv_objects': 0, 'group_files': {}, 'materials': {},
       'source_triangles': 0, 'culled_degenerate_faces': 0}
inventory_rows = []
for fn, top, desc in FILES:
    path = os.path.join(MODEL, fn)
    if not os.path.exists(path):
        raise ValueError('Required public GLB is missing: '+fn)
    J, BIN = read_glb(path)
    validate_glb_materials(J,MATDB,fn)
    ftri = fobj = 0
    for ni, W, anc in walk(J):
        n = J['nodes'][ni]
        if 'mesh' not in n: continue
        name = n.get('name', f'node{ni}'); ex = n.get('extras') or {}
        parts = name.split('|')
        if fn == 'vmu01_canopy.glb':
            ext = ex.get('highlight') == 'extension' or (len(parts) > 1 and parts[1].lower().startswith('ext'))
            comp = parts[-1] if len(parts) > 2 else parts[-1]
            lpath = (top, 'VMU01', CANOPY_LAYER, 'Extension (new)' if ext else 'Existing', comp)
            grp = 'VMU01'
        else:
            grp = parts[0] if len(parts) > 1 else (anc[-1] if anc else os.path.splitext(fn)[0])
            if fn == 'site_ground.glb': lpath = (top, 'Ground', parts[1] if len(parts) > 1 else name)
            else: lpath = (top, grp, parts[1] if len(parts) > 1 else name)
        Nrm = np.linalg.inv(W[:3, :3]).T
        for pi, prim in enumerate(J['meshes'][n['mesh']]['primitives']):
            if prim.get('mode', 4) != 4: continue
            P = accessor(J, BIN, prim['attributes']['POSITION']).astype(np.float64)
            P = (P @ W[:3, :3].T) + W[:3, 3]
            Nn = None
            if 'NORMAL' in prim['attributes']:
                Nn = accessor(J, BIN, prim['attributes']['NORMAL']).astype(np.float64) @ Nrm.T
                Nn /= np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-12)
                Nn = np.c_[Nn[:, 0], -Nn[:, 2], Nn[:, 1]]
            F = accessor(J, BIN, prim['indices']).reshape(-1, 3).astype(np.int64) if 'indices' in prim else np.arange(len(P)).reshape(-1, 3)
            if np.linalg.det(W[:3, :3]) < 0: F = F[:, ::-1]
            cn, rgb, entry = mat_rgb(J, prim.get('material'))
            lp = lpath if len(J['meshes'][n['mesh']]['primitives']) == 1 else lpath[:-1] + (f'{lpath[-1]} [{cn}]',)
            mi = render_material(cn, rgb, entry)
            info = {'material': cn, 'hex': '#%02X%02X%02X' % rgb, 'file': fn}
            li = layer(lp, rgb, mi, info)
            ex2 = dict(ex); ex2.setdefault('finish', cn)
            uv = None
            if 'TEXCOORD_0' in prim['attributes']:
                uv = accessor(J, BIN, prim['attributes']['TEXCOORD_0'])
                rep['uv_objects'] += 1
            key = source_key(fn, ni, pi)
            Vr = to_rhino(P)
            gid, valid_triangles = add_mesh(Vr, F, Nn, uv, li, name, ex2, key)
            row = {'component_id': str(gid), 'source_key': key, 'source_file': fn,
                   'name': name, 'layer_path': '::'.join(safe(p) for p in lp),
                   'group': ex2.get('group', grp), 'part': ex2.get('part', ''),
                   'role': ex2.get('role', ''), 'finish': cn, 'confidence': ex2.get('confidence', ''),
                   'vertices': len(P), 'source_triangles': len(F), 'triangles': valid_triangles,
                   'culled_degenerate_faces': len(F) - valid_triangles,
                   'uv_count': len(uv) if uv is not None else 0}
            for axis, low, high in zip('xyz', Vr.min(0), Vr.max(0)):
                row['min_' + axis + '_mm'] = float(low)
                row['max_' + axis + '_mm'] = float(high)
            inventory_rows.append(row)
            rep['group_files'].setdefault(lp[1] if top == 'MOCKUP_VMU' else f'SITE::{lp[1]}', set()).add(fn)
            rep['materials'][cn] = rep['materials'].get(cn, 0) + valid_triangles
            rep['source_triangles'] += len(F)
            rep['culled_degenerate_faces'] += len(F) - valid_triangles
            nt = valid_triangles; ftri += nt; fobj += 1
            Vr = to_rhino(P); g = rep['groups'].setdefault(lp[1] if top == 'MOCKUP_VMU' else f'SITE::{lp[1]}', {'triangles': 0, 'objects': 0, 'min_mm': [1e18] * 3, 'max_mm': [-1e18] * 3})
            g['triangles'] += nt; g['objects'] += 1
            g['min_mm'] = np.minimum(g['min_mm'], Vr.min(0)).tolist(); g['max_mm'] = np.maximum(g['max_mm'], Vr.max(0)).tolist()
    rep['files'][fn] = {'triangles': ftri, 'objects': fobj, 'mtime': time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(path))), 'bytes': os.path.getsize(path), 'desc': desc}
    rep['triangles'] += ftri; rep['objects'] += fobj
    print(f'{fn}: {fobj} objects, {ftri:,} triangles ({time.time() - t0:.0f} s)')

for p, c in layer_rgb.items():
    if is_red(c): rep['red_layers_' + p[0]].append({'layer': '::'.join(p), 'rgb': c})
assert not rep['red_layers_MOCKUP_VMU'], ('red layer in MOCKUP_VMU', rep['red_layers_MOCKUP_VMU'])
dup = {g: sorted(f) for g, f in rep['group_files'].items() if g in ('VMU02', 'VMU03', 'VMU04', 'VMU05', 'TRELLIS') and len(f) != 1}
assert not dup, ('VMU group exported from more than one GLB (duplicate)', dup)
assert rep['group_files'].get('VMU01', set()) <= {'vmu_cad.glb', 'vmu01_canopy.glb'}, rep['group_files'].get('VMU01')
legacy = [m for m in rep['materials'] if m.startswith('EXT_CANOPY')]
assert not legacy, ('legacy sketch-extension materials still present', legacy)
ext_layers = [p for p in layer_idx if len(p) > 3 and p[2] == CANOPY_LAYER and p[3] == 'Extension (new)']
if 'vmu01_canopy.glb' in rep['files']: assert ext_layers, 'canopy extension sub-layer missing'
rep['extension_layers'] = ['::'.join(p) for p in ext_layers if len(p) == 5]
cx = {}
try: cx = read_glb(os.path.join(MODEL, 'vmu01_canopy.glb'))[0]['scenes'][0].get('extras', {})
except Exception: pass
FIN = cx.get('finish') or {}
if not FIN and cx.get('canopy', {}).get('params'):
    P = cx['canopy']['params']; FIN = {'scheme': P.get('SCHEME', '?'), 'top': P.get('TOP_FINISH', '?'), 'clad_3mm': P.get('CLAD_FINISH', '?'), 'columns': P.get('COLUMN_FINISH', '?')}
def _fhex(n): return MATDB.get(canon(n) or '', {}).get('hex', '?') if n else '?'
canopy_mats = {}
for p, i in layer_idx.items():
    if len(p) == 5 and p[2] == CANOPY_LAYER:
        canopy_mats.setdefault(out.Layers.FindIndex(i).GetUserString('material'), []).append('::'.join(p[3:]))
rep['canopy_finish'] = {'glb_finish': FIN, 'layer_materials': {k: sorted(v) for k, v in canopy_mats.items()}}
if FIN.get('uses_ral7038') is False or FIN.get('scheme') == 'ORDERS':
    assert 'AL_RAL7038' not in canopy_mats, ('RAL 7038 on a canopy layer although the GLB finish scheme excludes it', canopy_mats.get('AL_RAL7038'))
want = {FIN.get(k) for k in ('top', 'clad_3mm', 'columns', 'joints', 'frame') if FIN.get(k)} | {'RC_PLAIN'}
if want and FIN.get('joints'):
    assert set(canopy_mats) <= want, ('canopy layer material not in the GLB finish block', sorted(set(canopy_mats) - want))
rep['group_files'] = {g: sorted(f) for g, f in rep['group_files'].items()}
CC = cx.get('canopy', {}).get('columns') or []
COLS = cx.get('COLUMNS') or cx.get('canopy', {}).get('params', {}).get('COLUMNS')
col_rows = [{k: c.get(k) for k in ('id', 'region', 'layout', 'xy_plan_m', 'dwg_block_xy_mm', 'dwg_block_xy_mm_asdrawn', 'moved_from_source_mm', 'rule',
                                   'cap_y', 'dist_inside_edge_m', 'under_canopy', 'meets_soffit', 'confidence')} for c in CC]
rep['canopy_columns'] = {'COLUMNS': COLS, 'n': len(CC), 'outside_or_free': [c['id'] for c in col_rows if not (c.get('under_canopy') and c.get('meets_soffit'))],
                         'moved_mm': {c['id']: c['moved_from_source_mm'] for c in col_rows if (c.get('moved_from_source_mm') or 0) > 1}}
if COLS == 'dwg_cen':
    assert CC and not rep['canopy_columns']['outside_or_free'], ('canopy column outside the canopy / not meeting the soffit', rep['canopy_columns'])
T2 = {}
try: T2 = json.load(open(os.path.join(MODEL, 'vmu_cad_summary.json'), encoding='utf-8')).get('g2_vmu01_tower', {})
except Exception: pass
T2P = T2.get('params', {})
G8, B3 = {}, {}
try:
    _cs = json.load(open(os.path.join(MODEL, 'vmu_cad_summary.json'), encoding='utf-8')); G8 = _cs.get('G2_TYPE8', {}); B3 = _cs.get('B3_trellis_redo', {})
except Exception: pass

geo = {}
try: geo = json.load(open(os.path.join(HERE, 'georef.json'), encoding='utf-8'))
except Exception: pass
info_l = layer(('MOCKUP_VMU', '_Info'), (90, 90, 90))
att = r.ObjectAttributes(); att.LayerIndex = info_l; att.Name = 'mock-up VMU site origin'
att.Id = component_id('document/site-origin')
out.Objects.AddTextDot('mock-up VMU yard (future completed state). Origin = layout plan ' + json.dumps(geo.get('origin_R3m', '')) +
                       ' m; X=East Y=North Z=Up mm; Z=0 = yard slab top', r.Point3d(0, 0, 20000), att)
S = out.Strings
S['MOCKUP.component_ids'] = 'UUID5 from GLB filename/node/primitive indices; stable on unchanged source topology'
S['MOCKUP.inventory'] = os.path.basename(INVENTORY) + '; one mesh primitive per row, not a fabrication quantity take-off'
S['MOCKUP.uv_objects'] = str(rep['uv_objects'])
S['MOCKUP.culled_degenerate_faces'] = str(rep['culled_degenerate_faces'])
S['MOCKUP.units'] = 'millimetres; X = East, Y = North, Z = Up; Z = 0 = yard slab top'
S['MOCKUP.origin'] = 'site origin = layout plan ' + json.dumps(geo.get('origin_R3m', '')) + ' m (build/georef.json)'
S['MOCKUP.files'] = json.dumps({k: {kk: v[kk] for kk in ('triangles', 'objects', 'mtime')} for k, v in rep['files'].items()}, ensure_ascii=False)
S['MOCKUP.missing'] = ', '.join(rep['missing']) or 'none'
S['MOCKUP.materials'] = ('layer colours = model/materials.json sRGB (contract section 4); hex = SCE-equivalent body albedo (colour_basis SCE, card appearance in hex_sci); '
                         'render materials named by canonical material')
q1 = (f"Q1 canopy finish scheme {FIN.get('scheme', '?')} (from vmu01_canopy.glb): top {FIN.get('top', '?')} {_fhex(FIN.get('top'))}, "
      f"3 mm band / fascia / chamfer / soffit {FIN.get('clad_3mm', '?')} {_fhex(FIN.get('clad_3mm'))}, columns + base plates {FIN.get('columns', '?')} {_fhex(FIN.get('columns'))}"
      + (' (alternative scheme RAL7038 = build_canopy MOCKUP_CANOPY_SCHEME=RAL7038)' if FIN.get('scheme') == 'ORDERS' else '')
      + '; ')
S['MOCKUP.defaults'] = ('')
S['MOCKUP.canopy_finish'] = FIN.get('text_en') or q1
S['MOCKUP.canopy_extension'] = ('layer MOCKUP_VMU::VMU01::Canopy (existing + extension)::Extension (new) - real finish, same scheme as the existing canopy '
                               f"(top {FIN.get('top', '?')} {_fhex(FIN.get('top'))}, 3 mm parts {FIN.get('clad_3mm', '?')} {_fhex(FIN.get('clad_3mm'))}, "
                               f"columns {FIN.get('columns', '?')} {_fhex(FIN.get('columns'))}; never red); "
                               f"extension {cx.get('extension_area_m2', '?')} m2, existing {cx.get('existing_canopy_area_m2', '?')} m2, "
                               f"{cx.get('columns_total', cx.get('new_columns', '?'))} CHS150 columns (layout {COLS or '?'}), oculus D{cx.get('oculus_diameter_m', '?')} m")
S['MOCKUP.canopy_columns'] = json.dumps({'COLUMNS': COLS, 'layout': cx.get('canopy', {}).get('column_layout', {}).get('text'),
                                        'confidence': cx.get('canopy', {}).get('column_layout', {}).get('confidence'), 'columns': col_rows}, ensure_ascii=False)
if T2P:
    S['MOCKUP.vmu01_tower'] = ('')
_ctx = {}
try: _ctx = read_glb(os.path.join(MODEL, 'site_context.glb'))[0]['scenes'][0].get('extras', {})
except Exception: pass
if _ctx.get('attribution'):
    S['MOCKUP.context_attribution'] = str(_ctx['attribution'])[:4000]
S['MOCKUP.ground'] = ('SITE::Ground = site_ground.glb: yard slab, damp patches (the viewer blurs them into soft stains), drains, IC chambers, '
                     'hydrants, crane rails + red safety lines, yellow line, main road carriageway ~0.8-0.95 m below the yard, kerbs, verges')
os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
if not out.Write(OUT, 8):
    raise RuntimeError('Could not write Rhino file: ' + OUT)
os.makedirs(os.path.dirname(os.path.abspath(INVENTORY)), exist_ok=True)
with open(INVENTORY, 'w', encoding='utf-8-sig', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=list(inventory_rows[0]))
    writer.writeheader()
    writer.writerows(inventory_rows)
rep['inventory'] = INVENTORY
rep['inventory_rows'] = len(inventory_rows)
rep['layers'] = len(layer_idx); rep['seconds'] = round(time.time() - t0, 1); rep['bytes'] = os.path.getsize(OUT)
os.makedirs(os.path.dirname(REPORT), exist_ok=True)
json.dump(rep, open(REPORT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f"wrote {OUT}: {rep['objects']} objects, {rep['triangles']:,} triangles, {rep['layers']} layers, {rep['bytes'] / 1e6:.1f} MB, {rep['seconds']} s")
if rep['missing']: print('missing:', rep['missing'])
if rep['red_layers_SITE']: print('red-hued SITE layers (real context finishes):', rep['red_layers_SITE'])
