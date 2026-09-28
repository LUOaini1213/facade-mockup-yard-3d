# Build scripts

These Python scripts document how the model in `model/` was produced: a facade visual mock-up yard (five
mock-ups VMU-01 .. VMU-05, the VMU-01 canopy extension and the surrounding yard) in its future completed
state. They are published as a record of the **method**. They do **not** run out of the box: every builder
reads confidential project inputs (shop drawings, the layout plan, a legacy CAD model, a site survey and
site photos) that are not part of this repository and will not be published.

All provenance comments, document references and project identifiers were removed; each script keeps a
short module docstring, its geometry, parameters and algorithms. Where the original scripts carried values
that may not be redistributed, those values were moved out of the code into private input files (see
below) or the code path was removed:

- no aerial imagery, map tiles, terrain, online-map building data or third-party 3D-map data is used
  anywhere, and nothing derived from them is published;
- only the factories and structures next to the yard are modelled (`build_context2.py`, from the layout plan,
  the site survey and site photos); buildings further away are not modelled;
- the accessway canopy in `build_context2.py` is placed from the layout plan and two site photos only (the
  derivation is in the comment above `ACCESSWAY_CANOPY_PAGE`);
- the main road in `build_ground.py` is generic: a dual carriageway laid out along the surveyed road-side lot
  line with nominal widths (4.0 m verge, 4 lanes of 3.5 m per direction, 2.0 m hatched median, 4.0 m far
  verge), a standard 2 m / 4 m dash pattern, a 45 degree median hatch every 5 m, 2 % crossfall and a level
  assumed 0.5 m below the yard slab;
- the second crane runway (R2) is not on the layout plan: its NNE rail is placed from a site photo and its
  SSW rail at the gauge of the runway that is drawn (R1);
- palm and tree positions in `build_features2.py` are procedural (seeded rows along the two road verges);
- brand lettering on site equipment is not modelled;
- object ids of the legacy CAD model are referenced through aliases (`obj_01` ...) resolved from a private map;
- the colours of the surroundings in `materials_lib.py` come from site-photo samples (grass, hoarding and metal
  roofs) or generic values (asphalt); the derivation is in the comment above each entry;
- survey values of the lot (the lot corners, the south lot line length and bearing) are read from the private
  survey extract, not written in the code. `model/site_features.json` carries the lot line rounded to 1 m (five
  vertices), but the yard slab, the hoarding and the chain-link fence in `site_ground.glb`, `site_context.glb`
  and the 3dm follow the surveyed lot lines at survey accuracy.

Scripts that need nothing private: `gltfw.py`, `georef.py` (it uses the rounded plan bearing 290.34 deg when
the survey extract is absent), `site_frame.py` (after `georef.py`) and the material library `materials_lib.py`
(importable; its self-test compares against a private contract table).

## Conventions

- Plan frame: metres on the layout plan (`page_to_r3`, scale in `georef.json`); glTF frame: x = East,
  y = Up, z = -North, metres, origin at the yard origin, y = 0 = top of the yard slab (`site_frame.py`).
- Rhino export: millimetres, X = East, Y = North, Z = Up.
- Private inputs are read from `SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')`. Use an absolute
  path: most builders change the working directory to `build/`, so a relative value resolves from there.
- Options are environment variables with the prefix `MOCKUP_` (for example `MOCKUP_CANOPY_TOP`,
  `MOCKUP_CANOPY_SCHEME`, `MOCKUP_VMU04_BASE_Y`, `MOCKUP_VMU05_BASE`, `MOCKUP_WEST_FACTORY_STATE`).
- Canonical material names come from `materials_lib.py` (for example `AL_MOUSEGREY`, `GL01_VISION`,
  `GL03_VISION_B`, `GL_DOOR`, `AL_T01`, `AL_T02`, `AL_RAL7038`, `AL_RAL9016`). The canopy is never red: the
  canopy finish options are checked against red in the library self-test and in `export_3dm.py`.

## Build order

1. `georef.py` - writes `build/georef.json` (plan scale, plan bearing, yard origin in plan metres).
2. `r3_extract.py` - vectors and words of the layout plan -> `r3_segs.npy`, `r3_cols.json`, `layout_words.json`.
3. `cache_3dm.py` - render meshes of the legacy CAD model -> `legacy_cad_cache_n.pkl` (the registration
   scripts read an earlier cache without normals, `legacy_cad_cache.pkl`).
4. `register_r3.py`, `register_groups.py` - registration of the legacy CAD groups on the layout plan ->
   `group_registration.json` (`overlay_check.py`, `overlay_groups.py`, `topview.py` draw debug images).
5. `canopy_extract.py`, `canopy_raster.py`, `canopy_register.py`, `canopy_circles.py`, `canopy_circles2.py` -
   analysis of the canopy-extension plan (outline and column circles in plan metres).
6. `materials_lib.py` - self-test and `model/materials.json`.
7. `build_cad.py` -> `model/vmu_cad.glb` (VMU-01 tower without canopy, VMU-03, trellis).
8. `build_canopy.py` -> `model/vmu01_canopy.glb` (existing canopy + canopy extension).
9. `build_vmu02.py`, `build_vmu04.py`, `build_vmu05.py` -> `model/vmu02.glb`, `vmu04.glb`, `vmu05.glb`.
10. `build_context2.py` -> `model/site_context.glb`; then `build_ground.py` -> `model/site_ground.glb`
    (it uses the context footprints as keep-out areas); then `build_context2.py` once more so that the
    gantry crane stands on the runway written by `build_ground.py`.
11. `build_features2.py` -> `model/site_features.json`, `model/vegetation_notes.json`.
12. `export_3dm.py` -> `model/vmu_site_future.3dm`.
13. `validate.py` (optional) - photo-pose and plan checks; needs the private photos.

`build_context.py` and `build_features.py` are the superseded first versions of steps 10 and 11 (kept as a
record; the published files do not come from them).

Published files: `site_context.glb`, `site_ground.glb` and `site_features.json` are the output of steps 10 and
11 as published here, run with the private inputs; the five mock-up GLBs are the output of steps 7 to 9 with
canonical material names. Before publication the metadata of every GLB (node extras, scene extras) was
reduced to a whitelist of generic keys (group, layer, finish, part / role, confidence level, sizes and bounding
boxes, and the parameter block of the canopy), and `site_features.json`, `materials.json` and
`vegetation_notes.json` to the keys the viewer reads; the geometry was not changed. The published `vmu_site_future.3dm` is a format
conversion of the published GLBs (layers `MOCKUP_VMU::...` and `SITE::...`).

## Private inputs (not included)

| name in SOURCES_DIR | used by | content |
|---|---|---|
| `layout_plan` (PDF) | r3_extract | layout plan of the five mock-ups |
| `canopy_extension_plan` (PDF) | canopy_extract, canopy_raster, canopy_circles2 | canopy-extension drawing |
| `legacy_cad.3dm` | cache_3dm | legacy CAD model of the mock-ups |
| `legacy_cad_object_ids.json` | build_cad | alias -> CAD object id map |
| `material_contract.md`, `materials_recipe.json` | materials_lib self-test, validate | material contract table |
| `canopy_plan_extract.json`, `canopy_plan_dxf`, `canopy_plan_dwg`, `canopy_section` | build_canopy | canopy drawings and their extract |
| `canopy_candidate_a.json`, `canopy_candidate_b.json` | build_canopy, build_features2, validate | canopy outlines |
| `vmu02_spec.json`, `vmu02_local_to_gltf.json` | build_vmu02 | element spec from the shop drawings |
| `vmu04_spec.json` | build_vmu04 | element spec from the shop drawings |
| `vmu05_spec.json`, `vmu05_layout_segs.npy` | build_vmu05 | element spec and layout segments |
| `site_survey.json` | georef, build_context2, build_ground, build_features2 | site survey extract (lot line and corners, south-line length / bearing, drains, fence, factory walls, columns) |
| `camera_poses.json` | build_context2 (optional), validate | solved photo poses |
| `photo_correspondences.json`, `photos` | validate | site photos and picked image points |

Build intermediates written next to the scripts (`r3_segs.npy`, `group_registration.json`,
`legacy_cad_cache*.pkl`, `canopy_*.json`, debug images, `_scratch/`) are derived from the private inputs and
are not included either (`.gitignore` excludes them).

## Dependencies

Python 3.12+ with numpy, scipy, shapely, mapbox_earcut, trimesh, opencv-python, Pillow, PyMuPDF (`fitz`),
ezdxf, rhino3dm; `validate.py` also uses Playwright to render the viewer headless.
