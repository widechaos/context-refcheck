"""Behavior and boundary checks against synthetic input only."""
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from context_refcheck import core
from context_refcheck.cli import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, path, data):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data if isinstance(data, bytes) else data.encode())
        return file

    def codes(self, report):
        return {f["code"] for f in report["findings"]}

    def manifest(self, checks):
        self.write('.context-refcheck.json', json.dumps({'schema_version': 1, 'checks': checks}))

    def test_three_no_configuration_pairs(self):
        for language in ('python', 'javascript', 'nested'):
            docs = ['nested/HANDOFF.md'] if language == 'nested' else None
            for variant, expected in (('healthy', 0), ('broken', 1)):
                with self.subTest(language=language, variant=variant):
                    report, code = core.check(str(EXAMPLES / language / variant), docs)
                    self.assertEqual(code, expected)
                    self.assertTrue(report['complete'])
                    self.assertEqual(report['execution'], 'never')
                    self.assertEqual(report['summary']['documents'], 1)
                    self.assertEqual(report['summary']['declarations'], 0)
                    self.assertEqual(report['coverage']['evidence'], 'not_configured')
                    self.assertEqual(report['coverage']['semantics'], 'not_checked')
                    if variant == 'healthy':
                        self.assertEqual(report['summary']['warnings'], 0)
                        self.assertEqual(report['summary']['matched'], 2)
                    else:
                        findings = [f for f in report['findings'] if f['severity'] == 'error']
                        self.assertTrue(any(f['code'] == 'ENTRY_MISSING' for f in findings))
                        expected_line = {'python': 8, 'javascript': 5, 'nested': 5}[language]
                        self.assertTrue(any(f['line'] == expected_line and f['code'] == 'ENTRY_MISSING' for f in findings))

    def test_evidence_is_optional_and_detects_bytes_only(self):
        for variant, expected in (('healthy', 0), ('broken', 1)):
            report, code = core.check(str(EXAMPLES / 'evidence' / variant))
            self.assertEqual(code, expected)
            self.assertEqual('EVIDENCE_CHANGED' in self.codes(report), variant == 'broken')

    def test_manual_repair_changes_broken_result(self):
        self.write('CLAUDE.md', '`python3 scripts/old.py`\n')
        self.write('scripts/check.py', 'raise RuntimeError("never execute")\n')
        before, code = core.check(str(self.root))
        self.assertEqual(code, 1)
        self.write('CLAUDE.md', '`python3 scripts/check.py`\n')
        after, code = core.check(str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(after['summary']['matched'], 1)

    def test_default_absence_info_and_all_absent_error(self):
        self.write('CLAUDE.md', '# Nothing to check\n')
        report, code = core.check(str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(report['summary']['info'], 2)
        self.assertEqual(report['summary']['warnings'], 0)
        (self.root / 'CLAUDE.md').unlink()
        report, code = core.check(str(self.root))
        self.assertEqual(code, 2)
        self.assertFalse(report['complete'])

    def test_explicit_missing_document_is_incomplete(self):
        self.write('CLAUDE.md', '# Existing\n')
        report, code = core.check(str(self.root), ['CLAUDE.md', 'notes/no.md'])
        self.assertEqual(code, 2)
        self.assertFalse(report['complete'])

    def test_nested_parent_reference_and_root_escape(self):
        self.write('nested/HANDOFF.md', '[ok](../docs/guide.md)\n[bad](../../outside.txt)\n')
        self.write('docs/guide.md', '# Guide\n')
        report, code = core.check(str(self.root), ['nested/HANDOFF.md'])
        self.assertEqual(code, 1)
        self.assertEqual(report['summary']['matched'], 1)
        self.assertIn('PATH_BLOCKED', self.codes(report))

    def test_blocked_paths_are_not_opened_and_not_echoed(self):
        paths = ['../outside.txt', '/private/file.txt', '~/.ssh/id_rsa', '%2e%2e/file.txt',
                 'C:\\data\\file.txt', '\\\\host\\file.txt', '.env', 'env/file.txt',
                 '.ssh/id_rsa', 'keys/private.pem', 'a/credentials.json', 'a/secret-note.md']
        self.write('CLAUDE.md', '\n'.join(f'[reference]({p})' for p in paths))
        opened = []
        real_open = os.open
        def observed(path, *args, **kwargs):
            opened.append(str(path))
            return real_open(path, *args, **kwargs)
        with patch.object(core.os, 'open', side_effect=observed):
            # Preserve the capability check when wrapping os.open.
            with patch.object(core.os, 'supports_dir_fd', {core.os.open}):
                report, code = core.check(str(self.root))
        self.assertEqual(code, 1)
        # Only root, default documents, and optional manifest may have been opened.
        self.assertTrue(set(opened) <= {str(self.root), 'CLAUDE.md', 'AGENTS.md', 'HANDOFF.md', '.context-refcheck.json'})
        dumped = json.dumps(report)
        for forbidden in ('outside.txt', '/private/', 'id_rsa', 'private.pem', 'secret-note'):
            self.assertNotIn(forbidden, dumped)
        self.assertEqual(len([f for f in report['findings'] if f['code'] == 'PATH_BLOCKED']), len(paths))

    def test_symlinks_internal_external_and_ancestor_are_blocked(self):
        self.write('file.txt', 'synthetic ordinary file')
        os.symlink('file.txt', self.root / 'inside.txt')
        os.symlink('/not-a-real-target-context-refcheck', self.root / 'outside.txt')
        (self.root / 'real').mkdir()
        self.write('real/file.txt', 'ordinary')
        os.symlink('real', self.root / 'alias')
        self.write('CLAUDE.md', '[one](inside.txt)\n[two](outside.txt)\n[three](alias/file.txt)\n')
        report, code = core.check(str(self.root))
        self.assertEqual(code, 1)
        self.assertEqual(sum(f['code'] == 'PATH_BLOCKED' for f in report['findings']), 3)

    def test_root_symlink_with_trailing_slash_is_not_followed(self):
        self.write('real/CLAUDE.md', '# Valid\n')
        os.symlink('real', self.root / 'alias')
        report, code = core.check(str(self.root / 'alias') + '/')
        self.assertEqual(code, 2)
        self.assertIn('INPUT_INVALID', self.codes(report))

    def test_read_errors_do_not_leak_tracebacks(self):
        self.write('CLAUDE.md', '# Valid\n')
        with patch.object(core.os, 'read', side_effect=PermissionError('synthetic sensitive message')):
            report, code = core.check(str(self.root))
        self.assertEqual(code, 2)
        self.assertIn('INPUT_INVALID', self.codes(report))
        self.assertNotIn('sensitive message', json.dumps(report))

    def test_fifo_no_content_read(self):
        os.mkfifo(self.root / 'pipe.txt')
        self.write('CLAUDE.md', '[pipe](pipe.txt)\n')
        with patch.object(core.os, 'read', wraps=os.read) as read:
            report, code = core.check(str(self.root))
        self.assertEqual(code, 1)
        self.assertIn('PATH_BLOCKED', self.codes(report))
        # Only the regular Markdown file was read (data plus EOF).
        self.assertEqual(read.call_count, 2)

    def test_commands_never_execute_or_connect_and_do_not_write(self):
        marker = self.root / 'marker.txt'
        self.write('scripts/check.py', f'open({str(marker)!r}, "w").write("executed")\n')
        self.write('package.json', '{"scripts":{"test":"touch marker.txt; curl https://example.invalid"}}')
        self.write('CLAUDE.md', '`python3 scripts/check.py`\n`npm run test`\n`curl https://example.invalid`\n`python3 scripts/check.py && touch marker.txt`\n`$(touch marker.txt)`\n')
        contents = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('execution forbidden')), \
             patch.object(os, 'system', side_effect=AssertionError('execution forbidden')), \
             patch.object(socket, 'socket', side_effect=AssertionError('network forbidden')):
            report, code = core.check(str(self.root))
        self.assertEqual(code, 1)
        self.assertEqual(report['summary']['matched'], 2)
        self.assertEqual(sum(f['code'] == 'ENTRY_UNSUPPORTED' for f in report['findings']), 3)
        self.assertFalse(marker.exists())
        self.assertEqual(contents, {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_fences_examples_inline_commands_and_unknown_shell(self):
        self.write('scripts/check.py', 'raise Exception("never")')
        self.write('CLAUDE.md', '```sh\n$ python3 scripts/check.py\n```\n\n```bash\npython3 fake/file.py\nprintf output\n```\n\n```python\nopen("fake/data.csv")\n```\n\n```shell\npnpm run test\n```\n\n`python3 fake/file.py --help`\n')
        report, code = core.check(str(self.root))
        self.assertEqual(code, 1)
        self.assertEqual(report['summary']['matched'], 1)
        self.assertEqual(report['summary']['skipped_blocks'], 2)
        self.assertEqual(sum(f['code'] == 'ENTRY_UNSUPPORTED' for f in report['findings']), 2)
        self.assertNotIn('PATH_MISSING', self.codes(report))

    def test_npm_single_fence(self):
        self.write('CLAUDE.md', '```console\n$ npm run test\n```\n')
        self.write('package.json', '{"scripts":{"test":"never run this"}}')
        self.assertEqual(core.check(str(self.root))[1], 0)

    def test_unclosed_and_unsupported_markdown(self):
        self.write('CLAUDE.md', '[label][ref]\n[ref]: docs/file.md\n[complex](some(path).md)\n```sh\npython3 missing.py\n')
        report, code = core.check(str(self.root))
        self.assertEqual(code, 1)
        self.assertIn('REFERENCE_UNSUPPORTED', self.codes(report))
        self.assertNotIn('ENTRY_MISSING', self.codes(report))

    def test_unicode_spaces_and_remote_fragment_skips(self):
        self.write('notes/中文 名称.md', '# Guide')
        self.write('CLAUDE.md', '[guide](<notes/中文 名称.md>)\n[remote](https://example.invalid/a)\n[local](#heading)\n[part](notes/中文.md#missing)\n')
        self.write('notes/中文.md', '# Guide')
        report, code = core.check(str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(report['summary']['matched'], 2)
        self.assertEqual(report['summary']['skipped'], 2)
        self.assertEqual(report['coverage']['fragments'], 'not_checked')

    def test_manifest_quote_binding_and_explicit_package(self):
        quote = 'Use `npm run test`.'
        self.write('CLAUDE.md', quote + '\n')
        self.write('package.json', '{"scripts":{"test":"never"}}')
        self.write('frontend/package.json', '{"scripts":{"test":"never"}}')
        item = dict(id='test', kind='entry', document='CLAUDE.md', quote=quote,
                    command='npm run test', package='frontend/package.json')
        self.manifest([item])
        self.assertEqual(core.check(str(self.root))[1], 0)
        self.write('CLAUDE.md', '# changed\n')
        report, code = core.check(str(self.root))
        self.assertEqual(code, 1)
        self.assertIn('SOURCE_MISSING', self.codes(report))
        self.write('CLAUDE.md', quote + '\n' + quote + '\n')
        report, code = core.check(str(self.root))
        self.assertEqual(code, 1)
        self.assertIn('SOURCE_AMBIGUOUS', self.codes(report))

    def test_malformed_json_and_schema(self):
        self.write('CLAUDE.md', '# Test\n')
        samples = [b'\xff', '{"checks":[],"checks":[],"schema_version":1}',
                   '{"schema_version":true,"checks":[]}', '{"schema_version":1,"checks":[],"root":".."}',
                   '{"schema_version":1,"checks":[{"kind":[]}]}',
                   '{"schema_version":1,"checks":null}', '{"schema_version":NaN,"checks":[]}']
        for data in samples:
            with self.subTest(data=data):
                self.write('.context-refcheck.json', data)
                report, code = core.check(str(self.root))
                self.assertEqual(code, 2)
                self.assertIn('INPUT_INVALID', self.codes(report))

    def test_invalid_declarations(self):
        self.write('CLAUDE.md', 'Evidence: `reports/check.txt`.\n')
        item = dict(id='evidence', kind='evidence', document='CLAUDE.md', quote='Evidence: `reports/check.txt`.',
                    target='reports/check.txt', sha256='0' * 64)
        for update in ({'sha256': 'bad'}, {'target': 'unrelated.txt'}, {'document': 'not-selected.md'},
                       {'id': '\x1bsecret'}, {'unknown': 'value'}):
            with self.subTest(update=update):
                self.manifest([dict(item, **update)])
                self.assertEqual(core.check(str(self.root))[1], 2)
        self.manifest([item, item])
        self.assertEqual(core.check(str(self.root))[1], 2)

    def test_sensitive_evidence_is_not_read(self):
        self.write('CLAUDE.md', 'Evidence: `.env`.\n')
        self.write('.env', 'INVALID_SYNTHETIC_MARKER')
        self.manifest([dict(id='evidence', kind='evidence', document='CLAUDE.md', quote='Evidence: `.env`.',
                            target='.env', sha256='0'*64)])
        original = os.read
        touched = []
        def observed(fd, size):
            data = original(fd, size)
            touched.append(data)
            return data
        with patch.object(core.os, 'read', side_effect=observed):
            report, code = core.check(str(self.root))
        self.assertEqual(code, 1)
        self.assertIn('PATH_BLOCKED', self.codes(report))
        self.assertNotIn(b'INVALID_SYNTHETIC_MARKER', b''.join(touched))

    def test_byte_document_reference_and_declaration_limits(self):
        self.write('CLAUDE.md', 'x' * (core.MAX_FILE + 1))
        self.assertEqual(core.check(str(self.root))[1], 2)
        self.write('CLAUDE.md', '# Valid\n')
        report, code = core.check(str(self.root), ['CLAUDE.md'] * 33)
        self.assertEqual(code, 2)
        self.assertIn('LIMIT_EXCEEDED', self.codes(report))
        self.manifest([{}] * 257)
        self.assertEqual(core.check(str(self.root))[1], 2)
        (self.root/'.context-refcheck.json').unlink()
        self.write('CLAUDE.md', '[url](https://example.invalid)\n' * 4097)
        self.assertEqual(core.check(str(self.root))[1], 2)
        self.write('CLAUDE.md', '# Text')
        with patch.object(core, 'MAX_TOTAL', 2):
            self.assertEqual(core.check(str(self.root))[1], 2)

    def test_read_change_detection(self):
        self.write('CLAUDE.md', '# Before\n')
        original = os.read
        changed = False
        def mutate(fd, size):
            nonlocal changed
            data = original(fd, size)
            if not changed:
                changed = True
                self.write('CLAUDE.md', '# After and longer\n')
            return data
        with patch.object(core.os, 'read', side_effect=mutate):
            report, code = core.check(str(self.root))
        self.assertEqual(code, 2)
        self.assertIn('INPUT_CHANGED', self.codes(report))
        self.assertEqual(report['summary']['matched'], 0)

    def test_invalid_utf8_document(self):
        self.write('CLAUDE.md', b'\xff')
        self.assertEqual(core.check(str(self.root))[1], 2)

    def test_platform_no_safe_fallback(self):
        with patch.object(core.os, 'supports_dir_fd', set()):
            report, code = core.check(str(self.root))
        self.assertEqual(code, 2)
        self.assertIn('PLATFORM_UNSUPPORTED', self.codes(report))

    def test_text_and_json_do_not_echo_body_or_terminal_escape(self):
        self.write('CLAUDE.md', 'INVALID_SYNTHETIC_MARKER\n[ref](docs/\x1b[31mfile.md)\n')
        for fmt in ('text', 'json'):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(['check', '--root', str(self.root), '--format', fmt])
            text = output.getvalue()
            self.assertEqual(code, 1)
            self.assertNotIn('\x1b', text)
            self.assertNotIn('INVALID_SYNTHETIC_MARKER', text)
            self.assertNotIn(str(self.root), text)
            if fmt == 'json':
                self.assertEqual(json.loads(text)['execution'], 'never')

    def test_stable_report(self):
        self.write('CLAUDE.md', '`npm run old`\n[missing](docs/old.md)\n')
        self.write('package.json', '{"scripts":{}}')
        self.assertEqual(core.check(str(self.root)), core.check(str(self.root)))


if __name__ == '__main__':
    unittest.main()
