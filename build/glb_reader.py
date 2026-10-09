"""Read the uncompressed GLB geometry published in this repository."""
import json
import struct

import numpy as np

CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16,
      5125: np.uint32, 5126: np.float32}
NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


def read_glb(path):
    with open(path, 'rb') as stream:
        data = stream.read()
    magic, version, total = struct.unpack_from('<III', data)
    if magic != 0x46546C67 or version != 2 or total != len(data):
        raise ValueError('Expected a complete GLB 2.0 file: ' + str(path))
    offset, document, binary = 12, None, None
    while offset < total:
        length, kind = struct.unpack_from('<II', data, offset)
        offset += 8
        if offset + length > total:
            raise ValueError('Truncated GLB chunk: ' + str(path))
        if kind == 0x4E4F534A:
            document = json.loads(data[offset:offset + length])
        elif kind == 0x004E4942:
            binary = data[offset:offset + length]
        offset += length
    if document is None or binary is None:
        raise ValueError('GLB is missing its JSON or BIN chunk: ' + str(path))
    return document, binary


def accessor(document, binary, index):
    spec = document['accessors'][index]
    if 'sparse' in spec:
        raise ValueError('Sparse accessors are not supported by this exporter')
    view = document['bufferViews'][spec['bufferView']]
    dtype = np.dtype(CT[spec['componentType']]).newbyteorder('<')
    width, count = NC[spec['type']], spec['count']
    start = view.get('byteOffset', 0) + spec.get('byteOffset', 0)
    stride = view.get('byteStride', dtype.itemsize * width)
    values = np.ndarray((count, width), dtype=dtype, buffer=binary,
                        offset=start, strides=(stride, dtype.itemsize))
    if spec.get('normalized') and np.issubdtype(dtype, np.integer):
        limits = np.iinfo(dtype)
        values = values.astype(np.float64) / limits.max
        if limits.min < 0:
            values = np.maximum(values, -1.0)
    return values


def node_matrix(node):
    if 'matrix' in node:
        return np.array(node['matrix'], dtype=np.float64).reshape(4, 4).T
    matrix = np.eye(4)
    if 'scale' in node:
        matrix = np.diag([*node['scale'], 1.0]) @ matrix
    if 'rotation' in node:
        x, y, z, w = node['rotation']
        rotation = np.array([
            [1 - 2 * (y*y + z*z), 2 * (x*y - z*w), 2 * (x*z + y*w)],
            [2 * (x*y + z*w), 1 - 2 * (x*x + z*z), 2 * (y*z - x*w)],
            [2 * (x*z - y*w), 2 * (y*z + x*w), 1 - 2 * (x*x + y*y)]])
        transform = np.eye(4)
        transform[:3, :3] = rotation
        matrix = transform @ matrix
    if 'translation' in node:
        transform = np.eye(4)
        transform[:3, 3] = node['translation']
        matrix = transform @ matrix
    return matrix


def walk(document):
    scene = document['scenes'][document.get('scene', 0)]
    stack = [(index, np.eye(4), ()) for index in reversed(scene['nodes'])]
    while stack:
        index, parent, ancestors = stack.pop()
        node = document['nodes'][index]
        world = parent @ node_matrix(node)
        yield index, world, ancestors
        for child in reversed(node.get('children', [])):
            stack.append((child, world, ancestors + (node.get('name', ''),)))
