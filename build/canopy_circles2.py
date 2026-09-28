"""Detects the column circles in both panels (original / proposed) of the canopy-extension plan, maps them into plan
metres and compares them with the existing columns of the legacy CAD model.
"""
import numpy as np, cv2, json, fitz, pickle
import os
SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')
Z=10.0
T=json.load(open('canopy_to_r3m.json'))
p=fitz.open(os.path.join(SOURCES_DIR, 'canopy_extension_plan'), filetype='pdf')[0]
def detect(clip):
    pix=p.get_pixmap(matrix=fitz.Matrix(Z,Z),clip=fitz.Rect(*clip),colorspace=fitz.csGRAY)
    img=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width)
    ink=(img<140).astype(np.uint8)*255
    cs,_=cv2.findContours(ink,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_NONE)
    res=[]
    for c in cs:
        a=cv2.contourArea(c); per=cv2.arcLength(c,True)
        if per<20: continue
        if 4*np.pi*a/(per*per)>0.85:
            (x,y),r=cv2.minEnclosingCircle(c); res.append((x/Z+clip[0],y/Z+clip[1],r/Z))
    out=[]
    for f in sorted(res,key=lambda t:-t[2]):
        for g in out:
            if np.hypot(f[0]-g[0],f[1]-g[1])<0.5 and abs(f[2]-g[2])<0.7: break
        else: out.append(f)
    return out
A=detect((121,41.9,720.8,595.2)); B=detect((121,595.2,720.8,1148.5))
bigA=max(A,key=lambda t:t[2]); bigB=max(B,key=lambda t:t[2]); off=np.array(bigB[:2])-np.array(bigA[:2])
print('panel offset',off)
pts=[(x,y,r,'orig') for x,y,r in A]+[(x-off[0],y-off[1],r,'prop') for x,y,r in B]
def tf(x,y):
    qc=np.array(T['qc']); q=np.array([x,-y])-qc
    if T['mirror']: q[0]*=-1
    c_,s_=np.cos(T['rot']),np.sin(T['rot']); return T['scale']*(q@np.array([[c_,s_],[-s_,c_]]))+[T['tx'],T['ty']]
merged=[]
for x,y,r,src in pts:
    for m in merged:
        if np.hypot(x-m['x'],y-m['y'])<1.0 and abs(r-m['r'])<0.8: m['src'].add(src); break
    else: merged.append(dict(x=x,y=y,r=r,src={src}))
C=pickle.load(open('legacy_cad_cache.pkl','rb')); R=json.load(open('group_registration.json'))
g=R['reg']['VMU01']; c0=np.array(g['c0']); a=np.radians(g['rot_deg']); ca,sa=np.cos(a),np.sin(a)
cols=[]
for i,m in enumerate(C['meshes']):
    if R['assign'].get(str(i))=='VMU01' and m['layer']=='铁架::150X5圆管' and m['V'][:,2].max()<3.3:
        cxy=(m['V'].min(0)+m['V'].max(0))[:2]/2; cols.append(((cxy-c0)@np.array([[ca,sa],[-sa,ca]])+[g['tx'],g['ty']]).tolist())
print('existing rhino columns (site):',np.round(cols,3).tolist())
out=[]
for m in merged:
    s=tf(m['x'],m['y']); d=min(np.hypot(s[0]-c[0],s[1]-c[1]) for c in cols)
    out.append(dict(site=s.round(4).tolist(),r_m=round(m['r']*T['scale'],4),src=sorted(m['src']),nearest_existing_col=round(float(d),3)))
for o in sorted(out,key=lambda o:(-o['r_m'],o['site'][0])): print(o)
json.dump(dict(circles=out,existing_cols=cols),open('canopy_circles_r3m.json','w'),indent=1)
