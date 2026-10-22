# PR27 bounded final validation

## Boundary and verdict

The independently reviewed baseline supplied for this task is
`8a034ab0d04c9043e5ce19834c4a48029649035a`. The integrated executable/package
candidate reviewed here is `f82713870400f926e5da712169982d6ce7611c96`.
This evidence commit changes documentation only; it does not change that code,
package metadata, lockfile, fixtures, workflows, or tests.

**Verdict: no blocking integration regressions found in this bounded delta.**
A fresh non-author validation agent inspected the complete delta, relevant
runtime/download callers, regression tests, and the installed httpcore 1.0.9
trace/HTTP11 exception-cleanup implementation. This is the explicitly authorized
independent-inspection fallback, not a formal GitHub approval or a new broad
review of previously accepted features.

A read-only Codex review was attempted but could not inspect the repository:
its sandbox reported `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`.
No sandbox/approval bypass was attempted; that attempt is **not** approval.

## Scoped findings checked

- Apache-2.0 remains declared in Python and standalone plugin metadata. Root and
  plugin license copies match the expected full-text bytes. The clean installed
  wheel contains the actual `dist-info/licenses/LICENSE`, with matching
  `License-Expression` and `License-File`; no workspace assets are bundled.
- The owner-confirmed sketch is unchanged from the review baseline. The Mixamo
  FBX is absent from the current tree. The three notebook paths skip optional
  retargeting without an FBX, preserve the rigged GLB output, reject an explicitly
  missing file, and clear an earlier upload selection. No replacement download
  or new asset-license grant is introduced.
- SIGTERM during `Popen` return/assignment is deferred until ownership is recorded;
  cleanup reaps the real child and restores the previous handler. Repeated TERM
  and both default/ignored prior handlers are covered.
- Absolute artifact deadline ownership starts before response headers and lasts
  through body reads. Idle HTTP/1 connections are rejected before sending request
  bytes and retried on a fresh socket; unrelated active connections survive.
  Timer cancellation/join and partial-file cleanup are covered. HTTP/2 is rejected
  rather than interrupting a multiplexed socket. `httpcore==1.0.9` is explicit in
  project requirements and lock metadata and was exercised by installed tests.
- Added-line security inspection found no introduced production secret, shell
  injection, dynamic execution, pickle loading or SQL construction. Notebook-test
  `exec` calls execute repository-controlled fixture cells, not external input.

## Executed local gates

| Gate | Actual result |
|---|---|
| Locked application, Python 3.13.12, complete tests plus real CLI/plugin partitions | **290 passed, 53 subtests passed**, no failures/errors/skips |
| Fresh wheel, fresh dependency venv, outside-checkout import | **239 application tests passed** |
| Same installed wheel, plugin partition | **51 passed, 53 subtests passed** |
| Installed package license checks, both model setup plans, `uv pip check` | Passed |
| Focused Ruff 0.17.1, both canonical commands, whitespace check | Passed |
| Cancellation/deadline focused rerun | **16 passed** |
| Official Hermes v0.22.2 SDK at `d923a5eb487a17c0a68801bba9ef0f56c81040a8` | Real doctor/discovery registered exactly four tools; validator passed without warnings |
| SDK missing-dependency negative gate (`python -S`) | Failed meaningfully as required |

The original independent review repro scripts were copied into the evidence
scratch directory, changing only their defect-detection assertions into fixed
behavior assertions. The real-child repro returned exit 143, owned/closed runtime,
restored handler, and **no live child** after cleanup. The trickling-header repro
returned `TimeoutError` at **0.201 seconds** for a 0.2-second budget, with **zero
remaining files**. Both fixtures shut down completely.

Commands are the canonical `.github/workflows/ci.yml` commands, with disposable
`HERMES_HOME`, actual installed CLI/Python paths, `TERM=dumb` and `NO_COLOR=1`.
The wheel command is `sh scripts/verify-native-wheel.sh`; the SDK command is
`scripts/verify-plugin-sdk.py` against a separately downloaded immutable SDK
archive and isolated dependency environment. Local raw JUnit, SDK log and copied
repros are under `/home/mg/.hermes/cache/scratch/remesher-pr27-final/`; these are
operator evidence, not shipped repository artifacts.

## Remaining delivery boundaries

The final documentation commit must be normally pushed, read back from the
remote, and receive all five canonical contexts on its exact SHA. The final
handoff reports that SHA, run IDs, context conclusions, and review-thread count;
this document does not preclaim future hosted results.

Fresh both-model GPU receipts are owned by the parallel acceptance worker and
must be bound to the same executable source. No inference, weight download,
global environment change, release, catalog submission, branch-protection change,
or merge was performed by this validator. Broader third-party distribution rights,
hardware/quality claims outside the stated acceptance, and release decisions
remain separate owner gates.
