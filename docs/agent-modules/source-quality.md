# Source quality checks

The shared command owns source discovery, callable inventory, duplicate review and file-growth review. Run from the repository root with Python 3.12:

```sh
python -m venv /tmp/rustdesk-quality-env
/tmp/rustdesk-quality-env/bin/python -m pip install -r tools/quality/requirements.txt
/tmp/rustdesk-quality-env/bin/python -m unittest discover -s tools/quality -p 'test_*.py' -v
/tmp/rustdesk-quality-env/bin/python tools/quality/check.py --base HEAD
```

`quality-report/inventory.json` and `inventory.md` list definitions; `report.json` and `summary.md` show changes, findings, roles and sizes. Local uncommitted content is explicitly marked dirty in report metadata. CI inventories each pushed tip and PR head, not every intermediate commit. Artifacts are kept for 30 days even after gate failure. PR comparison uses the merge base; push comparison uses the previous pushed tip. Missing comparison history is reported, never disguised as an empty successful diff.

## Coverage and rollout

Rust and Dart use pinned tree-sitter grammars; Python uses its AST. Methods, nested functions and closures are included. Reference counts are unknown, not zero. Macro expansion is not inventoried. Other source languages are listed as coverage gaps and still measured for size. Generated bridge/registrant files, generated Dart suffixes, shared external `hbb_common`, and build output are excluded in `inventory.py`. Test definitions are categorized separately. Syntax errors fail the gate.

Identical syntax bodies with at least 30 tokens produce duplicate candidates; literal and identifier differences remain significant. This is deliberately conservative and does not prove semantic equivalence or detect all redundant helpers. New candidates require review; the fixed upstream rollout revision in `check.py` retains legacy candidates visibly as **unreviewed**. It must not be refreshed to hide growth.

`tools/quality/decisions.json` is the canonical decision manifest. Duplicate records are keyed by the reported fingerprint and contain the exact sorted `members`, a substantive `reason`, and `decision` (`distinct-contracts` or `prohibited`). Body or membership changes invalidate approval. Remove stale entries only after inspecting why the group disappeared.

## File review

New files reaching 500 physical lines require review. Existing upstream files above the threshold remain visibly unreviewed until touched growth reaches 100 lines or 20%, whichever comes first. Growth is measured cumulatively against the rollout or last substantive review, not the previous commit. A cohesive large file may remain intact.

A file record is keyed by its relative path and contains `role`, `rationale`, `boundary_summary`, `decision` (`keep` or `split-completed`), `reviewed_hash` (SHA-256), `reviewed_revision` (full Git SHA that is an ancestor of the checked head), `reviewed_lines`, `reviewed_at`, `measurement` (`physical-lines-v1`), `growth_lines`, and `growth_fraction`. Record reviewer identity when known. Git content verifies the claimed hash and line count. Review the committed content, then record that revision in a follow-up change; do not fabricate a future SHA. Renamed/deleted records fail until reconciled. Removing a review while its source file still exists fails against the comparison manifest, preventing fallback to the older rollout allowance.

Set `role_changed: true` when responsibilities or boundaries need re-review; it blocks until a substantive review updates the record and clears the declaration. Role, dependency, public API and registry-pattern changes also require human review below the size trigger. Automatic semantic drift detection is **not implemented**. Reviewers must compare role headers and record registry adoption/defer rationale and concrete reconsideration conditions in this module when applicable. Do not treat a passing size gate as architectural approval.

## Verification status

Local scanner/policy regression tests and a repository scan are the first validation layer. The workflow is configured for push/PR/manual runs; a workflow file does not establish a successful remote run or branch-protection enforcement. Neither these checks nor their unit tests are live desktop E2E tests; that specification remains in [live-e2e.md](live-e2e.md).

## SQ-001 — Test the enforcement tool against bypasses

Verified during Codex review of this new tooling: trait-method identities collided, Dart factories/operators were omitted, empty records bypassed validation, malformed roles interrupted reports, deleted reviews restored legacy growth allowances, and unrelated-branch content could stand in as review evidence. These were defects in the fork tooling, not findings about upstream RustDesk.

Prevention: distinguish callable owners and repeated occurrences; cover Dart variants; reject empty/malformed decisions; preserve failure artifacts; compare prior review manifests; and verify review commits are ancestors of HEAD. Parser/policy regressions and an isolated real-Git integration test exercise these failures. Revisit when grammar packages, symbol identity, manifest schema, or baseline selection changes. This is project evidence; no new universal abstraction or cross-project rule was introduced.
