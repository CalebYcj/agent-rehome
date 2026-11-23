"""Register a staged project in a closed Windows Antigravity Desktop 2.33.1 profile."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid

from agent_rehome import dump, validate
from antigravity_source import varint, wire_fields
from antigravity_stage import field, timestamp, workspace_uri, write_session
from cli_output import configure, print
from platform_paths import sqlite_read_uri
from project_io import check_space, chunks, json_bytes, measure, write_checked
from project_rehome import safe


def runtime_open():
    if os.name == 'nt':
        output = subprocess.check_output(['tasklist', '/NH', '/FI', 'IMAGENAME eq language_server.exe'],
                                         creationflags=subprocess.CREATE_NO_WINDOW)
        return b'language_server.exe' in output.lower()
    names = ('language_server', 'Antigravity') if sys.platform == 'darwin' else ('language_server', 'antigravity')
    return any(
        subprocess.run(['pgrep', '-x', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        for name in names
    )


def atomic_write(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        pending = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


def summary_ids(data):
    offset, ids = 0, set()
    while offset < len(data):
        tag, offset = varint(data, offset)
        if tag != 10:
            raise ValueError('Unrecognized Antigravity summary cache format')
        length, offset = varint(data, offset)
        if offset + length > len(data):
            raise ValueError('Truncated Antigravity summary cache')
        key = next(wire_fields(data[offset:offset + length], 1), b'').decode('ascii')
        if str(uuid.UUID(key)) != key or key in ids:
            raise ValueError('Invalid or duplicate Antigravity summary key')
        ids.add(key)
        offset += length
    return ids


def sqlite_time(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(timezone.utc).isoformat(' ')


def stage_backup_files(backup, workspace, profile, project_id, uri, sessions):
    staging = backup / 'new'
    rows, entries = [], bytearray()
    for sid, bundle in sessions:
        title = bundle['title']
        database = staging / 'conversations' / (sid + '.db')
        database.parent.mkdir(parents=True, exist_ok=True)
        native = write_session(database, bundle, workspace, staging, sid, project_id, uri, native_profile=profile)
        with closing(sqlite3.connect(sqlite_read_uri(database), uri=True)) as db:
            tid, = db.execute('SELECT trajectory_id FROM trajectory_meta').fetchone()
            meta, = db.execute("SELECT data FROM trajectory_metadata_blob WHERE id='main'").fetchone()
            last_user_index, = db.execute('SELECT max(idx) FROM steps WHERE step_type=14').fetchone()
        first, last_user = (bundle['turns'][k]['user']['ts'] for k in (0, -1))
        last_turn = bundle['turns'][-1]
        replies = [item for item in last_turn['items'] if item['kind'] == 'message']
        last = (replies or [last_turn['user']])[-1]['ts']
        summary = (field(1, title) + field(2, native['steps']) + field(3, timestamp(last)) + field(4, tid)
                   + field(5, 1) + field(7, timestamp(first)) + field(9, field(1, uri))
                   + field(10, timestamp(last_user)) + field(15, field(1, title)) + field(16, last_user_index)
                   + field(17, meta) + field(22, 4))
        entries.extend(field(1, field(1, sid) + field(2, summary)))
        rows.append((sid, title, bundle['turns'][0]['user']['text'], native['steps'], sqlite_time(last),
                     json.dumps([uri]), project_id, sqlite_time(last_user), last_user_index, summary))
        annotation = staging / 'annotations' / (sid + '.pbtxt')
        annotation.parent.mkdir(parents=True, exist_ok=True)
        annotation.write_text('title: ' + json.dumps(title, ensure_ascii=False) + '\n', encoding='utf-8')
    return staging, rows, entries


def register(workspace, profile, project_id, *, apply=False):
    workspace, profile = workspace.resolve(), profile.resolve()
    if str(uuid.UUID(project_id)) != project_id or profile.name != 'antigravity':
        raise ValueError('Choose an Antigravity Desktop data directory and native project UUID')
    if workspace.is_relative_to(profile.parent) or profile.is_relative_to(workspace):
        raise ValueError('Keep the restored workspace outside Antigravity data')
    receipt = json.loads(safe(workspace, '.rehome/restore-antigravity.json').read_text(encoding='utf-8'))
    if receipt.get('status') != 'isolated-native-stage' or Path(receipt['workspace']).resolve() != workspace:
        raise ValueError('Expected an Antigravity staging receipt for this workspace')
    registration = safe(workspace, '.rehome/antigravity-desktop.json')
    if registration.exists():
        raise ValueError('A desktop registration was already attempted for this workspace; inspect its receipt')

    uri = workspace_uri(workspace)
    project_path = safe(profile.parent, f'config/projects/{project_id}.json')
    project_before = project_path.read_bytes()
    project = json.loads(project_before)
    if project['id'] != project_id or project['projectResources']['resources'] != [{'folderUri': uri}]:
        raise ValueError('Native project does not match the exact staged workspace URI')
    if project.get('projectConversations', {}).get('conversations'):
        raise ValueError('Choose a new empty native project')

    sessions = []
    legacy_bundles = None
    for entry in receipt['sessions']:
        sid = entry['id']
        if str(uuid.UUID(sid)) != sid or any(safe(profile, rel).exists() for rel in
                 (f'conversations/{sid}.db', f'annotations/{sid}.pbtxt', f'brain/{sid}')):
            raise ValueError('A staged Antigravity ID is invalid or already exists')
        source_id = entry.get('source_id')
        if source_id is None:
            if legacy_bundles is None:
                exchange_root = safe(workspace, '.rehome/exchange')
                legacy_bundles = [json.loads(safe(workspace, f'.rehome/exchange/{path.name}').read_text(encoding='utf-8'))
                                  for path in exchange_root.glob('*.json')]
            matches = [b['source']['session_id'] for b in legacy_bundles if b['title'] == entry['title']]
            if len(matches) != 1:
                raise ValueError('Ambiguous chat in an older Antigravity staging receipt; stage a fresh workspace')
            source_id = matches[0]
        if str(uuid.UUID(source_id)) != source_id:
            raise ValueError('Invalid Antigravity source chat ID')
        bundle = json.loads(safe(workspace, f'.rehome/exchange/{source_id}.json').read_text(encoding='utf-8'))
        validate(bundle)
        if bundle['source']['session_id'] != source_id or bundle['title'] != entry['title'] or not bundle['turns']:
            raise ValueError('Antigravity staging receipt differs from the portable history')
        sessions.append((sid, bundle))
    ids = {sid for sid, _ in sessions}
    if not ids or len(ids) != len(sessions):
        raise ValueError('Expected a nonempty batch of unique Antigravity chats')

    index = safe(profile, 'conversation_summaries.db')
    cache = safe(profile, 'agyhub_summaries_proto.pb')
    cache_existed = cache.is_file()
    cache_before = cache.read_bytes() if cache_existed else b''
    if ids & summary_ids(cache_before):
        raise ValueError('A staged Antigravity ID is already in the native cache')
    with closing(sqlite3.connect(sqlite_read_uri(index), uri=True)) as db:
        columns = {x[1] for x in db.execute('PRAGMA table_info(conversation_summaries)')}
        expected_columns = {'conversation_id','title','preview','step_count','last_modified_time','workspace_uris',
                            'status','source','project_id','nesting_depth','not_fully_idle','killed',
                            'last_user_input_time','last_user_input_step_index','app_data_dir','raw_summary'}
        if not expected_columns <= columns:
            raise ValueError('Unrecognized Antigravity conversation index layout')
        registered = {row[0] for row in db.execute('SELECT conversation_id FROM conversation_summaries')}
        if ids & registered or db.execute('SELECT 1 FROM conversation_summaries WHERE project_id=? LIMIT 1', (project_id,)).fetchone():
            raise ValueError('Native project or session IDs already have indexed histories')
    result = {'status': 'ready', 'project_id': project_id, 'workspace': str(workspace),
              'sessions': [sid for sid, _ in sessions], 'desktop_visible': False, 'continuation_verified': False}
    if not apply:
        return result
    if runtime_open():
        raise ValueError('Close the Antigravity Desktop window before registering the staged chats')

    profile_bytes = sum(safe(workspace, item['workspace_path']).stat().st_size for _, bundle in sessions
                        for turn in bundle['turns'] for item in turn['user'].get('attachments', []))
    histories = sum(3 * json_bytes(bundle) + 65536 for _, bundle in sessions)
    check_space([(profile, 2 * (profile_bytes + histories + len(cache_before)) + index.stat().st_size)])
    backup = safe(profile, f'rehome-backups/{project_id}')
    backup.mkdir(parents=True)
    (backup / 'project.json').write_bytes(project_before)
    if cache_existed:
        (backup / cache.name).write_bytes(cache_before)
    with closing(sqlite3.connect(sqlite_read_uri(index), uri=True)) as original, closing(sqlite3.connect(backup / index.name)) as copy:
        original.backup(copy)
    result.update(status='pending', backup=str(backup), cache_before_sha256=hashlib.sha256(cache_before).hexdigest())
    dump(registration, result)

    staging, rows, additions = stage_backup_files(backup, workspace, profile, project_id, uri, sessions)
    plan = [(path, safe(profile, path.relative_to(staging).as_posix()))
            for path in staging.rglob('*') if path.is_file()]
    result['new_files'] = [str(target) for _, target in plan]
    dump(registration, result)
    project['projectConversations'] = {'conversations': [{'conversationId': sid} for sid, _ in sessions]}
    project_after = json.dumps(project, ensure_ascii=False, indent=2).encode() + b'\n'
    cache_after = cache_before + additions
    try:
        with closing(sqlite3.connect(index, timeout=5)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            cache_changed = cache.exists() != cache_existed or (cache_existed and cache.read_bytes() != cache_before)
            if runtime_open() or cache_changed or project_path.read_bytes() != project_before:
                raise ValueError('Antigravity started or its registry changed during preparation')
            if db.execute('SELECT 1 FROM conversation_summaries WHERE project_id=? LIMIT 1', (project_id,)).fetchone():
                raise ValueError('The target Antigravity project gained a conversation during preparation')
            for source, dest in plan:
                dest.parent.mkdir(parents=True, exist_ok=True)
                write_checked(dest, chunks(source), measure(chunks(source)))
            db.executemany('''INSERT INTO conversation_summaries
                (conversation_id,title,preview,step_count,last_modified_time,workspace_uris,status,source,project_id,
                nesting_depth,not_fully_idle,killed,last_user_input_time,last_user_input_step_index,app_data_dir,raw_summary)
                VALUES (?,?,?,?,?,?,'CASCADE_RUN_STATUS_IDLE','',?,0,0,0,?,?,'antigravity',?)''', rows)
            if runtime_open():
                raise ValueError('Antigravity started during registration')
            atomic_write(cache, cache_after)
            atomic_write(project_path, project_after)
    except Exception:
        if not runtime_open():
            for path, before, after in ((cache, cache_before, cache_after), (project_path, project_before, project_after)):
                if path.is_file() and path.read_bytes() == after:
                    if path == cache and not cache_existed:
                        path.unlink()
                    else:
                        atomic_write(path, before)
        raise
    result['status'] = 'registered-offline'
    dump(registration, result)
    return result


def main():
    configure()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cwd', type=Path, required=True)
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.exit(1, 'Desktop registration has only been verified on Windows\n')
    try:
        print(json.dumps(register(args.cwd, Path.home() / '.gemini/antigravity', args.project_id,
                                  apply=args.apply), ensure_ascii=False))
    except (ValueError, KeyError, OSError, sqlite3.Error) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
