"""Offline format probe. WorkBuddy-shaped output has no native task registration."""
import argparse
import base64
import datetime as dt
import json
import shutil
import tempfile
import uuid
from pathlib import Path

import agent_rehome as rehome
import exchange


def workbuddy_message(role, text):
    kind = 'input_text' if role == 'user' else 'output_text'
    return {'type': 'message', 'role': role, 'content': [{'type': kind, 'text': text}]}


def project_turns(records, root):
    turns = []
    pending = {}
    for row in records:
        if row['type'] == 'message':
            timestamp = dt.datetime.fromtimestamp(row['timestamp'] / 1000, dt.timezone.utc).isoformat()
            text = '\n'.join(block['text'] for block in row['content']
                             if block['type'] in ('input_text', 'output_text'))
            if row['role'] == 'user':
                user = {'ts': timestamp, 'text': text}
                for block in row['content']:
                    if block['type'] == 'image_blob_ref':
                        user.setdefault('attachments', []).append({
                            'image': True, 'mime': block['mime'],
                            'local_path': str(exchange.safe(root, block['blob_path'])),
                        })
                turns.append({'user': user, 'items': []})
            else:
                turns[-1]['items'].append({'kind': 'message', 'ts': timestamp, 'text': text})
        elif row['type'] == 'function_call':
            timestamp = dt.datetime.fromtimestamp(row['timestamp'] / 1000, dt.timezone.utc).isoformat()
            item = {'kind': 'tool', 'ts': timestamp, 'name': row['name'],
                    'args': json.loads(row['arguments']), 'input': row['arguments']}
            turns[-1]['items'].append(item)
            pending[row['callId']] = item
        elif row['type'] == 'function_call_result':
            item = pending.pop(row['callId'])
            item.update(output=row['output']['text'], is_error=row['status'] != 'completed')
    assert not pending
    return turns


def workbuddy_preview(turns, claude_rows, root):
    records = []
    image_blocks = [block for row in claude_rows if row['type'] == 'user'
                    and isinstance(row['message']['content'], list)
                    for block in row['message']['content'] if block['type'] == 'image']
    assert len(image_blocks) == 1
    image_path = root / 'blobs' / 'sample.png'
    image_path.parent.mkdir()
    image_path.write_bytes(base64.b64decode(image_blocks[0]['source']['data']))
    for index, turn in enumerate(turns):
        message = workbuddy_message('user', turn['user']['text'])
        if index == 0:
            message['content'].append({'type': 'image_blob_ref', 'mime': 'image/png',
                                       'blob_path': 'blobs/sample.png'})
        records.append(message)
        for item in turn['items']:
            if item['kind'] == 'message':
                records.append(workbuddy_message('assistant', item['text']))
            else:
                call_id = str(uuid.uuid4())
                records.extend([
                    {'type': 'function_call', 'callId': call_id, 'name': item['name'],
                     'arguments': json.dumps(item['args'])},
                    {'type': 'function_call_result', 'callId': call_id, 'name': item['name'],
                     'output': {'text': item['output']},
                     'status': 'incomplete' if item['is_error'] else 'completed'},
                ])
    return records


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        source = root / 'source'
        source.mkdir()
        project_file = source / 'notes.md'
        project_file.write_text('离线样本\n', encoding='utf-8')
        image = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+oR2YAAAAASUVORK5CYII=')
        first = workbuddy_message('user', '请读项目笔记和图片')
        first['content'].append({'type': 'image_blob_ref', 'mime': 'image/png',
                                 'blob_path': 'blobs/sample.png'})
        records = [
            first,
            {'type': 'function_call', 'id': 'call-row', 'callId': 'joined-id', 'name': 'Read',
             'arguments': '{"file_path":"notes.md"}'},
            {'type': 'function_call_result', 'id': 'result-row', 'callId': 'joined-id',
             'output': {'text': '离线样本'}, 'status': 'completed'},
            workbuddy_message('assistant', '读到了笔记'),
            workbuddy_message('user', '记住本轮结果'),
            workbuddy_message('assistant', '已记录'),
        ]
        timestamp = 1795046400000
        session_id = str(uuid.uuid4())
        for index, row in enumerate(records):
            row.update(timestamp=timestamp + index, cwd=str(source), sessionId=session_id)
        (source / 'blobs').mkdir()
        (source / 'blobs/sample.png').write_bytes(image)
        source_log = root / 'workbuddy.jsonl'
        source_log.write_text(''.join(json.dumps(row) + '\n' for row in records), encoding='utf-8')

        target = root / 'claude-project'
        shutil.copytree(source, target, ignore=shutil.ignore_patterns('blobs'))
        args = argparse.Namespace(target_home=str(root / 'claude-home'), no_desktop=True,
                                  claude_model='claude-sonnet-4-5', claude_version='2.1.321')
        turns = project_turns(rehome.read(source_log), source)
        rows, _ = rehome.build_claude_history({'turns': turns, 'title': '交换样本'}, args,
                                              session_id, str(target))
        assert all(row['cwd'] == str(target) for row in rows[:-1])
        assert [row['parentUuid'] for row in rows[1:-1]] == [row['uuid'] for row in rows[:-2]]
        tool = rows[1]['message']['content'][0]
        assert rows[2]['message']['content'][0]['tool_use_id'] == tool['id']
        recovered_image = base64.b64decode(rows[0]['message']['content'][1]['source']['data'])
        assert recovered_image == image
        claude_log = root / 'claude.jsonl'
        claude_log.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')

        bundle = rehome.export('claude', str(claude_log), root, full_tools=True)
        reverse_target = root / 'workbuddy-preview'
        shutil.copytree(target, reverse_target)
        preview = workbuddy_preview(exchange.to_v1(bundle)['turns'], rehome.read(claude_log),
                                    reverse_target)
        for index, row in enumerate(preview):
            row.update(timestamp=timestamp + index, cwd=str(reverse_target), sessionId=session_id)
        preview_log = reverse_target / 'preview.jsonl'
        preview_log.write_text(''.join(json.dumps(row) + '\n' for row in preview), encoding='utf-8')
        roundtrip = project_turns(rehome.read(preview_log), reverse_target)
        assert [turn['user']['text'] for turn in roundtrip] == ['请读项目笔记和图片', '记住本轮结果']
        assert [item['text'] for turn in roundtrip for item in turn['items']
                if item['kind'] == 'message'] == ['读到了笔记', '已记录']
        assert roundtrip[0]['items'][0]['output'] == '离线样本'
        assert roundtrip[0]['items'][0]['args'] == {'file_path': 'notes.md'}
        assert Path(roundtrip[0]['user']['attachments'][0]['local_path']).read_bytes() == image
        assert (reverse_target / 'notes.md').read_bytes() == project_file.read_bytes()




def test_workbuddy_project_package(targets=('claude', 'codex')):
    import contextlib
    import io
    import sqlite3
    from unittest.mock import patch

    import project_rehome
    import workbuddy_receive
    import workbuddy_source

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        workspace = root / 'source'
        workspace.mkdir()
        (workspace / 'project.txt').write_text('project text', encoding='utf-8')
        input_dir = root / 'input'
        input_dir.mkdir()
        note = input_dir / 'note.txt'
        note.write_text('external file', encoding='utf-8')
        home = root / 'workbuddy-home'
        blobs = home / 'blobs'
        blobs.mkdir(parents=True)
        image = blobs / 'image.png'
        image.write_bytes(base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAQAAAACCAIAAADwyuo0AAAAFElEQVR4nGP8zwACjAwgmgnMhgIAKjcCA84vINUAAAAASUVORK5CYII='))
        encoded = workbuddy_source.project_slug(workspace)
        history = home / 'projects' / encoded
        history.mkdir(parents=True)
        sid = '12345678-1234-4567-8123-123456789012'
        rows = [
            {'type': 'message', 'role': 'user', 'id': 'u1', 'content': [
                {'type': 'input_text', 'text': '<system-reminder data-role="additional-data">'
                 f'<attached_files><file path="{note}" /></attached_files></system-reminder>'
                 '<user_query>open both</user_query>'},
                {'type': 'image_blob_ref', 'blob_path': str(image), 'mime': 'image/png'}]},
            {'type': 'message', 'role': 'assistant', 'id': 'abandoned', 'parentId': 'u1',
             'content': [{'type': 'output_text', 'text': 'inactive branch'}]},
            {'type': 'function_call', 'id': 'call', 'parentId': 'u1', 'callId': 'same',
             'name': 'Read', 'arguments': '{"path":"note.txt"}'},
            {'type': 'function_call_result', 'id': 'result', 'parentId': 'call', 'callId': 'same',
             'output': {'text': 'external file'}, 'status': 'completed'},
            {'type': 'message', 'role': 'assistant', 'id': 'a1', 'parentId': 'result',
             'content': [{'type': 'output_text', 'text': 'read both'}]},
            {'type': 'message', 'role': 'user', 'id': 'u2', 'parentId': 'a1',
             'content': [{'type': 'input_text', 'text': 'view image from tool'}]},
            {'type': 'function_call', 'id': 'view', 'parentId': 'u2', 'callId': 'view-call',
             'name': 'ViewImage', 'arguments': '{}'},
            {'type': 'function_call_result', 'id': 'view-result', 'parentId': 'view',
             'callId': 'view-call', 'status': 'completed',
             'output': {'type': 'text', 'text': json.dumps([
                 {'type': 'image_blob_ref', 'blob_path': str(image), 'mime': 'image/png'}])}},
        ]
        for index, row in enumerate(rows):
            row.update(cwd=str(workspace), sessionId=sid, timestamp=1795046400000 + index)
        (history / (sid + '.jsonl')).write_text(''.join(json.dumps(row) + '\n' for row in rows),
                                                encoding='utf-8')
        package = root / 'package'
        withheld = root / 'restricted'
        mkdir = Path.mkdir

        def shim_mkdir(path, mode=0o777, parents=False, exist_ok=False):
            if path == package / 'attachments' and path.is_dir() and not parents:
                raise FileExistsError(path)
            return mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

        with contextlib.redirect_stdout(io.StringIO()), patch.object(Path, 'mkdir', shim_mkdir):
            project_rehome.pack('workbuddy', workspace, package, home, attachment_roots=[input_dir])
            project_rehome.pack('workbuddy', workspace, withheld, home)
        manifest = project_rehome.load_manifest(package)
        bundle, = manifest['conversations']
        assert bundle['source']['agent'] == 'workbuddy'
        assert bundle['turns'][0]['user']['text'] == 'open both'
        assert [item['kind'] for item in bundle['turns'][0]['items']] == ['tool', 'message']
        assert {loss['kind'] for loss in bundle['losses']} == {'workbuddy_context', 'inactive_branch'}
        assert len(manifest['attachments']) == 2
        tool_image, = bundle['turns'][1]['user']['attachments']
        assert tool_image['mode'] == 'tool-result' and tool_image['image']
        restricted = project_rehome.load_manifest(withheld)
        assert len(restricted['attachments']) == 1
        assert any(loss['reason'] == 'sensitive' for loss in restricted['conversations'][0]['losses'])
        claude_registry = root / 'claude-desktop-registry'
        claude_registry.mkdir()
        for agent in targets:
            target = root / f'{agent}-project'
            target_home = root / f'{agent}-home'
            if agent == 'codex':
                target_home.mkdir()
                with contextlib.closing(sqlite3.connect(target_home / 'state_5.sqlite')) as db:
                    db.executescript((Path(__file__).parent / 'fixtures/codex_schema.sql').read_text(encoding='utf-8'))
            with contextlib.redirect_stdout(io.StringIO()):
                result = project_rehome.restore(package, target, agent, target_home, agent != 'claude',
                                                model='fixture-model', claude_model='fixture-model',
                                                claude_version='0.0.0-test',
                                                desktop_registry=claude_registry if agent == 'claude' else None)
            assert len(result['sessions']) == 1
            assert {p.read_bytes() for p in (target / '.rehome/attachments').iterdir()} == {
                note.read_bytes(), image.read_bytes()}
            if agent == 'claude':
                session = result['sessions'][0]
                entry = json.loads(Path(session['desktop_registry']).read_text(encoding='utf-8'))
                assert entry['cliSessionId'] == session['id']
                assert Path(entry['cwd']).resolve() == target
                log, = (target_home / 'projects').glob(f'*/{session["id"]}.jsonl')
                assert any(row.get('cwd') == str(target) for row in rehome.read(log))
        target = root / 'portable-workspace'
        result = workbuddy_receive.prepare(package, target)
        assert result['status'] == 'workspace-ready' and not result['native_history_registered']
        assert result['files'] == 1 and result['attachments'] == 2
        chat = json.loads((target / result['chats'][0]['path']).read_text(encoding='utf-8'))
        assert {(target / item['workspace_path']).read_bytes()
                 for item in chat['turns'][0]['user']['attachments']} == {
                     note.read_bytes(), image.read_bytes()}
        assert (target / chat['turns'][1]['user']['attachments'][0]['workspace_path']).read_bytes() == image.read_bytes()
        # A previously restored project may inventory the same image as both a
        # workspace file and a historical attachment. Matching copies coalesce.
        claude_package = root / 'claude-return'
        with contextlib.redirect_stdout(io.StringIO()):
            project_rehome.pack('claude', root / 'claude-project', claude_package,
                                root / 'claude-home')
        returned = root / 'claude-return-workspace'
        workbuddy_receive.prepare(claude_package, returned)
        assert next((returned / '.rehome/attachments').glob('*.png')).read_bytes() == image.read_bytes()
        assert next((returned / '.rehome/attachments').glob('*.txt')).read_bytes() == note.read_bytes()
        check_native_projection(root, target, chat, returned)


def check_native_projection(root, workspace, chat, claude_workspace):
    from contextlib import closing
    import sqlite3

    import workbuddy_native
    import workbuddy_source

    assert workbuddy_source.project_slug('/' + 'Users/fixture/WorkBuddy/my-project') == (
        'Users-fixture-WorkBuddy-my-project')
    assert workbuddy_source.project_slug('c:\\' + 'Users\\fixture\\WorkBuddy\\my-project') == (
        'c-Users-fixture-WorkBuddy-my-project')

    original = json.dumps(chat, ensure_ascii=False)
    session_id = str(uuid.uuid4())
    records, omitted = workbuddy_native.project_history(chat, str(workspace), session_id)
    assert json.dumps(chat, ensure_ascii=False) == original
    assert omitted and any('/attachments/' in item for item in omitted)
    assert any('/items/' in item for item in omitted)
    expected = []
    for turn in chat['turns']:
        expected.append(('user', turn['user']['text']))
        expected.extend(('assistant', item['text']) for item in turn['items']
                        if item['kind'] == 'message')
    history = root / f'{session_id}.jsonl'
    workbuddy_native.write_history(history, records)
    actual = rehome.read(history)
    assert [(row['role'], row['content'][0]['text']) for row in actual] == expected
    assert {row['cwd'] for row in actual} == {str(workspace)}
    assert {row['sessionId'] for row in actual} == {session_id}
    assert workbuddy_source.belongs_to(actual, workspace)
    previous = None
    for row in actual:
        assert row.get('parentId') == (previous['id'] if previous else None)
        if row['role'] == 'assistant':
            assert row['providerData']['conversationRequestId'] == previous['providerData']['conversationRequestId']
        previous = row
    try:
        workbuddy_native.write_history(history, records)
    except FileExistsError:
        pass
    else:
        raise AssertionError('WorkBuddy history overwrite must be refused')
    assert rehome.read(history) == actual

    blob_root = root / 'workbuddy-blobs'
    with_attachments, omissions = workbuddy_native.project_history(
        chat, str(workspace), session_id, blob_root=blob_root)
    assert omissions and not any('/attachments/' in item for item in omissions)
    first_text, attachments, stripped = workbuddy_source.user_text(with_attachments[0]['content'])
    assert stripped and first_text == chat['turns'][0]['user']['text']
    assert {a['image'] for a in attachments} == {True, False}
    for item in attachments:
        recovered = Path(item['path'])
        reference = next(a for a in chat['turns'][0]['user']['attachments']
                         if bool(a.get('image')) == item['image'])
        assert recovered.read_bytes() == (workspace / reference['workspace_path']).read_bytes()
    reused, _ = workbuddy_native.project_history(chat, str(workspace), session_id, blob_root=blob_root)
    assert reused[0]['content'] == with_attachments[0]['content']

    workbuddy_home = root / 'native-workbuddy-home'
    workbuddy_home.mkdir()
    with closing(sqlite3.connect(workbuddy_home / 'workbuddy.db')) as db, db:
        db.executescript("""
            CREATE TABLE spaces (
                id TEXT PRIMARY KEY, user_id TEXT, device_id TEXT, name TEXT, primary_folder_path TEXT,
                create_folder_path TEXT, sort_order INTEGER, created_at INTEGER, updated_at INTEGER, source_kind TEXT,
                status TEXT DEFAULT 'active', transport TEXT DEFAULT 'local', deleted_at INTEGER DEFAULT -1
            );
            CREATE TABLE space_folders (space_id TEXT, path TEXT);
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, cwd TEXT, user_id TEXT, title TEXT, custom_title TEXT, status TEXT, created_at INTEGER,
                updated_at INTEGER, last_activity_at INTEGER, transport TEXT, source_mode TEXT,
                mode TEXT, use_sandbox_cli INTEGER, space_id TEXT
            );
            INSERT INTO spaces (id, user_id, device_id, sort_order) VALUES ('template-space', 'fixture-account', 'fixture-device', 3);
            INSERT INTO spaces (id, user_id, device_id) VALUES ('other-space', 'other-account', 'other-device');
        """)
        workbuddy_native.register_space(db, template_id='template-space', space_id='fixture-space',
                                       cwd=str(workspace), title='Test workspace', timestamp=1)
        assert db.execute('SELECT name, primary_folder_path, user_id, device_id, sort_order FROM spaces WHERE id = ?',
                          ('fixture-space',)).fetchone() == (
                              'Test workspace', str(workspace), 'fixture-account', 'fixture-device', 4)
        args = dict(cwd=str(workspace), session_id=session_id, title=chat['title'], records=actual)
        try:
            workbuddy_native.register_in_space(db, space_id='other-space', **args)
        except ValueError:
            pass
        else:
            raise AssertionError('A session cannot be registered under an unrelated space')
        workbuddy_native.register_in_space(db, space_id='fixture-space', **args)
        try:
            workbuddy_native.register_in_space(db, space_id='fixture-space', **args)
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError('Duplicate session ID must be refused')
        assert db.execute('SELECT id, cwd, user_id, space_id, status FROM sessions').fetchall() == [
            (session_id, str(workspace), 'fixture-account', 'fixture-space', 'completed')]

    registered_workspace = root / 'registered-workspace'
    import workbuddy_receive
    workbuddy_receive.prepare(root / 'package', registered_workspace)
    native = workbuddy_native.restore_project(registered_workspace, workbuddy_home, 'template-space')
    assert native['status'] == 'native-registered-sidebar-unverified'
    assert len(native['sessions']) == 1 and Path(native['backup']).is_file()
    with closing(sqlite3.connect(workbuddy_home / 'workbuddy.db')) as db:
        assert db.execute('SELECT title, custom_title, space_id FROM sessions WHERE id=?',
                          (native['sessions'][0]['id'],)).fetchone() == (
                              chat['title'], chat['title'], native['space_id'])
    try:
        workbuddy_native.restore_project(registered_workspace, workbuddy_home, 'template-space')
    except ValueError as error:
        assert 'already exists' in str(error)
    else:
        raise AssertionError('Repeating native registration must not create a second chat')

    claude_source = json.loads((claude_workspace / '.rehome/restore-workbuddy.json').read_text(encoding='utf-8'))
    source_chat = json.loads((claude_workspace / claude_source['chats'][0]['path']).read_text(encoding='utf-8'))
    assert source_chat['source']['agent'] == 'claude'
    direct = workbuddy_native.restore_project(claude_workspace, workbuddy_home, 'template-space')
    id_, = [entry['id'] for entry in direct['sessions']]
    assert direct['status'] == 'native-registered-sidebar-unverified'
    with closing(sqlite3.connect(workbuddy_home / 'workbuddy.db')) as db:
        assert db.execute('SELECT id, space_id FROM sessions WHERE id=?', (id_,)).fetchone() == (
            id_, direct['space_id'])
    log, = (workbuddy_home / 'projects').glob(f'*/{id_}.jsonl')
    users = [row for row in rehome.read(log) if row.get('role') == 'user']
    assert len(users) == len(source_chat['turns'])
    image_assets = [block for row in users for block in row['content'] if block['type'] == 'image_blob_ref']
    assert image_assets and all(Path(asset['blob_path']).is_file() for asset in image_assets)



def test_project_slug_preserves_dots():
    import workbuddy_source
    assert workbuddy_source.project_slug('/' + 'Users/demo/.gemini/v1.0/my.project') == 'Users-demo-.gemini-v1.0-my.project'


def test_migration_metadata_excluded_and_no_receipt_collision():
    import project_rehome
    import workbuddy_receive
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ws = root / 'ws'
        ws.mkdir()
        (ws / 'README.md').write_text('keep\n', encoding='utf-8')
        (ws / '.rehome' / 'exchange').mkdir(parents=True)
        (ws / '.rehome' / 'restore-workbuddy.json').write_text('{}', encoding='utf-8')
        (ws / '.rehome' / 'exchange' / 's1.json').write_text('{}', encoding='utf-8')
        (ws / '.rehome' / 'custom-note.md').write_text('user note\n', encoding='utf-8')
        collected = {p.relative_to(ws).as_posix() for p in project_rehome.files(ws)}
        assert collected == {'README.md', '.rehome/custom-note.md'}, collected

        # Simulate a pre-fix return package containing project/.rehome/restore-workbuddy.json
        pkg = root / 'pkg'
        (pkg / 'project' / '.rehome').mkdir(parents=True)
        (pkg / 'project' / 'README.md').write_bytes(b'keep\n')
        (pkg / 'project' / '.rehome' / 'restore-workbuddy.json').write_text('{}', encoding='utf-8')
        (pkg / 'attachments').mkdir()
        sid = '12345678-1234-4567-8123-123456789012'
        ev_id = 'aaaaaaaa-1234-4567-8123-123456789012'
        turn_id = '6f1c2a9e-4b7d-4c1e-9a3f-c1a0dec0de01'
        (pkg / 'sessions' / sid).mkdir(parents=True)
        ev = {
            'id': ev_id, 'parent_id': None, 'seq': 0,
            'ts': '2026-11-24T00:00:00Z', 'turn_id': turn_id,
            'branch': 'main', 'kind': 'user_message', 'raw_ref': None, 'text': 'hi', 'attachments': [],
        }
        ev_path = pkg / 'sessions' / sid / 'events.jsonl'
        ev_path.write_text(json.dumps(ev) + '\n', encoding='utf-8')
        loss_path = ev_path.parent / 'losses.json'
        loss_path.write_text('[]', encoding='utf-8')
        def sha(p):
            import hashlib
            return hashlib.sha256(p.read_bytes()).hexdigest()
        manifest = {
            'schema': 'agent-exchange/v2', 'type': 'project',
            'source': {'agent': 'workbuddy', 'os': 'macOS'}, 'created_at': '2026-11-24T00:00:00Z',
            'project': {
                'name': 'ws', 'root_hint': 'ws',
                'files': [
                    {'path': 'project/README.md', 'sha256': sha(pkg / 'project' / 'README.md'), 'bytes': 5},
                    {'path': 'project/.rehome/restore-workbuddy.json', 'sha256': sha(pkg / 'project' / '.rehome' / 'restore-workbuddy.json'), 'bytes': 2},
                ],
            },
            'attachments': [],
            'losses_summary': {},
            'sessions': [{
                'id': sid,
                'metadata': {
                    'source': {'agent': 'workbuddy', 'session_id': sid},
                    'title': 't', 'project': {},
                    'session': {'id': sid, 'branches': [{'id': 'main', 'forked_from': None}], 'forked_from': None, 'subagent_of': None},
                    'losses_summary': {},
                },
                'events': {'path': f'sessions/{sid}/events.jsonl', 'sha256': sha(ev_path)},
                'losses': {'path': f'sessions/{sid}/losses.json', 'sha256': sha(loss_path)},
                'branches': [{'id': 'main', 'events_ref': f'sessions/{sid}/events.jsonl'}],
            }],
        }
        (pkg / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        dest = root / 'dest'
        res = workbuddy_receive.prepare(pkg, dest, target_agent='workbuddy')
        assert res['status'] == 'workspace-ready'
        assert (dest / 'README.md').read_bytes() == b'keep\n'


if __name__ == '__main__':
    test_project_slug_preserves_dots()
    test_migration_metadata_excluded_and_no_receipt_collision()
    main()
    test_workbuddy_project_package()
