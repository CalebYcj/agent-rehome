"""Register a prepared workspace and its old chats in WorkBuddy."""
import argparse
from contextlib import closing
import datetime as dt
import html
import json
import re
import sqlite3
import sys
import uuid
from pathlib import Path, PureWindowsPath

import agent_rehome
import exchange
from cli_output import configure, print
from platform_paths import path_key, portable_name, sqlite_read_uri
from project_io import check_space, chunks, measure, write_checked
from workbuddy_source import project_slug


IMAGE_SUFFIXES = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/gif': '.gif', 'image/webp': '.webp'}


def copy_attachment(source, target, expected):
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_checked(target, chunks(source), expected)
    except FileExistsError:
        if measure(chunks(target)) != expected:
            raise ValueError('Existing WorkBuddy attachment differs from the package')


def attachment_content(user, cwd, blob_root, index, omitted):
    text = {'type': 'input_text', 'text': user['text']}
    content = [text]
    files = []
    mentions = []
    for number, attachment in enumerate(user.get('attachments', [])):
        suffix = IMAGE_SUFFIXES.get(attachment.get('mime'))
        within_workspace = attachment.get('workspace_path')
        if (blob_root is None or not within_workspace or not within_workspace.startswith('.rehome/attachments/')
                or attachment.get('image') and not suffix
                or not attachment.get('image') and '</user_query>' in user['text']):
            omitted.append(f'turn/{index}/attachments/{number}')
            continue
        source = exchange.safe(Path(cwd), within_workspace)
        digest, length = expected = (attachment['sha256'], attachment['bytes'])
        if measure(chunks(source)) != expected:
            raise ValueError('Restored WorkBuddy attachment differs from the package')
        if not attachment.get('image'):
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', portable_name(
                attachment.get('name') or source.name)).rstrip(' .')
            if not name or PureWindowsPath(name).is_reserved():
                name = source.name
            named_file = exchange.safe(Path(cwd), f'.rehome/workbuddy-files/{digest}/{name}')
            copy_attachment(source, named_file, expected)
            files.append(f'<file path="{html.escape(str(named_file), quote=True)}" />')
            mentions.append(f'@"{named_file}" ')
            continue
        blob = exchange.safe(blob_root, f'{digest[:2]}/{digest}{suffix}')
        copy_attachment(source, blob, expected)
        content.extend([
            {'type': 'image_blob_ref', 'blob_id': digest, 'blob_path': str(blob),
             'mime': attachment['mime'], 'size': length,
             'original_filename': attachment.get('name') or source.name},
            {'type': 'input_text', 'text': f'<image_local_path>{html.escape(str(source))}</image_local_path>'},
        ])
    if files:
        attached_files = '\n'.join(files)
        text['text'] = ('<system-reminder data-role="additional-data">\n'
                        f'<attached_files>\n{attached_files}\n</attached_files>\n'
                        f'</system-reminder>\n<user_query>{"".join(mentions)}{user["text"]}</user_query>')
    return content


def project_history(bundle, cwd, session_id, *, blob_root=None):
    agent_rehome.validate(bundle)
    bundle = exchange.to_v1(bundle)
    session_id = str(uuid.UUID(session_id))
    records = []
    omitted = []
    parent_id = None
    for index, turn in enumerate(bundle['turns']):
        user = turn['user']
        user_id = str(uuid.uuid4())
        request_id = uuid.uuid4().hex
        request = {'agent': 'cli', 'conversationRequestId': request_id}
        records.append({
            'type': 'message', 'role': 'user', 'id': user_id,
            'cwd': cwd, 'sessionId': session_id,
            'timestamp': agent_rehome.backend.to_ms(user['ts']),
            'content': attachment_content(user, cwd, blob_root, index, omitted),
            'providerData': {**request, 'startsNewUserRequest': True},
        })
        if parent_id is not None:
            records[-1]['parentId'] = parent_id
        parent_id = user_id
        for item_index, item in enumerate(turn['items']):
            if item['kind'] != 'message':
                omitted.append(f'turn/{index}/items/{item_index}')
                continue
            message_id = str(uuid.uuid4())
            records.append({
                'type': 'message', 'role': 'assistant', 'id': message_id,
                'parentId': parent_id, 'cwd': cwd, 'sessionId': session_id,
                'timestamp': agent_rehome.backend.to_ms(item['ts']),
                'status': 'completed',
                'content': [{'type': 'output_text', 'text': item['text']}],
                'providerData': {**request, 'messageId': message_id},
            })
            parent_id = message_id
    return records, omitted


def register_space(db, *, template_id, space_id, cwd, title, timestamp):
    """Create a space under the account/device owning an explicitly selected local space."""
    template = db.execute(
        "SELECT user_id, device_id FROM spaces WHERE id = ? AND status = 'active' "
        "AND transport = 'local' AND deleted_at = -1", (template_id,),
    ).fetchone()
    if not template:
        raise ValueError('Choose an active local WorkBuddy account space')
    folders = db.execute(
        "SELECT f.path FROM space_folders f JOIN spaces s ON s.id = f.space_id "
        "WHERE s.user_id = ? AND s.status = 'active' AND s.deleted_at = -1", (template[0],),
    )
    if any(path_key(path) == path_key(cwd) for (path,) in folders):
        raise ValueError('The target folder already belongs to an active WorkBuddy space')
    order, = db.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM spaces "
        "WHERE user_id = ? AND status = 'active' AND deleted_at = -1", (template[0],),
    ).fetchone()
    db.execute(
        "INSERT INTO spaces (id, user_id, device_id, name, primary_folder_path, create_folder_path, "
        "sort_order, created_at, updated_at, source_kind) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'user')",
        (space_id, *template, title, cwd, cwd, order, timestamp, timestamp),
    )
    db.execute('INSERT INTO space_folders (space_id, path) VALUES (?, ?)', (space_id, cwd))


def register_in_space(db, *, space_id, cwd, session_id, title, records):
    """Insert a new session for an explicitly selected existing local space."""
    space = db.execute(
        "SELECT user_id FROM spaces WHERE id = ? AND status = 'active' "
        "AND transport = 'local' AND deleted_at = -1", (space_id,),
    ).fetchone()
    folders = db.execute('SELECT path FROM space_folders WHERE space_id = ?', (space_id,))
    if not space or not any(path_key(path) == path_key(cwd) for (path,) in folders):
        raise ValueError('Choose an active local WorkBuddy space that already contains the target folder')
    if not records or any(row['sessionId'] != session_id or row['cwd'] != cwd for row in records):
        raise ValueError('WorkBuddy history and session registration disagree')
    created_at = records[0]['timestamp']
    last_activity = max(row['timestamp'] for row in records)
    db.execute(
        "INSERT INTO sessions (id, cwd, user_id, title, custom_title, status, created_at, updated_at, "
        "last_activity_at, transport, source_mode, mode, use_sandbox_cli, space_id) "
        "VALUES (?, ?, ?, ?, ?, 'completed', ?, ?, ?, 'local', 'craft', 'craft', 1, ?)",
        (session_id, cwd, space[0], title, title, created_at, last_activity, last_activity, space_id),
    )


def write_history(path, records):
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        try:
            for row in records:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
            handle.flush()
        except BaseException:
            handle.close()
            path.unlink()
            raise


def restore_project(workspace, home, template_id):
    workspace, home = workspace.resolve(strict=True), home.resolve(strict=True)
    if workspace.is_relative_to(home) or home.is_relative_to(workspace):
        raise ValueError('Restore into a workspace separate from the WorkBuddy data folder')
    receipt = exchange.safe(workspace, '.rehome/restore-workbuddy.json')
    staged = json.loads(receipt.read_text(encoding='utf-8'))
    if staged.get('status') != 'workspace-ready' or path_key(staged['workspace']) != path_key(workspace):
        raise ValueError('Prepare this workspace with workbuddy_receive.py first')
    bundles = [json.loads(exchange.safe(workspace, item['path']).read_text(encoding='utf-8'))
               for item in staged['chats']]
    if not bundles:
        raise ValueError('The prepared workspace has no conversations')
    for bundle in bundles:
        agent_rehome.validate(bundle)
    now = dt.datetime.now()
    backup = exchange.safe(home, 'rehome-backups/' + now.strftime('%Y%m%d-%H%M%S-%f') + '/workbuddy.db')
    dbfile = exchange.safe(home, 'workbuddy.db')
    cwd = str(workspace)
    if cwd[1:2] == ':':
        cwd = cwd[0].lower() + cwd[1:]
    history_dir = exchange.safe(home, 'projects/' + project_slug(cwd))
    blob_root = exchange.safe(home, 'blobs')
    if history_dir.exists():
        raise ValueError('WorkBuddy history folder already exists; choose a new workspace')
    attachments = [a for b in bundles for turn in exchange.to_v1(b)['turns']
                   for a in turn['user'].get('attachments', [])]
    histories_size = sum(exchange.safe(workspace, item['path']).stat().st_size for item in staged['chats'])
    check_space([(backup, dbfile.stat().st_size), (history_dir, histories_size),
                 (blob_root, sum(a['bytes'] for a in attachments if a.get('image'))),
                 (workspace, sum(a['bytes'] for a in attachments if not a.get('image')))])
    with closing(sqlite3.connect(sqlite_read_uri(dbfile), uri=True, timeout=5)) as source:
        backup.parent.mkdir(parents=True)
        with closing(sqlite3.connect(backup)) as snapshot:
            source.backup(snapshot)
            if snapshot.execute('PRAGMA quick_check').fetchone() != ('ok',):
                raise ValueError('WorkBuddy database backup did not pass integrity check')

    space_id = str(uuid.uuid4())
    written = []
    sessions = []
    created_directory = False
    with closing(sqlite3.connect(dbfile.as_uri() + '?mode=rw', uri=True, timeout=5)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            register_space(db, template_id=template_id, space_id=space_id, cwd=cwd,
                           title=workspace.name, timestamp=int(now.timestamp() * 1000))
            history_dir.mkdir(parents=True)
            created_directory = True
            for bundle in bundles:
                session_id = str(uuid.uuid4())
                records, omitted = project_history(bundle, cwd, session_id, blob_root=blob_root)
                register_in_space(db, space_id=space_id, cwd=cwd, session_id=session_id,
                                  title=bundle['title'], records=records)
                path = history_dir / f'{session_id}.jsonl'
                write_history(path, records)
                written.append(path)
                sessions.append({'id': session_id, 'title': bundle['title'], 'omitted': omitted})
            db.commit()
        except BaseException:
            db.rollback()
            for path in written:
                path.unlink()
            if created_directory:
                history_dir.rmdir()
            raise
    return {'status': 'native-registered-sidebar-unverified', 'workspace': cwd, 'space_id': space_id,
            'sessions': sessions, 'backup': str(backup)}


def main():
    configure()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('--template-space', required=True, help='ID of an existing space owned by the target account')
    parser.add_argument('--workbuddy-home', type=Path, default=Path.home() / '.workbuddy')
    parser.add_argument('--experimental-macos', action='store_true',
                        help='Opt in to native registration for a controlled macOS pilot')
    args = parser.parse_args()
    if sys.platform != 'win32' and not (sys.platform == 'darwin' and args.experimental_macos):
        parser.exit(1, 'Native WorkBuddy registration is validated on Windows; macOS requires an explicit pilot.\n')
    try:
        result = restore_project(args.workspace, args.workbuddy_home, args.template_space)
        print(json.dumps(result, ensure_ascii=False))
    except (KeyError, ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
