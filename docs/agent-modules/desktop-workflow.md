# Desktop workflow

Scope: Kevin's Mac viewer to Windows Lappy setup and the RustDesk development fork. First priority is fast switching among three physical monitors; second is desktop shortcuts, focus, and window recall. Preserve iPhone/Android compatibility; custom mobile enhancements are later work.

Evidence baseline: 2026-11-15, upstream source revision `7949eca16c15b3eb86d89a9d4f5ac223026dd215`. Source inspection only unless stated otherwise. Installed Mac release is 1.5.3; the development checkout is upstream master and must not be assumed identical to that release.

## Architecture and helper ownership

The canonical project map and build/test conventions are in [AGENTS.md](../../AGENTS.md). Native sessions run through Rust and the Flutter bridge; modern UI is in `flutter/`. Keep platform integration in its owning platform layer. Existing upstream code guidance favors additive changes; Kevin's explicit preference is to fix shared causes and avoid redundant helpers while preserving behavior. Apply that preference with a narrow regression surface, not unrelated restructuring.

Selected ownership map, **not a complete generated helper inventory**:

| Responsibility | Existing owner | Constraint |
| --- | --- | --- |
| Session shortcut dispatch and next/previous/all-display actions | [shortcut_model.dart](../../flutter/lib/models/shortcut_model.dart) | Reuse the registered action path; preserve privacy-mode eligibility and multi-window behavior. |
| Native shortcut matching | [shortcuts.rs](../../src/keyboard/shortcuts.rs) | Inspect matching and key-consumption behavior before adding another listener. |
| Session/display state | [model.dart](../../flutter/lib/models/model.dart) | Check peer capabilities and session ownership before changing display state. |
| Shortcut behavior tests | [shortcut_model_test.dart](../../flutter/test/shortcut_model_test.dart), [keyboard_shortcuts_test.dart](../../flutter/test/keyboard_shortcuts_test.dart) | Extend existing behavior tests when relevant; these have not been run in this checkout. |

## Lessons and decisions

### RD-001 — Reuse the display-switch path

Observation verified by source inspection: `ShortcutModel` already registers next, previous, and all-display actions. The all-display value is a UI sentinel; the existing monitor-opening path expands it to actual display indices and updates local state. Sending the sentinel directly through a new helper would bypass this contract.

Decision: inspect and extend the existing action and monitor-opening path before adding helpers or transport calls. Validate single-display, all-display, and separate-window behavior when changing that path.

Evidence: the `switchDisplayBy`, `openDisplay`, and all-display registration in [shortcut_model.dart](../../flutter/lib/models/shortcut_model.dart).

Status: verified source contract, documented prevention; no custom implementation or runtime verification yet. Revisit when upstream changes these handlers, capability negotiation, or multi-window behavior.

### RD-002 — Separate setup evidence from feature evidence

Observation: Mac release 1.5.3 was checksum-verified against official release metadata, accepted by unsandboxed code-signature/Gatekeeper checks, installed, and opened. An initial sandboxed validation failed, so that result alone did not establish an invalid package. Windows RustDesk installation and end-to-end tests are unverified; the existing Zoho session reported view-only mode and a control request did not establish restored control.

Decision: distinguish package integrity, platform trust, installation, connection, input, and workflow acceptance. Investigate contradictory verification results without disabling security controls. Do not infer successful remote input from video or from tool calls that produce no visible state change.

Status: observed setup lesson, documented prevention. Setup is incomplete. Revisit on a new installer/version, restored host control, or a completed connection test. Keep session IDs, credentials and private logs outside this module.

## Review and enforcement status

The [source quality module](source-quality.md) documents the implemented inventory and file-review gate, coverage limitations, manifest format, and validation status. Existing upstream files and duplicates are explicitly unreviewed. Remote enforcement must be verified separately.

Before claiming a workflow improvement, verify the installed build on the Mac-to-Windows path: access to all three physical monitors, switching without reconnecting, local versus remote shortcut routing, focus recovery, and hide/recall behavior. Add relevant automated regressions around changed seams and distinguish local tests from CI and live acceptance.
