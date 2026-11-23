"""Wait for Windows Antigravity Desktop and its language server to exit, then apply offline registration."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from agent_rehome import dump
import antigravity_desktop
from cli_output import configure, print
from project_rehome import safe


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def active_processes():
    """Return running Antigravity / language_server image names on Windows."""
    if os.name != 'nt':
        return []
    found = []
    for image in ('Antigravity.exe', 'language_server.exe'):
        output = subprocess.check_output(
            ['tasklist', '/NH', '/FI', f'IMAGENAME eq {image}'],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if image.lower().encode('ascii') in output.lower():
            found.append(image)
    return found


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0 or os.name != 'nt':
        return False
    output = subprocess.check_output(
        ['tasklist', '/NH', '/FI', f'PID eq {pid}'],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return str(pid).encode('ascii') in output


def _validate_extra_receipt(extra_receipt, profile):
    if extra_receipt is None:
        return None
    extra = Path(extra_receipt)
    if extra.is_symlink() or (extra.exists() and extra.is_dir()):
        raise ValueError('Extra relay receipt path must be a regular file path, not a directory or symlink')
    resolved = extra.resolve()
    if resolved.suffix.lower() != '.json':
        raise ValueError('Extra relay receipt path must end with .json')
    home = Path.home().resolve()
    forbidden = [home / name for name in ('.gemini', '.codex', '.claude', 'claude-data')]
    if profile is not None:
        prof = Path(profile).resolve()
        forbidden.extend([prof, prof.parent])
    if any(resolved.is_relative_to(root.resolve()) for root in forbidden if root):
        raise ValueError('Extra relay receipt path cannot point inside Antigravity or agent data directories')
    return resolved


def _validate_timing(timeout, poll_interval):
    try:
        t = float(timeout)
        p = float(poll_interval)
    except (TypeError, ValueError) as exc:
        raise ValueError('Timeout and poll interval must be finite positive numbers') from exc
    if not math.isfinite(t) or t <= 0:
        raise ValueError(f'Invalid timeout {timeout!r}: must be a finite number > 0')
    if not math.isfinite(p) or p <= 0:
        raise ValueError(f'Invalid poll interval {poll_interval!r}: must be a finite number > 0')
    return t, p


def _write_receipt(workspace, payload, extra_receipt=None):
    target = safe(workspace, '.rehome/antigravity-relay.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    dump(target, payload)
    if extra_receipt is not None:
        extra_receipt.parent.mkdir(parents=True, exist_ok=True)
        dump(extra_receipt, payload)
    return str(target)


def _read_relay_receipt(workspace):
    relay_path = safe(workspace, '.rehome/antigravity-relay.json')
    if not relay_path.is_file():
        return None
    try:
        return json.loads(relay_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def _existing_registration(workspace):
    reg_path = safe(workspace, '.rehome/antigravity-desktop.json')
    if not reg_path.is_file():
        return None
    return json.loads(reg_path.read_text(encoding='utf-8'))


def _claim_or_reject(workspace, project_id, *, pid_probe=pid_alive, launch_token=None, recover=False):
    """Validate relay claim ownership under lock without overwriting another active/pending claim."""
    prev = _read_relay_receipt(workspace)

    if launch_token is not None:
        # Token-bearing child may ONLY take over a matching in-lock 'launching' claim.
        if not isinstance(prev, dict) or prev.get('status') != 'launching':
            raise ValueError('Relay launch claim is missing, already terminal, or not in launching state')
        if prev.get('launch_token') != launch_token or prev.get('project_id') != project_id:
            raise ValueError('Relay launch claim is missing, expired, or superseded by a newer task')
        return

    if not isinstance(prev, dict):
        return

    status = prev.get('status')
    prev_pid = prev.get('pid')

    if status == 'launching':
        if recover and (not isinstance(prev_pid, int) or prev_pid <= 0 or not pid_probe(prev_pid)):
            return
        raise ValueError('A pending Antigravity relay launch claim already exists for this workspace (use --recover if abandoned)')

    if status == 'waiting':
        if prev_pid and prev_pid != os.getpid() and pid_probe(prev_pid):
            raise ValueError(f'An Antigravity relay worker (PID {prev_pid}) is already waiting for this workspace')
        if recover:
            return
        raise ValueError('An Antigravity relay worker claim is already present (use --recover if abandoned)')


def _can_write_failure_under_lock(workspace, *, owner_token=None, owner_pid=None):
    """Only write a failure receipt to the main relay file if no other task owns or completed it."""
    prev = _read_relay_receipt(workspace)
    if not isinstance(prev, dict):
        return True
    status = prev.get('status')
    if owner_token is not None:
        return prev.get('launch_token') == owner_token
    if owner_pid is not None and status == 'waiting' and prev.get('pid') == owner_pid:
        return True
    if status in ('launching', 'waiting', 'completed', 'already-registered'):
        return False
    return True


@contextmanager
def _relay_lock(workspace):
    lock_path = safe(workspace, '.rehome/antigravity-relay.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the same file across runs. The OS releases its lock on process exit,
    # so nobody needs to unlink a file another process might just have locked.
    with lock_path.open('a+b') as stream:
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError('Another Antigravity relay is already active or the workspace lock cannot be acquired') from exc
        yield


def run_relay(
    workspace,
    profile,
    project_id,
    *,
    timeout=120.0,
    poll_interval=0.5,
    extra_receipt=None,
    launch_token=None,
    recover=False,
    process_probe=active_processes,
    pid_probe=pid_alive,
    monotonic=time.monotonic,
    sleep=time.sleep,
):
    workspace, profile = Path(workspace).resolve(), Path(profile).resolve()
    validated_extra = _validate_extra_receipt(extra_receipt, profile)
    if str(uuid.UUID(project_id)) != project_id:
        raise ValueError('Invalid Antigravity project UUID')
    started_at = utc_now()

    def fail_payload(stage, error_msg, waited=0.0, **extra_fields):
        return {
            'status': 'failed',
            'stage': stage,
            'project_id': project_id,
            'workspace': str(workspace),
            'profile': str(profile),
            'started_at': started_at,
            'finished_at': utc_now(),
            'waited_seconds': waited,
            'error': error_msg,
            **extra_fields,
        }

    try:
        timeout, poll_interval = _validate_timing(timeout, poll_interval)
    except ValueError as exc:
        payload = fail_payload('preflight', str(exc))
        with _relay_lock(workspace):
            if launch_token is None and _can_write_failure_under_lock(workspace):
                payload['receipt'] = _write_receipt(workspace, payload, validated_extra)
        return payload, 1

    with _relay_lock(workspace):
        _claim_or_reject(workspace, project_id, pid_probe=pid_probe, launch_token=launch_token, recover=recover)

        existing = _existing_registration(workspace)
        if existing is not None:
            status = existing.get('status')
            if status == 'registered-offline' and existing.get('project_id') == project_id:
                payload = {
                    'status': 'already-registered',
                    'project_id': project_id,
                    'workspace': str(workspace),
                    'profile': str(profile),
                    'started_at': started_at,
                    'finished_at': utc_now(),
                    'waited_seconds': 0.0,
                    'backup': existing.get('backup'),
                    'sessions': existing.get('sessions', []),
                    'desktop_receipt': str(safe(workspace, '.rehome/antigravity-desktop.json')),
                }
                payload['receipt'] = _write_receipt(workspace, payload, validated_extra)
                return payload, 0
            payload = fail_payload(
                'preflight',
                f'Desktop registration mismatch or incomplete state: status={status!r}, project_id={existing.get("project_id")!r}',
            )
            if _can_write_failure_under_lock(workspace, owner_token=launch_token, owner_pid=os.getpid()):
                payload['receipt'] = _write_receipt(workspace, payload, validated_extra)
            return payload, 1

        try:
            preview = antigravity_desktop.register(workspace, profile, project_id, apply=False)
        except Exception as exc:
            payload = fail_payload('preflight', str(exc))
            if _can_write_failure_under_lock(workspace, owner_token=launch_token, owner_pid=os.getpid()):
                payload['receipt'] = _write_receipt(workspace, payload, validated_extra)
            return payload, 1

        waiting_payload = {
            'status': 'waiting',
            'pid': os.getpid(),
            'launch_token': launch_token,
            'project_id': project_id,
            'workspace': str(workspace),
            'profile': str(profile),
            'started_at': started_at,
            'timeout_seconds': timeout,
            'sessions': preview.get('sessions', []),
        }
        _write_receipt(workspace, waiting_payload, validated_extra)

        start_tick = monotonic()
        deadline = start_tick + timeout
        try:
            open_procs = process_probe()
        except Exception as exc:
            payload = fail_payload('wait-exit', f'Process probe failed: {exc}', waited=0.0)
            payload['receipt'] = _write_receipt(workspace, payload, validated_extra)
            return payload, 1

        while open_procs:
            now_tick = monotonic()
            if now_tick >= deadline:
                payload = {
                    'status': 'timeout',
                    'stage': 'wait-exit',
                    'project_id': project_id,
                    'workspace': str(workspace),
                    'profile': str(profile),
                    'started_at': started_at,
                    'finished_at': utc_now(),
                    'waited_seconds': round(now_tick - start_tick, 3),
                    'timeout_seconds': timeout,
                    'open_processes': list(open_procs),
                    'error': f'Timed out after {timeout}s waiting for {", ".join(open_procs)} to exit',
                }
                payload['receipt'] = _write_receipt(workspace, payload, validated_extra)
                return payload, 1
            sleep(min(poll_interval, max(0.01, deadline - now_tick)))
            try:
                open_procs = process_probe()
            except Exception as exc:
                payload = fail_payload('wait-exit', f'Process probe failed: {exc}', waited=round(monotonic() - start_tick, 3))
                payload['receipt'] = _write_receipt(workspace, payload, validated_extra)
                return payload, 1

        waited = round(monotonic() - start_tick, 3)
        try:
            applied = antigravity_desktop.register(workspace, profile, project_id, apply=True)
        except Exception as exc:
            payload = fail_payload('apply', str(exc), waited=waited)
            payload['receipt'] = _write_receipt(workspace, payload, validated_extra)
            return payload, 1

        payload = {
            'status': 'completed',
            'project_id': project_id,
            'workspace': str(workspace),
            'profile': str(profile),
            'started_at': started_at,
            'finished_at': utc_now(),
            'waited_seconds': waited,
            'backup': applied.get('backup'),
            'sessions': applied.get('sessions', []),
            'new_files': applied.get('new_files', []),
            'desktop_receipt': str(safe(workspace, '.rehome/antigravity-desktop.json')),
        }
        payload['receipt'] = _write_receipt(workspace, payload, validated_extra)
        return payload, 0


def launch_detached(
    workspace,
    profile,
    project_id,
    *,
    timeout=120.0,
    poll_interval=0.5,
    extra_receipt=None,
    recover=False,
    pid_probe=pid_alive,
    popen=subprocess.Popen,
):
    workspace, profile = Path(workspace).resolve(), Path(profile).resolve()
    validated_extra = _validate_extra_receipt(extra_receipt, profile)
    if str(uuid.UUID(project_id)) != project_id:
        raise ValueError('Invalid Antigravity project UUID')
    started_at = utc_now()

    def fail_payload(error_msg):
        return {
            'status': 'failed',
            'stage': 'preflight',
            'project_id': project_id,
            'workspace': str(workspace),
            'profile': str(profile),
            'started_at': started_at,
            'finished_at': utc_now(),
            'waited_seconds': 0.0,
            'error': error_msg,
        }

    try:
        timeout, poll_interval = _validate_timing(timeout, poll_interval)
    except ValueError as exc:
        payload = fail_payload(str(exc))
        with _relay_lock(workspace):
            if _can_write_failure_under_lock(workspace):
                payload['receipt'] = _write_receipt(workspace, payload, validated_extra)
        return payload, 1

    with _relay_lock(workspace):
        _claim_or_reject(workspace, project_id, pid_probe=pid_probe, launch_token=None, recover=recover)

        existing = _existing_registration(workspace)
        if existing is not None:
            status = existing.get('status')
            if status == 'registered-offline' and existing.get('project_id') == project_id:
                payload = {
                    'status': 'already-registered',
                    'project_id': project_id,
                    'workspace': str(workspace),
                    'profile': str(profile),
                    'started_at': started_at,
                    'finished_at': utc_now(),
                    'waited_seconds': 0.0,
                    'backup': existing.get('backup'),
                    'sessions': existing.get('sessions', []),
                    'desktop_receipt': str(safe(workspace, '.rehome/antigravity-desktop.json')),
                }
                payload['receipt'] = _write_receipt(workspace, payload, validated_extra)
                return payload, 0
            payload = fail_payload(
                f'Desktop registration mismatch or incomplete state: status={status!r}, project_id={existing.get("project_id")!r}',
            )
            if _can_write_failure_under_lock(workspace):
                payload['receipt'] = _write_receipt(workspace, payload, validated_extra)
            return payload, 1

        try:
            antigravity_desktop.register(workspace, profile, project_id, apply=False)
        except Exception as exc:
            payload = fail_payload(str(exc))
            if _can_write_failure_under_lock(workspace):
                payload['receipt'] = _write_receipt(workspace, payload, validated_extra)
            return payload, 1

        launch_token = str(uuid.uuid4())
        launching = {
            'status': 'launching',
            'pid': os.getpid(),
            'launch_token': launch_token,
            'project_id': project_id,
            'workspace': str(workspace),
            'profile': str(profile),
            'started_at': started_at,
            'timeout_seconds': timeout,
        }
        receipt = _write_receipt(workspace, launching, validated_extra)

        cmd = [
            sys.executable,
            '-B',
            str(Path(__file__).resolve()),
            '--cwd',
            str(workspace),
            '--profile',
            str(profile),
            '--project-id',
            project_id,
            '--timeout',
            str(timeout),
            '--poll-interval',
            str(poll_interval),
            '--launch-token',
            launch_token,
        ]
        if validated_extra is not None:
            cmd.extend(['--receipt', str(validated_extra)])

    flags = 0
    if os.name == 'nt':
        flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    try:
        proc = popen(
            cmd,
            cwd=str(workspace),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
    except Exception as exc:
        payload = fail_payload(f'Failed to spawn detached relay worker: {exc}')
        with _relay_lock(workspace):
            if _can_write_failure_under_lock(workspace, owner_token=launch_token):
                payload['receipt'] = _write_receipt(workspace, payload, validated_extra)
        return payload, 1

    return {
        'status': 'launched',
        'pid': proc.pid,
        'project_id': project_id,
        'workspace': str(workspace),
        'receipt': receipt,
    }, 0


def main():
    configure()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cwd', type=Path, required=True)
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--profile', type=Path, default=Path.home() / '.gemini/antigravity')
    parser.add_argument('--timeout', type=float, default=120.0)
    parser.add_argument('--poll-interval', type=float, default=0.5)
    parser.add_argument('--receipt', type=Path, default=None)
    parser.add_argument('--launch-token', default=None, help=argparse.SUPPRESS)
    parser.add_argument('--recover', action='store_true', help='Explicitly supersede an abandoned dead-PID claim')
    parser.add_argument('--launch', action='store_true', help='Preflight and spawn a detached relay worker')
    args = parser.parse_args()
    try:
        if args.launch:
            result, code = launch_detached(
                args.cwd,
                args.profile,
                args.project_id,
                timeout=args.timeout,
                poll_interval=args.poll_interval,
                extra_receipt=args.receipt,
                recover=args.recover,
            )
            print(json.dumps(result, ensure_ascii=False))
            return code
        result, code = run_relay(
            args.cwd,
            args.profile,
            args.project_id,
            timeout=args.timeout,
            poll_interval=args.poll_interval,
            extra_receipt=args.receipt,
            launch_token=args.launch_token,
            recover=args.recover,
        )
        print(json.dumps(result, ensure_ascii=False))
        return code
    except (ValueError, KeyError, OSError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
