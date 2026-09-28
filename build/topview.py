"""Debug: top-view raster of the cached legacy CAD model.
"""
import pickle, numpy as np, collections
from PIL import Image, ImageDraw
C=pickle.load(open('legacy_cad_cache.pkl','rb'))
M=C['meshes']; dm=set(C['defmembers'])
print('top-level meshes that are def members:',sum(1 for m in M if m['id'] in dm))
ids=collections.Counter(m['id'] for m in M); print('dup ids', sum(1 for k,v in ids.items() if v>1))
allv=np.vstack([m['V'] for m in M if not m['layer'].startswith('SCALE')])
print('bbox',allv.min(0),allv.max(0))
mn=allv.min(0)-1; mx=allv.max(0)+1; s=20
W=int((mx[0]-mn[0])*s); H=int((mx[1]-mn[1])*s)
im=Image.new('RGB',(W,H),'white'); d=ImageDraw.Draw(im)
for m in M:
    if m['layer'].startswith('SCALE'): continue
    v=m['V']; P=np.c_[(v[:,0]-mn[0])*s, (mx[1]-v[:,1])*s]
    col=tuple(int(c*200) for c in m['color'])
    for f in m['F'][::max(1,len(m['F'])//4000)]:
        d.polygon([tuple(P[i]) for i in f],fill=col)
for c in C['curves']:
    P=[((x-mn[0])*s,(mx[1]-y)*s) for x,y,z in c['pts']]
    d.line(P,fill=(255,0,0),width=2)
im.save('legacy_cad_top.png'); print(W,H,mn,mx)
print(collections.Counter(c['layer'] for c in C['curves']))
