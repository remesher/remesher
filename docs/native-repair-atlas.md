# Native repair/atlas quality controls

`--repair-resolution 768` selects the solid-remesh grid independently of the
1536 generation grid. Existing `--mesh-repair solid --no-decimation` remains
required; smoothing stays zero and preclustering/face caps stay disabled.
Default repair resolution remains512.

`--native-atlas-resolution 4096` changes **both** native UV unwrap resolution
and PBR bake texture size; only1024(default) and4096 are accepted. It does not
change sampling, shape geometry, camera, or repair. Legacy Comfy3D rejects a
nondefault native atlas. This is not the entire official postprocessing preset.

```sh
comfy-prompt-cli image-to-glb --backend native-local \
  --native-config /absolute/native-setup.json --image /absolute/padded.png \
  --native-shape-resolution 1536 --native-camera-angle 42.75103780924466 \
  --mesh-seed 42 --texture-seed 43 --no-decimation \
  --mesh-repair solid --repair-resolution 768 --native-atlas-resolution 4096
```

Hermes `remesher_generate` accepts `repair_resolution` and
`native_atlas_resolution`. The plugin JSON selected by `REMESHER_SETTINGS`
may also contain these two keys as defaults; explicit request values override
them. These are **plugin settings**, not fields in the versioned native setup
file, which remains responsible for paths/device/model. Defaults do not enable
repair or no-decimation without the corresponding explicit request.
Without a settings JSON, `REMESHER_REPAIR_RESOLUTION=768` and
`REMESHER_NATIVE_ATLAS_RESOLUTION=4096` supply the same validated defaults.

## Controlled wrestler result

Two sequential native GPU runs changed only repair512→768, then atlas1024→4096.
All raw decoded geometry matches the preceding1536 control bit-for-bit, and
both768 repaired/final geometry arrays match across atlas choices. Existing
latents were not saved, so sampling was repeated at the same seeds; UV packing
and texture pixels are nondeterministic across repeats. No full GLB-byte or
texture-latent determinism claim.

768 retains sharper beard/hair and boot/clothing features, but hands remain
fused/coarse. 4096 gives at most modest crispness and **does not fix dark rear
arm/shoulder regions or the pale back patch**. Exact-weld nonmanifold edges
increase from14(control final) to33(new finals); no manifold/print-ready claim.
No decimation, vertex cap, smoothing, crop/FOV change, downloads or new NVIDIA
packages. Existing runtime CUDA acceleration remains enabled; this is not a
new portability certification.

| Final | Faces | Atlas | Bytes | SHA256 |
|---|---:|---:|---:|---|
| repair512 control |229942|1024|6645932|`54bbfab7c690bd74103d8d04ea265b83ef1aecfc2f24956cb9ae7bcbbff662dd`|
| repair768 A |525742|1024|13552852|`c0b4966e8d9b76bae6f1fdbf299da8ddba38641e326e1ae2b79dab52b601140f`|
| repair768 B |525742|4096|22616832|`26e15758e10542f2e41bd203fc1ae5b62c313e79b562d082fd260de5abef2454`|

Acceptance evidence on the experiment host:
`/home/mg/remesher-native-runtime/pixal-repair-atlas-acceptance/REPORT.md`.
It links actual GLBs, fixed-camera textured/clay body and upper/hand/boot
front/rear/side closeups, executed graphs, memory logs, exact source/wheel
hashes and JUnit. Full suite:266 passed,53 subtests,zero skips. Registered
plugin→installed wheel→saved config→pristine GPU path passed, including a
final-source4096 repeats after config and environment parsing fixes. Owned scopes kept64GiB max,
56GiB high,2GiB swap; A/B peaks8.325/8.335GiB, minimum host available above78GiB,
fish-speech unchanged, child PIDs/ports/scopes cleaned. No merge authorized.

Quality remains provisional; successful export and more triangles are not
proof of a uniformly better character.
