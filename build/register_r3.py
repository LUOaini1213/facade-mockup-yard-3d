"""Finds the translation (and checks rotation / scale) that maps the legacy CAD plan onto the layout plan
(coarse grid search + local refinement on a distance transform of the plan lines).
"""
import numpy as np, pickle
from scipy import ndimage
S=np.load('r3_segs.npy'); s=15000/71.645/1000.0
C=pickle.load(open('legacy_cad_cache.pkl','rb'))
reg=(480,380,810,730)
m=(np.minimum(S[:,0],S[:,2])>reg[0])&(np.maximum(S[:,0],S[:,2])<reg[2])&(np.minimum(S[:,1],S[:,3])>reg[1])&(np.maximum(S[:,1],S[:,3])<reg[3])&(S[:,4]==0)
R=S[m]
res=10.0
def raster_segs(seg_xy, mn, shape):
    img=np.zeros(shape,bool)
    for x1,y1,x2,y2 in seg_xy:
        n=int(max(abs(x2-x1),abs(y2-y1))*res)+2
        xs=((np.linspace(x1,x2,n)-mn[0])*res).astype(int); ys=((np.linspace(y1,y2,n)-mn[1])*res).astype(int)
        ok=(xs>=0)&(xs<shape[1])&(ys>=0)&(ys<shape[0]); img[ys[ok],xs[ok]]=True
    return img
Rm=np.c_[R[:,0]*s, -R[:,1]*s, R[:,2]*s, -R[:,3]*s]
mn=np.array([Rm[:,[0,2]].min()-5, Rm[:,[1,3]].min()-5]); mx=np.array([Rm[:,[0,2]].max()+5, Rm[:,[1,3]].max()+5])
shape=(int((mx[1]-mn[1])*res)+1,int((mx[0]-mn[0])*res)+1)
img=raster_segs(Rm[:,:4],mn,shape)
dt=ndimage.distance_transform_edt(~img)/res
pts=[]
for mm in C['meshes']:
    if mm['layer'].startswith('SCALE') : continue
    v=mm['V']
    if v[:,2].max()<0.5 and mm['layer'].startswith('铁架::地面埋板'): continue
    pts.append(v[::max(1,len(v)//300),:2])
P=np.vstack(pts); print('pts',len(P))
def score(tx,ty,rot=0.0):
    c,sn=np.cos(rot),np.sin(rot)
    q=P@np.array([[c,sn],[-sn,c]])+[tx,ty]
    ix=((q[:,0]-mn[0])*res).astype(int); iy=((q[:,1]-mn[1])*res).astype(int)
    ok=(ix>=0)&(ix<shape[1])&(iy>=0)&(iy<shape[0])
    d=np.full(len(q),5.0); d[ok]=np.minimum(dt[iy[ok],ix[ok]],5.0)
    return d.mean()
cP=(P.min(0)+P.max(0))/2; cR=(mn+mx)/2
best=(1e9,None)
for dx in np.arange(-25,25.01,0.5):
    for dy in np.arange(-25,25.01,0.5):
        sc=score(cR[0]-cP[0]+dx,cR[1]-cP[1]+dy)
        if sc<best[0]: best=(sc,(cR[0]-cP[0]+dx,cR[1]-cP[1]+dy))
print('coarse',best)
tx,ty=best[1]; b=best
for step in [0.1,0.02,0.005]:
    for it in range(30):
        improved=False
        for ddx,ddy in [(step,0),(-step,0),(0,step),(0,-step)]:
            sc=score(tx+ddx,ty+ddy)
            if sc<b[0]-1e-6: b=(sc,(tx+ddx,ty+ddy)); tx,ty=tx+ddx,ty+ddy; improved=True
        if not improved: break
print('fine',b)
for rd in [-1,-0.5,-0.2,0,0.2,0.5,1]:
    print('rot',rd,round(score(tx,ty,np.radians(rd)),4))
np.save('rhino_to_r3m.npy',np.array([tx,ty,s]))
c=score(tx,ty)
