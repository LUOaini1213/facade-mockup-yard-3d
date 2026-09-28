"""Per-group rigid registration (rotation + translation) of the legacy CAD mock-up groups onto the layout plan.
"""
import numpy as np, pickle, json
from scipy import ndimage
S=np.load('r3_segs.npy'); s=15000/71.645/1000.0
C=pickle.load(open('legacy_cad_cache.pkl','rb'))
GROUPS={
 'VMU01':(8.5,24.5,19.0,38.5),'VMU03':(28.5,35.5,17.5,43.5),'VMU05':(30.5,35.5,43.8,48.5),
 'TRELLIS':(28.5,37.5,9.5,16.0),'VMU02':(28.5,37.5,-7.0,8.5),'VMU04':(2.5,8.5,-3.5,2.5)}
TARGET={'VMU01':(119.34,-113.92),'VMU03':(131.97,-107.43),'VMU05':(133.18,-92.73),
        'TRELLIS':(131.21,-130.5),'VMU02':(131.48,-142.37),'VMU04':(105.47,-143.4)}
def grp(m):
    v=m['V']; c=(v.min(0)+v.max(0))/2
    for g,(a,b,cc,dd) in GROUPS.items():
        if a<=c[0]<=b and cc<=c[1]<=dd: return g
    return None
assign={}
for i,m in enumerate(C['meshes']):
    if m['layer'].startswith('SCALE'): continue
    assign[i]=grp(m)
import collections; print(collections.Counter(assign.values()))
un=[ (C['meshes'][i]['layer'],np.round((C['meshes'][i]['V'].min(0)+C['meshes'][i]['V'].max(0))/2,2).tolist()) for i,g in assign.items() if g is None]
print('unassigned',len(un),un[:20])
Rm=np.c_[S[:,0]*s,-S[:,1]*s,S[:,2]*s,-S[:,3]*s][S[:,4]==0]
res=20.0; mn=np.array([95.0,-160.0]); mx=np.array([145.0,-80.0])
shape=(int((mx[1]-mn[1])*res)+1,int((mx[0]-mn[0])*res)+1); img=np.zeros(shape,bool)
for x1,y1,x2,y2 in Rm:
    if not(mn[0]-2<x1<mx[0]+2 and mn[1]-2<y1<mx[1]+2): continue
    n=int(max(abs(x2-x1),abs(y2-y1))*res)+2
    xs=((np.linspace(x1,x2,n)-mn[0])*res).astype(int); ys=((np.linspace(y1,y2,n)-mn[1])*res).astype(int)
    ok=(xs>=0)&(xs<shape[1])&(ys>=0)&(ys<shape[0]); img[ys[ok],xs[ok]]=True
dt=ndimage.distance_transform_edt(~img)/res
result={}
for g in GROUPS:
    pts=[]
    for i,gg in assign.items():
        if gg!=g: continue
        v=C['meshes'][i]['V']
        if C['meshes'][i]['layer'].startswith('铁架::地面埋板'): continue
        pts.append(v[::max(1,len(v)//400),:2])
    P=np.vstack(pts); c0=(P.min(0)+P.max(0))/2; Q=P-c0
    def score(tx,ty,rot):
        c,sn=np.cos(rot),np.sin(rot); q=Q@np.array([[c,sn],[-sn,c]])+[tx,ty]
        ix=((q[:,0]-mn[0])*res).astype(int); iy=((q[:,1]-mn[1])*res).astype(int)
        ok=(ix>=0)&(ix<shape[1])&(iy>=0)&(iy<shape[0]); d=np.full(len(q),3.0); d[ok]=np.minimum(dt[iy[ok],ix[ok]],3.0); return d.mean()
    T=np.array(TARGET[g]); best=(9e9,None)
    for rot in np.radians(np.arange(-6,6.01,1.0)):
        for dx in np.arange(-4,4.01,0.25):
            for dy in np.arange(-4,4.01,0.25):
                sc=score(T[0]+dx,T[1]+dy,rot)
                if sc<best[0]: best=(sc,[T[0]+dx,T[1]+dy,rot])
    tx,ty,rot=best[1]; b=best[0]
    for step,rstep in [(0.05,np.radians(0.25)),(0.01,np.radians(0.05)),(0.002,np.radians(0.01))]:
        for it in range(60):
            imp=False
            for d in [(step,0,0),(-step,0,0),(0,step,0),(0,-step,0),(0,0,rstep),(0,0,-rstep)]:
                sc=score(tx+d[0],ty+d[1],rot+d[2])
                if sc<b-1e-7: b=sc; tx,ty,rot=tx+d[0],ty+d[1],rot+d[2]; imp=True
            if not imp: break
    c,sn=np.cos(rot),np.sin(rot); q=Q@np.array([[c,sn],[-sn,c]])+[tx,ty]
    ix=((q[:,0]-mn[0])*res).astype(int); iy=((q[:,1]-mn[1])*res).astype(int); ok=(ix>=0)&(ix<shape[1])&(iy>=0)&(iy<shape[0])
    near=(dt[iy[ok],ix[ok]]<0.1).mean()
    result[g]=dict(c0=c0.tolist(),tx=tx,ty=ty,rot_deg=float(np.degrees(rot)),score=float(b),near01=float(near),n=len(P))
    print(g,{k:(round(v,4) if isinstance(v,float) else v) for k,v in result[g].items()})
json.dump(dict(groups=GROUPS,assign={str(k):v for k,v in assign.items()},reg=result,s=s),open('group_registration.json','w'),indent=1)
