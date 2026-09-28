"""Rasterises the original-canopy panel of the canopy-extension plan and lists its largest closed regions.
Needs the confidential drawing in SOURCES_DIR.
"""
import fitz, numpy as np, cv2, json
import os
SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')
p=fitz.open(os.path.join(SOURCES_DIR, 'canopy_extension_plan'), filetype='pdf')[0]
clip=fitz.Rect(121,41.9,720.8,595.2)
Z=10.0
pix=p.get_pixmap(matrix=fitz.Matrix(Z,Z),clip=clip,colorspace=fitz.csGRAY)
img=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width)
cv2.imwrite('canopy_orig_panel.png',img)
ink=(img<128).astype(np.uint8)
k=np.ones((3,3),np.uint8); inkc=cv2.dilate(ink,k,1)
ff=inkc.copy()*255; h,w=ff.shape; mask=np.zeros((h+2,w+2),np.uint8)
cv2.floodFill(ff,mask,(5,5),128)
region=(ff!=128).astype(np.uint8)
n,lab,st,cen=cv2.connectedComponentsWithStats(region,8)
idx=1+np.argsort(-st[1:,cv2.CC_STAT_AREA])
for j in idx[:5]: print('comp',j,st[j],cen[j])
