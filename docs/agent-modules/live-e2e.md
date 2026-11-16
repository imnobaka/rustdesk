# Live desktop E2E

Core skill: `test-e2e`. Scope: Mac viewer to Windows Lappy, first for physical-monitor switching and then shortcuts, focus and recall. See [desktop workflow](desktop-workflow.md) for source ownership and current setup evidence.

Status as of 2026-11-15: **test specification only**. No live RustDesk session, event-driven runner, event instrumentation, timing baseline, or E2E CI run has been verified. Mac 1.5.3 is installed; Windows setup/control remains unverified. Do not interpret these scenarios as executed tests. Record actual build identities before testing; source master is not the installed release.

## Environment and observation contract

Use the existing authorized WireGuard path and real Mac/Windows applications. Preserve Zoho and other recovery access. Confirm control of the intended host before input tests. Use a temporary test window with distinct visible content on each physical monitor so selected display, delivered frames, and input target can be distinguished without reading unrelated user work. Record the display identities and mapping; do not assume indices remain stable across reconnects.

Select actual supported event/log sources during harness implementation. Required observations are session lifecycle, requested/active display identity, a new frame from the selected display, focus/input-routing state where exposed, and the visible result of test input. Do not invent event names or infer all of these from one UI badge. If only screenshots/AX polling is available, label the run as limited live acceptance rather than complete race instrumentation.

Subscribe before each action and correlate to the session and switch request when supported. Establish per-phase and total deadlines from measured normal behavior and the desired responsiveness requirement; neither is established yet. Record the product timeout separately from harness deadlines. Timing gates remain pending until those budgets are specified.

## Required scenarios

| Scenario | Trigger and observable acceptance |
| --- | --- |
| Physical monitor switching | From a verified connected session, select each of the three physical monitors. Observe new frames containing its test marker and input reaching its test window, within the agreed budget and without reconnecting. |
| Overlapping switches | Trigger a second switch while the first is pending, then exercise the reverse event ordering through controlled test infrastructure. The latest intended selection wins; late frames/state cannot leave the UI displaying or controlling the wrong monitor. |
| Switch timeout and late response | Delay or withhold completion on a test-owned path. Observe the product's bounded error/recovery and verify that a late completion cannot overwrite a newer selection or revive a closed session. |
| Local and remote shortcuts | Trigger configured chords with the intended window focused. Observe which side receives the action, including key-up/release; local actions must not leak into the host. |
| Focus change during input | Change focus while a test key/button is held. Observe release and correct routing after returning; no stuck key, stray input or duplicate action. |
| Hide/recall and reconnect | Hide and recall during an active session and during a pending connection. Observe the intended window/session, preserved or explicitly restored connection, correct focus, and rejection of obsolete session events. |

Before injecting delay or loss, identify a reversible, session-scoped mechanism and its cleanup. Do not interrupt the shared VPN or disable host security. Restore only test-owned state; preserve existing user windows and monitor configuration. Collect sanitized state transitions and targeted screenshots. Unexpected writes or inability to restore input/display state stop the scenario and require a clear recovery report.

## Implementation and maintenance

Reuse existing shortcut/display tests for lower-level regressions; they do not substitute for these live scenarios. Integrate a live job with suitable device access into the existing CI when that infrastructure exists. Required live scenarios unavailable to CI must remain explicitly blocked/skipped, never reported as passing.

After a demonstrated failure, use `learn` to record its cause, reproducing event ordering, prevention and verification evidence here or in the owning workflow module. Revisit this specification when display-switch contracts, shortcut routing, window lifecycle, transport, or test environment changes. Helpers and architecture remain owned by the linked workflow module.
