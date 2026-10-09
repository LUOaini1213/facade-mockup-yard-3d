"""Canonical inputs, derived caches and saved RDK scalars cannot wash defects."""
import copy
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PIL import Image
import rhino3dm as r
from material_integrity import PUBLIC_GLBS,validate_materials,verify_native_scalars
from prepare_rhino_assets import derive,load_json,prepare,validate_glb_materials,verify_derived

ROOT=Path(__file__).resolve().parent.parent


def fixture(root):
    (root/'model').mkdir()
    table={'SAMPLE':{'hex':'#808080','metalness':.25,'roughness':.5,
                    'textures':{'size_m':2,'map':{'file':'texture.png','colorSpace':'srgb'}}}}
    (root/'model'/'materials.json').write_text(json.dumps(table),encoding='utf-8')
    Image.new('RGB',(2,2),(80,90,100)).save(root/'texture.png')
    document={'asset':{'version':'2.0'},'materials':[{'name':'SAMPLE',
        'pbrMetallicRoughness':{'baseColorFactor':[.5,.5,.5,1],'metallicFactor':.25,'roughnessFactor':.5}}]}
    raw=json.dumps(document).encode();raw+=b' '*((-len(raw))%4)
    glb=struct.pack('<III',0x46546C67,2,28+len(raw))+struct.pack('<II',len(raw),0x4E4F534A)+raw+struct.pack('<II',0,0x004E4942)
    for filename in PUBLIC_GLBS:(root/'model'/filename).write_bytes(glb)
    return table


class MaterialSchemaTests(unittest.TestCase):
    def test_current_canonical_table_is_strict_and_context_registered(self):
        database=validate_materials(load_json(ROOT/'model'/'materials.json'))
        self.assertEqual(len(database),87)
        for name in ('CTX_STEEL_GREY','CTX_FENCE_MESH','CTX_LAMP','CTX_CONTAINER_GREY'):
            self.assertIn(name,database)

    def test_invalid_finite_ranges_scale_and_aliases_rejected(self):
        base={'A':{'hex':'#123456','metalness':0,'roughness':.5}}
        for key,value in [('metalness',True),('roughness',float('nan')),('clearcoat',1.001),('hex','red')]:
            table=copy.deepcopy(base);table['A'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_materials(table)
        for size in (0,-1,float('inf'),True,1e-320):
            table=copy.deepcopy(base);table['A']['textures']={'size_m':size}
            with self.subTest(size=size),self.assertRaises(ValueError):validate_materials(table)
        table=copy.deepcopy(base);table['A']['alias_of']='A'
        with self.assertRaises(ValueError):validate_materials(table)
        table=copy.deepcopy(base);table['A']['unknown_render_field']=1
        with self.assertRaises(ValueError):validate_materials(table)
        table=copy.deepcopy(base);table['A']['procedural']={'type':'woodgrain','typo_scale':2}
        with self.assertRaises(ValueError):validate_materials(table)
        table=copy.deepcopy(base);table['A']['glass']={'ior':1.5,'vlt':.4,'specularColor':[1,float('nan'),0]}
        with self.assertRaises(ValueError):validate_materials(table)

    def test_glb_missing_registered_name_or_nonfinite_scalar_rejected(self):
        table={'A':{'hex':'#123456','metalness':0,'roughness':.5}}
        for material in ({'name':'UNKNOWN'},{'name':'A','pbrMetallicRoughness':{'roughnessFactor':float('inf')}},
                         {'name':'A','pbrMetallicRoughness':{'baseColorFactor':[0,0,0]}}):
            with self.subTest(material=material),self.assertRaises(ValueError):
                validate_glb_materials({'materials':[material]},table,'test.glb')

    def test_json_duplicate_and_nonfinite_constants_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'input.json'
            for text in ('{"roughness":0.2,"roughness":0.8}','{"roughness":NaN}'):
                path.write_text(text)
                with self.assertRaises(ValueError):load_json(path)


class DerivedAssetTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.table=fixture(self.root)

    def test_derive_and_check_are_read_only(self):
        prepare(self.root)
        with (patch.object(Path,'write_bytes',side_effect=AssertionError('write')),
             patch.object(Path,'write_text',side_effect=AssertionError('write')),
             patch.object(Path,'unlink',side_effect=AssertionError('delete'))):
            self.assertEqual(verify_derived(self.root),[])

    def test_source_table_glb_texture_and_derived_bytes_are_bound(self):
        prepare(self.root)
        original=load_json(self.root/'model'/'rhino_assets.json')
        # Matching the cache's own hash is insufficient if its input changed.
        self.table['SAMPLE']['roughness']=.7
        (self.root/'model'/'materials.json').write_text(json.dumps(self.table))
        self.assertTrue(any('materials' in x or 'inputs' in x for x in verify_derived(self.root)))
        self.table['SAMPLE']['roughness']=.5
        (self.root/'model'/'materials.json').write_text(json.dumps(self.table))
        Image.new('RGB',(2,2),(81,90,100)).save(self.root/'texture.png')
        self.assertTrue(any('inputs' in x for x in verify_derived(self.root)))
        prepare(self.root)
        current=load_json(self.root/'model'/'rhino_assets.json')
        filename=next(iter(current['files']))
        (self.root/'model'/filename).write_bytes(b'bad image')
        self.assertTrue(any('bytes differ' in x for x in verify_derived(self.root)))
        current['inputs']['glbs']['model/site_context.glb']='forged'
        self.assertTrue(any('inputs' in x for x in verify_derived(self.root,current)))
        self.assertNotEqual(original['inputs']['textures'],current['inputs']['textures'])

    def test_invalid_input_cannot_delete_prior_assets(self):
        directory=self.root/'model'/'rhino_assets';directory.mkdir()
        previous=directory/'keep.png';previous.write_bytes(b'previous delivery')
        self.table['SAMPLE']['textures']['size_m']=0
        (self.root/'model'/'materials.json').write_text(json.dumps(self.table))
        with self.assertRaises(ValueError):prepare(self.root)
        self.assertEqual(previous.read_bytes(),b'previous delivery')

    def test_crlf_checkout_does_not_change_material_fingerprint(self):
        first,_=derive(self.root)
        path=self.root/'model'/'materials.json'
        text=json.dumps(self.table,indent=2)+'\n';path.write_bytes(text.encode())
        lf,_=derive(self.root)
        path.write_bytes(text.replace('\n','\r\n').encode())
        crlf,_=derive(self.root)
        self.assertEqual(lf,crlf)
        self.assertEqual(first['inputs']['materials']['canonical_sha256'],lf['inputs']['materials']['canonical_sha256'])


class SavedRDKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        native=r.File3dm.Read(str(ROOT/'model'/'vmu_site_future_native.3dm'))
        cls.xml={x.Name:x.XML(True) for x in native.RenderContent if x.Kind=='material'}
        cls.specs=load_json(ROOT/'model'/'rhino_assets.json')['materials']

    def test_real_native_color_roughness_metallic_glass_clearcoat_tampering(self):
        for name in ('AL_T02','GL01_VISION'):
            self.assertEqual(verify_native_scalars(self.xml[name+' | Native PBR'],self.specs[name]),[])
            for key in ('pbr-base-color','pbr-roughness','pbr-metallic','pbr-opacity','pbr-opacity-ior',
                        'pbr-clearcoat','pbr-clearcoat-roughness','pbr-alpha','pbr-emission','pbr-anisotropic'):
                xml=ET.fromstring(self.xml[name+' | Native PBR'])
                parameter=next(p for p in xml.findall('parameters-v8/parameter') if p.get('name')==key)
                parameter.text='0.9,0.9,0.9,1' if key in ('pbr-base-color','pbr-emission') else '0.123456'
                with self.subTest(name=name,key=key):
                    self.assertTrue(verify_native_scalars(xml,self.specs[name]))


if __name__=='__main__':unittest.main()
