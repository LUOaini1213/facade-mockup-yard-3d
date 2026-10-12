"""Regression tests for texture fidelity and stable native Rhino identities."""
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rhino3dm as r

from glb_reader import accessor
from rhino_mesh import make_mesh, component_id, source_key, world_uv


class RhinoMeshTests(unittest.TestCase):
    def setUp(self):
        self.vertices = np.array([[0., 0., 0.], [1000., 0., 0.], [0., 1000., 0.]])
        self.faces = np.array([[0, 1, 2]], dtype=np.int64)
        self.normals = np.array([[0., 0., 1.]] * 3)

    def test_uv_and_id_survive_native_file_roundtrip(self):
        # Outside [0,1] is valid glTF tiling and must not be clamped or flipped.
        uv = np.array([[-0.25, 2.5], [0.5, 0.0], [3.0, -1.0]], dtype=np.float32)
        mesh = make_mesh(self.vertices, self.faces, self.normals, uv)
        key = source_key('sample.glb', 2, 3)
        attrs = r.ObjectAttributes()
        attrs.Id = component_id(key)
        attrs.SetUserString('source_key', key)
        doc = r.File3dm()
        doc.Settings.ModelUnitSystem = r.UnitSystem.Millimeters
        self.assertEqual(doc.Objects.AddMesh(mesh, attrs), component_id(key))
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'sample.3dm')
            self.assertTrue(doc.Write(path, 8))
            restored = r.File3dm.Read(path)
        obj = list(restored.Objects)[0]
        self.assertEqual(obj.Attributes.Id, component_id(key))
        self.assertEqual(obj.Attributes.GetUserString('source_key'), key)
        actual_uv = np.array([(p.X, p.Y) for p in obj.Geometry.TextureCoordinates])
        np.testing.assert_array_equal(actual_uv, uv)
        self.assertEqual(len(obj.Geometry.Normals), 3)

    def test_id_is_stable_and_distinguishes_source_primitives(self):
        key = source_key('sample.glb', 2, 3)
        self.assertEqual(component_id(key), component_id(key))
        self.assertNotEqual(component_id(key), component_id(source_key('sample.glb', 2, 4)))
        self.assertNotEqual(component_id(key), component_id(source_key('other.glb', 2, 3)))

    def test_reject_mismatched_or_nonfinite_uv(self):
        for uv in (np.zeros((2, 2)), np.array([[0, 0], [1, 1], [np.nan, 0]])):
            with self.assertRaises(ValueError):
                make_mesh(self.vertices, self.faces, self.normals, uv)

    def test_normalized_interleaved_uv_accessor(self):
        binary = b''.join(struct.pack('<HHI', u, v, 123) for u, v in [(0, 65535), (32768, 16384)])
        document = {'accessors': [{'bufferView': 0, 'componentType': 5123, 'count': 2,
                                  'type': 'VEC2', 'normalized': True}],
                    'bufferViews': [{'byteStride': 8}]}
        np.testing.assert_allclose(accessor(document, binary, 0),
                                   np.array([[0, 1], [32768/65535, 16384/65535]]))

    def test_mesh_without_uv_stays_without_uv(self):
        self.assertEqual(len(make_mesh(self.vertices, self.faces).TextureCoordinates), 0)

    def test_collapsed_face_is_removed_without_changing_uv_or_vertices(self):
        vertices = np.vstack([self.vertices, self.vertices[1]])
        faces = np.array([[0, 1, 2], [0, 1, 3]], dtype=np.int64)
        uv = np.array([[0., 0.], [1., 0.], [0., 1.], [1., 1.]])
        mesh = make_mesh(vertices, faces, uv=uv)
        self.assertTrue(mesh.IsValid)
        self.assertEqual(len(mesh.Faces), 1)
        self.assertEqual(len(mesh.Vertices), 4)
        np.testing.assert_array_equal(np.array([(p.X, p.Y) for p in mesh.TextureCoordinates]), uv)

    def test_world_uv_respects_millimetres_and_normal_directions(self):
        p=np.array([[1000,2000,3000]]*5)
        n=np.array([[0,0,1],[1,0,0],[-1,0,0],[0,-1,0],[0,1,0]])
        np.testing.assert_array_equal(world_uv(p,n),[[1,2],[-2,3],[2,3],[-1,3],[1,3]])


if __name__ == '__main__':
    unittest.main()
