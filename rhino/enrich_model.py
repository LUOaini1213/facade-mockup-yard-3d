#! python3
"""Create the public model's complete native Rhino delivery, retaining mesh identities."""
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import traceback
from datetime import datetime, timezone

# Record entry before loading Rhino/Python.NET, which can initialise slowly.
ROOT = Path(os.environ['MOCKUP_RHINO_ROOT'])
PROGRESS = ROOT/'model'/'vmu_site_future_delivery_progress.json'
def progress(stage, **details):
    PROGRESS.write_text(json.dumps({'stage':stage,'utc':datetime.now(timezone.utc).isoformat(),**details},indent=2)+'\n',encoding='utf-8')
progress('python_started')

import Rhino
import scriptcontext as sc
import System.Drawing as SD
sys.path.insert(0,str(Path(__file__).resolve().parent))
from qa_delivery import verify as verify_delivery,scrub_environment

MODEL = Path(os.environ['MOCKUP_RHINO_QA_MODEL'])
OUTPUT = MODEL.with_name('vmu_site_future_native.3dm')
REPORT = Path(os.environ['MOCKUP_RHINO_QA_REPORT'])
G, D, R = Rhino.Geometry, Rhino.DocObjects, Rhino.Render
KINDS = {'base_color':D.TextureType.PBR_BaseColor,'normal':D.TextureType.Bump,
         'roughness':D.TextureType.PBR_Roughness,'metallic':D.TextureType.PBR_Metallic,
         'ao':D.TextureType.PBR_AmbientOcclusion}
SLOTS = {'base_color':'pbr-base-color','normal':'pbr-bump','roughness':'pbr-roughness',
         'metallic':'pbr-metallic','ao':'pbr-ambient-occlusion'}


def point(values):
    return G.Point3d(values[0]*1000, -values[2]*1000, values[1]*1000)


def vector(values):
    return G.Vector3d(values[0], -values[2], values[1])


def generate_world_uv(mesh):
    # Same dominant-normal world projection as viewer.js:addWorldUV. UVs are metres.
    for index in range(mesh.Vertices.Count):
        q = mesh.Vertices[index]
        x, y, z = q.X/1000, q.Z/1000, -q.Y/1000
        n = mesh.Normals[index] if mesh.Normals.Count else G.Vector3f(0,0,1)
        nx, ny, nz = n.X, n.Z, -n.Y
        ax, ay, az = abs(nx), abs(ny), abs(nz)
        if ay >= ax and ay >= az:
            u,v = x,-z
        elif ax >= az:
            u,v = z*(1 if nx >= 0 else -1),y
        else:
            u,v = -x*(1 if nz >= 0 else -1),y
        mesh.TextureCoordinates.Add(float(u),float(v))


def bind_material(doc, source, model_dir):
    material = D.Material()
    material.Name = source['name']
    material.ToPhysicallyBased()
    pbr = material.PhysicallyBased
    hex_color = source.get('hex') or '#AAAAAA'
    base_color = SD.ColorTranslator.FromHtml(hex_color)
    if source.get('base_color_is_baked'):
        base_color = SD.Color.White
    material.DiffuseColor = base_color
    material.SetUserString('canonical_finish',source['name'])
    material.SetUserString('physical_texture_size_m',str(source['size_m']))
    pbr.BaseColor = Rhino.Display.Color4f(base_color)
    pbr.Metallic = source['metallic']
    pbr.Roughness = source['roughness']
    pbr.Clearcoat = source.get('clearcoat',0)
    pbr.ClearcoatRoughness = source.get('clearcoat_roughness',.3)
    glass = source.get('glass')
    if glass and not glass.get('opaque'):
        pbr.Opacity = 1-float(glass.get('vlt',.4))*.85
        pbr.OpacityIOR = float(glass.get('ior',1.52))
    for slot, asset in source['slots'].items():
        texture = D.Texture()
        texture.FileName = str(model_dir / asset['file'])
        texture.Enabled = True
        if texture.MappingChannelId != 1:
            raise RuntimeError('Expected default mesh mapping channel 1')
        texture.ProjectionMode = D.TextureProjectionModes.MappingChannel
        texture.TreatAsLinear = asset['linear']
        texture.WrapU = texture.WrapV = D.TextureUvwWrapping.Repeat
        # ApplyUvwTransform and MappingChannelId are read-only in RhinoCommon 8.
        # Setting UvwTransform activates the texture's UV transform.
        repeat = 1/float(source['size_m'])
        texture.UvwTransform = G.Transform.Scale(G.Plane.WorldXY,repeat,repeat,1.0)
        if repeat != 1 and not texture.ApplyUvwTransform:
            raise RuntimeError('Texture physical repeat is not active: '+source['name']+'/'+slot)
        if not pbr.SetTexture(texture,KINDS[slot]):
            raise RuntimeError('Could not bind '+source['name']+'/'+slot)
    render_material = R.RenderMaterial.FromMaterial(material,doc)
    render_material.Name = source['name']+' | Native PBR'
    # FromMaterial in Rhino 8 resets bitmap repeat and linear flags. Set the RDK
    # children explicitly, then verify the saved render assets below.
    context=R.RenderContent.ChangeContexts.Program
    for slot,asset in source['slots'].items():
        child=render_material.FindChild(SLOTS[slot])
        if child is None: raise RuntimeError('Missing live RDK child: '+source['name']+'/'+slot)
        repeat=1/float(source['size_m'])
        child.SetRepeat(G.Vector3d(repeat,repeat,1),context)
        child.SetMappingChannel(1,context)
        child.SetParameter('treat-as-linear',asset['linear'],context)
    doc.RenderMaterials.Add(render_material)
    return render_material


def geometry_record(obj):
    mesh, attrs = obj.Geometry,obj.Attributes
    manifold = mesh.IsManifold()
    solid = mesh.IsSolid
    edges = mesh.GetNakedEdges() or []
    area = G.AreaMassProperties.Compute(mesh)
    volume = G.VolumeMassProperties.Compute(mesh) if solid else None
    if solid and volume is not None:
        reason = 'solid mesh; geometric volume, not a fabrication take-off'
    elif not mesh.IsClosed:
        reason = 'open mesh; volume omitted'
    elif not manifold:
        reason = 'non-manifold mesh; volume omitted'
    elif not mesh.IsOriented:
        reason = 'inconsistent face orientation; volume omitted'
    else:
        reason = 'volume integration failed; volume omitted'
    row = {'component_id':str(obj.Id),'source_key':attrs.GetUserString('source_key'),
           'name':attrs.Name,'group':attrs.GetUserString('group'),'finish':attrs.GetUserString('finish'),
           'is_valid':mesh.IsValid,'is_closed':mesh.IsClosed,'is_manifold':manifold,
           'is_oriented':mesh.IsOriented,'is_solid':solid,'disjoint_pieces':mesh.DisjointMeshCount,
           'naked_edge_polylines':len(edges),'naked_edge_length_m':sum(e.Length for e in edges)/1000,
           'area_m2':area.Area/1e6 if area else None,'volume_m3':abs(volume.Volume)/1e9 if volume else None,
           'volume_reason':reason,'uv_count':mesh.TextureCoordinates.Count,
           'uv_source':attrs.GetUserString('uv_source')}
    if area: area.Dispose()
    if volume: volume.Dispose()
    return row


def main():
    result = {'passed':False,'model':OUTPUT.name,'source_model':MODEL.name,
              'source_sha256':hashlib.sha256(MODEL.read_bytes()).hexdigest(),
              'rhino_version':str(Rhino.RhinoApp.Version),'errors':[]}
    try:
        progress('opening_source')
        if not Rhino.RhinoDoc.OpenFile(str(MODEL)):
            raise RuntimeError('Cannot open model')
        doc = Rhino.RhinoDoc.ActiveDoc
        sc.doc = doc
        assets = json.loads((ROOT/'model'/'rhino_assets.json').read_text(encoding='utf-8'))
        cameras = json.loads((ROOT/'model'/'rhino_views.json').read_text(encoding='utf-8'))
        materials = {name:bind_material(doc,material,MODEL.parent)
                     for name,material in assets['materials'].items()}
        progress('materials_bound',materials=len(materials))
        generated = 0
        for obj in list(doc.Objects):
            if not isinstance(obj.Geometry,G.Mesh):
                continue
            attrs = obj.Attributes.Duplicate()
            mesh = obj.Geometry
            if mesh.TextureCoordinates.Count == 0:
                duplicate = mesh.DuplicateMesh()
                generate_world_uv(duplicate)
                if not doc.Objects.Replace(obj.Id,duplicate):
                    raise RuntimeError('Cannot replace world-mapped mesh')
                attrs.SetUserString('uv_source','world_projection_m')
                generated += 1
            elif not attrs.GetUserString('uv_source'):
                attrs.SetUserString('uv_source','source')
            finish = attrs.GetUserString('finish')
            attrs.MaterialSource = D.ObjectMaterialSource.MaterialFromObject
            if not doc.Objects.ModifyAttributes(obj.Id,attrs,True):
                raise RuntimeError('Cannot update component attributes')
            updated = doc.Objects.FindId(obj.Id)
            updated.RenderMaterial = materials[finish]
            updated.CommitChanges()
        doc.Strings.SetString('MOCKUP.generated_uv_objects',str(generated))
        progress('world_uv_generated',components=generated)
        # The source-UV count remains 194; generated coordinates are explicitly separate.
        records = [geometry_record(o) for o in doc.Objects if isinstance(o.Geometry,G.Mesh)]
        quality = {'schema_version':1,'mesh_components':len(records),
                   'closed':sum(r['is_closed'] for r in records),'open':sum(not r['is_closed'] for r in records),
                   'solid':sum(r['is_solid'] for r in records),'invalid':sum(not r['is_valid'] for r in records),
                   'volume_available':sum(r['volume_m3'] is not None for r in records),
                   'generated_uv_objects':generated,'components':records,
                   'interpretation':'Mesh primitives may aggregate physical parts. Open surfaces are not automatically errors. Volume is only supplied for solids; no fabrication quantities or inferred engineering semantics.'}
        (MODEL.parent/'vmu_site_future_geometry.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        with (MODEL.parent/'vmu_site_future_geometry.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
        for layer in doc.Layers:
            if layer.Name=='_Info':
                layer.IsVisible=False;layer.CommitChanges()
        view = doc.Views.ActiveView
        view.Maximized=True
        modes = Rhino.Display.DisplayModeDescription
        mode = modes.GetDisplayMode(modes.RenderedId)
        if mode is None: raise RuntimeError('Native Rendered display mode is unavailable')
        view.ActiveViewport.DisplayMode=mode
        image_dir = ROOT/'renders'/'rhino'
        image_dir.mkdir(parents=True,exist_ok=True)
        saved_views,images=[],[]
        for index,camera in enumerate(cameras['views']):
            info = D.ViewInfo(view.ActiveViewport)
            info.Name = camera['key']+' | '+camera['name']
            vp=info.Viewport
            vp.ChangeToPerspectiveProjection(300,True,50)
            location,target=point(camera['position']),point(camera['target'])
            vp.SetCameraLocation(location)
            vp.SetCameraDirection(target-location)
            vp.SetCameraUp(vector(camera['up']))
            vp.TargetPoint=target
            near,far=cameras['near_m']*1000,cameras['far_m']*1000
            half_y=near*math.tan(math.radians(cameras['fov_y_degrees']/2))
            half_x=half_y*cameras['width']/cameras['height']
            if not vp.SetFrustum(-half_x,half_x,-half_y,half_y,near,far):
                raise RuntimeError('Invalid view frustum')
            existing=doc.NamedViews.FindByName(info.Name)
            if existing >= 0: doc.NamedViews.Delete(existing)
            # ViewInfo.Viewport is a detached copy. First apply it, then copy the
            # actual native viewport into the named-view table by viewport ID.
            view.ActiveViewport.SetViewProjection(vp,True)
            saved_index=doc.NamedViews.Add(info.Name,view.ActiveViewport.Id)
            if saved_index < 0: raise RuntimeError('Cannot save named view: '+info.Name)
            if doc.NamedViews[saved_index].Viewport.CameraLocation.DistanceTo(location)>1e-6:
                raise RuntimeError('Saved named-view camera differs: '+info.Name)
            saved_views.append({'key':camera['key'],'name':info.Name,
                                'position_mm':[location.X,location.Y,location.Z],
                                'target_mm':[target.X,target.Y,target.Z]})
            view.ActiveViewport.DisplayMode=mode
            if view.ActiveViewport.DisplayMode.Id != modes.RenderedId:
                raise RuntimeError('Native capture is not using Rendered display mode')
            view.Redraw()
            Rhino.RhinoApp.Wait()
            # Pass explicit local display attributes: ViewCapture can retain an
            # old wireframe pipeline in a freshly opened hidden Rhino window.
            attributes=mode.DisplayAttributes
            attributes.ShadingEnabled=True
            attributes.MeshSpecificAttributes.ShowMeshWires=False
            attributes.ShowSurfaceEdges=False
            attributes.ViewSpecificAttributes.DrawGrid=False
            attributes.ViewSpecificAttributes.DrawGridAxes=False
            attributes.ViewSpecificAttributes.DrawWorldAxes=False
            size=SD.Size(cameras['width'],cameras['height'])
            warmup=view.CaptureToBitmap(size,attributes)
            if warmup is not None: warmup.Dispose()
            view.Redraw();Rhino.RhinoApp.Wait()
            bitmap=view.CaptureToBitmap(size,attributes)
            if bitmap is None: raise RuntimeError('Native capture failed: '+camera['key'])
            filename=f'{index+1:02d}_{camera["key"]}.png'
            bitmap.Save(str(image_dir/filename),SD.Imaging.ImageFormat.Png)
            bitmap.Dispose()
            images.append('renders/rhino/'+filename)
            progress('capturing_views',completed=index+1,total=len(cameras['views']),view=camera['key'])
        # Restore overview for the delivered model's opening view.
        doc.NamedViews.Restore(doc.NamedViews.FindByName(saved_views[0]['name']),view.ActiveViewport)
        scrub_environment(doc)
        progress('saving_native_model')
        if not doc.SaveAs(str(OUTPUT),8,False,True,False,True):
            options=Rhino.FileIO.FileWriteOptions()
            options.FileVersion=8
            options.SuppressDialogBoxes=True;options.SuppressAllInput=True
            options.IncludeBitmapTable=True;options.WriteUserData=True
            if not doc.WriteFile(str(OUTPUT),options):
                raise RuntimeError('Cannot save native model: SaveAs and WriteFile both failed')
            options.Dispose()
        progress('reading_saved_model',bytes=OUTPUT.stat().st_size)
        result=verify_delivery(ROOT,MODEL,OUTPUT)
    except Exception:
        result['errors'].append(traceback.format_exc())
    REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    progress('complete' if result['passed'] else 'failed',errors=result['errors'])


if __name__=='__main__':
    main()
