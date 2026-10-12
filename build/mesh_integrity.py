"""Independent polygon-mesh edge topology and integrals, without Rhino predicates.

Exactly coincident vertices are welded for topology (normal/UV seams are not
holes). No tolerance closes a real gap. Edge-manifold/oriented/closed predicates
do not certify self-intersection, fabrication suitability or engineering roles.
"""
import math

import numpy as np


def arrays(mesh):
    return (np.array([(p.X, p.Y, p.Z) for p in mesh.Vertices], dtype=float),
            np.array(list(mesh.Faces), dtype=np.int64))


def triangulate(vertices, faces):
    """Rhino triangular faces repeat C as D; quads use the shorter diagonal."""
    vertices = np.asarray(vertices, dtype=float)
    faces = np.asarray(faces)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
        raise ValueError('Mesh coordinates must be finite Nx3 values')
    if faces.ndim != 2 or faces.shape[1] not in (3, 4) or not np.issubdtype(faces.dtype, np.integer):
        raise ValueError('Mesh faces must be integer triangles or quads')
    if not len(faces) or faces.min() < 0 or faces.max() >= len(vertices):
        raise ValueError('Empty mesh or out-of-range face index')
    if faces.shape[1] == 3:
        return faces.astype(np.int64, copy=True)
    triangle = faces[:, 2] == faces[:, 3]
    quads = faces[~triangle]
    ac = np.sum((vertices[quads[:, 0]] - vertices[quads[:, 2]]) ** 2, axis=1)
    bd = np.sum((vertices[quads[:, 1]] - vertices[quads[:, 3]]) ** 2, axis=1)
    short_ac, short_bd = quads[ac <= bd], quads[ac > bd]
    return np.concatenate((faces[triangle, :3], short_ac[:, [0, 1, 2]],
                           short_ac[:, [0, 2, 3]], short_bd[:, [0, 1, 3]],
                           short_bd[:, [1, 2, 3]]))


def topology(vertices, faces):
    vertices, faces = np.asarray(vertices, dtype=float), np.asarray(faces)
    triangles = triangulate(vertices, faces)
    positions, welded = np.unique(vertices, axis=0, return_inverse=True)
    polygon = welded[faces]
    if faces.shape[1] == 3:
        starts, ends = polygon.ravel(), np.roll(polygon, -1, axis=1).ravel()
    else:
        is_quad = faces[:, 2] != faces[:, 3]
        tri, quad = polygon[~is_quad, :3], polygon[is_quad]
        starts = np.concatenate((tri.ravel(), quad.ravel()))
        ends = np.concatenate((np.roll(tri, -1, axis=1).ravel(), np.roll(quad, -1, axis=1).ravel()))
    valid = not bool(np.any(starts == ends))
    directed = np.column_stack((starts, ends))
    edges, inverse, counts = np.unique(np.sort(directed, axis=1), axis=0,
                                      return_inverse=True, return_counts=True)
    signs = np.where(starts < ends, 1, -1)
    balance = np.bincount(inverse, weights=signs, minlength=len(edges))
    boundary = counts == 1
    manifold = valid and bool(np.all(counts <= 2))
    oriented = manifold and bool(np.all(balance[counts == 2] == 0))
    closed = valid and not bool(np.any(boundary))
    a, b, c = vertices[triangles[:, 0]], vertices[triangles[:, 1]], vertices[triangles[:, 2]]
    double_area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    # Rhino's archive-validity and topological-solid predicates allow collinear
    # triangles with distinct vertices. They contribute no area/volume; report
    # their count separately rather than silently removing source triangles.
    # A local origin prevents catastrophic cancellation at site coordinates.
    origin = vertices.mean(axis=0)
    signed_volume = float(np.einsum('ij,ij->i', a - origin,
                                   np.cross(b - origin, c - origin)).sum() / 6e9)
    area = float(double_area.sum() * .5e-6)
    naked = edges[boundary]
    length = float(np.linalg.norm(positions[naked[:, 0]] - positions[naked[:, 1]], axis=1).sum() / 1000)
    if not all(math.isfinite(v) for v in (area, signed_volume, length)):
        raise ValueError('Mesh integrals are not finite')
    solid = valid and closed and manifold and oriented
    return {'is_valid': valid, 'is_closed': closed, 'is_manifold': manifold,
            'is_oriented': oriented, 'is_solid': solid,
            'area_m2': area, 'volume_m3': abs(signed_volume) if solid else None,
            'naked_edge_length_m': length, 'boundary_edges': int(boundary.sum()),
            'zero_area_triangles': int((double_area == 0).sum()),
            'nonmanifold_edges': int((counts > 2).sum()),
            'orientation_conflicts': int(((counts == 2) & (balance != 0)).sum())}


def verify_record(mesh, record):
    """Reject forged topology and supplied/omitted volumes, including NaN."""
    actual = topology(*arrays(mesh))
    errors = []
    for key in ('is_valid', 'is_closed', 'is_manifold', 'is_oriented', 'is_solid'):
        if type(record.get(key)) is not bool or record[key] != actual[key]:
            errors.append('Actual mesh topology mismatch: ' + key)
    for key, relative, floor in (('area_m2', 2e-6, 1e-6),
                                  ('naked_edge_length_m', 2e-6, 1e-6)):
        value = record.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            errors.append('Nonfinite/missing mesh metric: ' + key)
        elif abs(value - actual[key]) > max(floor, abs(actual[key]) * relative):
            errors.append('Actual mesh metric mismatch: ' + key)
    supplied = record.get('volume_m3')
    if not actual['is_solid']:
        if supplied is not None:
            errors.append('Volume supplied for an actual non-solid mesh')
    elif isinstance(supplied, bool) or not isinstance(supplied, (int, float)) or not math.isfinite(supplied):
        errors.append('Actual solid volume missing or nonfinite')
    elif abs(supplied - actual['volume_m3']) > max(1e-8, actual['volume_m3'] * 2e-5):
        errors.append('Actual solid volume mismatch')
    if not isinstance(record.get('volume_reason'), str) or not record['volume_reason'].strip():
        errors.append('Mesh volume interpretation is missing')
    return actual, errors
