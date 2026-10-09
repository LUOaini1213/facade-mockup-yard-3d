#! python3
"""Run with Rhino 8 ScriptEditor on the open exported model; never edits geometry."""
import json
import os
from pathlib import Path
import uuid

import Rhino
import scriptcontext as sc


def main():
    doc = sc.doc
    errors, rows, keys, ids = [], [], set(), set()
    uv_objects, triangles, culled_faces = 0, 0, 0
    for obj in doc.Objects:
        mesh = obj.Geometry
        if not isinstance(mesh, Rhino.Geometry.Mesh):
            continue
        attrs = obj.Attributes
        key = attrs.GetUserString('source_key')
        object_id = str(obj.Id)
        if not mesh.IsValid:
            errors.append('Invalid mesh: ' + object_id)
        if not key or key in keys or object_id in ids:
            errors.append('Missing or duplicate component identity: ' + object_id)
        keys.add(key)
        ids.add(object_id)
        if attrs.GetUserString('component_id') != object_id:
            errors.append('Object ID and component_id differ: ' + object_id)
        expected_id = uuid.uuid5(uuid.UUID('247a3cf6-23b2-5ae4-b994-4255c63fe8c9'), key or '')
        if str(expected_id) != object_id:
            errors.append('Object ID is not derived from its source key: ' + object_id)
        uv_count = mesh.TextureCoordinates.Count
        if attrs.GetUserString('has_uv') == 'true':
            uv_objects += 1
            if uv_count != mesh.Vertices.Count:
                errors.append('Missing texture coordinates: ' + object_id)
        elif uv_count and attrs.GetUserString('uv_source')!='world_projection_m':
            errors.append('Unexpected texture coordinates: ' + object_id)
        layer = doc.Layers[attrs.LayerIndex]
        if layer.GetUserString('material') != attrs.GetUserString('finish'):
            errors.append('Layer and component finishes differ: ' + object_id)
        triangles += mesh.Faces.TriangleCount + 2 * mesh.Faces.QuadCount
        culled_faces += int(attrs.GetUserString('culled_degenerate_faces') or 0)
        rows.append({'component_id': object_id, 'source_key': key,
                     'vertices': mesh.Vertices.Count, 'triangles': mesh.Faces.TriangleCount,
                     'uv_count': uv_count, 'finish': attrs.GetUserString('finish')})
    if doc.ModelUnitSystem != Rhino.UnitSystem.Millimeters:
        errors.append('Expected millimetre model units')
    expected_uv = doc.Strings.GetValue('MOCKUP.uv_objects')
    if not expected_uv or int(expected_uv) != uv_objects:
        errors.append('UV object count disagrees with document metadata')
    if int(doc.Strings.GetValue('MOCKUP.culled_degenerate_faces') or -1) != culled_faces:
        errors.append('Degenerate-face repair count disagrees with document metadata')
    if not rows:
        errors.append('No exported mesh components in active document')
    sources = json.loads(doc.Strings.GetValue('MOCKUP.files') or '{}')
    if len(rows) != sum(item['objects'] for item in sources.values()):
        errors.append('Component count differs from source export metadata')
    if triangles != sum(item['triangles'] for item in sources.values()):
        errors.append('Triangle count differs from source export metadata')
    result = {'model': Path(doc.Path).name, 'rhino_version': str(Rhino.RhinoApp.Version),
              'passed': not errors, 'mesh_objects': len(rows), 'triangles': triangles,
              'uv_objects': uv_objects, 'culled_degenerate_faces': culled_faces,
              'errors': errors, 'components': rows}
    target = os.environ.get('MOCKUP_RHINO_QA_REPORT')
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Rhino native QA: {} meshes, {} triangles, {} UV objects, {} errors'.format(
        len(rows), triangles, uv_objects, len(errors)))
    for error in errors:
        print(error)
    return result


if __name__ == '__main__':
    main()
