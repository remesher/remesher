# Opt-in native 512 → 1536 shape refinement

`image-to-glb --native-shape-resolution 1536` adds the two-node cascade from
ComfyUI's shipped Pixal3D workflow: `Trellis2UpsampleStage(target_resolution=1536)`
followed by a 12-step Euler **simple** KSampler, CFG 7.5, using the existing
shape model and mesh seed. Shape decoding and texture-stage conditioning/latent
are rewired to the refined outputs. Default 512 preserves the existing graph.
Only 512 and 1536 are accepted; there is no automatic 1024 fallback.

The Hermes `remesher_generate` request exposes `native_shape_resolution` and
optional `native_camera_angle` (horizontal degrees). These are per-request
controls, not persistent changes to operator runtime setup. Existing native
setup configuration still selects paths/device/model. Legacy backends reject
nondefault native shape settings. Omit camera override to retain MoGe behavior.

Example with an already masked, padded input and a deliberately frozen camera:

```sh
comfy-prompt-cli image-to-glb --backend native-local \
  --native-config /absolute/native-setup.json \
  --image /absolute/prepared.png \
  --native-shape-resolution 1536 --native-camera-angle 42.75103780924466 \
  --mesh-seed 42 --texture-seed 43 --no-decimation \
  --mesh-repair solid --repair-resolution 512
```

This is **shape-cascade parity**, not full official-preset parity. Repair remains
512 with zero smoothing, precluster cap disabled, and UV/PBR atlas remains 1024.
No new checkpoints or NVIDIA-only dependencies are installed. Generation
resolution is not polygon count; no-decimation disables the simplifier rather
than substituting a large cap. With repair enabled, raw decoded and repaired
SaveGLB outputs remain in the private runtime output directory, separately from
the downloaded final GLB. Inspect raw detail before attributing loss to repair.

1536 can require more memory. Use an explicitly approved bounded process,
verify effective cgroup limits, retain memory/events and server logs, and stop
rather than silently reducing resolution. A valid graph is not GPU acceptance
or a quality-improvement claim. Independent review remains required.
