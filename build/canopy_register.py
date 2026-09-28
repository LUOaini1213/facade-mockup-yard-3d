"""Registers the rasterised canopy outline onto the layout plan (scale / rotation / mirror / translation search against
a distance transform of the plan lines) and writes the canopy outline in plan metres.
"""
import fitz, numpy as np, cv2, json
from scipy import ndimage
Z=10.0; clip0=(121,41.9)
img=cv2.imread('canopy_orig_panel.png',0)
ink=(img<128).astype(np.uint8); inkc=cv2.dilate(ink,np.ones((3,3),np.uint8),1)
ff=inkc*255; mask=np.zeros((ff.shape[0]+2,ff.shape[1]+2),np.uint8); cv2.floodFill(ff,mask,(5,5),128)
region=(ff!=128).astype(np.uint8)
n,lab,st,cen=cv2.connectedComponentsWithStats(region,8)
j=1+np.argmax(st[1:,cv2.CC_STAT_AREA]*(st[1:,cv2.CC_STAT_WIDTH]<5500))
reg=(lab==j).astype(np.uint8)
reg=cv2.erode(reg,np.ones((3,3),np.uint8),2)
cs,_=cv2.findContours(reg,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
c=max(cs,key=cv2.contourArea)[:,0,:].astype(float)
Ppt=np.c_[c[:,0]/Z+clip0[0], c[:,1]/Z+clip0[1]]
print('contour pts',len(Ppt),'bbox',Ppt.min(0),Ppt.max(0))
S=np.load('r3_segs.npy'); s=15000/71.645/1000.0
Rm=np.c_[S[:,0]*s,-S[:,1]*s,S[:,2]*s,-S[:,3]*s][S[:,4]==0]
res=50.0; mn=np.array([103.0,-137.0]); mx=np.array([121.0,-113.0])
shape=(int((mx[1]-mn[1])*res)+1,int((mx[0]-mn[0])*res)+1); im=np.zeros(shape,bool)
for x1,y1,x2,y2 in Rm:
    if not(mn[0]-1<min(x1,x2) and max(x1,x2)<mx[0]+1 and mn[1]-1<min(y1,y2) and max(y1,y2)<mx[1]+1): continue
    k=int(max(abs(x2-x1),abs(y2-y1))*res)+2
    xs=((np.linspace(x1,x2,k)-mn[0])*res).astype(int); ys=((np.linspace(y1,y2,k)-mn[1])*res).astype(int)
    ok=(xs>=0)&(xs<shape[1])&(ys>=0)&(ys<shape[0]); im[ys[ok],xs[ok]]=True
dt=ndimage.distance_transform_edt(~im)/res
Q=np.c_[Ppt[:,0],-Ppt[:,1]]; qc=(Q.min(0)+Q.max(0))/2; Q=Q-qc
Qs=Q[::3]
def score(params,mirror):
    sc,rot,tx,ty=params; c_,s_=np.cos(rot),np.sin(rot)
    q=Qs.copy()
    if mirror: q[:,0]*=-1
    q=sc*(q@np.array([[c_,s_],[-s_,c_]]))+[tx,ty]
    ix=((q[:,0]-mn[0])*res).astype(int); iy=((q[:,1]-mn[1])*res).astype(int)
    ok=(ix>=0)&(ix<shape[1])&(iy>=0)&(iy<shape[0]); d=np.full(len(q),2.0); d[ok]=np.minimum(dt[iy[ok],ix[ok]],2.0); return d.mean()
center=np.array([111.9,-125.4]); best=(9,None)
for mirror in [False,True]:
  for rot0 in [0,90,180,270]:
    for scl in np.linspace(0.028,0.036,17):
      for dx in np.arange(-2,2.01,0.25):
        for dy in np.arange(-2,2.01,0.25):
          v=score((scl,np.radians(rot0),center[0]+dx,center[1]+dy),mirror)
          if v<best[0]: best=(v,[scl,np.radians(rot0),center[0]+dx,center[1]+dy],mirror)
print('coarse',best[0],best[1],best[2])
p=np.array(best[1]); b=best[0]; mirror=best[2]
steps=np.array([2e-4,np.radians(0.2),0.02,0.02])
for lvl in range(4):
    for it in range(80):
        imp=False
        for k in range(4):
            for sg in (1,-1):
                q=p.copy(); q[k]+=sg*steps[k]; v=score(q,mirror)
                if v<b-1e-8: b=v; p=q; imp=True
        if not imp: break
    steps/=4
print('fine',b,'scale m/pt',p[0],'rot deg',np.degrees(p[1]),'t',p[2:],'mirror',mirror)
json.dump(dict(qc=qc.tolist(),scale=p[0],rot=p[1],tx=p[2],ty=p[3],mirror=bool(mirror),score=b),open('canopy_to_r3m.json','w'))
def tf(P):
    q=np.c_[P[:,0],-P[:,1]]-qc
    if mirror: q[:,0]*=-1
    c_,s_=np.cos(p[1]),np.sin(p[1]); return p[0]*(q@np.array([[c_,s_],[-s_,c_]]))+p[2:]
outline_r3m=tf(Ppt)
json.dump(dict(outline=outline_r3m.tolist()),open('canopy_outline_r3m.json','w'))
q=tf(Ppt); ix=((q[:,0]-mn[0])*res).astype(int); iy=((q[:,1]-mn[1])*res).astype(int)
print('within 3cm',(dt[iy,ix]<0.03).mean(),'within 8cm',(dt[iy,ix]<0.08).mean())
