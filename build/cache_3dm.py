"""Caches every render mesh of the legacy CAD model (.3dm, mm -> m, Rhino Z-up kept) with layer / material / object ids
into a pickle used by the registration and CAD builders. Needs the confidential CAD model in SOURCES_DIR.
"""
import rhino3dm as r, numpy as np, pickle, collections, hashlib
import os
SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')
src=os.path.join(SOURCES_DIR, 'legacy_cad.3dm')
doc=r.File3dm.Read(src)
objs={str(o.Attributes.Id):o for o in doc.Objects}
defs={str(d.Id):d for d in doc.InstanceDefinitions}
layers=[l.FullPath for l in doc.Layers]
mats=[]
for m in doc.Materials:
    c=m.DiffuseColor
    mats.append(dict(name=m.Name,rgb=[c[0]/255,c[1]/255,c[2]/255],transp=m.Transparency,refl=m.Reflectivity,shine=m.Shine))
out=[]; stats=collections.Counter(); curves=[]
def visit(o,xf=np.eye(4),parentmat=None,parentlayer=None,depth=0):
    a=o.Attributes; g=o.Geometry; li=a.LayerIndex
    lay=doc.Layers[li]
    if not lay.Visible or str(a.Mode).endswith('Hidden'): stats['hidden']+=1; return
    mat=a.MaterialIndex if a.MaterialSource==r.ObjectMaterialSource.MaterialFromObject else lay.RenderMaterialIndex
    if a.MaterialSource==r.ObjectMaterialSource.MaterialFromParent and parentmat is not None: mat=parentmat
    col=a.ObjectColor if a.ColorSource==r.ObjectColorSource.ColorFromObject else lay.Color
    col=[col[0]/255,col[1]/255,col[2]/255]
    if isinstance(g,r.InstanceReference):
        tr=np.array(g.Xform.ToFloatArray(True)).reshape(4,4)
        for oid in defs[str(g.ParentIdefId)].GetObjectIds(): visit(objs[str(oid)],xf@tr,mat,li,depth+1)
        stats['inst']+=1; return
    meshes=[]
    if isinstance(g,r.Mesh): meshes=[g]
    elif isinstance(g,r.Brep): meshes=[f.GetMesh(r.MeshType.Render) for f in g.Faces]
    elif isinstance(g,r.Extrusion): meshes=[g.GetMesh(r.MeshType.Render)]
    elif isinstance(g,(r.Curve,)):
        try:
            n=200; t0,t1=g.Domain.T0,g.Domain.T1
            pts=np.array([[g.PointAt(t0+(t1-t0)*i/n).X,g.PointAt(t0+(t1-t0)*i/n).Y,g.PointAt(t0+(t1-t0)*i/n).Z] for i in range(n+1)])
            pts=(pts@xf[:3,:3].T+xf[:3,3])/1000; curves.append(dict(layer=layers[li],pts=pts.astype(np.float32),id=str(a.Id)))
        except Exception as e: pass
        stats['curve']+=1; return
    else: stats['other:'+type(g).__name__]+=1; return
    V=[];F=[];NN=[];off=0
    for me in meshes:
        if me is None: stats['nomesh']+=1; continue
        v=np.array([[p.X,p.Y,p.Z] for p in me.Vertices],dtype=np.float64)
        try:
            nn=np.array([[q.X,q.Y,q.Z] for q in me.Normals],dtype=np.float64)
            if len(nn)!=len(v): nn=None
        except Exception: nn=None
        if not len(v): continue
        NN.append(nn if nn is not None else np.full((len(v),3),np.nan))
        f=[]
        for fa in me.Faces:
            a0,b0,c0,d0=fa
            f.append([a0,b0,c0])
            if c0!=d0: f.append([a0,c0,d0])
        V.append(v); F.append(np.array(f,dtype=np.int64)+off); off+=len(v)
    if not V: return
    v=np.vstack(V); v=(v@xf[:3,:3].T+xf[:3,3])/1000.0
    nrm=np.vstack(NN)@xf[:3,:3].T; ln=np.linalg.norm(nrm,axis=1,keepdims=True); nrm=np.where(ln>1e-9,nrm/np.maximum(ln,1e-9),np.nan)
    out.append(dict(id=str(a.Id),name=a.Name,layer=layers[li],layer_idx=li,mat=int(mat),color=col,
                    type=type(g).__name__,V=v.astype(np.float64),N=nrm.astype(np.float32),F=np.vstack(F).astype(np.int32)))
    stats[type(g).__name__]+=1
for o in doc.Objects:
    if o.Attributes.IsInstanceDefinitionObject if hasattr(o.Attributes,'IsInstanceDefinitionObject') else False: continue
    visit(o)
defmembers=set(str(i) for d in doc.InstanceDefinitions for i in d.GetObjectIds())
out=[m for m in out if m['id'] not in defmembers or True]
pickle.dump(dict(meshes=out,mats=mats,layers=layers,curves=curves,defmembers=list(defmembers)),open('legacy_cad_cache_n.pkl','wb'),protocol=4)
tri=sum(len(m['F']) for m in out)
print('objects',len(out),'triangles',tri,stats, 'defmembers',len(defmembers))
