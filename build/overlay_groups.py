"""Debug overlay: per-group registered legacy CAD meshes over the layout-plan lines.
"""
import numpy as np, pickle, json
from PIL import Image, ImageDraw
S=np.load('r3_segs.npy'); R=json.load(open('group_registration.json')); s=R['s']
C=pickle.load(open('legacy_cad_cache.pkl','rb'))
def xf(g,v):
    r=R['reg'][g]; c0=np.array(r['c0']); a=np.radians(r['rot_deg']); c,sn=np.cos(a),np.sin(a)
    q=(v[:,:2]-c0)@np.array([[c,sn],[-sn,c]])+[r['tx'],r['ty']]; return q
res=25; x0,y0,x1,y1=100,-150,140,-86
W,H=int((x1-x0)*res),int((y1-y0)*res)
im=Image.new('RGB',(W,H),'white'); d=ImageDraw.Draw(im)
def px(X,Y): return ((X-x0)*res,(y1-Y)*res)
for i,mm in enumerate(C['meshes']):
    g=R['assign'].get(str(i))
    if not g: continue
    q=xf(g,mm['V']); F=mm['F'][::max(1,len(mm['F'])//3000)]
    col=(120,170,255) if mm['V'][:,2].max()>0.5 else (200,200,200)
    for f in F: d.polygon([px(*q[k]) for k in f],fill=col)
for x1_,y1_,x2_,y2_,c,w,pid,fl in S:
    X1,Y1,X2,Y2=x1_*s,-y1_*s,x2_*s,-y2_*s
    if x0-5<X1<x1+5 and y0-5<Y1<y1+5: d.line([px(X1,Y1),px(X2,Y2)],fill=(0,0,0),width=1)
im.save('overlay_groups.png'); im.crop((0,int(20*res),int(20*res),int(52*res))).save('overlay_vmu01.png')
