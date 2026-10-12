#! python3
"""Native saved-RDK, embedded-image and camera verification; no legacy simulation."""
import hashlib,json,os,sys,traceback
from pathlib import Path
import xml.etree.ElementTree as ET
import Rhino

SLOTS={'base_color':'pbr-base-color','normal':'pbr-bump','roughness':'pbr-roughness',
       'metallic':'pbr-metallic','ao':'pbr-ambient-occlusion'}


def scrub_environment(doc):
    for environment in list(doc.RenderEnvironments):
        if not doc.RenderEnvironments.Remove(environment):
            raise RuntimeError('Cannot remove local Studio environment')
    doc.RenderSettings.BackgroundStyle=Rhino.Display.BackgroundStyle.SolidColor


def verify(root,source,output):
    sys.path.insert(0,str(root/'build'))
    from material_integrity import verify_native_scalars
    assets=json.loads((root/'model'/'rhino_assets.json').read_text(encoding='utf-8'))
    cameras=json.loads((root/'model'/'rhino_views.json').read_text(encoding='utf-8'))
    quality=json.loads((root/'model'/'vmu_site_future_geometry.json').read_text(encoding='utf-8'))
    model=Rhino.FileIO.File3dm.Read(str(output))
    if model is None: raise RuntimeError('Cannot independently read saved native model')
    embedded={Path(item.Filename).name:item for item in model.EmbeddedFiles}
    scratch=root/'build'/'_scratch'/'embedded_check';scratch.mkdir(parents=True,exist_ok=True)
    embedded_verified=[]
    for relative,spec in assets['files'].items():
        name=Path(relative).name
        if name not in embedded: raise RuntimeError('Missing embedded asset: '+name)
        path=scratch/name
        if not embedded[name].SaveToFile(str(path)): raise RuntimeError('Cannot extract embedded asset: '+name)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=spec['sha256']:
            raise RuntimeError('Embedded texture hash mismatch: '+name)
        embedded_verified.append(name)
    contents={item.Name:item for item in model.RenderMaterials}
    checks=[];scalar_checks=[]
    for name,spec in assets['materials'].items():
        material=contents.get(name+' | Native PBR')
        if material is None:raise RuntimeError('Missing saved PBR material: '+name)
        xml=ET.fromstring(material.XML(True))
        scalar_errors=verify_native_scalars(xml,spec)
        if scalar_errors:raise RuntimeError(name+': '+'; '.join(scalar_errors))
        scalar_checks.append({'material':name,'readback':'saved_RDK_XML'})
        children={t.get('child-slot-name'):t for t in xml.findall('texture')}
        for slot,asset in spec['slots'].items():
            child=children.get(SLOTS[slot])
            if child is None:raise RuntimeError('Missing saved RDK slot: '+name+'/'+slot)
            values={p.get('name'):p.text for p in child.findall('parameters-v8/parameter')}
            if Path(values.get('filename','')).name!=Path(asset['file']).name:
                raise RuntimeError('Saved texture filename changed: '+name+'/'+slot)
            linear=values.get('treat-as-linear')=='true'
            if linear!=asset['linear']:raise RuntimeError('Saved RDK colour space changed: '+name+'/'+slot)
            repeat=1/float(spec['size_m'])
            actual=[float(v) for v in values.get('rdk-texture-repeat','').split(',')]
            if len(actual)!=3 or max(abs(a-b) for a,b in zip(actual,[repeat,repeat,1]))>1e-9:
                raise RuntimeError('Saved RDK physical repeat changed: '+name+'/'+slot)
            if values.get('rdk-texture-mapping-channel')!='1':
                raise RuntimeError('Saved mapping channel changed: '+name+'/'+slot)
            # Enabled state belongs to the parent slot, independent of bitmap data.
            parent={p.get('name'):p.text for p in xml.findall('parameters-v8/parameter')}
            if parent.get(SLOTS[slot]+'-on')!='true':raise RuntimeError('Saved RDK slot is disabled: '+name+'/'+slot)
            checks.append({'material':name,'slot':slot,'linear':linear,'repeat_per_m':repeat,
                           'mapping_channel':1,'readback':'saved_RDK_XML'})
    views={v.Name.split(' | ')[0]:v for v in model.NamedViews}
    if len(views)!=13:raise RuntimeError('Expected thirteen saved named views')
    saved=[];images=[]
    for index,camera in enumerate(cameras['views']):
        view=views[camera['key']];p=camera['position'];target=camera['target']
        expected=[p[0]*1000,-p[2]*1000,p[1]*1000]
        actual=view.Viewport.CameraLocation
        if max(abs(a-b) for a,b in zip([actual.X,actual.Y,actual.Z],expected))>1e-6:
            raise RuntimeError('Saved camera position changed: '+camera['key'])
        saved.append({'key':camera['key'],'name':view.Name,'position_mm':expected,
                      'target_mm':[target[0]*1000,-target[2]*1000,target[1]*1000]})
        relative=f'renders/rhino/{index+1:02d}_{camera["key"]}.png'
        if not (root/relative).is_file():raise RuntimeError('Missing native image: '+relative)
        images.append(relative)
    model.Dispose()
    return {'passed':True,'model':output.name,'source_model':source.name,
        'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'rhino_version':str(Rhino.RhinoApp.Version),'errors':[],
        'generated_uv_objects':quality['generated_uv_objects'],
        'geometry_quality':{k:v for k,v in quality.items() if k!='components'},
        'textured_materials':sum(bool(m['slots']) for m in assets['materials'].values()),
        'embedded_assets':embedded_verified,'named_views':saved,'images':images,
        'display_mode_id':str(Rhino.Display.DisplayModeDescription.RenderedId),
        'material_slots':checks,'material_scalars':scalar_checks,'output_bytes':output.stat().st_size,
        'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest()}


def main():
    root=Path(os.environ['MOCKUP_RHINO_ROOT']);source=Path(os.environ['MOCKUP_RHINO_QA_MODEL'])
    output=source.with_name('vmu_site_future_native.3dm')
    report=Path(os.environ['MOCKUP_RHINO_QA_REPORT'])
    try:
        result=verify(root,source,output)
    except Exception:result={'passed':False,'errors':[traceback.format_exc()]}
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (root/'model'/'vmu_site_future_delivery_progress.json').write_text(
        json.dumps({'stage':'complete' if result['passed'] else 'failed','report':report.name})+'\n',encoding='utf-8')


if __name__=='__main__':main()
