"""Run source quality checks and publish revision-linked inventories and review reports."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from inventory import ROOT, digest, git, scan
from policy import changes, evaluate

# Fixed upstream starting point; changing it requires an explicit rollout decision.
ROLLOUT = '7949eca16c15b3eb86d89a9d4f5ac223026dd215'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', help='PR merge base or previous pushed SHA')
    parser.add_argument('--output', type=Path, default=ROOT / 'quality-report')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    metadata = {'head': git('rev-parse', 'HEAD'), 'rollout': ROLLOUT, 'base': args.base,
                'worktree_dirty': bool(git('status', '--porcelain'))}
    current = scan()
    (args.output / 'inventory.json').write_text(json.dumps(current, indent=2) + '\n')
    previous, baseline_error, base = None, None, None
    if args.base and set(args.base) != {'0'}:
        try:
            base = git('rev-parse', '--verify', args.base + '^{commit}')
            previous = scan(base)
            if previous['errors']:
                baseline_error = 'Comparison revision has parser errors; diff is incomplete'
        except (subprocess.CalledProcessError, ValueError) as exc:
            baseline_error = f'Comparison baseline unavailable: {exc}'
    else:
        baseline_error = 'Comparison baseline unavailable: first run/new branch or no --base supplied'
    try:
        rollout = scan(ROLLOUT)
        if rollout['errors']:
            raise ValueError('Rollout revision has parser errors')
        decisions = json.loads((ROOT / 'tools/quality/decisions.json').read_text())
        prior_decisions = None
        evidence_base = base or 'HEAD^'
        manifest = 'tools/quality/decisions.json'
        try:
            exists = git('ls-tree', evidence_base, '--', manifest)
        except subprocess.CalledProcessError:
            exists = ''
        if exists:
            prior_decisions = json.loads(git('show', f'{evidence_base}:{manifest}'))
        result = evaluate(current, rollout, decisions, prior_decisions)
        # Validate evidence without executing historical code or trusting claimed sizes.
        for path, review in decisions['files'].items():
            revision = review.get('reviewed_revision', '')
            if not isinstance(revision, str) or len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
                continue  # Already reported by policy validation.
            try:
                subprocess.run(['git', '-C', str(ROOT), 'merge-base', '--is-ancestor', revision, 'HEAD'], check=True)
                data = subprocess.check_output(['git', '-C', str(ROOT), 'show', f'{revision}:{path}'])
                if digest(data) != review.get('reviewed_hash') or len(data.splitlines()) != review.get('reviewed_lines'):
                    result['failures'].append(f'Review evidence mismatch: {path}')
            except subprocess.CalledProcessError:
                result['failures'].append(f'Review evidence unavailable: {path}')
    except (subprocess.CalledProcessError, ValueError, OSError, TypeError) as exc:
        result = {'failures': [f'Cannot evaluate policy: {exc}'], 'duplicates': [], 'files': []}
    result.update({'metadata': metadata, 'diff': changes(current, previous),
                   'baseline_warning': baseline_error})
    if previous and previous['errors']:
        result['failures'].append(baseline_error)
    (args.output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    text = ['# Source quality report', '', f"Revision: `{metadata['head']}`", '',
            f"Definitions: {len(current['definitions'])}; source files: {len(current['files'])}",
            f"Coverage gaps: {len(current['coverage_gaps'])}; parser errors: {len(current['errors'])}", '',
            '## Coverage limitations', '', *['- ' + s for s in current['limitations']], '',
            *['- Unsupported inventory language: `' + p + '`' for p in current['coverage_gaps']], '',
            '## Changes', '', baseline_error or 'Comparison baseline available.', '']
    for kind in ('added', 'removed', 'changed', 'moved'):
        text += [f"{kind}: {len(result['diff'][kind])}"]
        text += ['- ' + str(x) for x in result['diff'][kind]]
    text += ['', '## Gate findings', ''] + (['- ' + f for f in result['failures']] or ['No gate failures.'])
    text += ['', '## Duplicate candidates', '',
             'Identical substantive syntax bodies are review candidates, not proof of shared semantics.', '']
    for group in result['duplicates']:
        text += [f"- {group['status']}: `{group['fingerprint']}`"]
        text += [f"  - `{d['path']}:{d['line']}` — `{d['symbol']}`" for d in group['members']]
    text += ['', '## File roles and size', '', '| File | Role | Lines | Reference | Status |',
             '| --- | --- | ---: | ---: | --- |']
    for f in result['files']:
        role = f['role'].replace('|', '\\|').replace('\n', ' ')
        text.append(f"| {f['path']} | {role} | {f['lines']} | {f['reference_lines']} | {f['status']} |")
    listing = ['# Callable inventory', '', f"Revision: `{metadata['head']}`", '',
               '| File:line | Symbol | Kind | Test |', '| --- | --- | --- | --- |']
    for d in current['definitions']:
        symbol = d['symbol'].replace('|', '\\|').replace('\n', ' ')
        listing.append(f"| {d['path']}:{d['line']} | {symbol} | {d['kind']} | {d['test']} |")
    (args.output / 'inventory.md').write_text('\n'.join(listing) + '\n')
    (args.output / 'summary.md').write_text('\n'.join(text) + '\n')
    print(f"{len(current['definitions'])} definitions; {len(current['coverage_gaps'])} coverage gaps; "
          f"{len(result['failures'])} gate failures. Report: {args.output}")
    return 1 if result['failures'] else 0


if __name__ == '__main__':
    sys.exit(main())
