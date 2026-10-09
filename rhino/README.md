# Work with the model in Rhino 8

Open `model/vmu_site_future_native.3dm` for the textured model and its 13 named views.
`model/vmu_site_future.3dm` remains the reproducible geometry/source-UV baseline.
Both models use millimetres:
X = East, Y = North, Z = Up, and the yard slab top is Z = 0.
The baseline contains **235 mesh components + 1 information TextDot**, 245 layers
and 44 materials. The native version retains the same meshes/layers and adds
44 object-material variants named `canonical finish | Native PBR`; existing layer
materials remain available. The canonical finish IDs stay unchanged.
Components are GLB mesh primitives, and a primitive can aggregate several physical parts.
The model is a mesh coordination/reference model; it does not contain editable NURBS
construction geometry, Grasshopper definitions or IFC building-element classes.

The native delivery embeds the full-resolution assets and is larger than GitHub's
100 MiB ordinary-file limit. Only `model/vmu_site_future_native.3dm` uses Git LFS;
the geometry baseline and public GLBs remain ordinary Git files. Install Git LFS
before cloning, or fetch the full binary in an existing checkout:

```powershell
git lfs install
git clone https://github.com/LUOaini1213/facade-mockup-yard-3d.git
cd facade-mockup-yard-3d
git lfs pull
```

CI jobs that read the native model must use `actions/checkout` with `lfs: true`.
The public-source regeneration path below can also recreate it locally.

Each mesh has object UserText for `component_id`, `source_key`, `group`, `finish`,
and any public source properties such as `part`, `role` or `confidence`.
The native Rhino object GUID equals `component_id`. IDs are UUID5 values derived from
the GLB filename, node index and primitive index; they remain stable when geometry or
finishes or node names change without reindexing the source graph. Renaming source
GLB files, reordering nodes or splitting/merging primitives changes those IDs.

## Find components

In Rhino 8, run `ScriptEditor`, open `rhino/select_components.py`, and press Run.
Choose a property (`group`, `finish`, `role` or `component_id`) and a value.
Matching visible/selectable mesh components are selected for inspection.
The accompanying `model/vmu_site_future_inventory.csv` has one row per mesh component,
including its ID, source primitive, layer, finish, vertex/triangle/UV counts, source
triangle count, removed degenerate-face count and bounding box in millimetres.
It is a coordination inventory, **not a fabrication quantity take-off**.

## Regenerate and verify from public files

These commands use only the seven committed GLBs and `model/materials.json`.
The confidential drawing/CAD inputs are not needed for this conversion.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-rhino.txt
.\.venv\Scripts\python.exe build\export_3dm.py
.\.venv\Scripts\python.exe -m unittest discover -s build -p "test_*.py" -v
.\.venv\Scripts\python.exe build\check_3dm.py --report model\vmu_site_future_qa.json
```

`MOCKUP_3DM_OUT`, `MOCKUP_3DM_REPORT` and `MOCKUP_3DM_INVENTORY` optionally override
the output paths. The standalone checker expects the seven source GLBs in the model's
directory, so place a custom model output there when checking it.

The export retains all existing vertices and normals and writes `TEXCOORD_0`
unchanged into native mesh texture coordinates. It preserves **194 UV-bearing meshes
and 621,885 UV coordinates**. UVs remain dimensionless; neither axis conversion nor
the metre-to-mm conversion applies to them. Normalized integer UV accessors are
decoded according to their glTF normalized range. The baseline does not invent UVs;
the native delivery adds explicitly labelled world-projection UVs to the 41 meshes
without source coordinates, using the same dominant-normal projection as `viewer.js`.

The legacy published model had 11 invalid meshes caused by collapsed triangles.
Only those degenerate faces are culled; all vertices, normals and UV associations
are retained. The seven GLBs still have **2,223,601 source triangles**. The valid Rhino
export has **2,222,589 triangles**, after removing **1,012 degenerate faces**. The
checker verifies source-triangle membership/winding, bounding boxes, original/retained
surface area, every UV coordinate, IDs and inventory values. The checked public model
lost **0.0 m² of surface area**, and its largest bounding-box round-off was
**0.007568359375 mm**. See `model/vmu_site_future_qa.json` for the generated evidence.

## PBR materials, views and native images

The native delivery binds the public image assets for **8 finishes**. The 19
content-addressed PNGs in `model/rhino_assets/` are embedded in the 3dm and listed
with hashes in `model/rhino_assets.json`. Base-colour images use sRGB; normals,
roughness and AO use linear data. Colour multipliers are baked in linear light.
ARM R is converted to the viewer's effective AO (strength 0.7), G to roughness;
the viewer leaves ARM B unused, so the native material keeps its scalar metallic
value. The HDG roughness-map mean correction is also baked. No external URL or
confidential source is needed when opening the native file.

The material table has 87 registered entries. Four previously unregistered
context finishes now use the existing `site_context.glb` values for colour,
metallic and roughness: steel, fence, lamp and container. Fence alpha (0.35)
and the lamp's linear emission are retained in native PBR. The native fence
is an alpha approximation; the browser's procedural chain-link texture is
not reproduced. Vision-glass viewport opacity remains `1 - 0.85 * vlt`, with
the registered IOR; this display mapping does not measure glass transmission.

Material inputs reject unknown names/fields, alias cycles, nonfinite numbers
and nonpositive physical texture scales. The schema-2 assets manifest binds
the canonical material table, all seven GLBs and every used texture input,
plus the derived PNG bytes. Text fingerprints normalize LF/CRLF; binary
inputs use exact SHA-256. Native and independent checks inspect the saved
RDK base colour, metallic, roughness, clearcoat, clearcoat roughness,
anisotropy, glass opacity/IOR, alpha and emission for every used material,
including finishes without texture slots.

Texture repeat uses the public physical size: 0.5 m for HDG, 2.5 m for yard
concrete, 2 m for corrugated metal, and 2.1 m for asphalt. The UVs used by these
finishes are in metres; repeat is therefore `1 / size_m`, independent of the
Rhino document's millimetre units. Source UV coordinates remain unchanged.

`model/rhino_views.json` captures the **13 exact current viewer presets**, their
positions/targets/up vectors and vertical 45° field of view. They become native
Rhino named views. `renders/rhino/` contains 13 **1600 × 1000 Rendered-mode viewport
captures**, plus a contact sheet. Rendered mode is selected by its invariant ID,
so this also works with a Chinese Rhino installation.

These captures use Rhino's native viewport lighting. The browser's custom wood,
ribbing and formliner GLSL effects, runtime yard albedo/stain calibration, sun/sky,
procedural planting and post-processing
are not portable PBR image assets; they are not reproduced exactly. No physical
NURBS detail or engineering element classes are inferred from those shader effects.

Regenerate the native delivery on Windows with licensed Rhino 8:

```powershell
python -m playwright install chromium
python build\prepare_rhino_assets.py
python build\prepare_rhino_assets.py --check
python build\capture_views.py
python build\run_rhino_qa.py --enrich --timeout 900
python build\check_3dm.py --model model\vmu_site_future_native.3dm --inventory model\vmu_site_future_inventory.csv --report model\vmu_site_future_native_source_qa.json
python build\check_delivery.py
```

For a read-only verification of an existing delivery, run
`python build\prepare_rhino_assets.py --check` and
`python build\check_delivery.py --no-write-reports`. These commands recompute
the checks without modifying textures, reports or the contact sheet.

`capture_views.py` reads the unchanged viewer through a temporary localhost server.
The native launcher opens the baseline and writes a separate native 3dm; it does
not overwrite the baseline. `vmu_site_future_delivery_progress.json` reports the
current stage during a run. `vmu_site_future_rhino_delivery.json` records native
asset extraction/hash verification, saved material slots, colour spaces, physical
repeat and named views; `vmu_site_future_delivery_qa.json` independently checks the
saved geometry, metric CSV, cameras and image sizes using rhino3dm/NumPy/Pillow.
The native checker reads the saved RDK XML directly: Rhino's legacy `ToMaterial()`
simulation can omit linear-data flags. `python build\run_rhino_qa.py --delivery-only`
rechecks an existing native delivery without rerunning geometry or screenshots.
The automatically created Studio environment is removed after capture so the
model does not require a texture inside the author's local Rhino installation.

## Geometry quality inventory

`model/vmu_site_future_geometry.csv` and `.json` contain a row for every one of
the 235 meshes: validity, closure, manifold status, orientation, solid status,
disjoint pieces, naked-edge polyline count/length (m), area (m²), UV source and
volume (m³). The native check finds **129 closed, 106 open, 101 solid, 0 invalid**
meshes. Only the 101 solids receive a volume; every omitted volume has a reason.
Closure alone does not prove that a mesh is manifold, oriented or a solid.
Open curtain-wall skins can be intentional; their area is useful, but their
volume is omitted. A GLB primitive can aggregate disconnected physical parts,
so these rows are not a fabrication quantity take-off. NumPy independently
recomputes closure, edge-manifold status, orientation and solid eligibility
from the actual mesh polygons, rather than trusting JSON or CSV flags.
Coincident seam vertices are welded exactly; no tolerance closes actual gaps.
Quads use the shorter diagonal for integration, and disconnected pieces are
retained. Archive-valid collinear triangles contribute zero area/volume.
Areas, naked-edge lengths and eligible geometric volumes are recomputed;
volume for an actual non-solid, missing/duplicate rows and forged summaries
fail verification even if JSON and CSV agree. These edge predicates do not
certify self-intersection or fabrication readiness. The 106 intended open
surfaces remain open.

Implementation references: [Rhino PBR materials and image slots](https://docs.mcneel.com/rhino/8/help/en-us/commands/materials.htm),
[rendering assets in openNURBS](https://developer.rhino3d.com/en/guides/opennurbs/accessing-rendering-assets/),
[native ViewCapture](https://developer.rhino3d.com/api/rhinocommon/rhino.display.viewcapture),
and [glTF material colour-space/channel conventions](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#materials).

## Run native Rhino QA

On Windows with licensed Rhino 8 installed, run this from the repository root:

```powershell
python build\run_rhino_qa.py
```

The launcher copies both native scripts to an ASCII temporary directory, starts
Rhino hidden, opens the saved model, and writes `model/vmu_site_future_rhino_qa.json`.
It waits at most 240 seconds and terminates only its own process if that limit is
exceeded. `--timeout`, `--model`, `--report` and `--rhino` override the defaults;
`RHINO_EXE` can also specify the executable. A missing/failed report returns an error.
The published export passed this native check in Rhino **8.33.26188.13001**;
the generated evidence is `model/vmu_site_future_rhino_qa.json`.

With the exported model open, run `rhino/qa_model.py` in Rhino 8 `ScriptEditor`.
It checks native mesh validity, source-derived IDs, UV counts, layer finishes, units,
component/triangle totals and the repair audit, and prints the result. It does not
change the document.
If the environment variable `MOCKUP_RHINO_QA_REPORT` is set before starting Rhino,
the script also writes the report to that absolute path. Expected counts are 235
mesh components, 2,222,589 triangles, 194 UV-bearing meshes and 1,012 culled faces.
