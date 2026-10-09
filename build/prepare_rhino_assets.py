"""Package public textures and split linear ARM channels for native Rhino PBR."""
import base64
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image
from glb_reader import read_glb

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / 'model' / 'rhino_assets'


def tint_srgb(pixels, multiplier):
    """Apply a linear-light tint; map PNG data returns to sRGB for Rhino."""
    srgb = np.asarray(pixels,dtype=float)/255.0
    linear = np.where(srgb <= .04045,srgb/12.92,((srgb+.055)/1.055)**2.4)
    linear *= np.asarray(multiplier)
    return np.where(linear <= .0031308,linear*12.92,
                    1.055*np.maximum(linear,0)**(1/2.4)-.055)*255


def split_arm(pixels, roughness):
    """Return the public viewer's effective AO and roughness, with B unused."""
    values=np.asarray(pixels,dtype=float)
    return 255+.7*(values[...,0]-255), values[...,1]*roughness


def read_image(reference):
    if reference.startswith('data:'):
        return Image.open(io.BytesIO(base64.b64decode(reference.split(',', 1)[1]))).convert('RGB')
    path = (ROOT / reference).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('Texture must be inside this repository')
    return Image.open(path).convert('RGB')


def write_image(filename, array):
    buffer=io.BytesIO()
    Image.fromarray(np.clip(np.rint(array),0,255).astype(np.uint8)).save(buffer,format='PNG',optimize=True,compress_level=9)
    data=buffer.getvalue()
    filename='asset_'+hashlib.sha256(data).hexdigest()[:20]+'.png'
    path=ASSETS/filename
    path.write_bytes(data)
    return 'rhino_assets/'+filename


def prepare():
    ASSETS.mkdir(parents=True, exist_ok=True)
    # This dedicated directory contains only reproducible generated image files.
    if ASSETS.resolve().parent != (ROOT/'model').resolve():
        raise ValueError('Unexpected generated-assets directory')
    for previous in ASSETS.glob('*.png'):
        previous.unlink()
    database = json.loads((ROOT / 'model' / 'materials.json').read_text(encoding='utf-8'))
    used = set()
    for path in sorted((ROOT / 'model').glob('*.glb')):
        document, _ = read_glb(path)
        used.update(item['name'] for item in document.get('materials', []))
    materials = {}
    for name in sorted(used):
        entry = database.get(name, {})
        textures = entry.get('textures', {})
        item = {'name':name, 'hex':entry.get('hex'), 'metallic':entry.get('metalness', 0),
                'roughness':entry.get('roughness', .6), 'glass':entry.get('glass'),
                'clearcoat':entry.get('clearcoat',0), 'clearcoat_roughness':entry.get('clearcoatRoughness',.3),
                'size_m':textures.get('size_m',1), 'slots':{}}
        for source, target in [('map','base_color'),('normalMap','normal'),('roughnessMap','roughness')]:
            if source not in textures:
                continue
            reference = textures[source]['file']
            image = read_image(reference)
            pixels = np.asarray(image)
            if target == 'roughness':
                # Viewer triRough multiplies base roughness by tex / mean.
                pixels = pixels[...,0].astype(float) * entry.get('roughness',.5) / textures.get('roughness_map_mean',1)
                item['roughness'] = 1.0
            elif target == 'base_color' and textures.get('color_with_map_linear'):
                # Bake the linear multiplier, retaining the canonical body-colour metadata.
                pixels = tint_srgb(pixels,textures['color_with_map_linear'])
                item['base_color_is_baked'] = True
            item['slots'][target] = {'file':write_image(name+'_'+target+'.png',pixels),
                                     'linear':target!='base_color'}
        if 'armMap' in textures:
            pixels = np.asarray(read_image(textures['armMap']['file']))
            channels=split_arm(pixels,textures.get('roughness_with_map',entry.get('roughness',1)))
            item['roughness'] = 1.0
            # The public viewer does not assign metallicMap; retain scalar metallic.
            item['arm_metallic_not_used_by_viewer'] = True
            for target,values in zip(('ao','roughness'),channels):
                item['slots'][target] = {'file':write_image(name+'_'+target+'.png',values),'linear':True}
        materials[name] = item
    files = {}
    for material in materials.values():
        for slot in material['slots'].values():
            path = ROOT / 'model' / slot['file']
            files[slot['file']] = {'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                                  'bytes':path.stat().st_size,'dimensions':list(Image.open(path).size)}
    result = {'schema_version':1,'source':'public materials.json + textures only',
              'materials':materials,'files':files,
              'notes':['ARM channels R=AO, G=roughness, B=metallic; viewer keeps scalar metallic, so B is not applied.',
                       'AO is baked with viewer strength 0.7; roughness multipliers are baked into linear PNGs.',
                       'Original browser GLSL procedural effects are not physical geometry and are documented separately.']}
    (ROOT/'model'/'rhino_assets.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Packaged',len(files),'textures for',sum(bool(m['slots']) for m in materials.values()),'materials')
    return result


if __name__=='__main__':
    prepare()
