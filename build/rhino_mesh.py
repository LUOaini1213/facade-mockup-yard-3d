"""Rhino mesh conversion and identities shared by export and validation."""
import uuid

import numpy as np
import rhino3dm as r

COMPONENT_NAMESPACE = uuid.UUID('247a3cf6-23b2-5ae4-b994-4255c63fe8c9')


def source_key(filename, node_index, primitive_index):
    return f'{filename}/node/{node_index}/primitive/{primitive_index}'


def component_id(key):
    """Stable while the source GLB filename/node/primitive indices stay stable."""
    return uuid.uuid5(COMPONENT_NAMESPACE, key)


def world_uv(vertices_mm, normals):
    """Public viewer dominant-normal projection, in metres, from Rhino Z-up arrays."""
    p=np.asarray(vertices_mm,dtype=float)/1000
    n=np.asarray(normals,dtype=float)
    # Rhino (x,y,z) = glTF (x,-z,y).
    x,y,z=p[:,0],p[:,2],-p[:,1]
    nx,ny,nz=n[:,0],n[:,2],-n[:,1]
    ax,ay,az=abs(nx),abs(ny),abs(nz)
    top=(ay>=ax)&(ay>=az)
    side=(~top)&(ax>=az)
    u=np.where(top,x,np.where(side,z*np.where(nx>=0,1,-1),-x*np.where(nz>=0,1,-1)))
    v=np.where(top,-z,y)
    return np.c_[u,v]


def make_mesh(vertices, faces, normals=None, uv=None):
    vertices = np.asarray(vertices)
    faces = np.asarray(faces)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
        raise ValueError('Mesh vertices must be finite Nx3 coordinates')
    if faces.ndim != 2 or faces.shape[1] != 3 or not np.issubdtype(faces.dtype, np.integer):
        raise ValueError('Mesh faces must be integer Nx3 indices')
    if faces.size and (faces.min() < 0 or faces.max() >= len(vertices)):
        raise ValueError('Mesh face index outside vertex array')
    mesh = r.Mesh()
    for x, y, z in vertices.tolist():
        mesh.Vertices.Add(x, y, z)
    for a, b, c in faces.tolist():
        mesh.Faces.AddFace(a, b, c)
    if normals is not None:
        normals = np.asarray(normals)
        if normals.shape != vertices.shape or not np.isfinite(normals).all():
            raise ValueError('Normals must be finite and match vertex count')
        for x, y, z in normals.tolist():
            mesh.Normals.Add(x, y, z)
    if uv is not None:
        uv = np.asarray(uv)
        if uv.shape != (len(vertices), 2) or not np.isfinite(uv).all():
            raise ValueError('Texture coordinates must be finite Nx2 values matching vertex count')
        # rhino3dm exposes this append method as __add__, unlike RhinoCommon.Add.
        # UVs are dimensionless: axis and metre-to-mm transforms affect vertices only.
        for u, v in uv.tolist():
            mesh.TextureCoordinates.__add__(u, v)
    if not mesh.IsValid:
        # Legacy CAD meshes include collapsed triangles. Remove only degenerate
        # faces; retain every vertex, normal and UV, including unused vertices.
        mesh.Faces.CullDegenerateFaces()
    if not mesh.IsValid:
        raise ValueError('Rhino rejected mesh: ' + str(mesh.IsValidWithLog))
    return mesh
