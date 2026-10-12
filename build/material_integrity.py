"""Strict public material inputs and the exact native PBR scalar mapping.

No Rhino imports: the same mapping is used by generation and XML readback.
Browser-only glass/procedural recipes remain explicit source metadata.
"""
import math
import re
import xml.etree.ElementTree as ET

PUBLIC_GLBS = ('site_context.glb', 'site_ground.glb', 'vmu01_canopy.glb',
               'vmu02.glb', 'vmu04.glb', 'vmu05.glb', 'vmu_cad.glb')
ENTRY_KEYS = set('Y Y_sce Y_sci alias_of alpha anisotropy category clearcoat clearcoatRoughness codes colour_basis confidence emission_linear glass gloss60_GU hex hex_sci lab_sci legacy linear lrv metalness procedural range roughness specular_pct textures'.split())
TEXTURE_KEYS = set('armMap arm_mean color_with_map_linear license map map_mean_linear normalMap roughnessMap roughness_map_mean roughness_with_map set size_m uv'.split())
GLASS_KEYS = set('envMapIntensity f0_luminance fallback ior ior_for_rext opaque rext rint side specularColor specularColorSpace specularIntensity thickness tint tint_Y tint_for_vlt_threejs tint_linear transmission transparent vlt vlt_effective_threejs'.split())
PROCEDURAL_KEYS=set('type slot grain_axis value_amplitude value_amplitude_range grain_period_m axis pitch_m depth_m profile rib_w_m groove_w_m depths_m'.split())


def number(value, label, low=0, high=None, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + ' must be finite numeric data')
    if (value <= low if positive else value < low) or (high is not None and value > high):
        raise ValueError(label + ' is outside the allowed range')


def finite_tree(value, label='material'):
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(label + ' contains a non-string key')
            finite_tree(item, label + '.' + key)
    elif isinstance(value, list):
        for item in value:
            finite_tree(item, label)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError(label + ' contains nonfinite data')
    elif not isinstance(value, (str, int, float, bool, type(None))):
        raise ValueError(label + ' contains unsupported data')


def colour(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}', value):
        raise ValueError(label + ' must be a six-digit #RRGGBB colour')


def vector(value,label,size,low=0,high=None):
    if not isinstance(value,list) or len(value)!=size:
        raise ValueError(label+' must have '+str(size)+' numeric components')
    for item in value:number(item,label,low=low,high=high)


def strings(table,keys,label):
    for key in keys:
        if key in table and not isinstance(table[key],str):
            raise ValueError(label+'.'+key+' must be a string')


def validate_materials(database):
    if not isinstance(database, dict) or not database:
        raise ValueError('materials.json must be a nonempty name/object table')
    finite_tree(database)
    for name, entry in database.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(entry, dict):
            raise ValueError('Every material requires a nonempty name and object')
        unknown = set(entry) - ENTRY_KEYS
        if unknown:
            raise ValueError(name + ': unknown material fields ' + ', '.join(sorted(unknown)))
        for required in ('hex', 'metalness', 'roughness'):
            if required not in entry:
                raise ValueError(name + ': missing ' + required)
        colour(entry['hex'], name + '.hex')
        if 'hex_sci' in entry:colour(entry['hex_sci'],name+'.hex_sci')
        strings(entry,('category','colour_basis','confidence'),name)
        if 'legacy' in entry and type(entry['legacy']) is not bool:
            raise ValueError(name+'.legacy must be boolean')
        for key in ('Y','Y_sci','Y_sce','lrv'):
            if key in entry:number(entry[key],name+'.'+key,high=1)
        for key in ('specular_pct','gloss60_GU'):
            if key in entry:number(entry[key],name+'.'+key)
        if 'lab_sci' in entry:vector(entry['lab_sci'],name+'.lab_sci',3,low=-math.inf)
        if 'codes' in entry:
            codes=entry['codes']
            if not isinstance(codes,dict) or set(codes)-{'nearest_ral','ral'}:
                raise ValueError(name+': invalid/unknown colour-code fields')
            strings(codes,('nearest_ral','ral'),name+'.codes')
        for key in ('metalness', 'roughness', 'clearcoat', 'clearcoatRoughness', 'anisotropy', 'alpha'):
            if key in entry:
                number(entry[key], name + '.' + key, high=1)
        for key in ('linear','emission_linear'):
            if key in entry:
                if not isinstance(entry[key],list) or len(entry[key])!=3:
                    raise ValueError(name+'.'+key+' must have three channels')
                for value in entry[key]: number(value,name+'.'+key)
        if 'alias_of' in entry and (not isinstance(entry['alias_of'], str) or entry['alias_of'] not in database):
            raise ValueError(name + ': unknown alias target')
        textures = entry.get('textures', {})
        if not isinstance(textures, dict) or set(textures) - TEXTURE_KEYS:
            raise ValueError(name + ': invalid/unknown texture fields')
        maps = set(textures) & {'map', 'normalMap', 'roughnessMap', 'armMap'}
        strings(textures,('set','license','uv'),name+'.textures')
        if maps and 'size_m' not in textures:
            raise ValueError(name + ': textured material requires physical size_m')
        if 'size_m' in textures:
            number(textures['size_m'], name + '.size_m', positive=True)
            if not math.isfinite(1/textures['size_m']):
                raise ValueError(name+': texture repeat must remain finite')
        for key in ('roughness_map_mean', 'roughness_with_map'):
            if key in textures:
                number(textures[key], name + '.' + key, positive=key == 'roughness_map_mean')
        for key in ('color_with_map_linear', 'map_mean_linear', 'arm_mean'):
            if key in textures:
                if not isinstance(textures[key], list) or len(textures[key]) != 3:
                    raise ValueError(name + '.' + key + ' must have three channels')
                for value in textures[key]:
                    number(value, name + '.' + key)
        for key in maps:
            spec = textures[key]
            if not isinstance(spec, dict) or set(spec) - {'file', 'colorSpace', 'convention', 'channels'}:
                raise ValueError(name + ': invalid image specification ' + key)
            if not isinstance(spec.get('file'), str) or not spec['file'].strip():
                raise ValueError(name + ': missing image file ' + key)
            if spec.get('colorSpace') != ('srgb' if key == 'map' else 'linear'):
                raise ValueError(name + ': incorrect image colour space ' + key)
            strings(spec,('convention','channels'),name+'.textures.'+key)
        procedural=entry.get('procedural',{})
        if not isinstance(procedural,dict) or set(procedural)-PROCEDURAL_KEYS:
            raise ValueError(name+': invalid/unknown procedural fields')
        strings(procedural,('type','slot','grain_axis','axis','profile'),name+'.procedural')
        for key in ('value_amplitude','pitch_m','depth_m','rib_w_m','groove_w_m'):
            if key in procedural:number(procedural[key],name+'.procedural.'+key)
        for key in ('value_amplitude_range','grain_period_m'):
            if key in procedural:
                vector(procedural[key],name+'.procedural.'+key,2)
                if procedural[key][0]>procedural[key][1]:raise ValueError(name+': inverted '+key)
        if 'depths_m' in procedural:
            if not isinstance(procedural['depths_m'],list) or not procedural['depths_m']:
                raise ValueError(name+': depths_m must be a nonempty list')
            for value in procedural['depths_m']:number(value,name+'.depths_m')
        ranges=entry.get('range',{})
        if not isinstance(ranges,dict) or set(ranges)-{'lighter_est','darker_est','Y'}:
            raise ValueError(name+': invalid/unknown range fields')
        for key in ('lighter_est','darker_est'):
            if key in ranges:colour(ranges[key],name+'.range.'+key)
        if 'Y' in ranges:
            vector(ranges['Y'],name+'.range.Y',2,high=1)
            if ranges['Y'][0]>ranges['Y'][1]:raise ValueError(name+': inverted Y range')
        glass = entry.get('glass')
        if glass is not None:
            if not isinstance(glass, dict) or set(glass) - GLASS_KEYS:
                raise ValueError(name + ': invalid/unknown glass fields')
            for key in ('opaque', 'transparent'):
                if key in glass and type(glass[key]) is not bool:
                    raise ValueError(name + ': glass.' + key + ' must be boolean')
            number(glass.get('ior'), name + '.glass.ior', low=1)
            if not glass.get('opaque', False):
                number(glass.get('vlt'), name + '.glass.vlt', high=1)
            for key in ('vlt', 'rext', 'rint', 'transmission'):
                if glass.get(key) is not None:
                    number(glass[key], name + '.glass.' + key, high=1)
            if 'thickness' in glass:
                number(glass['thickness'], name + '.glass.thickness')
            for key in ('envMapIntensity','specularIntensity','ior_for_rext'):
                if key in glass:number(glass[key],name+'.glass.'+key)
            for key in ('tint_Y','f0_luminance','vlt_effective_threejs'):
                if key in glass:number(glass[key],name+'.glass.'+key,high=1)
            for key in ('tint','tint_for_vlt_threejs'):
                if key in glass:colour(glass[key],name+'.glass.'+key)
            for key in ('specularColor','tint_linear'):
                if key in glass:vector(glass[key],name+'.glass.'+key,3,high=1)
            strings(glass,('side','specularColorSpace'),name+'.glass')
            if 'specularColorSpace' in glass and glass['specularColorSpace']!='linear':
                raise ValueError(name+': glass specularColorSpace must be linear')
            fallback=glass.get('fallback',{})
            if not isinstance(fallback,dict) or set(fallback)-{'hex','opacity','metalness','roughness','envMapIntensity'}:
                raise ValueError(name+': invalid/unknown glass fallback fields')
            if 'hex' in fallback:colour(fallback['hex'],name+'.glass.fallback.hex')
            for key in ('opacity','metalness','roughness'):
                if key in fallback:number(fallback[key],name+'.glass.fallback.'+key,high=1)
            if 'envMapIntensity' in fallback:number(fallback['envMapIntensity'],name+'.glass.fallback.envMapIntensity')
        # Alias loops are rejected even when the duplicate scalar fields look valid.
        seen, current = set(), name
        while database[current].get('alias_of'):
            if current in seen:
                raise ValueError(name + ': cyclic material alias')
            seen.add(current)
            current = database[current]['alias_of']
    return database


def native_scalars(spec):
    """Only the explicit native mapping, including glass's preview opacity."""
    rgb = '#FFFFFF' if spec.get('base_color_is_baked') else spec['hex']
    base = [int(rgb[i:i + 2], 16) / 255 for i in (1, 3, 5)] + [1.0]
    glass = spec.get('glass')
    vision = glass is not None and not glass.get('opaque', False)
    return {'pbr-base-color': base, 'pbr-metallic': float(spec['metallic']),
            'pbr-roughness': float(spec['roughness']),
            'pbr-clearcoat': float(spec.get('clearcoat', 0)),
            'pbr-clearcoat-roughness': float(spec.get('clearcoat_roughness', .3)),
            'pbr-anisotropic': float(spec.get('anisotropy', 0)),
            'pbr-opacity': 1 - float(glass['vlt']) * .85 if vision else 1.0,
            'pbr-opacity-ior': float(glass['ior']) if vision else 1.0,
            'pbr-alpha': float(spec.get('alpha',1)),
            'pbr-emission': list(spec.get('emission_linear',[0.,0.,0.]))+[1.]}


def verify_native_scalars(xml, spec):
    root = ET.fromstring(xml) if isinstance(xml, str) else xml
    parameters = root.findall('parameters-v8/parameter')
    names = [p.get('name') for p in parameters]
    if len(names) != len(set(names)):
        return ['Duplicate native RDK scalar parameter']
    actual = {p.get('name'): p.text for p in parameters}
    errors = []
    for key, expected in native_scalars(spec).items():
        try:
            observed = [float(v) for v in actual[key].split(',')]
            wanted = expected if isinstance(expected, list) else [expected]
            # RDK colours are float32; scalar values retain double precision.
            tolerance = 1e-6 if isinstance(expected, list) else 1e-9
            if len(observed) != len(wanted) or any(not math.isfinite(a) or abs(a - b) > tolerance for a, b in zip(observed, wanted)):
                errors.append('Saved native PBR scalar mismatch: ' + key)
        except (KeyError, TypeError, ValueError):
            errors.append('Missing/non-numeric native PBR scalar: ' + key)
    return errors
