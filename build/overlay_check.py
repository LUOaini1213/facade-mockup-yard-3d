"""Debug overlay: legacy CAD meshes (translated) over the layout-plan lines.
"""
import numpy as np, pickle
from PIL import Image, ImageDraw
S=np.load('r3_segs.npy'); tx,ty,s=np.load('rhino_to_r3m.npy')
C=pickle.load(open('legacy_cad_cache.pkl','rb'))
res=25; x0,y0,x1,y1=95,-160,140,-110
W,H=int((x1-x0)*res),int((y1-y0)*res)
im=Image.new('RGB',(W,H),'white'); d=ImageDraw.Draw(im)
def px(X,Y): return ((X-x0)*res,(y1-Y)*res)
for mm in C['meshes']:
    if mm['layer'].startswith('SCALE'): continue
    v=mm['V']; F=mm['F'][::max(1,len(mm['F'])//3000)]
    col=(120,170,255) if mm['V'][:,2].max()>0.5 else (200,200,200)
    for f in F: d.polygon([px(v[i,0]+tx,v[i,1]+ty) for i in f],fill=col)
for x1_,y1_,x2_,y2_,c,w,pid,fl in S:
    X1,Y1,X2,Y2=x1_*s,-y1_*s,x2_*s,-y2_*s
    if x0-5<X1<x1+5 and y0-5<Y1<y1+5: d.line([px(X1,Y1),px(X2,Y2)],fill=(0,0,0) if c==0 else (255,0,0),width=1)
im.save('overlay_r3_rhino.png'); print(W,H)
