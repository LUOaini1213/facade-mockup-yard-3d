# Third-party licences

This repository redistributes the third-party files listed below, unmodified, under their own licences. No aerial
imagery, map tiles, terrain data or online-map building data, and nothing measured on them, is included. Files not
listed here are original to this repository.

| Component | Files in this repository | Licence |
|---|---|---|
| three.js r160 (0.160.0) | `vendor/three.module.js`, `vendor/jsm/**` (only the example add-ons the viewer imports) | MIT |
| three-mesh-bvh 0.8.3 | `vendor/three-mesh-bvh/build/index.module.js` | MIT |
| three-gpu-pathtracer 0.0.23 | `vendor/three-gpu-pathtracer/build/index.module.js` | MIT (bundles glslSmartDeNoise, BSD-2-Clause) |
| Poly Haven textures and HDRIs | `textures/hdri/`, `textures/brushed_concrete/`, `textures/clean_asphalt/`, `textures/corrugated_iron_03/` | CC0 1.0 |
| ambientCG Metal009 | `textures/acg/Metal009/` | CC0 1.0 |
| Intel Open Image Denoise | not included (loaded from a local installation at run time) | Apache-2.0 |

## three.js

`vendor/three.module.js` and the files under `vendor/jsm/` are unmodified copies of three.js r160
(`build/three.module.js` and `examples/jsm/`). `vendor/jsm/` contains only the import closure of `viewer.js`:
OrbitControls, GLTFLoader, RGBELoader, Sky, CSS2DRenderer, EffectComposer, RenderPass, ShaderPass, MaskPass, Pass,
GTAOPass, OutlinePass, OutputPass, SMAAPass, BufferGeometryUtils and the shaders / helpers they import (CopyShader,
GTAOShader, OutputShader, PoissonDenoiseShader, SMAAShader, SimplexNoise). The licence text is also in
`vendor/LICENSE-three.js`.

`SMAAPass.js` / `SMAAShader.js` are the three.js port of SMAA (Subpixel Morphological Antialiasing,
https://github.com/iryoku/smaa, by Jorge Jimenez, Jose I. Echevarria, Belen Masia, Fernando Navarro and Diego Gutierrez;
SMAA is Copyright (C) 2013 by these authors and is distributed under its own MIT-style licence,
https://github.com/iryoku/smaa/blob/master/LICENSE.txt).
`SimplexNoise.js` is a port of Stefan Gustavson's simplex-noise implementation. Both are distributed as part of three.js.

```
The MIT License

Copyright © 2010-2023 three.js authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

## three-mesh-bvh

`vendor/three-mesh-bvh/` (build only, unmodified). Licence file: `vendor/three-mesh-bvh/LICENSE`.

```
MIT License

Copyright (c) 2018 Garrett Johnson

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## three-gpu-pathtracer

`vendor/three-gpu-pathtracer/` (build only, unmodified). Licence file: `vendor/three-gpu-pathtracer/LICENSE`.

```
MIT License

Copyright (c) 2021 Garrett Johnson

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

The build embeds the glslSmartDeNoise shader (used by its `DenoiseMaterial`, the viewer's in-browser denoiser fallback),
whose notice is kept in the file:

```
BSD 2-Clause License

Copyright (c) 2018-2019 Michele Morrone
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## Textures and HDRIs (CC0)

All image files under `textures/` are unmodified CC0 1.0 (public-domain dedication) assets; see `textures/LICENSES.txt`
for the file-by-file list. No attribution is required; the authors are credited as a courtesy.

- Poly Haven (https://polyhaven.com): HDRIs "Mud Road (Pure Sky)" (Sergey Rudavin; sky edits Jarod Guest) and
  "Kloofendal 48d Partly Cloudy (Pure Sky)" (Greg Zaal; sky edits Jarod Guest);
  textures brushed_concrete (Dario Barresi, Dimitrios Savva), clean_asphalt (Dimitrios Savva),
  corrugated_iron_03 (Charlotte Baglioni).
- ambientCG (https://ambientcg.com): Metal009.

The viewer contains no aerial imagery and no photographs. The far ground around the model is a neutral
plane textured with the CC0 clean_asphalt texture.

## Intel Open Image Denoise (not redistributed)

`ptdenoise.py` (used by `serve.py` for the optional path-traced stills) loads `OpenImageDenoise.dll` at run time via
ctypes. The DLL is **not** part of this repository and is never copied: by default the copy that ships with a local
Rhino 8 installation (`C:\Program Files\Rhino 8\System\OpenImageDenoise.dll`) is used in place; the environment
variable `OIDN_DLL` selects another installation. Intel Open Image Denoise is licensed under the Apache License 2.0
(https://www.apache.org/licenses/LICENSE-2.0; https://www.openimagedenoise.org). Without the DLL (or without numpy)
the viewer falls back to its in-browser denoiser.
