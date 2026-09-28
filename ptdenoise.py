"""ptdenoise.py - post-processing of the viewer's path-traced stills for serve.py (POST /pt_denoise).

Input (built by viewer.js ptFinalize, little-endian):
  b'MOCKUPT1' | uint32 header length | header JSON (utf-8, space-padded so the arrays start at a multiple of 16 bytes) | arrays
  header: {W, H, exposure, toneMapping: 'ACESFilmic', fog: {color: [r, g, b] linear, density} | null, rowsBottomUp: true,
           arrays: [{name, dtype 'f4' | 'f2', ch, offset (from the start of the array block), bytes}], ...}
  arrays: color    f4 RGBA  linear float accumulation of three-gpu-pathtracer (pt.target, NaN-guarded in the viewer)
          albedo   f2 RGBA  16-pass jittered raster albedo, alpha = pixel coverage (0 = sky)
          normal   f2 RGBA  16-pass jittered world normal, alpha = coverage-weighted view depth (FogExp2 depth)
Processing:
  1. NaN guard: non-finite pixels -> mean of their finite 3x3 neighbours (a NaN sample stays in the running average for good).
  2. Intel Open Image Denoise 2.x, filter "RT", hdr, albedo + normal guides, cleanAux, quality high. The DLL is NOT part of
     this repository and is never copied: by default the copy that ships with Rhino 8 is loaded in place
     (C:\\Program Files\\Rhino 8\\System\\OpenImageDenoise.dll, Apache-2.0); set OIDN_DLL to use another OpenImageDenoise.dll
     (path of the DLL or of its folder). OIDN loads OpenImageDenoise_device_cpu.dll with plain LoadLibrary, whose dependency
     tbb12.dll is then searched on PATH only -> the DLL folder is prepended to PATH for this process.
  3. Pure-sky pixels (coverage < 1e-3) keep the raw value (the background is noise-free).
  4. FogExp2 re-applied from the depth AOV (the path tracer drops scene.fog): lin += cov * f * (fogColour - lin),
     f = 1 - exp(-(density * depth)^2), in linear before the tone mapper, as the raster shaders do.
  5. three.js r160 ACESFilmicToneMapping at the viewer's exposure, then the r160 sRGB OETF, 8-bit PNG.
Availability: available() -> (ok, reason). serve.py answers 501 when numpy or the DLL is missing, the viewer then falls back
to DenoiseMaterial (in the browser) or raw.
Environment: OIDN_DLL = path of OpenImageDenoise.dll or of its folder (default: the Rhino 8 copy above);
             MOCKUP_PT_DENOISE=0 disables the endpoint.
Self-test: python ptdenoise.py
"""
import ctypes, io, json, os, struct, sys, threading, time, zlib

MAGIC = b'MOCKUPT1'
OIDN_DEFAULT_DLL = r'C:\Program Files\Rhino 8\System\OpenImageDenoise.dll'
QUALITY = {'default': 0, 'fast': 4, 'balanced': 5, 'high': 6}
_lib = None
_lock = threading.Lock()


def _dll_path():
    """OIDN_DLL (the DLL file, or a folder containing OpenImageDenoise.dll), else the Rhino 8 default."""
    p = os.environ.get('OIDN_DLL') or OIDN_DEFAULT_DLL
    return os.path.join(p, 'OpenImageDenoise.dll') if os.path.isdir(p) else p


def lib():
    """Load OpenImageDenoise.dll in place (no copy) and declare the few functions used."""
    global _lib
    if _lib is not None:
        return _lib
    p = _dll_path()
    if not os.path.isfile(p):
        raise FileNotFoundError('OpenImageDenoise.dll not found: ' + p + ' (set OIDN_DLL)')
    d = os.path.dirname(os.path.abspath(p))
    if hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(d)
    if d.lower() not in os.environ.get('PATH', '').lower().split(os.pathsep)[:1]:
        os.environ['PATH'] = d + os.pathsep + os.environ.get('PATH', '')   # tbb12.dll for the CPU device
    L = ctypes.CDLL(p)
    vp, cp, sz = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t
    L.oidnNewDevice.restype = vp; L.oidnNewDevice.argtypes = [ctypes.c_int]
    L.oidnCommitDevice.argtypes = [vp]
    L.oidnNewFilter.restype = vp; L.oidnNewFilter.argtypes = [vp, cp]
    L.oidnSetSharedFilterImage.argtypes = [vp, cp, vp, ctypes.c_int, sz, sz, sz, sz, sz]
    L.oidnSetFilterBool.argtypes = [vp, cp, ctypes.c_bool]
    L.oidnSetFilterInt.argtypes = [vp, cp, ctypes.c_int]
    L.oidnCommitFilter.argtypes = [vp]
    L.oidnExecuteFilter.argtypes = [vp]
    L.oidnGetDeviceError.restype = ctypes.c_int; L.oidnGetDeviceError.argtypes = [vp, ctypes.POINTER(ctypes.c_char_p)]
    L.oidnReleaseFilter.argtypes = [vp]; L.oidnReleaseDevice.argtypes = [vp]
    L._path = p
    _lib = L
    return L


def _err(L, dev, where):
    msg = ctypes.c_char_p()
    code = L.oidnGetDeviceError(dev, ctypes.byref(msg))
    if code:
        raise RuntimeError(f'OIDN error {code} at {where}: {msg.value.decode(errors="replace") if msg.value else ""}')


def available():
    """(ok, reason): numpy importable, DLL loadable, CPU device commits."""
    if os.environ.get('MOCKUP_PT_DENOISE', '1') == '0':
        return False, 'disabled (MOCKUP_PT_DENOISE=0)'
    try:
        import numpy  # noqa: F401
    except Exception as e:  # ImportError, or sys.modules['numpy'] = None
        return False, f'numpy missing ({type(e).__name__})'
    try:
        L = lib()
        dev = L.oidnNewDevice(1)   # OIDN_DEVICE_TYPE_CPU
        L.oidnCommitDevice(dev); _err(L, dev, 'device')
        L.oidnReleaseDevice(dev)
    except Exception as e:
        return False, f'OIDN unavailable ({type(e).__name__}: {e})'
    return True, 'OIDN ' + os.path.basename(os.path.dirname(L._path))


def denoise(color, albedo=None, normal=None, hdr=True, clean_aux=True, quality='high'):
    import numpy as np
    L = lib()
    FLOAT3 = 3
    c = np.ascontiguousarray(color[..., :3], dtype=np.float32)
    H, W = c.shape[:2]
    out = np.empty_like(c)
    with _lock:   # one filter at a time (memory; OIDN itself uses all cores)
        dev = L.oidnNewDevice(1)
        L.oidnCommitDevice(dev); _err(L, dev, 'device')
        f = L.oidnNewFilter(dev, b'RT')
        keep = [c, out]

        def img(name, a):
            a = np.ascontiguousarray(a[..., :3], dtype=np.float32); keep.append(a)
            L.oidnSetSharedFilterImage(f, name, a.ctypes.data, FLOAT3, W, H, 0, 12, 12 * W)
        img(b'color', c)
        if albedo is not None:
            img(b'albedo', albedo)
            if normal is not None:
                img(b'normal', normal)
        L.oidnSetSharedFilterImage(f, b'output', out.ctypes.data, FLOAT3, W, H, 0, 12, 12 * W)
        L.oidnSetFilterBool(f, b'hdr', bool(hdr))
        if albedo is not None:
            L.oidnSetFilterBool(f, b'cleanAux', bool(clean_aux))
        L.oidnSetFilterInt(f, b'quality', QUALITY.get(quality, 0))
        L.oidnCommitFilter(f); _err(L, dev, 'commit')
        L.oidnExecuteFilter(f); _err(L, dev, 'execute')
        L.oidnReleaseFilter(f); L.oidnReleaseDevice(dev)
    return out


# ------------------------------------------------------------------ colour pipeline (three r160)
def aces(c, exposure):
    """three.js r160 ACESFilmicToneMapping (linear sRGB in, clamped linear out)."""
    import numpy as np
    ACES_IN = np.array([[0.59719, 0.35458, 0.04823], [0.07600, 0.90834, 0.01566], [0.02840, 0.13383, 0.83777]], np.float32)
    ACES_OUT = np.array([[1.60475, -0.53108, -0.07367], [-0.10208, 1.10813, -0.00605], [-0.00327, -0.07276, 1.07602]], np.float32)
    c = c.astype(np.float32) * np.float32(exposure / 0.6)
    c = c @ ACES_IN.T
    a = c * (c + 0.0245786) - 0.000090537
    b = c * (0.983729 * c + 0.4329510) + 0.238081
    c = (a / b) @ ACES_OUT.T
    return np.clip(c, 0, 1)


def srgb8(lin01):
    """three.js r160 sRGBTransferOETF, rounded to 8 bit."""
    import numpy as np
    c = np.clip(lin01, 0, 1)
    s = np.where(c <= 0.0031308, c * 12.92, np.power(c, 0.41666) * 1.055 - 0.055)
    return np.clip(np.round(s * 255), 0, 255).astype(np.uint8)


def to8(lin, exposure):
    return srgb8(aces(lin, exposure))


def nan_guard(col):
    """Replace non-finite pixels (any channel) by the mean of their finite 3x3 neighbours (0 if none). Returns (fixed, count)."""
    import numpy as np
    bad = ~np.isfinite(col).all(-1)
    n = int(bad.sum())
    if not n:
        return col, 0
    col = col.copy()
    good = ~bad
    z = np.where(good[..., None], col, 0).astype(np.float64)
    H, W = bad.shape
    pz = np.pad(z, ((1, 1), (1, 1), (0, 0))); pg = np.pad(good.astype(np.float64), 1)
    ys, xs = np.nonzero(bad)
    s = np.zeros((n, col.shape[-1])); k = np.zeros(n)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            s += pz[ys + dy, xs + dx]; k += pg[ys + dy, xs + dx]
    col[ys, xs] = np.where(k[:, None] > 0, s / np.maximum(k, 1)[:, None], 0)
    return col, n


def png_bytes(img8):
    try:
        from PIL import Image
        bio = io.BytesIO(); Image.fromarray(img8).save(bio, 'PNG', compress_level=3); return bio.getvalue()
    except ImportError:   # stdlib PNG writer (RGB8, filter 0)
        H, W = img8.shape[:2]
        raw = b''.join(b'\x00' + img8[y].tobytes() for y in range(H))
        def chunk(t, d):
            return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
        return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', W, H, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b'')


# ------------------------------------------------------------------ request body
def parse(body):
    """-> (header dict, {name: float32 array H x W x ch, rows top-down})"""
    import numpy as np
    mv = memoryview(body)
    if bytes(mv[:8]) != MAGIC:
        raise ValueError('bad magic')
    n = struct.unpack('<I', mv[8:12])[0]
    hdr = json.loads(bytes(mv[12:12 + n]).decode('utf-8'))
    base = 12 + n
    W, H = int(hdr['W']), int(hdr['H'])
    if not (0 < W <= 16384 and 0 < H <= 16384):
        raise ValueError('bad size')
    out = {}
    for a in hdr['arrays']:
        dt = {'f4': np.float32, 'f2': np.float16}[a['dtype']]
        ch = int(a.get('ch', 4))
        off = base + int(a['offset']); cnt = W * H * ch
        if off + cnt * np.dtype(dt).itemsize > len(body):
            raise ValueError(f'array {a["name"]} truncated')
        arr = np.frombuffer(body, dtype=dt, count=cnt, offset=off).reshape(H, W, ch)
        if hdr.get('rowsBottomUp', True):
            arr = arr[::-1]
        out[a['name']] = arr.astype(np.float32)
    return hdr, out


def prepare(hdr, arrs):
    """Shared by process() and the tests: colour (NaN-guarded), guides, coverage, depth."""
    import numpy as np
    col, nan_in = nan_guard(arrs['color'][..., :3])
    alb4, nrm4 = arrs.get('albedo'), arrs.get('normal')
    g = {'col': col, 'nan_in': nan_in, 'have_aov': alb4 is not None and nrm4 is not None}
    if g['have_aov']:
        cov = np.clip(alb4[..., 3], 0, 1)
        g['cov'] = cov
        g['albedo'] = np.clip(alb4[..., :3] + (1 - cov)[..., None], 0, 1)   # sky albedo = 1
        g['normal'] = np.nan_to_num(nrm4[..., :3])
        g['depth'] = np.where(cov > 1e-4, nrm4[..., 3] / np.maximum(cov, 1e-4), 0)
    return g


def apply_fog(lin, g, fog):
    import numpy as np
    if not fog or not fog.get('density') or not g['have_aov']:
        return lin
    f = 1 - np.exp(-(float(fog['density']) * g['depth']) ** 2)
    fc = np.array(fog['color'][:3], np.float32)
    return lin + (g['cov'] * f)[..., None] * (fc - lin)


def process(body, mode=None):
    """-> (png bytes, stats dict). mode: 'oidn' (default) | 'tonemap' (no denoise; for checks)."""
    import numpy as np
    t0 = time.time()
    hdr, arrs = parse(body)
    mode = mode or hdr.get('mode', 'oidn')
    g = prepare(hdr, arrs)
    col = g['col']
    st = {'W': hdr['W'], 'H': hdr['H'], 'mode': mode, 'nonfinite_in': g['nan_in'], 'aov': g['have_aov'], 'parse_s': round(time.time() - t0, 3)}
    if mode == 'oidn':
        t1 = time.time()
        den = denoise(col, g.get('albedo'), g.get('normal'), hdr=True, clean_aux=True, quality='high')
        st['oidn_s'] = round(time.time() - t1, 3)
        if g['have_aov']:
            sky = g['cov'] < 1e-3
            den = np.where(sky[..., None], col, den)
            st['sky_frac'] = round(float(sky.mean()), 5)
        den, st['nonfinite_out_fixed'] = nan_guard(den)
    else:
        den = col
    lin = apply_fog(den, g, hdr.get('fog'))
    st['nonfinite_out'] = int((~np.isfinite(lin)).any(-1).sum())
    img8 = to8(np.nan_to_num(lin), float(hdr['exposure']))
    t2 = time.time(); png = png_bytes(img8); st['png_s'] = round(time.time() - t2, 3)
    st['total_s'] = round(time.time() - t0, 3)
    st['exposure'] = hdr['exposure']; st['fog'] = bool(hdr.get('fog'))
    try:
        st['dll'] = lib()._path if mode == 'oidn' else None
    except Exception:
        st['dll'] = None
    return png, st


def pack(W, H, color, albedo=None, normal=None, exposure=1.0, fog=None, extra=None):
    """Build a request body (tests; the viewer builds the same layout in JS). Arrays are H x W x 4, rows top-down."""
    import numpy as np
    arrays, blobs, off = [], [], 0
    for name, a, dt in (('color', color, 'f4'), ('albedo', albedo, 'f2'), ('normal', normal, 'f2')):
        if a is None:
            continue
        b = np.ascontiguousarray(a[::-1], dtype={'f4': np.float32, 'f2': np.float16}[dt]).tobytes()
        arrays.append({'name': name, 'dtype': dt, 'ch': 4, 'offset': off, 'bytes': len(b)}); blobs.append(b); off += len(b)
    hdr = {'W': W, 'H': H, 'exposure': exposure, 'toneMapping': 'ACESFilmic', 'fog': fog, 'rowsBottomUp': True, 'arrays': arrays, **(extra or {})}
    j = json.dumps(hdr).encode('utf-8'); pad = (-(12 + len(j))) % 16; j += b' ' * pad
    return MAGIC + struct.pack('<I', len(j)) + j + b''.join(blobs)


if __name__ == '__main__':   # self-test: synthetic noisy image with guides + an injected NaN
    import numpy as np
    ok, why = available(); print('available:', ok, why)
    if not ok:
        sys.exit(1)
    rng = np.random.default_rng(0)
    H, W = 240, 360
    y, x = np.mgrid[0:H, 0:W]
    clean = np.stack([(x / W), (y / H), 0.5 + 0 * x], -1).astype(np.float32)
    noisy = clean * rng.exponential(1.0, clean.shape).astype(np.float32)
    noisy[100, 100] = np.nan; noisy[5, 7, 1] = np.inf
    c4 = np.dstack([noisy, np.ones((H, W), np.float32)])
    a4 = np.dstack([clean, np.ones((H, W), np.float32)])
    n4 = np.dstack([0 * x, 0 * x + 1, 0 * x, 0 * x + 50.0]).astype(np.float32)
    body = pack(W, H, c4, a4, n4, exposure=1.04, fog={'color': [0.352, 0.343, 0.322], 'density': 0.0011})
    png, st = process(body)
    print(json.dumps(st))
    from PIL import Image
    im = np.asarray(Image.open(io.BytesIO(png)).convert('RGB')).astype(float)
    ref = to8(apply_fog(clean, prepare(*parse(body)), {'color': [0.352, 0.343, 0.322], 'density': 0.0011}), 1.04).astype(float)
    print('rmse vs clean %.2f levels (noisy input %.2f)' % (np.sqrt(((im - ref) ** 2).mean()), np.sqrt(((to8(np.nan_to_num(noisy, nan=0, posinf=0), 1.04) - ref) ** 2).mean())))
    assert st['nonfinite_in'] == 2 and st['nonfinite_out'] == 0, st
    print('self-test ok')
