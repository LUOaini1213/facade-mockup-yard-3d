"""Minimal glTF 2.0 (GLB) writer: float32 positions / normals, uint32 indices, PBR materials, named nodes and extras.
"""
import json, struct, numpy as np
class GLB:
    def __init__(s):
        s.bin=bytearray(); s.bufferViews=[]; s.accessors=[]; s.meshes=[]; s.nodes=[]; s.materials=[]; s.matidx={}; s.roots=[]
    def _view(s,data,target=None):
        while len(s.bin)%4: s.bin+=b'\0'
        off=len(s.bin); s.bin+=data
        bv={'buffer':0,'byteOffset':off,'byteLength':len(data)}
        if target: bv['target']=target
        s.bufferViews.append(bv); return len(s.bufferViews)-1
    def _acc(s,arr,ctype,typ,target,minmax=False):
        v=s._view(arr.tobytes(),target)
        a={'bufferView':v,'componentType':ctype,'count':int(arr.shape[0]),'type':typ}
        if minmax: a['min']=arr.min(0).astype(float).tolist(); a['max']=arr.max(0).astype(float).tolist()
        s.accessors.append(a); return len(s.accessors)-1
    def material(s,name,rgb,alpha=1.0,metal=0.0,rough=0.6,double=True,emissive=None,extras=None):
        if name in s.matidx: return s.matidx[name]
        m={'name':name,'pbrMetallicRoughness':{'baseColorFactor':[float(rgb[0]),float(rgb[1]),float(rgb[2]),float(alpha)],'metallicFactor':float(metal),'roughnessFactor':float(rough)},'doubleSided':double}
        if alpha<1: m['alphaMode']='BLEND'
        if emissive: m['emissiveFactor']=[float(x) for x in emissive]
        if extras: m['extras']=extras
        s.materials.append(m); s.matidx[name]=len(s.materials)-1; return s.matidx[name]
    def mesh(s,name,V,F,N=None,mat=0,colors=None,uvs=None):
        V=np.ascontiguousarray(V,dtype=np.float32); F=np.ascontiguousarray(F,dtype=np.uint32).reshape(-1)
        attrs={'POSITION':s._acc(V,5126,'VEC3',34962,True)}
        if N is not None: attrs['NORMAL']=s._acc(np.ascontiguousarray(N,dtype=np.float32),5126,'VEC3',34962)
        if uvs is not None: attrs['TEXCOORD_0']=s._acc(np.ascontiguousarray(uvs,dtype=np.float32),5126,'VEC2',34962)
        if colors is not None: attrs['COLOR_0']=s._acc(np.ascontiguousarray(colors,dtype=np.float32),5126,'VEC3',34962)
        ind=s._acc(F.reshape(-1,1),5125,'SCALAR',34963)
        s.accessors[ind]['type']='SCALAR'
        s.meshes.append({'name':name,'primitives':[{'attributes':attrs,'indices':ind,'material':mat}]}); return len(s.meshes)-1
    def node(s,name,mesh=None,children=None,extras=None,translation=None,root=False):
        n={'name':name}
        if mesh is not None: n['mesh']=mesh
        if children: n['children']=children
        if extras: n['extras']=extras
        if translation is not None: n['translation']=[float(x) for x in translation]
        s.nodes.append(n); i=len(s.nodes)-1
        if root: s.roots.append(i)
        return i
    def save(s,path,extras=None):
        while len(s.bin)%4: s.bin+=b'\0'
        g={'asset':{'version':'2.0','generator':'mock-up VMU site builder'},'scene':0,'scenes':[{'nodes':s.roots,'extras':extras or {}}],
           'nodes':s.nodes,'meshes':s.meshes,'materials':s.materials,'accessors':s.accessors,'bufferViews':s.bufferViews,'buffers':[{'byteLength':len(s.bin)}]}
        js=json.dumps(g,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        while len(js)%4: js+=b' '
        with open(path,'wb') as f:
            f.write(struct.pack('<III',0x46546C67,2,12+8+len(js)+8+len(s.bin)))
            f.write(struct.pack('<II',len(js),0x4E4F534A)); f.write(js)
            f.write(struct.pack('<II',len(s.bin),0x004E4942)); f.write(s.bin)
