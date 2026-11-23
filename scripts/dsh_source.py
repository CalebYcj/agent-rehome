"""Read DeepSeek Harness v4 user history into the portable exchange format."""
import datetime as dt
import json
import re
import struct
import uuid
from pathlib import Path

from platform_paths import path_key


LOG_NAME = 'session.v4.jsonl.zstd'
FILE_REFERENCE = re.compile(r'(?<!\S)@"([^"\r\n]+)"')


def zstd_module():
    try:
        from compression import zstd
    except ImportError:
        try:
            import zstandard as zstd
        except ImportError as error:
            raise ValueError('DSH v4 requires Python 3.14 Zstandard or the optional zstandard package') from error
    return zstd


def open_log(path, mode):
    zstd = zstd_module()
    options = {'encoding': 'utf-8', 'newline': '\n'}
    if mode in ('wt', 'at'):
        if hasattr(zstd, 'CompressionParameter'):
            options['options'] = {zstd.CompressionParameter.checksum_flag: 1}
        else:
            options['cctx'] = zstd.ZstdCompressor(write_checksum=True)
    return zstd.open(path, mode, **options)


def project_key(cwd):
    path = re.sub(r'[/\\:]+', '-', cwd).lstrip('-') or 'root'
    units = path.encode('utf-16-le', errors='surrogatepass')
    encoded = []
    for (code,) in struct.iter_unpack('<H', units):
        char = chr(code)
        encoded.append(char if re.fullmatch('[A-Za-z0-9._-]', char) else f'~{code:04X}')
    return '--' + ''.join(encoded)[:251] + '--'


def read_log(path):
    with open_log(path, 'rt') as stream:
        for line in stream:
            if not line.endswith('\n'):
                raise ValueError('DSH session has an incomplete final record')
            yield json.loads(line)


def project_sessions(home, project):
    return sorted((Path(home) / 'sessions' / project_key(str(project))).glob(f'session-*/{LOG_NAME}'))


def export(path, project, home, attach):
    rows = read_log(path)
    header = next(rows, {})
    if (header.get('type') != 'session' or header.get('version') != 4
            or not header.get('cwd') or path_key(header['cwd']) != path_key(str(project))
            or header.get('origin') == 'subagent' or header.get('isSeeded')):
        raise ValueError('Expected a root, unseeded DSH v4 session in the source workspace')
    native_id = header['id']
    if not native_id.startswith('session-') or native_id != path.parent.name:
        raise ValueError('DSH session id does not match its storage directory')
    session_id = str(uuid.UUID(native_id.removeprefix('session-')))
    title, turns, losses = None, [], []

    def loss(event, kind, reason='unsupported_by_target'):
        losses.append({'event': f'dsh/{event["seq"]}/{kind}', 'kind': kind,
                       'reason': reason, 'action': 'dropped'})

    def add_attachment(event, assets, item):
        asset, reason = attach(item)
        if asset:
            assets.append(asset)
            return True
        loss(event, 'image_attachment' if item['image'] else 'file_attachment', reason)
        return False

    for row in rows:
        kind, data = row['type'], row.get('data', {})
        if kind == 'session/title':
            title = data.get('title') or title
        elif kind == 'user/message' and row.get('surfaceOp') == 'append':
            if data.get('source', {}).get('kind') != 'user':
                loss(row, 'dsh_injected_context', 'harness_injected')
                continue
            text, assets = [], []
            for block in data['content']:
                if block['type'] == 'text':
                    original = block['text']
                    standalone_reference = FILE_REFERENCE.fullmatch(original.strip()) is not None

                    def resolve_reference(match):
                        file_name = match.group(1)
                        label = Path(file_name).name
                        copied = add_attachment(row, assets, {
                            'path': file_name, 'name': label, 'image': False,
                        })
                        if not copied:
                            return match.group(0)
                        return '' if standalone_reference else label

                    visible = FILE_REFERENCE.sub(resolve_reference, original)
                    if visible.strip() or visible == original:
                        text.append(visible)
                elif block['type'] == 'image':
                    ref = block['attachment']
                    match = re.fullmatch(r'sha256:([a-f0-9]{64})', ref['attachmentId'])
                    if not match:
                        loss(row, 'image_attachment')
                        continue
                    digest = match.group(1)
                    blob = Path(home) / 'attachments/v1/objects' / digest[:2] / digest
                    add_attachment(row, assets, {'path': str(blob), 'name': ref.get('name'),
                                                'image': True, 'mime': ref['mediaType'],
                                                'expected': (digest, ref['bytes'])})
                else:
                    loss(row, 'dsh_user_block')
            turns.append({'user': {'ts': timestamp(row), 'text': ''.join(text) or '[附件]',
                                   'attachments': assets}, 'items': []})
        elif kind == 'assistant/message' and row.get('surfaceOp') == 'append' and turns:
            blocks = data['message']['content']
            text = ''.join(block['text'] for block in blocks if block['type'] == 'text')
            if text:
                turns[-1]['items'].append({'kind': 'message', 'ts': timestamp(row), 'text': text})
            if any(block['type'] not in ('text', 'tool-call') for block in blocks):
                loss(row, 'dsh_assistant_block')
        elif kind in ('tool/call', 'tool/result', 'compaction/summary'):
            loss(row, kind)
    if not turns:
        raise ValueError('DSH session has no visible user history')
    return {'schema': 'agent-transcript/v1', 'source': {'agent': 'dsh', 'session_id': session_id},
            'title': title or turns[0]['user']['text'][:60], 'project': {'cwd': str(project)},
            'turns': turns, 'losses': losses}


def timestamp(row):
    return dt.datetime.fromtimestamp(row['time'] / 1000, dt.timezone.utc).isoformat(timespec='milliseconds')
