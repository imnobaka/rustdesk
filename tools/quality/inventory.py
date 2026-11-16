"""Discover first-party source and inventory syntax-level callable definitions."""
import ast
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import tokenize
import io

from tree_sitter import Language, Parser
import tree_sitter_dart
import tree_sitter_rust

ROOT = Path(__file__).resolve().parents[2]
SOURCE_EXTENSIONS = {'.rs', '.dart', '.py', '.c', '.cc', '.cpp', '.h', '.hpp',
                     '.m', '.mm', '.swift', '.kt', '.java', '.js', '.ts', '.tis', '.sh'}
PARSERS = {'.rs': Parser(Language(tree_sitter_rust.language())),
           '.dart': Parser(Language(tree_sitter_dart.language()))}
EXCLUDED = ('libs/hbb_common/', 'target/', 'build/', '.git/',
            'flutter/build/', 'flutter/.dart_tool/')
GENERATED = {'bridge_generated.rs', 'bridge_generated.io.rs', 'generated_bridge.dart',
             'generated_plugin_registrant.cc', 'generated_plugin_registrant.h',
             'GeneratedPluginRegistrant.swift', 'GeneratedPluginRegistrant.java'}


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args]).decode().strip()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def source_files(revision=None):
    """Read only tracked/unignored source; revision reads never execute old code."""
    if revision:
        paths = git('ls-tree', '-r', '--name-only', revision).splitlines()
    else:
        paths = git('ls-files', '--cached', '--others', '--exclude-standard').splitlines()
    for name in sorted(set(paths)):
        p = Path(name)
        if p.suffix not in SOURCE_EXTENSIONS or name.startswith(EXCLUDED):
            continue
        if p.name in GENERATED or p.name.endswith(('.g.dart', '.freezed.dart')):
            continue
        if revision:
            data = subprocess.check_output(['git', '-C', str(ROOT), 'show', f'{revision}:{name}'])
        else:
            if not (ROOT / name).is_file():
                continue
            data = (ROOT / name).read_bytes()
        yield name, data


def is_test(path, scope):
    return ('/test/' in '/' + path or '/tests/' in '/' + path or
            Path(path).stem.startswith('test_') or Path(path).stem.endswith(('_test', '_tests')) or
            'tests' in scope.split('::'))


def record(path, scope, kind, signature, line, body_tokens, visibility=None):
    encoded = json.dumps(body_tokens, ensure_ascii=False, separators=(',', ':')).encode()
    return {'path': path, 'symbol': scope, 'kind': kind, 'signature': signature,
            'line': line, 'visibility': visibility, 'references': None,
            'test': is_test(path, scope), 'fingerprint': digest(encoded),
            'tokens': len(body_tokens)}


def leaf_tokens(node):
    if 'comment' in node.type:
        return []
    if not node.children:
        return [(node.type, node.text.decode())]
    return [t for child in node.children for t in leaf_tokens(child)]


def tree_definitions(path, data):
    root = PARSERS[Path(path).suffix].parse(data).root_node
    if root.has_error:
        raise ValueError('syntax parser reported ERROR or missing nodes')
    result = []
    rust = path.endswith('.rs')

    def visit(node, scope):
        name_node = node.child_by_field_name('name')
        name = name_node.text.decode() if name_node else None
        body = node.child_by_field_name('body')
        kind = None
        signature = None
        if rust and node.type in {'function_item', 'closure_expression'}:
            kind = node.type
            name = name or f'<closure@{node.start_point.row + 1}:{node.start_point.column}>'
            signature = data[node.start_byte:body.start_byte].decode().strip() if body else ''
        elif not rust and node.type in {'function_signature', 'getter_signature',
                                       'setter_signature', 'constructor_signature',
                                       'factory_constructor_signature', 'operator_signature'}:
            if node.type == 'constructor_signature':
                name = '.'.join(c.text.decode() for c in node.children_by_field_name('name'))
            elif node.type == 'factory_constructor_signature':
                name = '.'.join(c.text.decode() for c in node.named_children if c.type == 'identifier')
            elif node.type == 'operator_signature':
                name = 'operator ' + next((c.text.decode() for c in node.named_children
                                          if 'operator' in c.type), '?')
            elif node.type == 'setter_signature':
                name = 'set ' + name
            container = node.parent if node.parent.type in {'method_signature', 'declaration'} else node
            candidate = container.next_named_sibling
            if candidate and candidate.type == 'function_body':
                body = candidate
            elif node.parent.type == 'lambda_expression':
                body = node.parent.child_by_field_name('body')
            if body:
                kind = node.type
                signature = node.text.decode()
        elif not rust and node.type == 'function_expression':
            kind = node.type
            name = f'<closure@{node.start_point.row + 1}:{node.start_point.column}>'
            signature = data[node.start_byte:body.start_byte].decode().strip() if body else ''
        qualified = '::'.join([*scope, name]) if name else '::'.join(scope)
        if kind and body:
            visibility = None
            if rust and kind == 'function_item':
                visibility = next((c.text.decode() for c in node.children
                                   if c.type == 'visibility_modifier'), 'private')
            elif not rust and name and not name.startswith('<'):
                visibility = 'private' if name.startswith('_') else 'public'
            result.append(record(path, qualified, kind, ' '.join(signature.split()),
                                 node.start_point.row + 1, leaf_tokens(body), visibility))
        next_scope = scope
        if node.type in {'class_definition', 'enum_declaration', 'trait_item', 'mod_item', 'impl_item',
                         'extension_declaration', 'mixin_declaration'}:
            type_node = node.child_by_field_name('type')
            label = name or (type_node.text.decode() if type_node else node.type)
            if rust and node.type == 'impl_item' and node.child_by_field_name('trait'):
                label = ' '.join(data[node.start_byte:body.start_byte].decode().split())
            next_scope = [*scope, label]
        elif kind and name:
            next_scope = [*scope, name]
        # Dart bodies are siblings of signatures, so assign their callable scope here.
        for child in node.named_children:
            child_scope = next_scope
            if not rust and child.type == 'function_body':
                previous = child.prev_named_sibling
                if previous:
                    signature_node = previous
                    if previous.type in {'method_signature', 'declaration'} and previous.named_children:
                        signature_node = previous.named_children[0]
                    owner = signature_node.child_by_field_name('name')
                    if owner:
                        child_scope = [*scope, owner.text.decode()]
            visit(child, child_scope)
    visit(root, [])
    return result


def python_definitions(path, data):
    tree = ast.parse(data)
    lines = data.decode().splitlines()
    result = []

    def visit(node, scope):
        next_scope = scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            name = getattr(node, 'name', f'<lambda@{node.lineno}:{node.col_offset}>')
            qualified = '::'.join([*scope, name])
            body = node.body if isinstance(node.body, list) else [node.body]
            normalized = [ast.dump(n, include_attributes=False) for n in body]
            signature = ('async ' if isinstance(node, ast.AsyncFunctionDef) else '') + '(' + ast.unparse(node.args) + ')'
            if getattr(node, 'returns', None):
                signature += ' -> ' + ast.unparse(node.returns)
            decorators = getattr(node, 'decorator_list', [])
            if decorators:
                signature = ' '.join('@' + ast.unparse(d) for d in decorators) + ' ' + signature
            r = record(path, qualified, type(node).__name__, signature, node.lineno, normalized)
            # Size is a review threshold only; identity uses the structural body above.
            text = '\n'.join(lines[node.lineno - 1:node.end_lineno])
            r['tokens'] = len(list(tokenize.generate_tokens(io.StringIO(text).readline)))
            result.append(r)
            next_scope = [*scope, name]
        elif isinstance(node, ast.ClassDef):
            next_scope = [*scope, node.name]
        for child in ast.iter_child_nodes(node):
            visit(child, next_scope)
    visit(tree, [])
    return result


def scan(revision=None):
    report = {'schema': 1, 'files': {}, 'definitions': [], 'coverage_gaps': [], 'errors': [],
              'tools': {p: importlib.metadata.version(p) for p in
                        ('tree-sitter', 'tree-sitter-rust', 'tree-sitter-dart')}}
    for path, data in source_files(revision):
        report['files'][path] = {'lines': len(data.splitlines()), 'hash': digest(data)}
        ext = Path(path).suffix
        try:
            if ext in PARSERS:
                definitions = tree_definitions(path, data)
            elif ext == '.py':
                definitions = python_definitions(path, data)
            else:
                report['coverage_gaps'].append(path)
                continue
            report['definitions'].extend(definitions)
        except (ValueError, SyntaxError, UnicodeError, tokenize.TokenError) as exc:
            report['errors'].append({'path': path, 'error': str(exc)})
    # Conditional implementations can still share a qualified spelling. Preserve all
    # occurrences rather than silently overwriting them in a baseline dictionary.
    counts = {}
    for d in report['definitions']:
        key = (d['path'], d['symbol'])
        counts[key] = counts.get(key, 0) + 1
        d['occurrence'] = counts[key]
    report['definitions'].sort(key=lambda d: (d['path'], d['symbol'], d['line']))
    report['limitations'] = ['Syntax definitions only: no macro expansion or reference analysis.',
                             'Dart declarations without bodies are not implementations.',
                             'Anonymous callable identities include location; fingerprint diff detects moves.',
                             'Other languages are measured for size but listed as inventory coverage gaps.']
    return report
