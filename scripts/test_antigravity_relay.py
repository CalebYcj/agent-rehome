"""Exercise Antigravity exit-relay waiting, backup, registration, idempotency, timeout, and failure receipts."""
from contextlib import closing, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid

import antigravity_desktop
import antigravity_relay
import antigravity_stage
import exchange


STAMP = '2026-11-23T07:00:00Z'


def _make_exchange_package(package_dir):
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / 'project').mkdir()
    readme = package_dir / 'project' / 'README.md'
    readme.write_text('# synthetic\n', encoding='utf-8')
    sid = str(uuid.uuid4())
    conv = {
        'schema': 'agent-transcript/v1',
        'source': {'agent': 'workbuddy', 'session_id': sid, 'os': 'Windows'},
        'title': 'Synthetic Relay Test',
        'turns': [{
            'user': {'ts': STAMP, 'text': 'Remember token AGY-RELAY-01', 'attachments': []},
            'items': [{'kind': 'message', 'ts': STAMP, 'text': 'Recorded AGY-RELAY-01'}],
        }],
        'losses': [],
    }
    legacy = {
        'schema': 'agent-exchange/v2',
        'source_agent': 'workbuddy',
        'source_os': 'Windows',
        'created_at': STAMP,
        'source_project': 'synthetic',
        'project': {'name': 'synthetic', 'root_hint': 'synthetic'},
        'files': [],
        'attachments': [],
        'conversations': [conv],
    }
    exchange.write_project(package_dir, legacy)


def _init_antigravity_profile(gemini_root, workspace, project_id):
    profile = gemini_root / 'antigravity'
    profile.mkdir(parents=True)
    config_projects = gemini_root / 'config' / 'projects'
    config_projects.mkdir(parents=True)
    uri = antigravity_stage.workspace_uri(workspace.resolve())
    (config_projects / f'{project_id}.json').write_text(json.dumps({
        'id': project_id,
        'name': workspace.name,
        'projectResources': {'resources': [{'folderUri': uri}]},
        'permissionGrants': {'v2Migrated': True},
        'settings': {},
        'isWorkspaceOnly': False,
    }), encoding='utf-8')
    with closing(sqlite3.connect(profile / 'conversation_summaries.db')) as db, db:
        db.execute('''CREATE TABLE conversation_summaries (
            conversation_id TEXT PRIMARY KEY, title TEXT, preview TEXT, step_count INTEGER,
            last_modified_time TEXT, workspace_uris TEXT, status TEXT, source TEXT,
            project_id TEXT, nesting_depth INTEGER, not_fully_idle INTEGER, killed INTEGER,
            last_user_input_time TEXT, last_user_input_step_index INTEGER,
            app_data_dir TEXT, raw_summary BLOB)''')
    return profile


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class AntigravityRelayTest(unittest.TestCase):
    def _setup_staged(self, root):
        pkg = root / 'pkg'
        ws = root / 'workspace'
        stage_profile = root / 'stage-profile'
        gemini_root = root / 'gemini-home'
        _make_exchange_package(pkg)
        with redirect_stdout(io.StringIO()):
            staged = antigravity_stage.stage(pkg, ws, stage_profile)
        pid = staged['project_registration']['project']['id']
        profile = _init_antigravity_profile(gemini_root, ws, pid)
        return ws, profile, pid, staged

    def test_relay_waits_for_exit_then_backs_up_and_registers(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, profile, pid, staged = self._setup_staged(Path(tmp))
            polls = iter([['Antigravity.exe', 'language_server.exe'], ['language_server.exe'], []])
            clock = FakeClock()
            extra_receipt = Path(tmp) / 'relay-out.json'
            with patch.object(antigravity_desktop, 'runtime_open', return_value=False):
                result, code = antigravity_relay.run_relay(
                    ws,
                    profile,
                    pid,
                    timeout=30.0,
                    poll_interval=0.5,
                    extra_receipt=extra_receipt,
                    process_probe=lambda: next(polls, []),
                    pid_probe=lambda _pid: False,
                    monotonic=clock.monotonic,
                    sleep=clock.sleep,
                )
            self.assertEqual(code, 0)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['waited_seconds'], 1.0)
            self.assertTrue(Path(result['backup']).is_dir())
            self.assertTrue(extra_receipt.is_file())
            desktop_receipt = json.loads((ws / '.rehome/antigravity-desktop.json').read_text(encoding='utf-8'))
            self.assertEqual(desktop_receipt['status'], 'registered-offline')
            relay_receipt = json.loads((ws / '.rehome/antigravity-relay.json').read_text(encoding='utf-8'))
            self.assertEqual(relay_receipt['status'], 'completed')
            with closing(sqlite3.connect(profile / 'conversation_summaries.db')) as db:
                rows = db.execute('SELECT conversation_id FROM conversation_summaries WHERE project_id=?', (pid,)).fetchall()
            self.assertEqual({r[0] for r in rows}, {s['id'] for s in staged['sessions']})

    def test_relay_duplicate_execution_returns_already_registered_and_blocks_live_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, profile, pid, _ = self._setup_staged(Path(tmp))
            clock = FakeClock()
            with patch.object(antigravity_desktop, 'runtime_open', return_value=False):
                first, code1 = antigravity_relay.run_relay(
                    ws, profile, pid, process_probe=lambda: [], pid_probe=lambda _p: False,
                    monotonic=clock.monotonic, sleep=clock.sleep,
                )
                second, code2 = antigravity_relay.run_relay(
                    ws, profile, pid, process_probe=lambda: [], pid_probe=lambda _p: False,
                    monotonic=clock.monotonic, sleep=clock.sleep,
                )
            self.assertEqual((code1, first['status']), (0, 'completed'))
            self.assertEqual((code2, second['status']), (0, 'already-registered'))

            ws2, profile2, pid2, _ = self._setup_staged(Path(tmp) / 'second')
            (ws2 / '.rehome/antigravity-relay.json').write_text(
                json.dumps({'status': 'waiting', 'pid': 999999}), encoding='utf-8'
            )
            with self.assertRaisesRegex(ValueError, 'already waiting'):
                antigravity_relay.run_relay(
                    ws2, profile2, pid2, process_probe=lambda: [], pid_probe=lambda p: p == 999999,
                    monotonic=clock.monotonic, sleep=clock.sleep,
                )

    def test_relay_timeout_writes_timeout_receipt_without_mutating_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, profile, pid, _ = self._setup_staged(Path(tmp))
            clock = FakeClock()
            result, code = antigravity_relay.run_relay(
                ws,
                profile,
                pid,
                timeout=2.0,
                poll_interval=0.5,
                process_probe=lambda: ['language_server.exe'],
                pid_probe=lambda _p: False,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )
            self.assertEqual(code, 1)
            self.assertEqual(result['status'], 'timeout')
            self.assertEqual(result['open_processes'], ['language_server.exe'])
            self.assertFalse((ws / '.rehome/antigravity-desktop.json').exists())
            self.assertFalse((profile / 'rehome-backups' / pid).exists())
            receipt = json.loads((ws / '.rehome/antigravity-relay.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['status'], 'timeout')

    def test_relay_failure_receipt_on_preflight_and_apply_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, profile, pid, _ = self._setup_staged(Path(tmp))
            (profile.parent / 'config' / 'projects' / f'{pid}.json').unlink()
            clock = FakeClock()
            res_pre, code_pre = antigravity_relay.run_relay(
                ws, profile, pid, process_probe=lambda: [], pid_probe=lambda _p: False,
                monotonic=clock.monotonic, sleep=clock.sleep,
            )
            self.assertEqual(code_pre, 1)
            self.assertEqual((res_pre['status'], res_pre['stage']), ('failed', 'preflight'))

            ws2, profile2, pid2, _ = self._setup_staged(Path(tmp) / 'apply-fail')
            with patch.object(antigravity_desktop, 'runtime_open', return_value=True):
                res_app, code_app = antigravity_relay.run_relay(
                    ws2, profile2, pid2, process_probe=lambda: [], pid_probe=lambda _p: False,
                    monotonic=clock.monotonic, sleep=clock.sleep,
                )
            self.assertEqual(code_app, 1)
            self.assertEqual((res_app['status'], res_app['stage']), ('failed', 'apply'))
            receipt = json.loads((ws2 / '.rehome/antigravity-relay.json').read_text(encoding='utf-8'))
            self.assertEqual((receipt['status'], receipt['stage']), ('failed', 'apply'))

    def test_launch_does_not_overwrite_completed_child_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, profile, pid, _ = self._setup_staged(Path(tmp))
            clock = FakeClock()

            class FakeProc:
                pid = 424242

            def fast_child_popen(cmd, **_kwargs):
                token = cmd[cmd.index('--launch-token') + 1]
                with patch.object(antigravity_desktop, 'runtime_open', return_value=False):
                    child_res, child_code = antigravity_relay.run_relay(
                        ws, profile, pid, launch_token=token, process_probe=lambda: [], pid_probe=lambda _p: False,
                        monotonic=clock.monotonic, sleep=clock.sleep,
                    )
                self.assertEqual((child_code, child_res['status']), (0, 'completed'))
                return FakeProc()

            launched, launch_code = antigravity_relay.launch_detached(
                ws, profile, pid, pid_probe=lambda _p: False, popen=fast_child_popen,
            )
            self.assertEqual((launch_code, launched['status'], launched['pid']), (0, 'launched', 424242))
            receipt = json.loads((ws / '.rehome/antigravity-relay.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['status'], 'completed')

    def test_launch_never_overwrites_receipt_after_popen_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, profile, pid, _ = self._setup_staged(Path(tmp))
            clock = FakeClock()
            writes = []
            orig_write = antigravity_relay._write_receipt

            class FakeProc:
                pid = 515151

            def spy_write(workspace, payload, extra_receipt=None):
                writes.append(payload.get('status'))
                return orig_write(workspace, payload, extra_receipt)

            def child_completes_during_popen(cmd, **_kwargs):
                token = cmd[cmd.index('--launch-token') + 1]
                with patch.object(antigravity_desktop, 'runtime_open', return_value=False):
                    res, code = antigravity_relay.run_relay(
                        ws, profile, pid, launch_token=token, process_probe=lambda: [], pid_probe=lambda _p: False,
                        monotonic=clock.monotonic, sleep=clock.sleep,
                    )
                self.assertEqual((code, res['status']), (0, 'completed'))
                return FakeProc()

            with patch.object(antigravity_relay, '_write_receipt', side_effect=spy_write):
                launched, launch_code = antigravity_relay.launch_detached(
                    ws, profile, pid, pid_probe=lambda _p: False, popen=child_completes_during_popen,
                )
            self.assertEqual((launch_code, launched['status'], launched['pid']), (0, 'launched', 515151))
            self.assertEqual(writes, ['launching', 'waiting', 'completed'])
            receipt = json.loads((ws / '.rehome/antigravity-relay.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['status'], 'completed')

    def test_trusted_child_distinguishes_own_launch_claim_while_parent_alive(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, profile, pid, _ = self._setup_staged(Path(tmp))
            clock = FakeClock()
            parent_pid = 777777

            class FakeProc:
                pid = 888888

            def child_with_parent_alive(cmd, **_kwargs):
                token = cmd[cmd.index('--launch-token') + 1]
                with patch('os.getpid', return_value=888888):
                    # Independent worker without matching token must be rejected while parent PID is alive.
                    with self.assertRaisesRegex(ValueError, 'superseded'):
                        antigravity_relay.run_relay(
                            ws, profile, pid, launch_token='other-token',
                            process_probe=lambda: [], pid_probe=lambda p: p == parent_pid,
                            monotonic=clock.monotonic, sleep=clock.sleep,
                        )
                    with patch.object(antigravity_desktop, 'runtime_open', return_value=False):
                        res, code = antigravity_relay.run_relay(
                            ws, profile, pid, launch_token=token,
                            process_probe=lambda: [], pid_probe=lambda p: p == parent_pid,
                            monotonic=clock.monotonic, sleep=clock.sleep,
                        )
                self.assertEqual((code, res['status']), (0, 'completed'))
                return FakeProc()

            with patch('os.getpid', return_value=parent_pid):
                launched, launch_code = antigravity_relay.launch_detached(
                    ws, profile, pid, pid_probe=lambda p: p == parent_pid, popen=child_with_parent_alive,
                )
            self.assertEqual((launch_code, launched['status'], launched['pid']), (0, 'launched', 888888))
            receipt = json.loads((ws / '.rehome/antigravity-relay.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['status'], 'completed')

    def test_launch_failure_writes_failed_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, profile, pid, _ = self._setup_staged(Path(tmp))

            def broken_popen(*_args, **_kwargs):
                raise OSError('spawn denied')

            res, code = antigravity_relay.launch_detached(
                ws, profile, pid, pid_probe=lambda _p: False, popen=broken_popen,
            )
            self.assertEqual(code, 1)
            self.assertEqual((res['status'], res['stage']), ('failed', 'preflight'))
            self.assertIn('spawn denied', res['error'])
            receipt = json.loads((ws / '.rehome/antigravity-relay.json').read_text(encoding='utf-8'))
            self.assertEqual((receipt['status'], receipt['stage']), ('failed', 'preflight'))

    def test_launch_rejects_mismatched_project_id_without_already_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, profile, pid, _ = self._setup_staged(Path(tmp))
            other_pid = str(uuid.uuid4())
            (ws / '.rehome/antigravity-desktop.json').write_text(
                json.dumps({'status': 'registered-offline', 'project_id': other_pid}),
                encoding='utf-8',
            )
            result, code = antigravity_relay.launch_detached(
                ws, profile, pid, pid_probe=lambda _p: False,
            )
            self.assertEqual(code, 1)
            self.assertEqual((result['status'], result['stage']), ('failed', 'preflight'))
            self.assertIn(other_pid, result['error'])
            receipt = json.loads((ws / '.rehome/antigravity-relay.json').read_text(encoding='utf-8'))
            self.assertEqual((receipt['status'], receipt['stage']), ('failed', 'preflight'))

    def test_parent_exited_claim_token_and_relaunch_invariants(self):
        with tempfile.TemporaryDirectory() as tmp:
            # 1. Parent exited, own token matches -> child claims and completes
            ws1, prof1, pid1, _ = self._setup_staged(Path(tmp) / 'own-match')
            (ws1 / '.rehome/antigravity-relay.json').write_text(
                json.dumps({'status': 'launching', 'pid': 919191, 'launch_token': 'tok-own', 'project_id': pid1}),
                encoding='utf-8',
            )
            with patch.object(antigravity_desktop, 'runtime_open', return_value=False):
                res1, code1 = antigravity_relay.run_relay(
                    ws1, prof1, pid1, launch_token='tok-own', process_probe=lambda: [], pid_probe=lambda _p: False,
                )
            self.assertEqual((code1, res1['status']), (0, 'completed'))

            # 2. Parent exited, stale token -> rejected, new-claim preserved, no registration
            ws2, prof2, pid2, _ = self._setup_staged(Path(tmp) / 'stale-tok')
            (ws2 / '.rehome/antigravity-relay.json').write_text(
                json.dumps({'status': 'launching', 'pid': 929292, 'launch_token': 'new-claim', 'project_id': pid2}),
                encoding='utf-8',
            )
            with self.assertRaisesRegex(ValueError, 'superseded'):
                antigravity_relay.run_relay(
                    ws2, prof2, pid2, launch_token='superseded-old-claim',
                    process_probe=lambda: [], pid_probe=lambda _p: False,
                )
            kept2 = json.loads((ws2 / '.rehome/antigravity-relay.json').read_text(encoding='utf-8'))
            self.assertEqual((kept2['status'], kept2['launch_token']), ('launching', 'new-claim'))
            self.assertFalse((ws2 / '.rehome/antigravity-desktop.json').exists())

            # 3. Relaunch between parent exit and child claim -> rejected, original claim still completes
            ws3, prof3, pid3, _ = self._setup_staged(Path(tmp) / 'relaunch-gap')
            (ws3 / '.rehome/antigravity-relay.json').write_text(
                json.dumps({'status': 'launching', 'pid': 939393, 'launch_token': 'tok-first', 'project_id': pid3}),
                encoding='utf-8',
            )
            with self.assertRaisesRegex(ValueError, 'pending Antigravity relay launch claim'):
                antigravity_relay.launch_detached(ws3, prof3, pid3, pid_probe=lambda _p: False)
            kept3 = json.loads((ws3 / '.rehome/antigravity-relay.json').read_text(encoding='utf-8'))
            self.assertEqual((kept3['status'], kept3['launch_token']), ('launching', 'tok-first'))
            with patch.object(antigravity_desktop, 'runtime_open', return_value=False):
                res3, code3 = antigravity_relay.run_relay(
                    ws3, prof3, pid3, launch_token='tok-first', process_probe=lambda: [], pid_probe=lambda _p: False,
                )
            self.assertEqual((code3, res3['status']), (0, 'completed'))

    def test_orphan_token_without_claim_and_terminal_state_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            # 1. No claim on disk -> orphan token must be rejected without writing receipt or registering
            ws1, prof1, pid1, _ = self._setup_staged(Path(tmp) / 'orphan')
            with self.assertRaisesRegex(ValueError, 'missing'):
                antigravity_relay.run_relay(
                    ws1, prof1, pid1, launch_token='orphan-token',
                    process_probe=lambda: [], pid_probe=lambda _p: False,
                )
            self.assertFalse((ws1 / '.rehome/antigravity-relay.json').exists())
            self.assertFalse((ws1 / '.rehome/antigravity-desktop.json').exists())

            # 2. Terminal state on disk -> token-bearing child must be rejected without overwriting
            ws2, prof2, pid2, _ = self._setup_staged(Path(tmp) / 'terminal')
            (ws2 / '.rehome/antigravity-relay.json').write_text(
                json.dumps({'status': 'completed', 'project_id': pid2}), encoding='utf-8',
            )
            with self.assertRaisesRegex(ValueError, 'already terminal'):
                antigravity_relay.run_relay(
                    ws2, prof2, pid2, launch_token='late-token',
                    process_probe=lambda: [], pid_probe=lambda _p: False,
                )
            kept = json.loads((ws2 / '.rehome/antigravity-relay.json').read_text(encoding='utf-8'))
            self.assertEqual(kept['status'], 'completed')

    def test_invalid_timeout_while_valid_claim_exists_preserves_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, prof, pid, _ = self._setup_staged(Path(tmp))
            claim = {'status': 'launching', 'pid': 949494, 'launch_token': 'valid-tok', 'project_id': pid}
            (ws / '.rehome/antigravity-relay.json').write_text(json.dumps(claim), encoding='utf-8')
            res, code = antigravity_relay.launch_detached(ws, prof, pid, timeout=0, pid_probe=lambda _p: False)
            self.assertEqual((code, res['status'], res['stage']), (1, 'failed', 'preflight'))
            kept = json.loads((ws / '.rehome/antigravity-relay.json').read_text(encoding='utf-8'))
            self.assertEqual((kept['status'], kept['launch_token']), ('launching', 'valid-tok'))

    def test_simultaneous_launch_is_blocked_by_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, profile, pid, _ = self._setup_staged(Path(tmp))
            lock_path = ws / '.rehome/antigravity-relay.lock'
            lock_path.write_text('', encoding='utf-8')
            with antigravity_relay._relay_lock(ws):
                with self.assertRaisesRegex(ValueError, 'already active'):
                    antigravity_relay.launch_detached(ws, profile, pid)
                self.assertFalse((ws / '.rehome/antigravity-relay.json').exists())
            with antigravity_relay._relay_lock(ws):
                self.assertTrue(lock_path.is_file())

    def test_process_probe_failure_and_invalid_timeout_write_failed_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, profile, pid, _ = self._setup_staged(Path(tmp))
            clock = FakeClock()

            def broken_probe():
                raise RuntimeError('tasklist failed')

            res_probe, code_probe = antigravity_relay.run_relay(
                ws, profile, pid, process_probe=broken_probe, pid_probe=lambda _p: False,
                monotonic=clock.monotonic, sleep=clock.sleep,
            )
            self.assertEqual(code_probe, 1)
            self.assertEqual((res_probe['status'], res_probe['stage']), ('failed', 'wait-exit'))
            self.assertIn('tasklist failed', res_probe['error'])

            for bad_timeout in (0, -5, float('nan')):
                res_bad, code_bad = antigravity_relay.launch_detached(
                    ws, profile, pid, timeout=bad_timeout, pid_probe=lambda _p: False,
                )
                self.assertEqual(code_bad, 1)
                self.assertEqual((res_bad['status'], res_bad['stage']), ('failed', 'preflight'))
                receipt = json.loads((ws / '.rehome/antigravity-relay.json').read_text(encoding='utf-8'))
                self.assertEqual((receipt['status'], receipt['stage']), ('failed', 'preflight'))

    def test_extra_receipt_rejects_forbidden_or_non_json_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, profile, pid, _ = self._setup_staged(Path(tmp))
            bad_targets = [
                profile / 'relay.json',
                profile.parent / 'relay.json',
                Path(tmp) / 'not-json.txt',
                Path(tmp),
            ]
            for target in bad_targets:
                with self.assertRaises(ValueError):
                    antigravity_relay.run_relay(
                        ws, profile, pid, extra_receipt=target, process_probe=lambda: [], pid_probe=lambda _p: False,
                    )
                if target.is_file():
                    self.fail(f'Forbidden extra receipt path was written: {target}')


if __name__ == '__main__':
    unittest.main(argv=[__file__])
