# Facade visual mock-up yard: future completed state

![Path-traced overview of the mock-up yard](renders/pt_01_overview.png)

This is a browser-based 3D model of five facade visual mock-ups (VMU-01 to VMU-05) standing in a precast yard. It shows
the yard as it will look once all five mock-ups are complete, including the VMU-01 canopy extension. The geometry comes
from CAD and shop-drawing data. Every finish is driven by one colour table. You can explore the model in real time in
the web viewer, or render path-traced stills from it.

## What is in the model

- **Mock-ups.** The model contains:
  - the VMU-01 tower, with its canopy and the canopy extension;
  - the curved VMU-03, and VMU-02, VMU-04 and VMU-05;
  - a trellis;
  - the yard around them: ground slab, drains, crane runways, gantry crane, sheds, containers, hoarding, viewing
    platform and high masts, with a generic main road and roadside planting outside the hoarding.
- **Size.** Seven glTF files hold 2,223,601 triangles. The same model is also provided as a Rhino file:
  `model/vmu_site_future.3dm`, in millimetres, with 235 mesh components + 1 information TextDot,
  245 layers and 44 materials. The Rhino export has 2,222,589 valid triangles after removing 1,012
  degenerate faces, with no measured loss of surface area. Source GLBs are unchanged.
- **Colour table.** `model/materials.json` defines 83 named materials. Thirteen measured finishes have been taken from
  colour cards and laboratory colour measurements, and each carries both an SCI and an SCE value. The renders use the
  SCE value (specular component excluded), which is how the eye sees a matt panel. Where a finish is specified by RAL
  number, the number is kept: RAL 7005, RAL 7038 and RAL 9016.
- **Canopy extension.** The extension is always shown in its specified finish: a Mouse Grey top with T02 3 mm parts.
  The viewer can draw an outline around it (the outline toggle, or `?outline=1`), but it is never tinted.

## Run the viewer

You need Python 3 and a browser with WebGL2 (a current Chrome or Edge). The viewer uses only the Python standard library.

```
python serve.py            # default port 18090
```

Then open **http://127.0.0.1:18090/index.html**. On Windows you can double-click `start_viewer.bat` instead; it starts
the server and opens the page.

What the viewer does:

- **Views and lighting.** It has 13 preset views. The sun position is computed for 1.3° N 103.8° E, UTC+8, from a date
  and time you choose. You can pick an overcast or a partly cloudy sky (CC0 HDRIs). GTAO ambient occlusion and SMAA
  anti-aliasing are on.
- **Tools.** Click any element to see its layer and finish. There is also a distance tool and PNG export.
- **URL options.** You can set these in the address bar:
  - `?date=YYYY-MM-DD&t=<minutes>` sets the date and time;
  - `?hdri=sunny` switches to the partly cloudy sky;
  - `?canopyScheme=ral7038` shows the alternative canopy finish;
  - `?outline=1` outlines the canopy extension.
- **Path-traced stills.** The *照片级静帧* panel runs three-gpu-pathtracer in the browser. `serve.py` then denoises the
  result with Intel Open Image Denoise, using the albedo and normal buffers, and applies fog and ACES tone mapping.
  - OIDN needs numpy and a local `OpenImageDenoise.dll`. By default the copy that ships with Rhino 8 is used; set
    `OIDN_DLL` to point to another copy.
  - Without OIDN, the viewer falls back to an in-browser denoiser.
  - On some integrated GPUs the path tracer renders correctly only when Chrome or Edge is started with
    `--use-angle=vulkan`.

The user interface is in Chinese.

## Use Rhino 8

Open `model/vmu_site_future_native.3dm` in Rhino 8 for embedded PBR images and all
13 named views; `model/vmu_site_future.3dm` retains the geometry/source-UV baseline.
Meshes retain their source UVs
(194 meshes / 621,885 UV coordinates), stable source-derived object GUIDs and component UserText.
Use `rhino/select_components.py` in `ScriptEditor` to select by group, finish, role or ID.
`model/vmu_site_future_inventory.csv` provides a checked inventory of the 235 mesh components.
See [the Rhino workflow](rhino/README.md) for public-file regeneration, validation and native Rhino QA.
The native delivery adds world mapping to 41 meshes without source UVs, embeds
19 image assets for 8 finishes at their physical scale, and includes 13 native
1600 × 1000 viewport captures in `renders/rhino/`. The full quality CSV reports
129 closed / 106 open / 101 solid meshes and supplies volume only for solids.
This remains a mesh reference model; browser GLSL effects and engineering element
classes are not inferred. See [the native contact sheet](renders/rhino/contact_sheet.jpg).

## Renders

![Contact sheet of all renders](renders/contact_sheet.jpg)

`renders/` holds 16 stills at 2400 × 1500 pixels:

- 14 raster views from the viewer (`01_overview.png` to `14_vmu01_louvre_closeup.png`), under an overcast sky with a
  morning sun. View 14 is lit by an afternoon sun instead.
- 2 path-traced stills, `pt_01_overview.png` and `pt_02_vmu01_canopy_extension.png`. Each was rendered at 128 samples
  per pixel and denoised with OIDN. On an integrated GPU they took about 10 and 16 minutes of tracing.

The PNG and JPEG files carry no text or EXIF metadata.

## Repository layout

```
index.html, viewer.js   web viewer (three.js r160 + three-gpu-pathtracer, vendored in vendor/)
serve.py                local server: static files, POST /save (screenshots -> renders/), POST /pt_denoise
ptdenoise.py            OIDN denoising + fog + ACES tone mapping for path-traced stills (optional)
start_viewer.bat        Windows launcher (python on PATH)
model/                  vmu_cad.glb          VMU-01 tower, VMU-03, trellis            71.2 MB
                        vmu01_canopy.glb     VMU-01 canopy + canopy extension          3.2 MB
                        vmu02.glb, vmu04.glb, vmu05.glb                                 2.5 MB
                        site_ground.glb      slab, drains, runways, generic road       1.3 MB
                        site_context.glb     sheds, gantry, containers, hoarding       2.1 MB
                        materials.json       colour table (87 registered materials)
                        site_features.json   palms, trees, people, vehicles, labels
                        vmu_site_future.3dm  the whole model for Rhino (mm)           62.9 MB
                        vmu_site_future_inventory.csv  checked mesh-component inventory
                        vmu_site_future_qa.json        GLB/Rhino comparison report
build/                  public Rhino export/checker + private-source modelling scripts (see build/README.md)
rhino/                  Rhino 8 component selector, native QA and workflow
textures/               CC0 textures and HDRIs (Poly Haven, ambientCG)
vendor/                 three.js, three-mesh-bvh, three-gpu-pathtracer (MIT)
renders/                16 stills + contact_sheet.jpg
THIRD_PARTY_LICENSES.md
```

## How accuracy was checked

- **Plan fit.** The plan edges of each unit were compared with the layout drawing. The check measured the nearest
  distance in both directions, then ran a trimmed ICP re-fit.
  - The re-fit would move a unit by at most 0.053 m (VMU-04).
  - For the other units, the canopy and the trellis, it would move them by 0.031 m or less.
  - These checks ran on the source model. The mock-up geometry in this repository is the same: the binary chunks of
    the five mock-up GLBs are byte-identical to the source files. The ground and surroundings (`site_ground.glb`,
    `site_context.glb`, `site_features.json`) were rebuilt for publication with the scripts in `build/` (see
    Limitations).
- **Rhino roundtrip.** The seven GLBs and the viewer still contain 2,223,601 source triangles. Rhino contains
  2,222,589 triangles after culling 1,012 degenerate faces from 11 previously invalid meshes. The checker finds
  no surface-area loss, verifies source triangle membership/winding, and compares all 621,885 UV coordinates
  exactly. The native objects and inventory share stable source-derived IDs. Bounding-box round-off is at most
  0.007568359375 mm. This public-file QA does not repeat the private plan/photo checks.
- **Colour crops.** The published raster renders were measured with element-ID masks for five elements: canopy top,
  roof coping, VMU-01 fins, VMU-04 precast and wood-grain aluminium. All 48 of 48 crops fall inside their tolerance
  windows:
  - CIELAB ΔL* / Δb* windows against the preceding baseline renders;
  - hue 32–38° and saturation 0.36–0.47 for the wood grain;
  - |b*| ≤ 3.5 for the white coping.

  Against the source renders, the mean colours of the masked crops agree within 0.15 in L*, a* and b*, except where
  the rebuilt surroundings (roadside trees, their shadows, the west factory and the gantry crane) change the masked
  pixels: views 01, 07 and 11, up to 20.7 in L* for the VMU-04 precast in view 11.
- **Cameras.** The 13 standard views reproduce the source camera positions and targets to within 0.01 m.

## Limitations

- **Future state.** The model shows the planned completed state. Several finishes and dimensions are still waiting to
  be confirmed by site measurement. The VMU-04 precast colour is an indicative value.
- **Build scripts.** The geometry builders in `build/` record the method and read confidential inputs that are not
  included (drawings, a CAD model, a site survey and site photos). The Rhino exporter, checker and regression tests
  run directly from the committed public GLBs and material table; they do not rebuild the private source geometry.
- **Surroundings.** Only the factories and structures next to the yard are modelled, from the layout plan, the site
  survey and site photos; buildings further away are not modelled. The sheds, the accessway canopy, the gantry crane,
  vehicles and people are approximate. The far ground is a neutral textured plane, not imagery.
- **Main road and planting.** The main road is generic: a dual carriageway laid out along the surveyed lot line with
  nominal widths (four 3.5 m lanes per direction, a 2 m hatched median, 4 m verges), standard markings and a level
  assumed 0.5 m below the yard. The palms and trees along it are procedural rows, not surveyed positions. The second
  crane runway, which the layout plan does not show, is placed from a site photo.
- **Coordinates.** Model coordinates are local metres from a yard origin, with no georeferencing. The sun model is the
  simplified NOAA algorithm at rounded coordinates.
- **Lot line.** The yard slab, the hoarding and the chain-link fence follow the surveyed lot lines at survey accuracy.
  `model/site_features.json` carries only a copy of the lot line rounded to 1 m, which the viewer uses to place views.

## Data and licences

- **Third-party components.** See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md):
  - three.js, three-mesh-bvh and three-gpu-pathtracer are MIT-licensed;
  - the Poly Haven and ambientCG textures and HDRIs are CC0;
  - Intel Open Image Denoise (Apache-2.0) is not included; it is loaded from a local installation.
- **Excluded data.** The repository contains no aerial or map imagery, no geometry or values measured on aerial
  imagery, map tiles or terrain data, no building data from online maps, no licensed height data and no site
  photographs. The road, the roadside planting, the second crane runway, the accessway canopy and the colours of the
  surroundings come from the drawings, the site survey, site photos or generic values (see
  [build/README.md](build/README.md)).
- **No licence is granted** for the model, renders, scripts or documentation in this repository. All rights are
  reserved unless the owner adds a LICENSE file. Third-party components remain under their own licences.

中文说明见 [README.zh-CN.md](README.zh-CN.md)。

## Complete Rhino delivery

Use the interpreter from the environment where `requirements-rhino.txt` was installed:

```powershell
.\.venv\Scripts\python.exe build\delivery.py --check
.\.venv\Scripts\python.exe build\delivery.py --rebuild
```

Offline `--check` verifies the committed delivery index, source geometry, canonical material derivation, mesh topology, native PBR scalars, cameras and captures without starting Rhino or rewriting reports. Native `--rebuild` requires licensed Rhino on Windows and refreshes the public GLB source export, textures, cameras, native model, captures and independent reports. All subprocesses use the selected interpreter.

`model/delivery_index.json` records source/code/configuration fingerprints, output fingerprints, Python/dependency versions and the native Rhino version. Changed inputs or outputs invalidate the old delivery. Interrupted builds remain failed rather than retaining an old success label. Text fingerprints normalize Git line endings; model and image fingerprints use exact bytes. The CI `--manifest-only` gate runs after the independent checks.
