"""Stage portable chats for an isolated Antigravity Desktop 2.33.1 runtime test."""
import argparse
from contextlib import closing
import datetime as dt
import json
import mimetypes
from pathlib import Path
import re
import sqlite3
import uuid

from agent_rehome import dump
from cli_output import configure, print
from platform_paths import portable_name
from project_io import check_space, chunks, json_bytes, measure, write_checked
from project_rehome import load_manifest, safe
from workbuddy_receive import prepare


SCHEMA = '''
CREATE TABLE trajectory_meta (
    trajectory_id TEXT PRIMARY KEY, cascade_id TEXT, trajectory_type INTEGER, source INTEGER);
CREATE TABLE steps (
    idx INTEGER PRIMARY KEY, step_type INTEGER NOT NULL DEFAULT 0, status INTEGER NOT NULL DEFAULT 0,
    has_subtrajectory NUMERIC NOT NULL DEFAULT false, metadata BLOB, error_details BLOB,
    permissions BLOB, task_details BLOB, render_info BLOB, step_payload BLOB,
    step_format INTEGER NOT NULL DEFAULT 0);
CREATE TABLE gen_metadata (idx INTEGER PRIMARY KEY, data BLOB, size INTEGER NOT NULL DEFAULT 0);
CREATE TABLE executor_metadata (idx INTEGER PRIMARY KEY, data BLOB);
CREATE TABLE parent_references (idx INTEGER PRIMARY KEY, data BLOB);
CREATE TABLE trajectory_metadata_blob (id TEXT DEFAULT 'main' PRIMARY KEY, data BLOB);
CREATE TABLE battle_mode_infos (idx INTEGER PRIMARY KEY, data BLOB);
PRAGMA user_version = 1;
'''


def varint(value):
    number = value & ((1 << 64) - 1)
    encoded = bytearray()
    while number > 127:
        encoded.append(128 | (number & 127))
        number >>= 7
    encoded.append(number)
    return bytes(encoded)


def field(tag, value):
    if isinstance(value, int):
        return varint(tag << 3) + varint(value)
    if isinstance(value, str):
        value = value.encode('utf-8')
    return varint(tag << 3 | 2) + varint(len(value)) + value


def timestamp(value):
    aware = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if aware.tzinfo is None:
        raise ValueError('Antigravity staging requires timestamps with time zones')
    delta = aware - dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    return field(1, delta.days * 86400 + delta.seconds) + field(2, delta.microseconds * 1000)


def workspace_uri(path):
    uri = path.as_uri()
    if path.drive and not path.drive.startswith('\\'):
        uri = uri.replace(path.drive, path.drive.lower().replace(':', '%3A'), 1)
    return uri


def media(cwd, profile, sid, attachment, native_profile):
    source = safe(cwd, attachment['workspace_path'])
    name = portable_name(attachment.get('name') or source.name)
    mime = attachment.get('mime') or mimetypes.guess_type(name)[0] or 'application/octet-stream'
    suffix = Path(name).suffix.lower()
    if not re.fullmatch(r'\.[a-z0-9]{1,16}', suffix):
        suffix = '.bin'
    sha, size = attachment['sha256'], attachment['bytes']
    relative = f'brain/{sid}/.user_uploaded/media_{sha}{suffix}'
    target = safe(profile, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        write_checked(target, chunks(source), (sha, size))
    elif measure(chunks(target)) != (sha, size):
        raise ValueError('Conflicting Antigravity staged attachment')
    native_target = safe(native_profile, relative)
    return field(9, field(1, mime) + field(4, name) + field(5, native_target.as_posix()) + field(9, name))


def write_session(path, bundle, cwd, profile, sid, pid, uri, *, native_profile=None):
    native_profile = native_profile or profile
    tid = str(uuid.uuid4())
    start = timestamp(bundle['turns'][0]['user']['ts'])
    workspace = field(1, uri)
    trajectory = field(1, workspace) + field(2, start) + field(6, sid) + field(7, uri) + field(18, pid)
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(SCHEMA)
        db.execute('INSERT INTO trajectory_meta VALUES (?,?,4,1)', (tid, sid))
        db.execute('INSERT INTO trajectory_metadata_blob VALUES (?,?)', ('main', trajectory))
        count = 0

        def write_step(kind, origin, created_at, body):
            nonlocal count
            meta = field(1, timestamp(created_at)) + field(3, origin) + field(12, sid)
            payload = field(1, kind) + field(4, 3) + field(5, meta) + body
            db.execute('INSERT INTO steps (idx,step_type,status,metadata,step_payload) VALUES (?,?,3,?,?)',
                       (count, kind, meta, payload))
            count += 1

        omitted = 0
        for turn in bundle['turns']:
            user = turn['user']
            text = user['text']
            uploads = b''.join(media(cwd, profile, sid, item, native_profile) for item in user.get('attachments', []))
            write_step(14, 4, user['ts'], field(19, field(2, text) + field(3, field(1, text)) + uploads))
            for item in turn['items']:
                if item['kind'] != 'message':
                    omitted += 1
                    continue
                text = item['text']
                write_step(15, 2, item['ts'], field(20, field(1, text) + field(8, text)))
    return {'id': sid, 'source_id': bundle['source']['session_id'], 'title': bundle['title'], 'file': str(path), 'steps': count,
            'items_retained_only_in_exchange': omitted}


def stage(package, cwd, profile):
    package, cwd, profile = package.resolve(), cwd.resolve(), profile.resolve()
    if any(a.is_relative_to(b) for a, b in ((cwd, profile), (profile, cwd), (profile, package), (package, profile))):
        raise ValueError('Choose separate workspace, package, and Antigravity staging directories')
    gemini_home = (Path.home() / '.gemini').resolve()
    if profile.exists() or any(path.is_relative_to(gemini_home) for path in (cwd, profile)):
        raise ValueError('Choose a new staging profile and workspace outside the real Antigravity data directory')
    manifest = load_manifest(package)
    if not manifest['conversations'] or any(not b['turns'] for b in manifest['conversations']):
        raise ValueError('Antigravity staging requires at least one visible turn per conversation')
    for bundle in manifest['conversations']:
        for turn in bundle['turns']:
            timestamp(turn['user']['ts'])
            for item in turn['items']:
                if item['kind'] == 'message':
                    timestamp(item['ts'])
    history_bytes = json_bytes(manifest['conversations'])
    project_bytes = sum(item['bytes'] for item in manifest['files'] + manifest['attachments'])
    upload_bytes = sum(item['bytes'] for bundle in manifest['conversations'] for turn in bundle['turns']
                       for item in turn['user'].get('attachments', []))
    check_space([(cwd, project_bytes + 2 * history_bytes),
                 (profile, upload_bytes + 3 * history_bytes + 65536 * len(manifest['conversations']))])
    workspace = prepare(package, cwd, target_agent='antigravity')
    profile.mkdir(parents=True)
    conversations = profile / 'conversations'
    conversations.mkdir()
    pid, uri = str(uuid.uuid4()), workspace_uri(cwd)
    sessions = []
    for entry in workspace['chats']:
        bundle = json.loads(safe(cwd, entry['path']).read_text(encoding='utf-8'))
        sid = str(uuid.uuid4())
        sessions.append(write_session(conversations / f'{sid}.db', bundle, cwd, profile, sid, pid, uri))
    project = {'id': pid, 'name': cwd.name, 'projectResources': {'resources': [{'folderUri': uri}]},
               'projectConversations': {'conversations': [{'conversationId': s['id']} for s in sessions]}}
    result = {'status': 'isolated-native-stage', 'profile': str(profile), 'workspace': str(cwd),
              'project_registration': {'project': project, 'backend': 1}, 'sessions': sessions,
              'files': workspace['files'], 'attachments': workspace['attachments'],
              'native_project_registered': False, 'native_sidebar_verified': False, 'continuation_verified': False}
    dump(cwd / '.rehome/restore-antigravity.json', result)
    return result


def main():
    configure()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--cwd', required=True, type=Path)
    parser.add_argument('--profile', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(stage(args.package, args.cwd, args.profile), ensure_ascii=False))
    except (ValueError, KeyError, OSError, sqlite3.Error) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
