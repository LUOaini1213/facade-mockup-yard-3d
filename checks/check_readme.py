"""Recompute the figures quoted in README.md and README.zh-CN.md from committed files.

Standard library only. Every count below is derived from a committed artifact (QA JSON,
inventory CSV, colour table, PNG headers or file sizes) and the exact phrase that quotes
it must be present in the README, so a stale README number fails. Figures from the
private-source checks (plan fit, colour crops, cameras) have no committed artifact; they
may appear only inside the README subsection that labels them as private, not
reproducible results. With --rhino, the layer/material/TextDot counts are also read from
the baseline 3dm (needs rhino3dm from requirements-rhino.txt).
"""
import argparse
import csv
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NUMBER_WORDS = {7: 'Seven'}
PRIVATE_EN = ('### Private-source checks (reported, not reproducible here)',
              ['0.053 m', '0.031 m', '48 of 48', '20.7', '0.15 in L*', '0.01 m'])
PRIVATE_ZH = ('### 保密资料核对（仅报告，本仓无法复现）',
              ['0.053 m', '0.031 m', '48 个色块', '20.7', '不超过 0.15', '0.01 m'])


def load(root, name):
    return json.loads((root / name).read_text(encoding='utf-8'))


def png_size(path):
    with path.open('rb') as stream:
        head = stream.read(24)
    if head[:8] != b'\x89PNG\r\n\x1a\n' or head[12:16] != b'IHDR':
        raise ValueError('Not a PNG: ' + str(path))
    return struct.unpack('>II', head[16:24])


def megabytes(root, *names):
    return '%.1f MB' % (sum((root / 'model' / name).stat().st_size for name in names) / 1e6)


def facts(root):
    qa = load(root, 'model/vmu_site_future_qa.json')
    native_qa = load(root, 'model/vmu_site_future_native_source_qa.json')
    delivery = load(root, 'model/vmu_site_future_rhino_delivery.json')
    geometry = load(root, 'model/vmu_site_future_geometry.json')
    views = load(root, 'model/rhino_views.json')
    materials = load(root, 'model/materials.json')
    with (root / 'model/vmu_site_future_inventory.csv').open(encoding='utf-8-sig', newline='') as stream:
        inventory = list(csv.DictReader(stream))
    for report in (qa, native_qa, delivery):
        if not report.get('passed') or report.get('errors'):
            raise ValueError('A committed QA report is not a pass')
    if qa['removed_surface_area_m2'] != 0 or qa['max_uv_error'] != 0:
        raise ValueError('QA report shows surface-area or UV loss')

    aliases = [name for name, entry in materials.items() if entry.get('alias_of')]
    colour = [name for name, entry in materials.items() if any(re.search('sc[ei]', key) for key in entry)]
    colour_aliases = [name for name in colour if materials[name].get('alias_of')]
    stills = sorted((root / 'renders').glob('*.png'))
    captures = sorted((root / 'renders/rhino').glob('*.png'))
    still_sizes = {png_size(path) for path in stills}
    capture_sizes = {png_size(path) for path in captures}
    if len(still_sizes) != 1 or len(capture_sizes) != 1:
        raise ValueError('Renders do not share one size')
    (sw, sh), (cw, ch) = still_sizes.pop(), capture_sizes.pop()
    if (cw, ch) != (views['width'], views['height']):
        raise ValueError('Native captures differ from model/rhino_views.json size')
    invalid_meshes = sum(1 for row in inventory if int(row['culled_degenerate_faces'] or 0) > 0)
    if sum(int(row['culled_degenerate_faces'] or 0) for row in inventory) != qa['culled_degenerate_faces']:
        raise ValueError('Inventory and QA disagree on culled faces')

    src, tri, cull = f"{qa['source_triangles']:,}", f"{qa['triangles']:,}", f"{qa['culled_degenerate_faces']:,}"
    uv, uvo, comps = f"{qa['uv_vertices']:,}", qa['uv_objects'], qa['mesh_objects']
    files = len(qa['source_files'])
    closed, opened, solid, invalid = geometry['closed'], geometry['open'], geometry['solid'], geometry['invalid']
    if geometry['mesh_components'] != comps or len(inventory) != comps:
        raise ValueError('Component counts disagree between QA, geometry and inventory')
    gen, assets, finishes = native_qa['generated_uv_objects'], len(delivery['embedded_assets']), delivery['textured_materials']
    nviews, bbox = len(views['views']), repr(qa['max_bbox_error_mm'])
    if len(delivery['named_views']) != nviews or len(captures) != nviews:
        raise ValueError('Named views, captures and viewer presets disagree')
    en = [
        f'GLBs ({src} triangles)', f'keeps all {uv} source UV coordinates exactly',
        f'after culling {cull} degenerate faces; {closed} of its {comps} mesh components are closed and {solid} are solid',
        f'{NUMBER_WORDS[files]} glTF files hold {src} triangles', f'with {comps} mesh components',
        f'The Rhino export has {tri} valid triangles after removing {cull} degenerate faces',
        f'{len(materials)} named records, including {len(aliases)} aliases',
        f'Thirteen records carry SCI/SCE colour fields: seven canonical entries and six aliases'
        if (len(colour), len(colour) - len(colour_aliases), len(colour_aliases)) == (13, 7, 6) else 'SCI/SCE count changed',
        f'It has {nviews} preset views', f'all {nviews} named views',
        f'({uvo} meshes / {uv} UV coordinates)', f'inventory of the {comps} mesh components',
        f'world mapping to {gen} meshes without source UVs', f'{assets} image assets for {finishes} finishes',
        f'{nviews} native {cw} × {ch} viewport captures', f'{closed} closed / {opened} open / {solid} solid meshes',
        f'holds {len(stills)} stills at {sw} × {sh} pixels', f'{len(stills)} stills + contact_sheet.jpg',
        f'still contain {src} source triangles', f'Rhino contains {tri} triangles after culling {cull} degenerate faces '
        f'from {invalid_meshes} previously invalid meshes', f'compares all {uv} UV coordinates exactly',
        f'Bounding-box round-off is at most {bbox} mm', f'colour table ({len(materials)} registered materials)',
        f'trellis {megabytes(root, "vmu_cad.glb")}', f'extension {megabytes(root, "vmu01_canopy.glb")}',
        f'vmu05.glb {megabytes(root, "vmu02.glb", "vmu04.glb", "vmu05.glb")}',
        f'generic road {megabytes(root, "site_ground.glb")}', f'hoarding {megabytes(root, "site_context.glb")}',
        f'Rhino (mm) {megabytes(root, "vmu_site_future.3dm")}',
    ]
    zh = [
        f'{files} 个 GLB（共 {src} 个三角面）', f'逐一保留全部 {uv} 组源 UV', f'剔除 {cull} 个退化三角面后表面积无损失',
        f'{comps} 个网格构件中 {closed} 个闭合、{solid} 个为实体', f'{files} 个 glTF 文件共 {src} 个三角面',
        f'含 {comps} 个网格构件', f'剔除 {cull} 个退化三角面后共有 {tri} 个有效三角面',
        f'{len(materials)} 条命名记录，其中 {len(aliases)} 条为别名',
        f'{len(colour)} 条记录包含 SCI/SCE 色值，实际为 {len(colour) - len(colour_aliases)} 条主记录及 {len(colour_aliases)} 个别名',
        f'{nviews} 个预设视角', f'{nviews} 个命名视图', f'（{uvo} 个网格，共 {uv} 组坐标）', f'{comps} 行网格构件清单',
        f'缺少 UV 的 {gen} 个网格', f'{finishes} 种饰面的 {assets} 张图片', f'{nviews} 张 {cw}×{ch} 的 Rhino Rendered 视口图',
        f'{closed} 个闭合、{opened} 个开放、{solid} 个实体、{invalid} 个无效网格',
        f'共有 {len(stills)} 张 {sw}×{sh} 的静帧', f'仍为 {src} 个三角面', f'移除原有 {invalid_meshes} 个无效网格中的 {cull} 个退化三角面后为 {tri} 个有效三角面',
        f'全部 {uv} 组 UV', f'包围盒舍入误差最大 {bbox} mm',
    ]
    return {'README.md': en, 'README.zh-CN.md': zh}


def rhino_facts(root):
    import rhino3dm
    model = rhino3dm.File3dm.Read(str(root / 'model/vmu_site_future.3dm'))
    dots = sum(1 for obj in model.Objects if isinstance(obj.Geometry, rhino3dm.TextDot))
    meshes = sum(1 for obj in model.Objects if isinstance(obj.Geometry, rhino3dm.Mesh))
    layers, materials = len(model.Layers), len(model.Materials)
    return {'README.md': [f'with {meshes} mesh components + {dots} information TextDot, {layers} layers and {materials} materials'],
            'README.zh-CN.md': [f'含 {meshes} 个网格构件和 {dots} 个说明文字点、{layers} 个图层及 {materials} 个材质']}


def private_figures_contained(text, heading, tokens):
    errors = []
    start = text.find(heading)
    if start < 0:
        return ['missing private-results heading ' + heading]
    end = text.find('\n## ', start)
    end = len(text) if end < 0 else end
    outside = text[:start] + text[end:]
    for token in tokens:
        if token in outside:
            errors.append(f'private-run figure {token!r} appears outside {heading!r}')
        if token not in text[start:end]:
            errors.append(f'private-run figure {token!r} missing from {heading!r}')
    return errors


def check(root, rhino=False):
    expected = facts(root)
    if rhino:
        for name, phrases in rhino_facts(root).items():
            expected[name] += phrases
    errors = []
    for name, phrases in expected.items():
        raw = (root / name).read_text(encoding='utf-8')
        text = re.sub(r'\s+', ' ', raw)
        for phrase in phrases:
            if re.sub(r'\s+', ' ', phrase) not in text:
                errors.append(f'{name}: expected phrase not found: {phrase!r}')
        heading, tokens = PRIVATE_EN if name == 'README.md' else PRIVATE_ZH
        errors += [name + ': ' + error for error in private_figures_contained(raw, heading, tokens)]
    return {'passed': not errors, 'checked_phrases': sum(len(p) for p in expected.values()), 'errors': errors}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--rhino', action='store_true', help='also read counts from the baseline 3dm (needs rhino3dm)')
    parser.add_argument('--root', type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args()
    report = check(args.root.resolve(), args.rhino)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
