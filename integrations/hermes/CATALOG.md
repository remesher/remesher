# Compatibility, catalog preparation and integration boundaries

## Supported packaging

This is a **Python `plugin.yaml` + `register(ctx)`** integration, not a portable
MCP server. It retains exactly four tools (`remesher_health`,
`remesher_generate`, `remesher_job`, `remesher_assets`) and the namespaced
`remesher:remesher` skill. No required credentials, hooks or middleware are
registered. The adapter itself is stdlib-only; client and inference dependencies
stay in separate environments. Configuration still uses `REMESHER_SETTINGS` or
the documented scalar environment settings. Profile `config_schema` migration
is not part of this release.

The compatibility floor is Hermes **0.22.2**, validated against the official
v0.22.2 commit `d923a5eb487a17c0a68801bba9ef0f56c81040a8` and the later installed
SDK `9e01b44dd23978f9ff40b7837467f3a9f1582130`. CI uses an immutable official
SDK revision and actual doctor/validator, not stubs. Platform metadata says
Linux; actual native inference acceptance is Linux ARM64 NVIDIA Spark. POSIX
code alone does not certify macOS, Windows, MPS, ROCm or CPU model execution.

## License decision is explicit, not inferred

The repository owner explicitly selected **Apache-2.0 for Remesher own code**.
The repository and this plugin directory include the exact Apache License 2.0
text as `LICENSE`; package and plugin metadata use SPDX `Apache-2.0`.
This grant does not relicense third-party code, runtimes, model weights, input
assets or generated outputs. No Meshy source is copied. Repository
`docs/licensing.md` records the scoped source/asset inspection: the owner confirmed
sketch ownership/rights and the Mixamo FBX was removed. This is not exhaustive
third-party distribution clearance or legal review.

## Preparing a catalog entry (not submitting one)

After the final integration/release commit exists, prepare an entry in a separate
Hermes catalog PR with:

- repo `https://github.com/remesher/remesher`, subdir `integrations/hermes`;
- the actual full 40-character reviewed commit SHA, not a branch/tag/placeholder;
- matching plugin version `0.2.1`, `license: "Apache-2.0"`,
  `requires_hermes: ">=0.22.2"`, category `tools`,
  tier `community` (only Nous assigns official/verified), platforms `[linux]`;
- the exact four tool names above and empty hook/middleware/required-env lists;
- disclosure of local subprocesses, detached supervisors, local image reads and
  upload to the configured ComfyUI server, optional owned GPU runtime, persistent
  job logs/assets, and separately approved setup installs/model downloads;
- documentation URL pinned to that same commit. README references to repository
  documentation use immutable URLs because an installed subdirectory does not
  contain the repository's parent `docs/` directory.

Run the README's pinned Git-subdirectory install in a fresh disposable
`HERMES_HOME`, doctor `--ci`, and validator `--install-deps --json`. Verify actual
four-tool registration, namespaced skill discovery, unconfigured health and
normal-config model routing. Test update persistence on disposable job data
only, with no active worker; never update the live profile as an admission test.
Passing validation is not catalog approval: maintainers review and merge the
catalog entry separately. First-party license selection is resolved; final review,
third-party distribution clearance and catalog admission remain separate gates.

## Meshy reference and scope

The October 22 reference was inspected at
`NousResearch/hermes-official-plugins/meshy`, pin
`c16e967d798d8dd3b1827a62673c18627f31e0ed` (0.4.0). Its portable MCP packaging does
not require rewriting this Python adapter. Meshy bundles its own three.js
renderer; no general-purpose Hermes SDK GLB renderer was established. Its local
turntable helper requires additional Node/Chromium/ffmpeg setup and is not an
automatic universal messenger hook. None is added or claimed here.

**Desktop viewer/gallery integration belongs to Teknium**, outside this release
and not an implementation obligation for Remesher. Preserve the existing
job-owned GLB paths, hashes and status tools for that external integration.
Messenger preview rendering is also outside current scope.

A future paid hosted Remesher service via managed **fstack-remesher** is a product
plan only. This release adds no billing, authentication or hosted runtime, and
defines no speculative hosted API. Native local runtimes and existing CLI/plugin
boundaries remain unchanged.
