"""Detects the circular column symbols in the rasterised canopy panel and maps them into plan metres.
"""
import numpy as np, cv2, json
Z=10.0; clip0=(121,41.9)
T=json.load(open('canopy_to_r3m.json'))
img=cv2.imread('canopy_orig_panel.png',0)
ink=(img<140).astype(np.uint8)*255
cs,hier=cv2.findContours(ink,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_NONE)
found=[]
for c in cs:
    a=cv2.contourArea(c); per=cv2.arcLength(c,True)
    if per<20: continue
    circ=4*np.pi*a/(per*per)
    (x,y),r=cv2.minEnclosingCircle(c)
    if circ>0.85 and 5<r<500: found.append((x,y,r,circ,a))
found.sort(key=lambda t:-t[2]); groups=[]
for f in found:
    for g in groups:
        if np.hypot(f[0]-g[0],f[1]-g[1])<4 and abs(f[2]-g[2])<6: g[3].append(f); break
    else: groups.append([f[0],f[1],f[2],[f]])
def tf(pt):
    qc=np.array(T['qc']); q=np.array([pt[0],-pt[1]])-qc
    if T['mirror']: q[0]*=-1
    c_,s_=np.cos(T['rot']),np.sin(T['rot']); return (T['scale']*(q@np.array([[c_,s_],[-s_,c_]]))+[T['tx'],T['ty']]).tolist()
out=[]
for g in groups:
    rs=[f[2] for f in g[3]]; r=np.mean(rs)/Z; x=np.mean([f[0] for f in g[3]])/Z+clip0[0]; y=np.mean([f[1] for f in g[3]])/Z+clip0[1]
    out.append(dict(pdf=[round(x,3),round(y,3)],r_pt=round(r,3),r_m=round(r*T['scale'],4),site=[round(v,4) for v in tf((x,y))],n=len(g[3])))
for o in sorted(out,key=lambda o:-o['r_m']): print(o)
json.dump(out,open('canopy_circles_r3m.json','w'),indent=1)
