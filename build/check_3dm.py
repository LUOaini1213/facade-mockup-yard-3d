"""Verify the Rhino export against committed GLBs and its inventory (no private inputs)."""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
import rhino3dm as r

from glb_reader import read_glb, accessor, walk
from rhino_mesh import component_id, source_key, make_mesh, world_uv


def surface_area_m2(vertices_mm, faces):
    edges1 = vertices_mm[faces[:, 1]] - vertices_mm[faces[:, 0]]
    edges2 = vertices_mm[faces[:, 2]] - vertices_mm[faces[:, 0]]
    return float(np.linalg.norm(np.cross(edges1, edges2), axis=1).sum() * 0.5e-6)


def verify(model_path, inventory_path):
    model_path, inventory_path = Path(model_path), Path(inventory_path)
    doc = r.File3dm.Read(str(model_path))
    if doc is None:
        raise ValueError('Cannot read Rhino model: ' + str(model_path))
    errors = []
    meshes = [obj for obj in doc.Objects if isinstance(obj.Geometry, r.Mesh)]
    by_key = {}
    for obj in meshes:
        key = obj.Attributes.GetUserString('source_key')
        if not key or key in by_key:
            errors.append('Missing or duplicate source key: ' + str(key))
        by_key[key] = obj
    with inventory_path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    inventory = {row['source_key']: row for row in rows}
    if len(inventory) != len(rows) or set(inventory) != set(by_key):
        errors.append('Inventory does not match mesh source keys exactly')
    if doc.Settings.ModelUnitSystem != r.UnitSystem.Millimeters:
        errors.append('Model unit is not millimetres')
    expected, triangles, uv_objects, uv_vertices = set(), 0, 0, 0
    source_triangles, culled_faces = 0, 0
    source_area, retained_area = 0.0, 0.0
    max_uv_error, max_bbox_error_mm = 0.0, 0.0
    generated_uv_objects, generated_uv_vertices, max_generated_uv_error = 0, 0, 0.0
    max_vertex_error_mm, max_normal_error = 0.0, 0.0
    source_files = sorted({row['source_file'] for row in rows})
    required = {'vmu_cad.glb', 'vmu01_canopy.glb', 'vmu02.glb', 'vmu04.glb',
                'vmu05.glb', 'site_ground.glb', 'site_context.glb'}
    if set(source_files) != required:
        errors.append('Inventory does not cover all seven public source GLBs')
    for filename in sorted(required):
        document, binary = read_glb(model_path.parent / filename)
        for node_index, world, ancestors in walk(document):
            node = document['nodes'][node_index]
            if 'mesh' not in node:
                continue
            for primitive_index, primitive in enumerate(document['meshes'][node['mesh']]['primitives']):
                if primitive.get('mode', 4) != 4:
                    continue
                key = source_key(filename, node_index, primitive_index)
                expected.add(key)
                obj = by_key.get(key)
                if obj is None:
                    errors.append('Missing mesh: ' + key)
                    continue
                mesh, attrs = obj.Geometry, obj.Attributes
                row = inventory.get(key, {})
                if str(attrs.Id) != str(component_id(key)) or attrs.GetUserString('component_id') != str(attrs.Id):
                    errors.append('Unstable or inconsistent component ID: ' + key)
                if not mesh.IsValid:
                    errors.append('Invalid Rhino mesh: ' + key)
                positions = accessor(document, binary, primitive['attributes']['POSITION']).astype(np.float64)
                positions = positions @ world[:3, :3].T + world[:3, 3]
                positions = np.c_[positions[:, 0], -positions[:, 2], positions[:, 1]] * 1000
                source_faces = (accessor(document, binary, primitive['indices']).reshape(-1, 3).astype(np.int64)
                                if 'indices' in primitive else np.arange(len(positions)).reshape(-1, 3))
                if np.linalg.det(world[:3, :3]) < 0:
                    source_faces = source_faces[:, ::-1]
                reference = make_mesh(positions, source_faces)
                triangle_count = len(reference.Faces)
                removed = len(source_faces) - triangle_count
                source_triangles += len(source_faces)
                culled_faces += removed
                triangles += triangle_count
                if len(mesh.Vertices) != len(positions) or len(mesh.Faces) != triangle_count:
                    errors.append('Vertex or triangle count mismatch: ' + key)
                else:
                    actual_positions = np.array([(p.X, p.Y, p.Z) for p in mesh.Vertices])
                    vertex_error = float(np.max(np.abs(actual_positions - positions)))
                    max_vertex_error_mm = max(max_vertex_error_mm, vertex_error)
                    if vertex_error > 0.02:
                        errors.append('Vertex positions changed beyond mm round-off: ' + key)
                actual_faces = np.array(list(mesh.Faces), dtype=np.int64)[:, :3].copy()
                reference_faces = np.array(list(reference.Faces), dtype=np.int64)[:, :3]
                if not np.array_equal(actual_faces, reference_faces):
                    errors.append('Retained triangle sequence differs from repaired source: ' + key)
                # Independent topology check: every exported triangle must exist
                # in the source, with its winding unchanged. Compare surface area
                # on the SAME source vertices so round-off cannot hide lost faces.
                row_type = np.dtype((np.void, source_faces.dtype.itemsize * 3))
                original_keys = np.ascontiguousarray(source_faces).view(row_type).ravel()
                exported_keys = actual_faces.view(row_type).ravel()
                if not np.isin(exported_keys, original_keys).all():
                    errors.append('Invented or rewound triangle: ' + key)
                original_area = surface_area_m2(positions, source_faces)
                exported_area = surface_area_m2(positions, actual_faces)
                source_area += original_area
                retained_area += exported_area
                if abs(original_area - exported_area) > 1e-4:
                    errors.append('Degenerate-face cleanup changed visible surface area: ' + key)
                if (attrs.GetUserString('source_triangles') != str(len(source_faces)) or
                        attrs.GetUserString('culled_degenerate_faces') != str(removed)):
                    errors.append('Degenerate-face repair audit differs from source: ' + key)
                bounds = mesh.GetBoundingBox()
                actual_bounds = np.array([[bounds.Min.X, bounds.Min.Y, bounds.Min.Z],
                                          [bounds.Max.X, bounds.Max.Y, bounds.Max.Z]])
                source_bounds = np.array([positions.min(0), positions.max(0)])
                bbox_error = float(np.max(np.abs(actual_bounds - source_bounds)))
                max_bbox_error_mm = max(max_bbox_error_mm, bbox_error)
                if bbox_error > 0.02:
                    errors.append('Axis, scale or bounds mismatch: ' + key)
                if 'NORMAL' in primitive['attributes']:
                    if len(mesh.Normals) != len(positions):
                        errors.append('Missing normals: ' + key)
                    else:
                        source_normals = accessor(document, binary, primitive['attributes']['NORMAL']).astype(np.float64)
                        source_normals = source_normals @ np.linalg.inv(world[:3, :3])
                        source_normals /= np.maximum(np.linalg.norm(source_normals, axis=1, keepdims=True), 1e-12)
                        source_normals = np.c_[source_normals[:, 0], -source_normals[:, 2], source_normals[:, 1]]
                        actual_normals = np.array([(p.X, p.Y, p.Z) for p in mesh.Normals])
                        normal_error = float(np.max(np.abs(actual_normals - source_normals)))
                        max_normal_error = max(max_normal_error, normal_error)
                        if normal_error > 1e-6:
                            errors.append('Normal values changed: ' + key)
                uv_count = 0
                if 'TEXCOORD_0' in primitive['attributes']:
                    uv_objects += 1
                    uv = accessor(document, binary, primitive['attributes']['TEXCOORD_0'])
                    uv_count = len(uv)
                    uv_vertices += uv_count
                    if len(mesh.TextureCoordinates) != uv_count:
                        errors.append('UV count mismatch: ' + key)
                    else:
                        actual_uv = np.array([(p.X, p.Y) for p in mesh.TextureCoordinates])
                        error = float(np.max(np.abs(actual_uv - uv))) if uv_count else 0.0
                        max_uv_error = max(max_uv_error, error)
                        if error > 1e-6:
                            errors.append('UV values changed: ' + key)
                elif len(mesh.TextureCoordinates):
                    if attrs.GetUserString('uv_source') != 'world_projection_m':
                        errors.append('Unexplained generated UV coordinates: '+key)
                    else:
                        native_normals=np.array([(n.X,n.Y,n.Z) for n in mesh.Normals])
                        if not len(native_normals): native_normals=np.tile([0,0,1],(len(positions),1))
                        expected_uv=world_uv(actual_positions,native_normals).astype(np.float32)
                        generated_uv=np.array([(p.X,p.Y) for p in mesh.TextureCoordinates])
                        generated_uv_objects+=1;generated_uv_vertices+=len(generated_uv)
                        error=float(np.max(abs(generated_uv-expected_uv))) if generated_uv.shape==expected_uv.shape else float('inf')
                        max_generated_uv_error=max(max_generated_uv_error,error)
                        if generated_uv.shape!=expected_uv.shape or not np.allclose(generated_uv,expected_uv,rtol=0,atol=1e-6):
                            errors.append('Generated world UV values differ from public mapping: '+key)
                layer = doc.Layers.FindIndex(attrs.LayerIndex)
                if layer is None or layer.GetUserString('material') != attrs.GetUserString('finish'):
                    errors.append('Layer material and finish disagree: ' + key)
                expected_row = {'component_id': str(attrs.Id), 'vertices': str(len(positions)),
                                'triangles': str(triangle_count), 'uv_count': str(uv_count),
                                'source_triangles': str(len(source_faces)), 'culled_degenerate_faces': str(removed),
                                'finish': attrs.GetUserString('finish'), 'name': attrs.Name,
                                'source_file': filename, 'layer_path': layer.FullPath}
                metadata = node.get('extras') or {}
                name_parts = node.get('name', f'node{node_index}').split('|')
                default_group = (name_parts[0] if len(name_parts) > 1 else
                                 (ancestors[-1] if ancestors else Path(filename).stem))
                expected_row.update({field: str(metadata.get(field, ''))
                                     for field in ('part', 'role', 'confidence')})
                expected_row['group'] = str(metadata.get('group', default_group))
                if filename == 'vmu01_canopy.glb' and 'group' not in metadata:
                    expected_row['group'] = 'VMU01'
                if any(row.get(field) != value for field, value in expected_row.items()):
                    errors.append('Inventory values disagree with model: ' + key)
                try:
                    inventory_bounds = np.array([[float(row['min_' + axis + '_mm']) for axis in 'xyz'],
                                                 [float(row['max_' + axis + '_mm']) for axis in 'xyz']])
                    if not np.isfinite(inventory_bounds).all() or not np.allclose(
                            inventory_bounds, source_bounds, rtol=0, atol=1e-6):
                        errors.append('Inventory bounding box differs from source: ' + key)
                except (KeyError, ValueError):
                    errors.append('Inventory bounding box is missing or nonnumeric: ' + key)
    if expected != set(by_key):
        errors.append('Rhino mesh set does not match GLB primitives exactly')
    report = {'model': model_path.name, 'inventory': inventory_path.name, 'passed': not errors,
              'mesh_objects': len(meshes), 'inventory_rows': len(rows), 'triangles': triangles,
              'source_triangles': source_triangles, 'culled_degenerate_faces': culled_faces,
              'source_area_m2': source_area, 'retained_area_m2': retained_area,
              'removed_surface_area_m2': source_area - retained_area,
              'source_files': source_files, 'uv_objects': uv_objects, 'uv_vertices': uv_vertices,
              'generated_uv_objects':generated_uv_objects,'generated_uv_vertices':generated_uv_vertices,
              'max_generated_uv_error':max_generated_uv_error,
              'max_uv_error': max_uv_error, 'max_bbox_error_mm': max_bbox_error_mm,
              'max_vertex_error_mm': max_vertex_error_mm, 'max_normal_error': max_normal_error,
              'errors': errors}
    return report


if __name__ == '__main__':
    default_model = Path(__file__).resolve().parent.parent / 'model' / 'vmu_site_future.3dm'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=default_model)
    parser.add_argument('--inventory', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    inventory = args.inventory or args.model.with_name(args.model.stem + '_inventory.csv')
    result = verify(args.model, inventory)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
