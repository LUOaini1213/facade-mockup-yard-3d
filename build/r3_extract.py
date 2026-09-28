"""Extracts the vector geometry (line segments with colour / width / path ids) and the word list of the layout-plan PDF.
Needs the confidential layout plan in SOURCES_DIR.
"""
import fitz, numpy as np, json, math
import os
SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')
d=fitz.open(os.path.join(SOURCES_DIR, 'layout_plan'), filetype='pdf'); p=d[0]
segs=[]
def bez(p0,p1,p2,p3,n=12):
    t=np.linspace(0,1,n)[:,None]
    return ((1-t)**3)*p0+3*((1-t)**2)*t*p1+3*(1-t)*t*t*p2+t**3*p3
cols={}
for pid,dr in enumerate(p.get_drawings()):
    c=dr.get('color') or dr.get('fill') or (0,0,0)
    key=tuple(round(v,3) for v in c)
    ci=cols.setdefault(key,len(cols))
    for it in dr['items']:
        if it[0]=='l':
            a,b=it[1],it[2]; segs.append([a.x,a.y,b.x,b.y,ci,dr.get('width') or 0,pid,1 if dr.get('fill') else 0])
        elif it[0]=='c':
            pts=bez(*[np.array([q.x,q.y]) for q in it[1:5]])
            for i in range(len(pts)-1): segs.append([*pts[i],*pts[i+1],ci,dr.get('width') or 0,pid,1 if dr.get('fill') else 0])
        elif it[0]=='re':
            r=it[1]; q=[(r.x0,r.y0),(r.x1,r.y0),(r.x1,r.y1),(r.x0,r.y1),(r.x0,r.y0)]
            for i in range(4): segs.append([*q[i],*q[i+1],ci,dr.get('width') or 0,pid,1 if dr.get('fill') else 0])
        elif it[0]=='qu':
            q=it[1]; pts=[q.ul,q.ur,q.lr,q.ll,q.ul]
            for i in range(4): segs.append([pts[i].x,pts[i].y,pts[i+1].x,pts[i+1].y,ci,dr.get('width') or 0,pid,1 if dr.get('fill') else 0])
S=np.array(segs,dtype=np.float64)
np.save('r3_segs.npy',S); json.dump({str(v):list(k) for k,v in cols.items()},open('r3_cols.json','w'))
print(S.shape, cols)
words=p.get_text('words'); json.dump(words,open('layout_words.json','w'))
print(len(words))
