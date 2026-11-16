"""Regression tests for syntax coverage and review gates, independent of app builds."""
import unittest

from inventory import tree_definitions, python_definitions
from policy import evaluate, changes


def report(lines=499, definitions=None):
    return {'files': {'example.rs': {'lines': lines, 'hash': 'a' * 64}},
            'definitions': definitions or [], 'errors': []}


def definition(name, fingerprint='same', test=False):
    return {'path': 'example.rs', 'symbol': name, 'fingerprint': fingerprint,
            'test': test, 'tokens': 40, 'signature': '()', 'line': 1}


class InventoryTests(unittest.TestCase):
    def test_rust_methods_nested_functions_closures(self):
        source = b'impl Widget { pub fn run(&self) { fn inner() {} let f = |x: i32| x + 1; } }'
        rows = tree_definitions('example.rs', source)
        self.assertIn('Widget::run', [r['symbol'] for r in rows])
        self.assertIn('Widget::run::inner', [r['symbol'] for r in rows])
        self.assertTrue(any(r['kind'] == 'closure_expression' for r in rows))
        self.assertEqual(rows[0]['visibility'], 'pub')

    def test_dart_methods_accessors_local_and_closure(self):
        source = b'class Widget { int get count => 1; void run() { int local() => 2; final f = (int x) => x + 1; } }'
        rows = tree_definitions('example.dart', source)
        symbols = [r['symbol'] for r in rows]
        self.assertIn('Widget::count', symbols)
        self.assertIn('Widget::run', symbols)
        self.assertIn('Widget::run::local', symbols)
        self.assertTrue(any(r['kind'] == 'function_expression' for r in rows))

    def test_trait_methods_and_dart_variants_have_distinct_identities(self):
        rows = tree_definitions('example.rs', b'impl A for X { fn f() {} } impl B for X { fn f() {} }')
        self.assertEqual(len({r['symbol'] for r in rows}), 2)
        source = b'class A { A() {} A.named() {} factory A.create() { return A(); } void operator +(A a) {} int get value => 1; set value(int x) {} } extension Foo on String { void f() {} }'
        rows = tree_definitions('example.dart', source)
        self.assertEqual(len(rows), 7)
        self.assertEqual(len({r['symbol'] for r in rows}), 7)
        self.assertIn('Foo::f', [r['symbol'] for r in rows])

    def test_python_nested_async(self):
        rows = python_definitions('example.py', b'class A:\n    async def run(self):\n        def local():\n            return 1\n        return local()\n')
        self.assertEqual([r['symbol'] for r in rows], ['A::run', 'A::run::local'])

    def test_python_signature_keeps_async_return_type_and_decorators(self):
        rows = python_definitions('example.py', b'@cache\nasync def run(x: int) -> str:\n    return str(x)\n')
        self.assertEqual(rows[0]['signature'], '@cache async (x: int) -> str')

    def test_comments_do_not_hide_duplicates_but_literals_do(self):
        a = tree_definitions('example.rs', b'fn a() { call("a"); }')[0]
        b = tree_definitions('example.rs', b'fn b() { /* detail */ call("a"); }')[0]
        c = tree_definitions('example.rs', b'fn c() { call("b"); }')[0]
        self.assertEqual(a['fingerprint'], b['fingerprint'])
        self.assertNotEqual(a['fingerprint'], c['fingerprint'])

    def test_parser_failure_visible(self):
        with self.assertRaises(ValueError):
            tree_definitions('bad.rs', b'fn broken( {')


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.decisions = {'schema': 1, 'files': {}, 'duplicates': {}}

    def test_initial_threshold_and_legacy_growth(self):
        self.assertFalse(evaluate(report(), report(), self.decisions)['failures'])
        self.assertTrue(evaluate(report(500), report(), self.decisions)['failures'])
        self.assertFalse(evaluate(report(599), report(500), self.decisions)['failures'])
        self.assertTrue(evaluate(report(600), report(500), self.decisions)['failures'])

    def test_keep_cumulative_growth_role_change_and_deleted(self):
        review = {'role': 'Own behavior', 'rationale': 'Cohesive; isolated tests',
                  'reviewed_hash': 'a' * 64, 'reviewed_revision': 'b' * 40,
                  'reviewed_lines': 600, 'reviewed_at': '2026-11-15',
                  'growth_lines': 100, 'growth_fraction': .2, 'decision': 'keep',
                  'boundary_summary': 'No transport ownership', 'measurement': 'physical-lines-v1'}
        self.decisions['files']['example.rs'] = review
        self.assertFalse(evaluate(report(699), report(), self.decisions)['failures'])
        self.assertTrue(evaluate(report(700), report(), self.decisions)['failures'])
        review['role_changed'] = True
        self.assertTrue(evaluate(report(600), report(), self.decisions)['failures'])
        missing = report(); missing['files'] = {}
        self.assertTrue(evaluate(missing, report(), self.decisions)['failures'])

    def test_duplicate_expansion_and_stale_exception(self):
        pair = [definition('one'), definition('two')]
        current = report(definitions=pair)
        self.assertTrue(evaluate(current, report(), self.decisions)['failures'])
        self.assertFalse(evaluate(current, current, self.decisions)['failures'])
        self.decisions['duplicates']['source:same'] = {
            'members': ['example.rs::one', 'example.rs::two'],
            'reason': 'Different lifecycle owners', 'decision': 'distinct-contracts'}
        self.assertFalse(evaluate(current, report(), self.decisions)['failures'])
        expanded = report(definitions=pair + [definition('three')])
        self.assertTrue(evaluate(expanded, current, self.decisions)['failures'])
        self.assertTrue(evaluate(report(), current, self.decisions)['failures'])

    def test_test_and_runtime_are_separate(self):
        rows = [definition('one'), definition('test_one', test=True)]
        self.assertFalse(evaluate(report(definitions=rows), report(), self.decisions)['failures'])

    def test_malformed_records_fail_closed(self):
        for malformed in ([], {'schema': 1, 'files': [], 'duplicates': {}},
                          {'schema': 1, 'files': {'x': None}, 'duplicates': {}}):
            with self.assertRaises(ValueError):
                evaluate(report(), report(), malformed)
        self.decisions['files']['example.rs'] = {'role': []}
        self.assertTrue(evaluate(report(), report(), self.decisions)['failures'])

    def test_empty_records_and_removed_review_cannot_restore_legacy(self):
        self.decisions['files']['example.rs'] = {}
        self.assertTrue(evaluate(report(800), report(1000), self.decisions)['failures'])
        previous = self.decisions
        clean = {'schema': 1, 'files': {}, 'duplicates': {}}
        self.assertTrue(evaluate(report(800), report(1000), clean, previous)['failures'])
        pair = report(definitions=[definition('one'), definition('two')])
        clean['duplicates']['source:same'] = {}
        self.assertTrue(evaluate(pair, pair, clean)['failures'])

    def test_move_diff_and_missing_baseline(self):
        before = report(definitions=[definition('one')])
        after = report(definitions=[definition('two')])
        self.assertEqual(len(changes(after, before)['moved']), 1)
        self.assertEqual(changes(after, None)['baseline'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
