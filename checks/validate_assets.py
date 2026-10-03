"""Read-only checks for the published assets; no private build inputs or packages.

This is a check of this repository's uncompressed, dense triangle GLB profile,
not a general glTF conformance validator. Unsupported profiles fail explicitly.
External textures are checked for local paths and nonempty files; embedded PNGs
are checked only for Base64 encoding and their signature, not decoded pixels.
JSON resources are parsed for syntax, unique keys and finite floating-point values;
their application-specific schema and material measurement provenance are not verified.
Layout rules: https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html
"""
from __future__ import annotations

import argparse
import base64
import hashlib
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MODELS = ("site_context", "site_ground", "vmu01_canopy", "vmu02", "vmu04", "vmu05", "vmu_cad")
TRIANGLES = 2_223_601
MATERIALS = 83
# These published context finishes deliberately use viewer/embedded GLB fallbacks.
FALLBACK_MATERIALS = {"CTX_STEEL_GREY", "CTX_FENCE_MESH", "CTX_LAMP", "CTX_CONTAINER_GREY"}


class AssetError(ValueError):
    """A public asset is missing, malformed or outside the supported profile."""


def require(ok, message):
    if not ok:
        raise AssetError(message)


def integer(value, label, minimum=0):
    require(type(value) is int and value >= minimum, f"{label}: expected integer >= {minimum}")
    return value


def reference(items, index, label):
    integer(index, label)
    require(index < len(items), f"{label}: reference out of range")
    return items[index]


def read_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result
    def bad_constant(value):
        raise AssetError(f"nonfinite JSON number: {value}")
    def finite_float(value):
        number = float(value)
        require(math.isfinite(number), f"nonfinite JSON number: {value}")
        return number
    return json.loads(text, object_pairs_hook=unique, parse_constant=bad_constant, parse_float=finite_float)


def validate_glb(path):
    """Validate binary ranges and actual index/float values; count stored triangles."""
    path = Path(path)
    data = path.read_bytes()
    require(len(data) >= 20, f"{path.name}: truncated GLB header")
    magic, version, length = struct.unpack_from("<4sII", data)
    require((magic, version, length) == (b"glTF", 2, len(data)), f"{path.name}: GLB header/length")
    chunks, offset = [], 12
    while offset < len(data):
        require(offset + 8 <= len(data), f"{path.name}: truncated chunk header")
        size, kind = struct.unpack_from("<II", data, offset)
        require(size % 4 == 0 and offset + 8 + size <= len(data), f"{path.name}: chunk boundary")
        chunks.append((kind, memoryview(data)[offset + 8:offset + 8 + size]))
        offset += 8 + size
    require([c[0] for c in chunks] == [0x4E4F534A, 0x004E4942], f"{path.name}: expected JSON then BIN")
    doc, binary = read_json(bytes(chunks[0][1])), chunks[1][1]
    require(doc.get("asset", {}).get("version") == "2.0", "asset.version must be 2.0")
    require(not doc.get("extensionsRequired"), "required extensions unsupported")
    buffers = doc["buffers"]
    require(len(buffers) == 1 and "uri" not in buffers[0], "expected one embedded buffer")
    size = integer(buffers[0]["byteLength"], "buffer.byteLength", 1)
    require(size <= len(binary) <= size + 3, "BIN length disagrees with buffer.byteLength")
    views, accessors = doc["bufferViews"], doc["accessors"]
    for view in views:
        require(view["buffer"] == 0, "bufferView references non-embedded buffer")
        start = integer(view.get("byteOffset", 0), "bufferView.byteOffset")
        size_view = integer(view["byteLength"], "bufferView.byteLength", 1)
        require(start + size_view <= size, "bufferView exceeds buffer")
        require("byteStride" not in view, "interleaved bufferViews unsupported by published profile")
    decoded = []
    for accessor in accessors:
        require("sparse" not in accessor, "sparse accessors unsupported by published profile")
        view = reference(views, accessor["bufferView"], "accessor.bufferView")
        component, kind = accessor["componentType"], accessor["type"]
        require((component, kind) in ((5126, "VEC2"), (5126, "VEC3"), (5125, "SCALAR")),
                "unsupported accessor component/type in published profile")
        count = integer(accessor["count"], "accessor.count", 1)
        offset = integer(accessor.get("byteOffset", 0), "accessor.byteOffset")
        start = view.get("byteOffset", 0) + offset
        width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[kind]
        require(offset % 4 == 0 and start % 4 == 0, "accessor is not component-aligned")
        require(offset + count * width * 4 <= view["byteLength"], "accessor exceeds bufferView")
        payload = binary[start:start + count * width * 4]
        if component == 5126:
            require(all(math.isfinite(v[0]) for v in struct.iter_unpack("<f", payload)),
                    "accessor contains nonfinite float")
            decoded.append(None)
        else:
            decoded.append(max(v[0] for v in struct.iter_unpack("<I", payload)))
    triangles = 0
    for mesh in doc["meshes"]:
        for primitive in mesh["primitives"]:
            require(primitive.get("mode", 4) == 4, "only TRIANGLES are supported")
            attrs = primitive["attributes"]
            position = reference(accessors, attrs["POSITION"], "POSITION")
            require((position["componentType"], position["type"]) == (5126, "VEC3"), "invalid POSITION")
            for semantic, index in attrs.items():
                attribute = reference(accessors, index, "attribute")
                require(attribute["count"] == position["count"], "attribute count differs from POSITION")
                if semantic == "NORMAL" or re.fullmatch(r"TEXCOORD_[0-9]+", semantic):
                    shape = "VEC3" if semantic == "NORMAL" else "VEC2"
                    require((attribute["componentType"], attribute["type"]) == (5126, shape),
                            f"invalid {semantic}: expected FLOAT/{shape} in published profile")
            index = primitive["indices"]
            indices = reference(accessors, index, "indices")
            require((indices["componentType"], indices["type"]) == (5125, "SCALAR"), "invalid indices")
            require(indices["count"] % 3 == 0, "triangle index count not divisible by three")
            require(decoded[index] < position["count"], "index exceeds POSITION vertex count")
            if "material" in primitive:
                reference(doc.get("materials", []), primitive["material"], "primitive.material")
            triangles += indices["count"] // 3
    nodes = doc["nodes"]
    parents = [None] * len(nodes)
    for index, node in enumerate(nodes):
        if "mesh" in node:
            reference(doc["meshes"], node["mesh"], "node.mesh")
        for child in node.get("children", []):
            reference(nodes, child, "node.children")
            require(parents[child] is None, "node has multiple or repeated parents")
            parents[child] = index
    # Inspect every node, including components not reached by the active scene.
    # With one parent per node, nodes unreachable from any root form a cycle.
    pending = [i for i, parent in enumerate(parents) if parent is None]
    visited = 0
    while pending:
        visited += 1
        pending.extend(nodes[pending.pop()].get("children", []))
    require(visited == len(nodes), "node hierarchy contains a cycle")
    reference(doc["scenes"], doc.get("scene", 0), "scene")
    for scene in doc["scenes"]:
        for node in scene["nodes"]:
            reference(nodes, node, "scene.nodes")
            require(parents[node] is None, "scene.nodes must contain only root nodes")
    return dict(file=path.name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                triangles=triangles, materials=[m["name"] for m in doc.get("materials", [])])


def local_file(root, uri, parent=None):
    """Resolve browser-relative paths, including case-sensitive checks on Windows."""
    parts = urlsplit(uri)
    require(not parts.scheme and not parts.netloc and not parts.path.startswith("/"), f"nonlocal asset: {uri}")
    root = Path(root).resolve()
    # resolve() on Windows normalises existing filename case. Keep the spelling
    # from the URL for the case check, while still checking the resolved target.
    path = Path(os.path.abspath((parent or root) / unquote(parts.path)))
    require(path.is_relative_to(root) and path.resolve().is_relative_to(root), f"asset escapes repository: {uri}")
    cursor = root
    for part in path.relative_to(root).parts:
        require(cursor.is_dir() and part in {p.name for p in cursor.iterdir()}, f"missing/case-mismatched asset: {uri}")
        cursor /= part
    require(path.is_file() and path.stat().st_size > 0, f"empty or missing asset: {uri}")
    return path


def validate_materials(root):
    materials = read_json(local_file(root, "model/materials.json").read_text(encoding="utf-8"))
    require(isinstance(materials, dict) and materials, "materials must be a nonempty mapping")
    textures = set()
    for name, material in materials.items():
        require(re.fullmatch(r"#[0-9a-fA-F]{6}", material["hex"]) is not None, f"invalid colour: {name}")
        for key in ("roughness", "metalness"):
            value = material[key]
            require(type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 1,
                    f"invalid {key}: {name}")
        seen, current = set(), name
        while "alias_of" in materials[current]:
            require(current not in seen, f"material alias cycle: {name}")
            seen.add(current)
            current = materials[current]["alias_of"]
            require(current in materials, f"missing material alias: {current}")
        for value in material.get("textures", {}).values():
            if isinstance(value, dict) and "file" in value:
                uri = value["file"]
                if uri.startswith("data:"):
                    require(uri.startswith("data:image/png;base64,"), "unsupported embedded texture")
                    payload = base64.b64decode(uri.split(",", 1)[1], validate=True)
                    require(payload.startswith(b"\x89PNG\r\n\x1a\n"), "invalid embedded PNG signature")
                else:
                    textures.add(local_file(root, uri).relative_to(root).as_posix())
    return materials, sorted(textures)


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.imports, self.scripts, self.in_map = {}, [], False
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.in_map = attrs.get("type") == "importmap"
            if attrs.get("src"):
                self.scripts.append(attrs["src"])

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_map = False

    def handle_data(self, data):
        if self.in_map:
            self.imports.update(read_json(data)["imports"])


# Literal imports in the checked-in ES modules (not a general JavaScript parser).
IMPORT = re.compile(r"(?:^|[;\n])\s*(?:import|export)\s+(?:[\w$*{},\s]+\s+from\s+)?['\"]([^'\"]+)['\"]")
DYNAMIC_IMPORT = re.compile(r"\bimport\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")


def validate_dependencies(root):
    root = Path(root).resolve()
    page = Page(local_file(root, "index.html").read_text(encoding="utf-8"))
    require(page.scripts, "index.html has no external scripts")
    pending = [local_file(root, uri) for uri in page.scripts]
    visited = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
        for name in IMPORT.findall(text) + DYNAMIC_IMPORT.findall(text):
            if name.startswith("."):
                target = local_file(root, name, path.parent)
            else:
                keys = [k for k in page.imports if name == k or (k.endswith("/") and name.startswith(k))]
                require(keys, f"unmapped JavaScript import: {name}")
                key = max(keys, key=len)
                target = local_file(root, page.imports[key] + name[len(key):])
            pending.append(target)
    viewer = local_file(root, "viewer.js").read_text(encoding="utf-8")
    resources = set(re.findall(r"['\"]((?:textures|model)/[^'\"\r\n]+\.(?:png|jpg|hdr|json|glb))['\"]", viewer))
    for uri in resources:
        path = local_file(root, uri)
        if path.suffix == ".json":
            read_json(path.read_text(encoding="utf-8"))
    return dict(modules=sorted(p.relative_to(root).as_posix() for p in visited), resources=sorted(resources))


def validate_public_assets(root=ROOT):
    root = Path(root).resolve()
    expected = {name + ".glb" for name in MODELS}
    require({p.name for p in (root / "model").glob("*.glb")} == expected, "published GLB file set differs")
    models = [validate_glb(root / "model" / name) for name in sorted(expected)]
    triangles = sum(m["triangles"] for m in models)
    require(triangles == TRIANGLES, f"triangle total: expected {TRIANGLES}, got {triangles}")
    materials, textures = validate_materials(root)
    require(len(materials) == MATERIALS, f"material count: expected {MATERIALS}, got {len(materials)}")
    fallback = {name for model in models for name in model["materials"] if name not in materials}
    require(fallback <= FALLBACK_MATERIALS, f"unrecognised material fallbacks: {sorted(fallback - FALLBACK_MATERIALS)}")
    dependencies = validate_dependencies(root)
    return dict(status="passed", models=models, triangles=triangles, material_count=len(materials),
                material_fallbacks=sorted(fallback), textures=textures, **dependencies)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        report = validate_public_assets(args.root)
    except (ValueError, OSError, KeyError, TypeError, struct.error) as exc:
        print(f"asset validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
