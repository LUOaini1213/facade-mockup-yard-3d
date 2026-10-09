"""Independently verify public texture assets, native geometry metrics, views and PNGs."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw
import rhino3dm as r
from material_integrity import verify_native_scalars
from mesh_integrity import verify_record
from prepare_rhino_assets import load_json, verify_derived

ROOT=Path(__file__).resolve().parent.parent


def verify_geometry(doc, quality, csv_rows):
    """Bind every JSON/CSV row to a source mesh and recompute its topology."""
    errors, rows, actuals = [], {}, {}
    components = quality.get('components')
    if not isinstance(components, list):
        return ['Geometry components must be a list'], {}, {}, 0., 0.
    for item in components:
        if not isinstance(item, dict) or not isinstance(item.get('component_id'), str):
            errors.append('Invalid geometry component identity'); continue
        key = item['component_id']
        if key in rows:
            errors.append('Duplicate geometry component: '+key)
        rows[key] = item
    meshes = [o for o in doc.Objects if isinstance(o.Geometry, r.Mesh)]
    identities = [str(o.Attributes.Id) for o in meshes]
    if len(set(identities)) != len(identities) or set(rows) != set(identities):
        errors.append('Geometry inventory differs from native meshes')
    area_error, volume_error = 0., 0.
    for obj in meshes:
        key = str(obj.Attributes.Id)
        if key not in rows:
            continue
        record = rows[key]
        for field, value in [('name', obj.Attributes.Name),
                             ('source_key', obj.Attributes.GetUserString('source_key')),
                             ('group', obj.Attributes.GetUserString('group')),
                             ('finish', obj.Attributes.GetUserString('finish'))]:
            if record.get(field) != value:
                errors.append('Actual mesh identity mismatch: '+key+'/'+field)
        try:
            actual, issues = verify_record(obj.Geometry, record)
            actuals[key] = actual
            errors.extend(key+': '+message for message in issues)
            if obj.Geometry.IsValid != record.get('is_valid'):
                errors.append(key+': Native archive validity mismatch')
            for field in ('area_m2', 'volume_m3'):
                value = record.get(field)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and actual[field] is not None:
                    difference = abs(actual[field]-value)
                    if field == 'area_m2': area_error = max(area_error, difference)
                    else: volume_error = max(volume_error, difference)
        except (ValueError, TypeError, IndexError) as exception:
            errors.append(key+': Cannot independently evaluate mesh: '+str(exception))
    expected = {'mesh_components': len(meshes),
                'closed': sum(v['is_closed'] for v in actuals.values()),
                'open': sum(not v['is_closed'] for v in actuals.values()),
                'solid': sum(v['is_solid'] for v in actuals.values()),
                'invalid': sum(not v['is_valid'] for v in actuals.values()),
                'volume_available': sum(v['is_solid'] for v in actuals.values()),
                'generated_uv_objects': sum(o.Attributes.GetUserString('uv_source') == 'world_projection_m' for o in meshes)}
    for key, value in expected.items():
        if type(quality.get(key)) is not int or quality[key] != value:
            errors.append('Actual geometry summary mismatch: '+key)
    csv_ids = [item.get('component_id') for item in csv_rows]
    if len(csv_ids) != len(set(csv_ids)):
        errors.append('Duplicate CSV component identity')
    if len(csv_ids) != len(rows) or set(csv_ids) != set(rows):
        errors.append('CSV component inventory is incomplete or unexpected')
    for item in csv_rows:
        record = rows.get(item.get('component_id'))
        if record is None:
            continue
        if set(item) != set(record):
            errors.append('CSV/JSON fields differ: '+item['component_id'])
        for key, value in record.items():
            if item.get(key) != ('' if value is None else str(value)):
                errors.append('CSV/JSON disagreement: '+item['component_id']+'/'+key)
    return errors, rows, actuals, area_error, volume_error


def check(write_reports=True):
    errors=[]
    assets=load_json(ROOT/'model'/'rhino_assets.json')
    errors.extend(verify_derived(ROOT, assets))
    for relative,spec in assets['files'].items():
        data=(ROOT/'model'/relative).read_bytes()
        if hashlib.sha256(data).hexdigest()!=spec['sha256']:
            errors.append('Asset hash mismatch: '+relative)
        with Image.open(ROOT/'model'/relative) as image:
            if list(image.size)!=spec['dimensions']:
                errors.append('Asset dimensions mismatch: '+relative)
    native=json.loads((ROOT/'model'/'vmu_site_future_rhino_delivery.json').read_text(encoding='utf-8'))
    if not native.get('passed'): errors.append('Native delivery did not pass')
    native_path=ROOT/'model'/'vmu_site_future_native.3dm'
    if native.get('output_sha256')!=hashlib.sha256(native_path.read_bytes()).hexdigest():
        errors.append('Native delivery report does not describe the current 3dm')
    if native.get('source_sha256')!=hashlib.sha256((ROOT/'model'/'vmu_site_future.3dm').read_bytes()).hexdigest():
        errors.append('Source geometry baseline differs from the native build input')
    expected_slots={(name,slot) for name,spec in assets['materials'].items() for slot in spec['slots']}
    actual_slots={(item['material'],item['slot']) for item in native.get('material_slots',[])}
    if expected_slots!=actual_slots: errors.append('Native PBR slot readback is incomplete')
    if set(assets['materials'])!={item['material'] for item in native.get('material_scalars',[])}:
        errors.append('Native PBR scalar readback is incomplete')
    if {Path(p).name for p in assets['files']}!=set(native.get('embedded_assets',[])):
        errors.append('Native embedded-asset readback is incomplete')
    quality=load_json(ROOT/'model'/'vmu_site_future_geometry.json')
    doc=r.File3dm.Read(str(native_path))
    slot_names={'base_color':'pbr-base-color','normal':'pbr-bump','roughness':'pbr-roughness',
                'metallic':'pbr-metallic','ao':'pbr-ambient-occlusion'}
    contents={item.Name:item for item in doc.RenderContent if item.Kind=='material'}
    content_ids={str(item.Id):item.Name for item in contents.values()}
    checked_slots=0
    for name,spec in assets['materials'].items():
        content=contents.get(name+' | Native PBR')
        if content is None:
            errors.append('Missing native object material: '+name);continue
        xml=ET.fromstring(content.XML(True))
        errors.extend(name+': '+message for message in verify_native_scalars(xml,spec))
        parent={p.get('name'):p.text for p in xml.findall('parameters-v8/parameter')}
        children={t.get('child-slot-name'):t for t in xml.findall('texture')}
        for slot,asset in spec['slots'].items():
            child=children.get(slot_names[slot])
            if child is None:
                errors.append('Missing saved RDK texture: '+name+'/'+slot);continue
            values={p.get('name'):p.text for p in child.findall('parameters-v8/parameter')}
            expected_repeat=[1/spec['size_m'],1/spec['size_m'],1]
            observed=[float(v) for v in values.get('rdk-texture-repeat','').split(',')]
            if len(observed)!=3 or not np.allclose(observed,expected_repeat,rtol=0,atol=1e-9):
                errors.append('Saved PBR physical scale mismatch: '+name+'/'+slot)
            if (values.get('treat-as-linear')=='true')!=asset['linear']:
                errors.append('Saved PBR colour space mismatch: '+name+'/'+slot)
            if values.get('rdk-texture-mapping-channel')!='1':
                errors.append('Saved PBR mapping channel mismatch: '+name+'/'+slot)
            if Path(values.get('filename','')).name!=Path(asset['file']).name or parent.get(slot_names[slot]+'-on')!='true':
                errors.append('Saved PBR file/enable mismatch: '+name+'/'+slot)
            checked_slots+=1
    meshes=[o for o in doc.Objects if isinstance(o.Geometry,r.Mesh)]
    with (ROOT/'model'/'vmu_site_future_geometry.csv').open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        if len(reader.fieldnames or [])!=len(set(reader.fieldnames or [])):
            errors.append('Duplicate CSV header')
        csv_rows=list(reader)
    issues,rows,actuals,area_error,volume_error=verify_geometry(doc,quality,csv_rows)
    errors.extend(issues)
    for obj in meshes:
        row=rows.get(str(obj.Attributes.Id))
        if row is None:continue
        material=doc.Materials.FindIndex(obj.Attributes.MaterialIndex)
        actual_name=content_ids.get(str(material.RenderMaterialInstanceId)) if material else None
        if actual_name!=row['finish']+' | Native PBR':
            errors.append('Object PBR assignment mismatch: '+row['source_key'])
    manifest=json.loads((ROOT/'model'/'rhino_views.json').read_text(encoding='utf-8'))
    views={view.Name.split(' | ')[0]:view for view in doc.NamedViews}
    if len(views)!=13: errors.append('Expected thirteen named views')
    camera_error=0.
    for camera in manifest['views']:
        if camera['key'] not in views:
            errors.append('Missing camera: '+camera['key']);continue
        viewport=views[camera['key']].Viewport
        p=camera['position'];expected=np.array([p[0],-p[2],p[1]])*1000
        loc=viewport.CameraLocation;actual=np.array([loc.X,loc.Y,loc.Z])
        error=float(abs(actual-expected).max());camera_error=max(camera_error,error)
        if error>1e-6:errors.append('Camera position changed: '+camera['key'])
        p=camera['target'];expected=np.array([p[0],-p[2],p[1]])*1000
        direction=expected-actual;direction/=np.linalg.norm(direction)
        observed=viewport.CameraDirection
        observed=np.array([observed.X,observed.Y,observed.Z],dtype=float)
        observed/=np.linalg.norm(observed)
        if not np.allclose(observed,direction,rtol=0,atol=1e-7):
            errors.append('Camera direction changed: '+camera['key'])
        frustum=viewport.GetFrustum()
        half_y=manifest['near_m']*1000*math.tan(math.radians(manifest['fov_y_degrees']/2))
        half_x=half_y*manifest['width']/manifest['height']
        expected_frustum={'left':-half_x,'right':half_x,'bottom':-half_y,'top':half_y,
                          'near':manifest['near_m']*1000,'far':manifest['far_m']*1000}
        if not all(abs(frustum[k]-v)<1e-6 for k,v in expected_frustum.items()):
            errors.append('Camera field of view/clipping changed: '+camera['key'])
    opening=doc.Views[0].Viewport.CameraLocation
    overview=manifest['views'][0]['position']
    if not np.allclose([opening.X,opening.Y,opening.Z],
                       np.array([overview[0],-overview[2],overview[1]])*1000,rtol=0,atol=1e-6):
        errors.append('Native model does not open at the overview camera')
    image_checks=[]
    contact=Image.new('RGB',(1200,4*220),(242,243,245));draw=ImageDraw.Draw(contact)
    for index,relative in enumerate(native.get('images',[])):
        with Image.open(ROOT/relative) as opened:
            image=opened.convert('RGB')
        pixels=np.asarray(image)
        deviation=float(pixels.std())
        if image.size!=(manifest['width'],manifest['height']) or deviation<5:
            errors.append('Blank or incorrectly sized native image: '+relative)
        image_checks.append({'file':relative,'dimensions':list(image.size),'pixel_std':deviation})
        thumb=image.copy();thumb.thumbnail((290,185))
        x=(index%4)*300;y=(index//4)*220
        contact.paste(thumb,(x,y+23));draw.text((x+4,y+3),Path(relative).stem,fill=(20,20,20))
    if len(image_checks)!=13:errors.append('Expected thirteen native PNGs')
    if write_reports:
        contact.save(ROOT/'renders'/'rhino'/'contact_sheet.jpg',quality=90)
    report={'passed':not errors,'errors':errors,'components':len(meshes),'asset_files':len(assets['files']),
            'named_views':len(views),'images':image_checks,'max_camera_error_mm':camera_error,
            'pbr_slots':checked_slots,'pbr_scalar_materials':len(assets['materials']),
            'max_area_error_m2':area_error,'max_volume_error_m3':volume_error,
            'source':'independent rhino3dm, NumPy and Pillow readback'}
    if write_reports:
        (ROOT/'model'/'vmu_site_future_delivery_qa.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-write-reports',action='store_true')
    args=parser.parse_args()
    raise SystemExit(0 if check(write_reports=not args.no_write_reports)['passed'] else 1)
