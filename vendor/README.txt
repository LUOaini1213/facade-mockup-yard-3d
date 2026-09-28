Vendored JavaScript libraries (unmodified upstream files; see ../THIRD_PARTY_LICENSES.md):

  three.module.js          three.js r160 (0.160.0) build/three.module.js            MIT  LICENSE-three.js
  jsm/                     three.js r160 examples/jsm - only the add-ons viewer.js imports and their own imports
                           (OrbitControls, GLTFLoader, RGBELoader, Sky, CSS2DRenderer, EffectComposer, RenderPass,
                           ShaderPass, MaskPass, Pass, GTAOPass, OutlinePass, OutputPass, SMAAPass, BufferGeometryUtils,
                           CopyShader, GTAOShader, OutputShader, PoissonDenoiseShader, SMAAShader, SimplexNoise)
                                                                                     MIT  LICENSE-three.js
  three-mesh-bvh/          three-mesh-bvh 0.8.3, build/index.module.js               MIT  three-mesh-bvh/LICENSE
  three-gpu-pathtracer/    three-gpu-pathtracer 0.0.23, build/index.module.js        MIT  three-gpu-pathtracer/LICENSE
                           (tested with three r160; viewer.js adds the Scene.prototype environmentRotation /
                           backgroundRotation shim it needs. On some integrated GPUs it renders correctly only with
                           Chrome / Edge started with --use-angle=vulkan.)

The builds reference *.js.map source maps that are not included.
