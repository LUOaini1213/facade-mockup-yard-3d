"""Derive public textures for Rhino; --check reads without modifying assets."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image
from glb_reader import read_glb
from material_integrity import PUBLIC_GLBS, finite_tree, number, validate_materials

ROOT = Path(__file__).resolve().parent.parent


def load_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: '+key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Non-finite JSON number: '+value)
    return json.loads(Path(path).read_text(encoding='utf-8'),
                      object_pairs_hook=pairs, parse_constant=invalid)


def tint_srgb(pixels, multiplier):
    """Apply a linear-light tint; map PNG data returns to sRGB for Rhino."""
    srgb = np.asarray(pixels, dtype=float)/255.0
    linear = np.where(srgb <= .04045, srgb/12.92, ((srgb+.055)/1.055)**2.4)
    linear *= np.asarray(multiplier)
    return np.where(linear <= .0031308, linear*12.92,
                    1.055*np.maximum(linear, 0)**(1/2.4)-.055)*255


def split_arm(pixels, roughness):
    """Return the public viewer's effective AO and roughness, with B unused."""
    values = np.asarray(pixels, dtype=float)
    return 255+.7*(values[..., 0]-255), values[..., 1]*roughness


def image_bytes(reference, root):
    if reference.startswith('data:'):
        if not reference.startswith('data:image/png;base64,'):
            raise ValueError('Only embedded base64 PNG textures are supported')
        data = base64.b64decode(reference.split(',', 1)[1], validate=True)
        return data, 'embedded:'+hashlib.sha256(data).hexdigest()
    path = (root/reference).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Texture must be inside this repository')
    return path.read_bytes(), path.relative_to(root).as_posix()


def encode_image(array):
    values = np.asarray(array)
    if not np.all(np.isfinite(values)):
        raise ValueError('Generated texture contains non-finite values')
    buffer = io.BytesIO()
    Image.fromarray(np.clip(np.rint(values), 0, 255).astype(np.uint8)).save(
        buffer, format='PNG', optimize=True, compress_level=9)
    data = buffer.getvalue()
    return 'rhino_assets/asset_'+hashlib.sha256(data).hexdigest()[:20]+'.png', data


def validate_glb_materials(document, database, filename):
    finite_tree(document, filename)
    materials = document.get('materials', [])
    if not isinstance(materials, list):
        raise ValueError(filename+': materials must be a list')
    names = []
    for material in materials:
        if not isinstance(material, dict) or material.get('name') not in database:
            raise ValueError(filename+': material name is absent from materials.json')
        names.append(material['name'])
        pbr = material.get('pbrMetallicRoughness', {})
        if not isinstance(pbr, dict):
            raise ValueError(filename+': invalid pbrMetallicRoughness')
        rgba = pbr.get('baseColorFactor', [1, 1, 1, 1])
        if not isinstance(rgba, list) or len(rgba) != 4:
            raise ValueError(filename+': baseColorFactor must have four components')
        for value in rgba:
            number(value, filename+'.baseColorFactor', high=1)
        number(pbr.get('metallicFactor', 1), filename+'.metallicFactor', high=1)
        number(pbr.get('roughnessFactor', 1), filename+'.roughnessFactor', high=1)
    return names


def derive(root=ROOT, database=None):
    """Return a deterministic manifest and PNG bytes; never write or delete."""
    root = Path(root).resolve()
    material_path = root/'model'/'materials.json'
    # Text checkout CRLF/LF is not a different material input; binary GLBs and
    # texture sources below remain bound to their exact bytes.
    raw_materials = material_path.read_bytes().replace(b'\r\n',b'\n')
    database = validate_materials(load_json(material_path) if database is None else database)
    canonical = json.dumps(database, ensure_ascii=False, sort_keys=True,
                           separators=(',', ':'), allow_nan=False).encode('utf-8')
    inputs = {'materials': {'file': 'model/materials.json',
                           'sha256': hashlib.sha256(raw_materials).hexdigest(),
                           'canonical_sha256': hashlib.sha256(canonical).hexdigest()},
              'glbs': {}, 'textures': {}}
    used = set()
    for filename in PUBLIC_GLBS:
        path = root/'model'/filename
        inputs['glbs']['model/'+filename] = hashlib.sha256(path.read_bytes()).hexdigest()
        document, _ = read_glb(path)
        used.update(validate_glb_materials(document, database, filename))
    blobs, materials = {}, {}

    def pixels(reference):
        data, label = image_bytes(reference, root)
        inputs['textures'][label] = hashlib.sha256(data).hexdigest()
        with Image.open(io.BytesIO(data)) as opened:
            return np.asarray(opened.convert('RGB'))

    def slot(values, linear):
        filename, data = encode_image(values)
        blobs[filename] = data
        return {'file': filename, 'linear': linear}

    for name in sorted(used):
        entry = database[name]
        textures = entry.get('textures', {})
        item = {'name': name, 'hex': entry['hex'], 'metallic': entry['metalness'],
                'roughness': entry['roughness'], 'glass': entry.get('glass'),
                'clearcoat': entry.get('clearcoat', 0),
                'clearcoat_roughness': entry.get('clearcoatRoughness', .3),
                'anisotropy': entry.get('anisotropy', 0),
                'alpha': entry.get('alpha',1),
                'emission_linear': entry.get('emission_linear',[0.,0.,0.]),
                'size_m': textures.get('size_m', 1), 'slots': {}}
        for source, target in [('map', 'base_color'), ('normalMap', 'normal'),
                               ('roughnessMap', 'roughness')]:
            if source not in textures:
                continue
            values = pixels(textures[source]['file'])
            if target == 'roughness':
                values = values[..., 0].astype(float)*entry['roughness']/textures.get('roughness_map_mean', 1)
                item['roughness'] = 1.0
            elif target == 'base_color' and 'color_with_map_linear' in textures:
                values = tint_srgb(values, textures['color_with_map_linear'])
                item['base_color_is_baked'] = True
            item['slots'][target] = slot(values, target != 'base_color')
        if 'armMap' in textures:
            channels = split_arm(pixels(textures['armMap']['file']),
                                 textures.get('roughness_with_map', entry['roughness']))
            item['roughness'] = 1.0
            item['arm_metallic_not_used_by_viewer'] = True
            for target, values in zip(('ao', 'roughness'), channels):
                item['slots'][target] = slot(values, True)
        materials[name] = item
    files = {}
    for filename, data in sorted(blobs.items()):
        with Image.open(io.BytesIO(data)) as opened:
            dimensions = list(opened.size)
        files[filename] = {'sha256': hashlib.sha256(data).hexdigest(),
                           'bytes': len(data), 'dimensions': dimensions}
    result = {'schema_version': 2, 'source': 'canonical materials + public GLBs + texture bytes',
              'inputs': inputs, 'materials': materials, 'files': files,
              'notes': ['ARM channels R=AO, G=roughness, B=metallic; viewer keeps scalar metallic, so B is not applied.',
                        'AO uses viewer strength 0.7; roughness and linear colour multipliers are baked into PNGs.',
                        'Vision-glass preview opacity is 1 - 0.85*vlt; canonical IOR is retained. This is a display approximation.',
                        'Browser GLSL procedural effects remain metadata; they are not physical geometry.']}
    return result, blobs


def verify_derived(root=ROOT, manifest=None):
    root = Path(root).resolve()
    expected, blobs = derive(root)
    actual = load_json(root/'model'/'rhino_assets.json') if manifest is None else manifest
    errors = []
    if not isinstance(actual, dict):
        return ['Derived-assets manifest must be an object']
    if set(actual) != set(expected):
        errors.append('Derived-assets manifest fields differ from canonical derivation')
    for key, value in expected.items():
        if actual.get(key) != value:
            errors.append('Derived-assets '+key+' differs from canonical derivation')
    directory = root/'model'/'rhino_assets'
    existing = {'rhino_assets/'+path.name for path in directory.iterdir() if path.is_file()} if directory.exists() else set()
    if existing != set(blobs):
        errors.append('Derived-assets file set has missing or unexpected files')
    for filename, data in blobs.items():
        path = root/'model'/filename
        if not path.exists() or path.read_bytes() != data:
            errors.append(filename+': bytes differ from canonical derivation')
    return errors


def prepare(root=ROOT):
    root = Path(root).resolve()
    result, blobs = derive(root)  # Validate all inputs before touching a previous delivery.
    directory = root/'model'/'rhino_assets'
    if directory.resolve().parent != (root/'model').resolve():
        raise ValueError('Unexpected generated-assets directory')
    directory.mkdir(parents=True, exist_ok=True)
    for filename, data in blobs.items():
        (root/'model'/filename).write_bytes(data)
    for previous in directory.glob('*.png'):
        if 'rhino_assets/'+previous.name not in blobs:
            previous.unlink()
    (root/'model'/'rhino_assets.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print('Packaged', len(blobs), 'textures for', sum(bool(m['slots']) for m in result['materials'].values()), 'materials')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Recompute and compare without writing or deleting')
    args = parser.parse_args()
    if args.check:
        errors = verify_derived()
        print('\n'.join(errors) if errors else 'PASS: derived assets match canonical inputs')
        raise SystemExit(bool(errors))
    prepare()
