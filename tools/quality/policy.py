"""Compare inventories and enforce explicit duplicate and file-review decisions."""
from collections import defaultdict
import math
import re


def duplicate_groups(report):
    groups = defaultdict(list)
    for d in report['definitions']:
        # Report substantive identical bodies, not trivial getters or declarations.
        if d['tokens'] >= 30:
            key = ('test:' if d['test'] else 'source:') + d['fingerprint']
            groups[key].append(d)
    return {key: values for key, values in groups.items() if len(values) > 1}


def identity(d):
    return d['path'] + '::' + d['symbol'] + (f"#{d['occurrence']}" if d.get('occurrence', 1) > 1 else '')


def changes(current, previous):
    if previous is None:
        return {'baseline': 'unavailable', 'added': [], 'removed': [], 'changed': [], 'moved': []}
    old = {identity(d): d for d in previous['definitions']}
    new = {identity(d): d for d in current['definitions']}
    added, removed = set(new) - set(old), set(old) - set(new)
    moved = []
    for key in sorted(added.copy()):
        matches = [k for k in removed if old[k]['fingerprint'] == new[key]['fingerprint']
                   and old[k]['signature'] == new[key]['signature']]
        if len(matches) == 1:
            prior = matches[0]
            moved.append({'from': prior, 'to': key})
            added.remove(key)
            removed.remove(prior)
    changed = [k for k in old.keys() & new.keys()
               if (old[k]['signature'], old[k]['fingerprint']) !=
                  (new[k]['signature'], new[k]['fingerprint'])]
    return {'baseline': 'available', 'added': sorted(added), 'removed': sorted(removed),
            'changed': sorted(changed), 'moved': moved}


def evaluate(current, rollout, decisions, previous_decisions=None):
    if not isinstance(decisions, dict) or decisions.get('schema') != 1:
        raise ValueError('Unsupported decisions schema')
    for section in ('files', 'duplicates'):
        if not isinstance(decisions.get(section), dict):
            raise ValueError(f'{section} must be an object')
        if any(not isinstance(v, dict) for v in decisions[section].values()):
            raise ValueError(f'{section} entries must be objects')
    failures = [f"Parser error: {e['path']}: {e['error']}" for e in current['errors']]
    rows = []
    roles = decisions.get('files', {})
    exceptions = decisions.get('duplicates', {})
    if decisions.get('schema') != 1:
        failures.append('Unsupported decisions schema')
    legacy_groups = duplicate_groups(rollout)
    groups = duplicate_groups(current)
    duplicate_rows = []
    for key, entries in groups.items():
        members = sorted(identity(d) for d in entries)
        old_members = {identity(d) for d in legacy_groups.get(key, [])}
        decision = exceptions.get(key)
        status = 'legacy-unreviewed' if set(members) <= old_members else 'review-required'
        if decision is not None:
            if decision.get('members') != members or not isinstance(decision.get('reason'), str) or not decision.get('reason', '').strip():
                failures.append(f'Stale/invalid duplicate decision: {key}')
            elif decision.get('decision') == 'distinct-contracts':
                status = 'accepted-distinct-contracts'
            elif decision.get('decision') == 'prohibited':
                status = 'prohibited'
            else:
                failures.append(f'Invalid duplicate decision: {key}')
        if status in {'review-required', 'prohibited'}:
            failures.append(f'Duplicate {status}: {key}: ' + ', '.join(members))
        duplicate_rows.append({'fingerprint': key, 'status': status, 'members': entries})
    for key in exceptions.keys() - groups.keys():
        failures.append(f'Stale duplicate decision (group no longer exists): {key}')
    for path, now in current['files'].items():
        prior = rollout['files'].get(path)
        review = roles.get(path)
        role, status, reviewed = '', 'below-threshold', None
        if review is not None:
            role = review.get('role', '')
            if not isinstance(role, str):
                role = 'invalid role'
            required = ('role', 'rationale', 'reviewed_hash', 'reviewed_lines', 'reviewed_at',
                        'reviewed_revision', 'growth_lines', 'growth_fraction', 'boundary_summary')
            invalid = any(k not in review or review[k] in ('', None) for k in required)
            invalid = invalid or review.get('decision') not in {'keep', 'split-completed'}
            count = review.get('reviewed_lines')
            absolute = review.get('growth_lines')
            fraction = review.get('growth_fraction')
            invalid = invalid or type(count) is not int or type(absolute) is not int
            invalid = invalid or type(fraction) not in (int, float)
            invalid = invalid or any(not isinstance(review.get(k), str) for k in
                                    ('role', 'rationale', 'reviewed_hash', 'reviewed_at',
                                     'reviewed_revision', 'boundary_summary'))
            invalid = invalid or review.get('measurement') != 'physical-lines-v1'
            invalid = invalid or type(review.get('role_changed', False)) is not bool
            if not invalid:
                invalid = not re.fullmatch(r'[0-9a-f]{64}', review['reviewed_hash'])
                invalid = invalid or not re.fullmatch(r'[0-9a-f]{40}', review['reviewed_revision'])
            if not invalid:
                invalid = count < 1 or absolute < 1 or not 0 < fraction <= 1
            if invalid:
                status = 'invalid-review'
            else:
                reviewed = count
                limit = min(absolute, max(1, math.ceil(count * fraction)))
                status = 'reviewed' if now['lines'] - count < limit else 'growth-review-required'
                if review.get('role_changed', False):
                    status = 'role-review-required'
        elif now['lines'] >= 500:
            if prior and prior['lines'] >= 500:
                reviewed = prior['lines']
                limit = min(100, max(1, math.ceil(prior['lines'] * 0.2)))
                status = ('legacy-unreviewed' if now['lines'] - prior['lines'] < limit
                          else 'growth-review-required')
            else:
                status = 'initial-review-required'
        if status.endswith('required') or status == 'invalid-review':
            failures.append(f'{status}: {path}')
        rows.append({'path': path, 'role': role or 'not reviewed', 'lines': now['lines'],
                     'reference_lines': reviewed, 'status': status})
    if previous_decisions:
        for path in previous_decisions.get('files', {}).keys() - roles.keys():
            if path in current['files']:
                failures.append(f'Removed review for existing file: {path}')
    for path in roles.keys() - current['files'].keys():
        failures.append(f'Review record points to missing/renamed/excluded file: {path}')
    return {'failures': failures, 'duplicates': duplicate_rows, 'files': rows}
