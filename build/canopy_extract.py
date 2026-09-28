"""Reads the canopy-extension plan (PDF vectors): chains the outline of the canopy and lists the small circles
(column symbols). Needs the confidential drawing in SOURCES_DIR.
"""
import fitz, numpy as np, json, collections
import os
SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')
p=fitz.open(os.path.join(SOURCES_DIR, 'canopy_extension_plan'), filetype='pdf')[0]
dr=p.get_drawings()
def pieces(x):
    out=[]
    for it in x['items']:
        if it[0]=='l': out.append([[it[1].x,it[1].y],[it[2].x,it[2].y]])
    return out
segs=[]
for i in range(117,143): segs+=pieces(dr[i])
segs=[np.array(s) for s in segs]
used=[False]*len(segs); poly=[segs[0][0],segs[0][1]]; used[0]=True
while True:
    end=poly[-1]; best=None
    for k,s in enumerate(segs):
        if used[k]: continue
        for fwd,(a,b) in [(True,(s[0],s[1])),(False,(s[1],s[0]))]:
            d=np.linalg.norm(a-end)
            if best is None or d<best[0]: best=(d,k,b)
    if best is None or best[0]>1.5: break
    used[best[1]]=True; poly.append(best[2])
P=np.array(poly); print('outline pts',len(P),'used',sum(used),'of',len(segs),'gap',round(float(np.linalg.norm(P[0]-P[-1])),3))
small=[]
for i,x in enumerate(dr):
    r=x['rect']
    if r.y1>595 or r.y0<41: continue
    if r.width<8 and r.height<8 and abs(r.width-r.height)<0.3 and r.width>0.5:
        small.append([i,round((r.x0+r.x1)/2,3),round((r.y0+r.y1)/2,3),round(r.width/2,3),len(x['items'])])
print('small circles',small)
big=[[0,229.44,200.16,34.68]]
for i,x in enumerate(dr):
    r=x['rect']
    if 180<r.x0<240 and 150<r.y0<215 and r.width>20 and i!=0: print('near big',i,[round(v,2) for v in (r.x0,r.y0,r.x1,r.y1)],len(x['items']),x.get('dashes'))
json.dump(dict(outline=P.tolist(),small=small,big=big),open('canopy_pdf.json','w'))
