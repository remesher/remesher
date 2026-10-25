# macOS provisioning acceptance

## Verified on Apple M2, 8 GiB, macOS 27

A fresh internal runtime and ComfyUI checkout were created using the public
`native-setup plan/apply/check` CLI, with explicit package-installation and
low-memory approvals. Previously downloaded external model weights were reused
and hash-verified; this was not a fresh model-download test.

- The runtime root was initially absent, and planning did not create it.
- Automated apply installed Python-environment packages using Python 3.12.12,
  torch 2.14.1 and torchvision 0.29.1. The Python interpreter was already
  available on the host; this does not claim OS/Python bootstrap installation.
- All 34 pinned-checkout requirements were satisfied; independent `pip check`
  passed. All four external model hashes verified.
- A real MPS tensor multiplication and synchronization passed. Apply/check
  reported ready with the invocation-local low-memory acknowledgment.
- A subsequent apply without package-install/model-download permission left
  runtime files, package inventory and config bytes/inode/mtime unchanged.
- Relevant parent verification: 174 tests and 57 subtests passed, no skips.
  The separately executed full suite retained six pre-existing Darwin
  rigging/atomic-publication failures; these are outside provisioning scope.

## Fresh-runtime generation: partial acceptance

The actual registered Hermes plugin submitted a full-quality image-to-GLB job
through a private `native_config` snapshot, using this newly provisioned runtime
and explicit per-job `native_allow_low_memory: true`. It verified the owned
server reported MPS. CPU fallback was enabled and OMP threads were explicitly
set to four. Input and graph controls matched the earlier successful manually
prepared-runtime run, apart from private filenames/output prefixes.

The new run completed structure, shape refinement, decoding and repair, then
reached texture sampling step 11/12 before the 12-hour deadline. No final
textured asset was returned. Intermediate decoded/repaired GLBs are not final
acceptance artifacts. The supervisor and recorded child processes subsequently
exited.

The earlier prepared-runtime plugin run completed in approximately six hours
and passed independent Blender import/render checks. That result must not be
substituted for completed generation on the freshly provisioned environment.
The fresh run's refinement and texture stages were slower; package inventories
showed differences in certifi, huggingface-hub, kornia and multidict, but no
causal dependency or memory-pressure explanation has been established.

## Scope

This change demonstrates automated macOS environment provisioning, readiness,
model reuse/verification and idempotence. It does not certify full-quality
completion within 12 hours on every 8 GiB Mac, GPU-only execution, rigging,
Windows support, or fully hash-locked transitive dependencies. The acceptance
harness used a 5 GiB disk reserve and keep-awake protection; these should not be
confused with additional guarantees in the plugin itself.
