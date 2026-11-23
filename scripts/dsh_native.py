"""Restore a portable Rehome project as DeepSeek Harness v4 chats."""
import argparse
import json
import ntpath
import os
import platform
import re
import shutil
import struct
import tempfile
import uuid
from pathlib import Path, PureWindowsPath

import agent_rehome
import exchange
from cli_output import configure, print
from dsh_source import LOG_NAME, open_log, project_key, zstd_module
from platform_paths import portable_name
from project_io import check_space, chunks, measure, write_checked
from workbuddy_receive import prepare


def probe(home):
    """Describe the explicitly selected data root without opening any chat."""
    home = home.resolve()
    try:
        codec = zstd_module().__name__
    except ValueError:
        codec = None
    sessions = exchange.safe(home, 'sessions')
    registry = exchange.safe(home, 'storages/workspace.json')
    status = 'missing'
    if registry.is_file():
        try:
            data = json.loads(registry.read_text(encoding='utf-8'))
            supported = data.get('unit') == {'name': 'workspace', 'version': 2}
            state = data.get('global', {})
            status = ('initialized-v2' if supported and state.get('initialized') is True
                      and not state.get('pendingMutation') else 'uninitialized-or-unsupported')
        except (AttributeError, ValueError):
            status = 'unrecognized'
    return {'system': platform.system(), 'architecture': platform.machine(),
            'python': platform.python_version(), 'zstandard_backend': codec,
            'cli_in_path': shutil.which('dsh') is not None,
            'sessions_directory': sessions.is_dir(),
            'v4_log_name_seen': next(sessions.glob(f'*/*/{LOG_NAME}'), None) is not None,
            'workspace_registry': status,
            'runtime_acceptance': 'unverified'}


def image_ref(source, attachment, home):
    with source.open('rb') as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR':
        raise ValueError('Invalid historical PNG header')
    width, height = struct.unpack('>II', header[16:])
    if not width or not height:
        raise ValueError('Invalid historical PNG dimensions')
    digest, size = expected = (attachment['sha256'], attachment['bytes'])
    if not re.fullmatch('[a-f0-9]{64}', digest):
        raise ValueError('Invalid historical PNG checksum')
    target = exchange.safe(home, f'attachments/v1/objects/{digest[:2]}/{digest}')
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_checked(target, chunks(source), expected)
    except FileExistsError:
        if measure(chunks(target)) != expected:
            raise ValueError('DSH image store contains different bytes for this checksum')
    return {'type': 'image', 'attachment': {'attachmentId': f'sha256:{digest}',
            'mediaType': 'image/png', 'bytes': size, 'width': width, 'height': height,
            'name': attachment.get('name') or source.name}}


def file_reference(source, attachment, cwd):
    original = portable_name(attachment.get('name') or source.name)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', original).rstrip(' .')
    reserved = ntpath.isreserved(name) if hasattr(ntpath, 'isreserved') else PureWindowsPath(name).is_reserved()
    if not name or len(name.encode('utf-8')) > 200 or reserved:
        name = source.name
    digest, size = attachment['sha256'], attachment['bytes']
    if not re.fullmatch('[a-f0-9]{64}', digest):
        raise ValueError('Invalid historical file checksum')
    relative = f'.rehome/dsh-files/{digest}/{name}'
    target = exchange.safe(cwd, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_checked(target, chunks(source), (digest, size))
    except FileExistsError:
        if measure(chunks(target)) != (digest, size):
            raise ValueError('Existing DSH file reference differs from the package')
    return f'\n@"{relative}"'


def history(bundle, cwd, home, sid):
    agent_rehome.validate(bundle)
    timestamp = agent_rehome.backend.to_ms
    first = timestamp(bundle['turns'][0]['user']['ts'])
    yield {'type': 'session', 'version': 4, 'id': sid, 'createdAt': first,
           'cwd': str(cwd), 'isSeeded': False, 'delegationDepth': 0, 'agentPreset': 'standard'}
    seq = 0

    def row(kind, when, data, surface=False):
        nonlocal seq
        result = {'type': kind, 'seq': seq, 'time': when, 'data': data}
        seq += 1
        if surface:
            result['surfaceOp'] = 'append'
        return result

    yield row('session/title', first, {'title': bundle['title'], 'messageSeqs': [], 'source': {'kind': 'user'}})
    for index, turn in enumerate(bundle['turns'], 1):
        user = turn['user']
        when = timestamp(user['ts'])
        turn_key = {'turn': index}
        step = {**turn_key, 'step': 1}
        content = [{'type': 'text', 'text': user['text']}]
        for attachment in user.get('attachments', []):
            relative = attachment['workspace_path']
            source = exchange.safe(cwd, relative)
            if attachment.get('image') and attachment.get('mime') == 'image/png':
                content.append(image_ref(source, attachment, home))
            else:
                content.append({'type': 'text', 'text': file_reference(source, attachment, cwd)})
        yield row('turn/start', when, turn_key)
        yield row('step/start', when, step)
        yield row('user/message', when, {'role': 'user', 'id': str(uuid.uuid4()), 'content': content,
                                        'source': {'kind': 'user'}}, True)
        for item in turn['items']:
            if item['kind'] != 'message':
                continue
            when = max(when, timestamp(item['ts']))
            yield row('assistant/message', when, {**step, 'stream': [], 'message': {
                'role': 'assistant', 'id': str(uuid.uuid4()), 'source': {
                    'kind': 'model', 'provider': bundle['source']['agent'], 'model': 'imported'},
                'content': [{'type': 'text', 'text': item['text']}]}}, True)
        yield row('step/end', when, step)
        yield row('turn/end', when, {**turn_key, 'reason': {'kind': 'completed'}})


def write_log(path, records):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temp_path = Path(temporary.name)
    try:
        # DSH probes the first compression frame as exactly one header line.
        with open_log(temp_path, 'wt') as stream:
            stream.write(json.dumps(next(records), ensure_ascii=False) + '\n')
        with open_log(temp_path, 'at') as stream:
            for event in records:
                stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def restore(package, cwd, home):
    zstd_module()
    cwd, home = cwd.resolve(), home.resolve()
    if not (home / 'sessions').is_dir():
        raise ValueError('Point --dsh-home to a DSH data directory containing sessions/')
    if cwd.is_relative_to(home) or home.is_relative_to(cwd):
        raise ValueError('Restore the project outside the DSH data directory')
    manifest = exchange.read_project(package)
    if not manifest['conversations']:
        raise ValueError('The package has no conversations')
    attachment_bytes = sum(item['bytes'] for item in manifest['attachments'])
    project_bytes = sum(item['bytes'] for item in manifest['files'])
    check_space([(home, attachment_bytes), (cwd, project_bytes + 2 * attachment_bytes)])
    prepared = prepare(package, cwd, target_agent='dsh')
    results = []
    for chat in prepared['chats']:
        bundle = json.loads(exchange.safe(cwd, chat['path']).read_text(encoding='utf-8'))
        sid = 'session-' + str(uuid.uuid4())
        directory = exchange.safe(home, f'sessions/{project_key(str(cwd))}/{sid}')
        directory.mkdir(parents=True)
        write_log(directory / LOG_NAME, history(bundle, cwd, home, sid))
        results.append({'id': sid, 'title': bundle['title'], 'log': str(directory / LOG_NAME),
                        'retained_only_in_exchange': sum(item['kind'] != 'message'
                            for turn in bundle['turns'] for item in turn['items'])})
    result = {'workspace': str(cwd), 'sessions': results, 'native_sidebar_verified': False,
              'attachments': prepared['attachments'], 'project_files': prepared['files']}
    agent_rehome.dump(cwd / '.rehome/restore-dsh.json', result)
    return result


def register(cwd, home, backup):
    """Bind only the sessions named in the restore receipt with DSH stopped."""
    cwd, home = cwd.resolve(), home.resolve()
    receipt = json.loads((cwd / '.rehome/restore-dsh.json').read_text(encoding='utf-8'))
    if Path(receipt['workspace']).resolve() != cwd or not receipt['sessions']:
        raise ValueError('Restore receipt does not identify this workspace')
    ids, title_cache = [], {}
    for entry in receipt['sessions']:
        sid = entry['id']
        if not re.fullmatch(r'session-[a-f0-9-]{36}', sid):
            raise ValueError('Invalid restored DSH session id')
        log = exchange.safe(home, f'sessions/{project_key(str(cwd))}/{sid}/{LOG_NAME}')
        with open_log(log, 'rt') as stream:
            header = json.loads(stream.readline())
            title = json.loads(stream.readline())
        if (header.get('id') != sid or header.get('cwd') != str(cwd) or header.get('version') != 4
                or header.get('isSeeded') is not False or header.get('delegationDepth') != 0):
            raise ValueError('Restored DSH session header does not match the workspace')
        if title.get('type') == 'session/title' and title['data']['title'] == entry['title']:
            title_cache[sid] = {'version': 7, 'record': {
                'identity': {'formatVersion': 4, 'createdAt': header['createdAt'], 'cwd': str(cwd),
                             'isSeeded': False, 'inheritedEventCount': 0},
                'rows': {'title': {'ver': 1, 'seq': title['seq'], 'val': entry['title']}},
            }}
        ids.append(sid)
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate restored DSH session id')
    path = exchange.safe(home, 'storages/workspace.json')
    original = path.read_bytes()
    db = json.loads(original)
    if db.get('unit') != {'name': 'workspace', 'version': 2} or db['global'].get('initialized') is not True or db['global'].get('pendingMutation'):
        raise ValueError('Expected an initialized, idle DSH workspace registry version 2')
    workspaces = db['tables']['workspaces']
    order = db['global']['workspaceIds']
    if len(order) != len(set(order)) or set(order) != set(workspaces):
        raise ValueError('DSH workspace registry order is inconsistent')
    matches = [(key, entry) for key, entry in workspaces.items() if Path(entry['path']).resolve() == cwd]
    if len(matches) > 1:
        raise ValueError('DSH already has multiple registrations for this workspace')
    if matches:
        key, entry = matches[0]
    else:
        key = str(uuid.uuid4())
        entry = {'path': str(cwd), 'title': cwd.name, 'sessionIds': [], 'createdAt': agent_rehome.now()}
        workspaces[key] = entry
        order.insert(0, key)
    if any(set(ids).intersection(other['sessionIds']) for k, other in workspaces.items() if key != k):
        raise ValueError('A restored DSH session already belongs to another workspace')
    additions = [sid for sid in ids if sid not in entry['sessionIds']]
    if not additions:
        return {'registered': 0, 'sessions': ids}
    entry['sessionIds'].extend(additions)
    entry['updatedAt'] = agent_rehome.now()
    with backup.open('xb') as stream:
        stream.write(original)
    cache_dir = exchange.safe(home, 'storages/session_projcache/sessions')
    if cache_dir.is_dir():
        for sid in additions:
            if sid not in title_cache:
                continue
            serialized = json.dumps(title_cache[sid], ensure_ascii=False).encode('utf-8')
            try:
                write_checked(exchange.safe(cache_dir, sid + '.json'), [serialized], measure([serialized]))
            except FileExistsError:
                pass
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temp_path = Path(temporary.name)
    try:
        temp_path.write_text(json.dumps(db, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if path.read_bytes() != original:
            raise ValueError('DSH workspace registry changed during registration')
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
    return {'registered': len(additions), 'sessions': ids, 'backup': str(backup.resolve())}


def main():
    configure()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path, nargs='?')
    parser.add_argument('--cwd', type=Path)
    parser.add_argument('--dsh-home', required=True, type=Path)
    parser.add_argument('--register-offline', metavar='BACKUP', type=Path,
                        help='Register an existing restore only while the DSH host is stopped')
    parser.add_argument('--probe', action='store_true', help='Inspect the selected data root without writes')
    args = parser.parse_args()
    if sum((args.package is not None, args.register_offline is not None, args.probe)) != 1:
        parser.error('provide exactly one of a portable package, --register-offline BACKUP, or --probe')
    if not args.probe and args.cwd is None:
        parser.error('--cwd is required for restore or registration')
    try:
        if args.probe:
            result = probe(args.dsh_home)
        elif args.register_offline:
            result = register(args.cwd, args.dsh_home, args.register_offline)
        else:
            result = restore(args.package, args.cwd, args.dsh_home)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
