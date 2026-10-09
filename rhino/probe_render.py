#! python3
"""Read native display settings and model render overrides for reproducible diagnostics."""
import json,os,traceback
from pathlib import Path
import Rhino
import System
import System.Drawing as SD
root=Path(os.environ['MOCKUP_RHINO_ROOT'])
result={}
try:
    model=root/'model'/'vmu_site_future_native.3dm'
    Rhino.RhinoDoc.OpenFile(str(model))
    doc=Rhino.RhinoDoc.ActiveDoc
    mode=Rhino.Display.DisplayModeDescription.GetDisplayMode(Rhino.Display.DisplayModeDescription.RenderedId)
    a=mode.DisplayAttributes
    names=['ShadingEnabled','UseAssignedObjectMaterial','ShowMeshEdges','ShowMeshNakedEdges',
           'ShowMeshNonmanifoldEdges','FrontMaterialTransparency','FrontOverrideObjectTransparency',
           'BackMaterialTransparency','BackOverrideObjectTransparency','CullBackfaces','BackfaceDisplayStyle']
    result['attributes']={n:str(getattr(a,n)) for n in names}
    result['mesh_attributes']={n:str(getattr(a.MeshSpecificAttributes,n)) for n in ['ShowMeshWires','ShowMeshVertices']}
    result['overrides']=[o.Attributes.Name for o in doc.Objects if o.Attributes.HasDisplayModeOverride(System.Guid.Empty)]
    result['objects']=[]
    for obj in doc.Objects:
        if obj.Attributes.GetUserString('finish') in ('CTX_CONCRETE_YARD','CTX_ASPHALT'):
            result['objects'].append({'name':obj.Attributes.Name,'material_source':str(obj.Attributes.MaterialSource),
                'render_material':obj.RenderMaterial.Name if obj.RenderMaterial else None})
    view=doc.Views.ActiveView
    view.ActiveViewport.DisplayMode=mode
    view.Maximized=True
    a.ShadingEnabled=True
    a.MeshSpecificAttributes.ShowMeshWires=False
    a.ShowSurfaceEdges=False
    a.ViewSpecificAttributes.DrawGrid=False
    a.ViewSpecificAttributes.DrawGridAxes=False
    a.ViewSpecificAttributes.DrawWorldAxes=False
    view.Redraw();Rhino.RhinoApp.Wait()
    warmup=view.CaptureToBitmap(SD.Size(1600,1000),a)
    if warmup:warmup.Dispose()
    view.Redraw();Rhino.RhinoApp.Wait()
    bitmap=view.CaptureToBitmap(SD.Size(1600,1000),a)
    bitmap.Save(str(root/'renders'/'rhino'/'probe_render.png'),SD.Imaging.ImageFormat.Png)
    bitmap.Dispose()
except Exception:result['error']=traceback.format_exc()
(root/'model'/'vmu_site_future_render_probe.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
