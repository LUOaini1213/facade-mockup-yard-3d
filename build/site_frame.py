"""Shared site frame: layout-plan metric coordinates (m) -> glTF (x = East, y = Up, z = -North) about the yard origin.
Reads georef.json written by georef.py.
"""
import numpy as np, json, math
G=json.load(open('georef.json'))
s=G['R3_scale_m_per_pt']; O=np.array(G['origin_R3m']); b=math.radians(G['plan_x_bearing'])
ex=np.array([math.sin(b),math.cos(b)]); ey=np.array([-math.cos(b),math.sin(b)])
def r3_to_gltf(P,z=None):
    P=np.atleast_2d(np.asarray(P,dtype=np.float64)); Q=P[:,:2]-O
    E=Q[:,0]*ex[0]+Q[:,1]*ey[0]; N=Q[:,0]*ex[1]+Q[:,1]*ey[1]
    Z=np.zeros(len(P)) if z is None else (np.full(len(P),z) if np.isscalar(z) else np.asarray(z))
    return np.c_[E,Z,-N]
def r3_dir_to_gltf(D):
    D=np.atleast_2d(D); E=D[:,0]*ex[0]+D[:,1]*ey[0]; N=D[:,0]*ex[1]+D[:,1]*ey[1]; return np.c_[E,-N]
def page_to_r3(px,py): return np.array([px*s,-py*s])
