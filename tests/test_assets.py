"""Small corrupted fixtures exercise checks without altering published assets."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate_assets", ROOT / "checks" / "validate_assets.py")
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


def triangle():
    binary = struct.pack("<9f3I", 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 2)
    doc = dict(asset={"version": "2.0"}, buffers=[{"byteLength": len(binary)}],
               bufferViews=[{"buffer": 0, "byteOffset": 0, "byteLength": 36},
                            {"buffer": 0, "byteOffset": 36, "byteLength": 12}],
               accessors=[{"bufferView": 0, "componentType": 5126, "type": "VEC3", "count": 3},
                          {"bufferView": 1, "componentType": 5125, "type": "SCALAR", "count": 3}],
               meshes=[{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
               materials=[{"name": "WHITE"}], nodes=[{"mesh": 0}], scenes=[{"nodes": [0]}], scene=0)
    return doc, binary


def glb(doc, binary):
    text = json.dumps(doc).encode()
    text += b" " * (-len(text) % 4)
    padded = binary + b"\0" * (-len(binary) % 4)
    return (struct.pack("<4sII", b"glTF", 2, 28 + len(text) + len(padded))
            + struct.pack("<II", len(text), 0x4E4F534A) + text
            + struct.pack("<II", len(padded), 0x004E4942) + padded)


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_model(self, doc, binary):
        path = self.root / "triangle.glb"
        path.write_bytes(glb(doc, binary))
        return path

    def test_valid_triangle_and_nonzero_accessor_offset(self):
        doc, binary = triangle()
        # Unused leading words in the POSITION bufferView are legal.
        binary = b"\0" * 4 + binary
        doc["buffers"][0]["byteLength"] += 4
        doc["bufferViews"][0]["byteLength"] += 4
        doc["bufferViews"][1]["byteOffset"] += 4
        doc["accessors"][0]["byteOffset"] = 4
        result = assets.validate_glb(self.write_model(doc, binary))
        self.assertEqual(result["triangles"], 1)
        self.assertEqual(result["materials"], ["WHITE"])

    def test_corrupt_binary_container_fails(self):
        doc, binary = triangle()
        good = glb(doc, binary)
        for label, bad in (("truncated", good[:-1]), ("wrong magic", b"BAD!" + good[4:]),
                           ("chunk size", good[:12] + struct.pack("<I", len(good)) + good[16:])):
            with self.subTest(label=label):
                path = self.root / "broken.glb"
                path.write_bytes(bad)
                with self.assertRaises(assets.AssetError):
                    assets.validate_glb(path)

    def test_corrupt_ranges_and_references_fail(self):
        original, binary = triangle()
        changes = [
            ("buffer", lambda d: d["buffers"][0].update(byteLength=4), "BIN length"),
            ("view", lambda d: d["bufferViews"][1].update(byteLength=16), "bufferView exceeds"),
            ("accessor", lambda d: d["accessors"][0].update(count=4), "accessor exceeds"),
            ("alignment", lambda d: d["accessors"][0].update(byteOffset=1), "aligned"),
            ("triangle count", lambda d: d["accessors"][1].update(count=2), "divisible"),
            ("negative reference", lambda d: d["accessors"][0].update(bufferView=-1), "integer"),
            ("bool count", lambda d: d["accessors"][0].update(count=True), "integer"),
            ("material", lambda d: d["meshes"][0]["primitives"][0].update(material=3), "material"),
            ("node", lambda d: d["scenes"][0].update(nodes=[5]), "scene.nodes"),
            ("sparse unsupported", lambda d: d["accessors"][0].update(sparse={}), "sparse"),
        ]
        for label, change, message in changes:
            with self.subTest(label=label):
                doc = copy.deepcopy(original)
                change(doc)
                with self.assertRaisesRegex(assets.AssetError, message):
                    assets.validate_glb(self.write_model(doc, binary))

    def test_binary_values_are_checked_not_just_metadata(self):
        doc, good = triangle()
        for label, offset, fmt, value, message in (("index", 44, "<I", 3, "index exceeds"),
                                                  ("nan", 0, "<f", float("nan"), "nonfinite")):
            with self.subTest(label=label):
                bad = bytearray(good)
                struct.pack_into(fmt, bad, offset, value)
                with self.assertRaisesRegex(assets.AssetError, message):
                    assets.validate_glb(self.write_model(doc, bad))

    def test_attribute_semantics_require_the_correct_float_shape(self):
        original, binary = triangle()
        # Explicit normal and UV streams, each with three vertices.
        binary += struct.pack("<9f6f", *(0, 0, 1) * 3, 0, 0, 1, 0, 0, 1)
        original["buffers"][0]["byteLength"] = len(binary)
        original["bufferViews"] += [{"buffer": 0, "byteOffset": 48, "byteLength": 36},
                                     {"buffer": 0, "byteOffset": 84, "byteLength": 24}]
        original["accessors"] += [{"bufferView": 2, "componentType": 5126, "type": "VEC3", "count": 3},
                                   {"bufferView": 3, "componentType": 5126, "type": "VEC2", "count": 3}]
        original["meshes"][0]["primitives"][0]["attributes"].update(NORMAL=2, TEXCOORD_0=3)
        self.assertEqual(assets.validate_glb(self.write_model(original, binary))["triangles"], 1)
        for semantic, wrong_index in (("NORMAL", 1), ("NORMAL", 3), ("TEXCOORD_0", 0), ("TEXCOORD_0", 1)):
            with self.subTest(semantic=semantic, wrong_index=wrong_index):
                doc = copy.deepcopy(original)
                doc["meshes"][0]["primitives"][0]["attributes"][semantic] = wrong_index
                with self.assertRaisesRegex(assets.AssetError, semantic):
                    assets.validate_glb(self.write_model(doc, binary))

    def test_node_hierarchy_rejects_cycles_and_multiple_parents(self):
        cases = {
            "self cycle": [{"children": [0]}],
            "two node cycle": [{"children": [1]}, {"children": [0]}],
            "unreachable cycle": [{}, {"children": [2]}, {"children": [1]}],
            "two parents": [{"children": [2]}, {"children": [2]}, {}],
            "repeated child": [{"children": [1, 1]}, {}],
        }
        for label, nodes in cases.items():
            with self.subTest(label=label):
                doc, binary = triangle()
                doc["nodes"] = nodes
                with self.assertRaisesRegex(assets.AssetError, "cycle|parent"):
                    assets.validate_glb(self.write_model(doc, binary))

    def test_disjoint_node_trees_and_shared_scene_roots_remain_valid(self):
        doc, binary = triangle()
        doc["nodes"] = [{"children": [1]}, {"mesh": 0}, {"mesh": 0}]
        doc["scenes"] = [{"nodes": [0, 2]}, {"nodes": [0]}]
        self.assertEqual(assets.validate_glb(self.write_model(doc, binary))["triangles"], 1)

    def test_scene_cannot_list_a_child_as_a_root(self):
        doc, binary = triangle()
        doc["nodes"] = [{"children": [1]}, {"mesh": 0}]
        doc["scenes"] = [{"nodes": [1]}]
        with self.assertRaisesRegex(assets.AssetError, "root"):
            assets.validate_glb(self.write_model(doc, binary))

    def test_json_rejects_overflow_and_nonfinite_literals_at_any_depth(self):
        for number in ("1e309", "-1e309", "NaN", "Infinity", "-Infinity"):
            with self.subTest(number=number), self.assertRaisesRegex(assets.AssetError, "nonfinite"):
                assets.read_json('{"nested":{"values":[' + number + ']}}')
        self.assertEqual(assets.read_json('{"scale":[1e308,-1.5,0]}'), {"scale": [1e308, -1.5, 0]})

    def material_file(self, materials):
        (self.root / "model").mkdir(exist_ok=True)
        (self.root / "model" / "materials.json").write_text(json.dumps(materials), encoding="utf-8")

    def test_material_alias_and_texture_integrity(self):
        material = {"hex": "#ffffff", "roughness": 0.5, "metalness": 0}
        self.material_file({"WHITE": material, "OLD": dict(material, alias_of="WHITE")})
        self.assertEqual(len(assets.validate_materials(self.root)[0]), 2)
        for bad, message in ((dict(material, alias_of="missing"), "missing material alias"),
                             (dict(material, alias_of="WHITE"), "alias cycle"),
                             (dict(material, textures={"map": {"file": "textures/missing.jpg"}}), "missing"),
                             (dict(material, roughness=float("nan")), "nonfinite")):
            with self.subTest(message=message):
                self.material_file({"WHITE": bad})
                with self.assertRaisesRegex(assets.AssetError, message):
                    assets.validate_materials(self.root)

    def test_required_dependency_closure_and_dynamic_import(self):
        (self.root / "index.html").write_text('<script type="importmap">'
            '{"imports":{"library/":"./vendor/"}}</script><script type="module" src="viewer.js"></script>')
        (self.root / "viewer.js").write_text("import {f} from 'library/a.js';\nimport('library/optional.js');")
        (self.root / "vendor").mkdir()
        (self.root / "vendor" / "a.js").write_text("export {f} from './b.js';")
        (self.root / "vendor" / "b.js").write_text("export const f = 1;")
        optional = self.root / "vendor" / "optional.js"
        optional.write_text("export const g = 1;")
        self.assertEqual(len(assets.validate_dependencies(self.root)["modules"]), 4)
        for missing in (optional, self.root / "vendor" / "b.js"):
            saved = missing.read_bytes()
            missing.unlink()
            with self.assertRaisesRegex(assets.AssetError, "missing"):
                assets.validate_dependencies(self.root)
            missing.write_bytes(saved)

    def test_viewer_json_resources_are_parsed_not_only_checked_for_existence(self):
        (self.root / "index.html").write_text('<script type="module" src="viewer.js"></script>')
        (self.root / "viewer.js").write_text("fetch('model/site_features.json');")
        (self.root / "model").mkdir()
        resource = self.root / "model" / "site_features.json"
        for text in ("not JSON", '{"palms":[1e309]}', '{"palms":[],"palms":[]}'):
            with self.subTest(text=text):
                resource.write_text(text)
                with self.assertRaises(ValueError):
                    assets.validate_dependencies(self.root)
        resource.write_text('{"palms":[],"trees":[]}')
        self.assertEqual(assets.validate_dependencies(self.root)["resources"], ["model/site_features.json"])

    def test_browser_path_case_and_repository_boundary(self):
        (self.root / "Exact.js").write_text("export const a=1;")
        self.assertTrue(assets.local_file(self.root, "Exact.js?v=2").is_file())
        for bad in ("exact.js", "../outside.js", "https://example.com/code.js"):
            with self.subTest(path=bad), self.assertRaises(assets.AssetError):
                assets.local_file(self.root, bad)

    def test_published_assets_match_declared_totals(self):
        result = assets.validate_public_assets(ROOT)
        self.assertEqual(result["triangles"], 2_223_601)
        self.assertEqual(result["material_count"], 83)
        self.assertEqual(len(result["models"]), 7)
        self.assertEqual(set(result["material_fallbacks"]), assets.FALLBACK_MATERIALS)


if __name__ == "__main__":
    unittest.main()
