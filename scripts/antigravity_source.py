"""Read saved main-thread Antigravity Desktop projects into the portable format."""
from contextlib import closing, nullcontext
from datetime import datetime, timezone
from itertools import chain
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
from urllib.parse import unquote, urlsplit
import uuid

from exchange import safe as contained_path
from platform_paths import path_key, portable_name, sqlite_read_uri
from project_io import linked


LOG = '.system_generated/logs/transcript.jsonl'
IDLE = 'CASCADE_RUN_STATUS_IDLE'
USER_REQUEST_START = '<USER_REQUEST>\n'
USER_REQUEST_END = '\n</USER_REQUEST>'


def source_file(home, relative):
    resolved = contained_path(home, relative)
    candidate = Path(home).resolve()
    for part in PurePosixPath(relative).parts:
        candidate /= part
        if (candidate.exists() or candidate.is_symlink()) and linked(candidate):
            raise ValueError('Linked Antigravity source entry: ' + relative)
    return resolved


def user_request(content):
    if not isinstance(content, str) or not content.startswith(USER_REQUEST_START):
        raise ValueError('Unrecognized Antigravity user message wrapper')
    text, close, tail = content[len(USER_REQUEST_START):].rpartition(USER_REQUEST_END)
    if not close or (tail and not re.match(r'\n<[A-Z][A-Z_]+>', tail)):
        raise ValueError('Unrecognized Antigravity user message wrapper')
    return text, bool(tail)


def local_path(uri):
    if uri.startswith('file://'):
        parsed = urlsplit(uri)
        if parsed.query or parsed.fragment:
            raise ValueError('Invalid Antigravity file URI')
        uri = unquote(parsed.path, errors='strict')
        if parsed.netloc and parsed.netloc.lower() != 'localhost':
            uri = '//' + parsed.netloc + uri
        elif re.match(r'^/[A-Za-z]:/', uri):
            uri = uri[1:]
    return uri.replace('\\', '/')


def project_sessions(home, roots):
    index = source_file(home, 'conversation_summaries.db')
    if not index.is_file():
        raise ValueError('Antigravity Desktop conversation index is missing; check --source-home')
    roots = {path_key(root) for root in roots}
    sessions = {}
    project_ids = set()
    with closing(sqlite3.connect(sqlite_read_uri(index), uri=True)) as db:
        entries = db.execute('''SELECT conversation_id, project_id, workspace_uris, status, not_fully_idle, step_count
            FROM conversation_summaries WHERE COALESCE(project_id, '') != ''
            AND COALESCE(parent_conversation_id, '') = '' ORDER BY conversation_id''')
        for sid, project_id, workspaces, status, running, count in entries:
            paths = json.loads(workspaces or '[]')
            if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
                raise ValueError('Unsupported Antigravity workspace list')
            paths = {path_key(local_path(path)) for path in paths}
            if not paths & roots:
                continue
            if paths - roots:
                raise ValueError('Antigravity conversation has multiple workspace folders; single-folder export only')
            project_ids.add(project_id)
            if len(project_ids) > 1:
                raise ValueError('Multiple Antigravity projects share this workspace folder')
            if str(uuid.UUID(sid)) != sid:
                raise ValueError('Invalid Antigravity conversation ID')
            log = source_file(home, f'brain/{sid}/{LOG}')
            title, = db.execute('SELECT title FROM conversation_summaries WHERE conversation_id=?', (sid,)).fetchone()
            sessions[log] = (sid, title, count, running or status != IDLE)
    if not sessions:
        raise ValueError('No Antigravity Desktop chats under this workspace')
    return sessions


def varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise ValueError('Invalid Antigravity protobuf varint')


def protobuf_fields(data):
    offset = 0
    while offset < len(data):
        tag, offset = varint(data, offset)
        wire = tag & 7
        if wire == 0:
            value, offset = varint(data, offset)
            yield tag >> 3, value
            continue
        if wire == 2:
            size, offset = varint(data, offset)
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
        else:
            raise ValueError('Unsupported Antigravity protobuf wire type')
        end = offset + size
        if end > len(data):
            raise ValueError('Truncated Antigravity protobuf field')
        if wire == 2:
            yield tag >> 3, data[offset:end]
        offset = end


def wire_fields(data, number):
    for tag, value in protobuf_fields(data):
        if tag == number and isinstance(value, bytes):
            yield value


def native_prefix(db, count, sid):
    """Recover the prefix that can predate the runtime's first transcript log."""
    if db is None or db.execute('PRAGMA user_version').fetchone() != (1,):
        raise ValueError('Antigravity transcript prefix requires a version-1 native database: ' + sid)
    rows = db.execute('''SELECT idx,step_type,status,step_format,metadata,step_payload
                         FROM steps WHERE idx<? ORDER BY idx''', (count,))
    seen = 0
    for idx, kind, status, encoding, metadata, payload in rows:
        if idx != seen or encoding != 0 or not isinstance(payload, bytes):
            raise ValueError('Unsupported Antigravity native transcript prefix: ' + sid)
        seen += 1
        entry = {'step_index': idx, 'type': f'NATIVE_STEP_{kind}', 'status': 'DONE' if status == 3 else 'OTHER'}
        if status != 3 or kind not in (14, 15):
            yield entry
            continue
        try:
            meta = dict(protobuf_fields(metadata or b''))
            fields = dict(protobuf_fields(meta[1]))
            seconds = fields.get(1, 0)
            if seconds >= 1 << 63:
                seconds -= 1 << 64
            created = datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=fields.get(2, 0) // 1000)
            entry['created_at'] = created.isoformat()
            if kind == 14 and meta.get(3) == 4:
                user_payload = next(wire_fields(payload, 19))
                user = dict(protobuf_fields(user_payload))
                visible = user[2].decode('utf-8')
                entry['type'], entry['source'] = 'USER_INPUT', 'USER_EXPLICIT'
                entry['content'] = USER_REQUEST_START + visible + USER_REQUEST_END
                entry['media'] = []
                for blob in wire_fields(user_payload, 9):
                    attachment = dict(protobuf_fields(blob))
                    entry['media'].append({'mime_type': attachment.get(1, b'').decode('utf-8'),
                                           'uri': attachment.get(5, b'').decode('utf-8')})
            elif kind == 15 and meta.get(3) == 2:
                planner = dict(protobuf_fields(next(wire_fields(payload, 20))))
                entry['type'], entry['source'] = 'PLANNER_RESPONSE', 'MODEL'
                entry['content'] = (planner.get(8) or planner.get(1, b'')).decode('utf-8')
                entry['thinking'] = bool(planner.get(3) or planner.get(16))
                entry['tool_calls'] = bool(planner.get(7))
        except (IndexError, KeyError, StopIteration, TypeError, ValueError) as error:
            raise ValueError('Unsupported Antigravity native transcript message: ' + sid) from error
        yield entry
    if seen != count:
        raise ValueError('Incomplete Antigravity native transcript prefix: ' + sid)


def transcript_rows(stream, db, sid, count):
    def records():
        for line in stream or ():
            entry = json.loads(line)
            if not line.endswith('\n') or not isinstance(entry, dict) or type(entry.get('step_index')) is not int:
                raise ValueError('Antigravity transcript has an invalid record: ' + sid)
            yield entry

    remaining = records()
    first = next(remaining, None)
    if first is None:
        if db is None or db.execute('SELECT count(*) FROM steps').fetchone() != (count,):
            raise ValueError('Antigravity transcript is unavailable and the saved step count cannot be confirmed: ' + sid)
        yield from native_prefix(db, count, sid)
        return
    if first['step_index'] > 0:
        yield from native_prefix(db, first['step_index'], sid)
    yield from chain((first,), remaining)


def attachment_names(db, index):
    if db is None:
        return {}
    try:
        row = db.execute('SELECT step_payload FROM steps WHERE idx=? AND step_type=14 AND step_format=0', (index,)).fetchone()
        if not row or not isinstance(row[0], bytes):
            return {}
        names = {}
        # Desktop 2.33.1: step.user_input.media.{display_name, stored_uri}.
        for user_input in wire_fields(row[0], 19):
            for media in wire_fields(user_input, 9):
                name = next(wire_fields(media, 4), b'').decode('utf-8')
                uri = next(wire_fields(media, 5), b'').decode('utf-8')
                if name and uri:
                    names[local_path(uri)] = name
        return names
    except (sqlite3.OperationalError, ValueError, IndexError):
        # The public transcript still provides the historical bytes and stored name.
        return {}


def upload(home, sid, uri):
    path = PurePosixPath(uri)
    if path.parts[-4:-1] != ('brain', sid, '.user_uploaded') or '..' in path.parts:
        raise ValueError('Attachment is outside its Antigravity conversation upload directory')
    if not re.fullmatch(r'media_[A-Za-z0-9_-]+\.[A-Za-z0-9]{1,16}', path.name):
        raise ValueError('Invalid Antigravity upload filename')
    return source_file(home, f'brain/{sid}/.user_uploaded/{path.name}')


def export(log, session, project, home, attach):
    sid, title, count, running = session
    if running:
        raise ValueError('Antigravity conversation is still running; retry after completion: ' + sid)
    before = log.stat() if log.is_file() else None
    db_path = source_file(home, f'conversations/{sid}.db')
    db = sqlite3.connect(sqlite_read_uri(db_path), uri=True) if db_path.is_file() else None
    turns, losses = [], []

    def loss(index, kind, reason='unsupported_by_target', action='dropped', part=''):
        losses.append({'event': f'antigravity/{index}/{kind}{part}', 'kind': kind,
                       'reason': reason, 'action': action})

    seen = 0
    with closing(db) if db is not None else nullcontext():
        with log.open(encoding='utf-8') if before is not None else nullcontext() as stream:
            for index, entry in enumerate(transcript_rows(stream, db, sid, count)):
                if entry['step_index'] != index:
                    raise ValueError('Antigravity transcript is incomplete or out of order: ' + sid)
                seen += 1
                kind, source = entry.get('type'), entry.get('source')
                content = entry.get('content', '')
                if entry.get('status') != 'DONE':
                    loss(index, 'incomplete_step')
                elif kind == 'USER_INPUT' and source == 'USER_EXPLICIT':
                    request, has_injected_context = user_request(content)
                    if has_injected_context:
                        loss(index, 'antigravity_injected_context', 'harness_injected')
                    assets = []
                    names = attachment_names(db, index) if entry.get('media') else {}
                    for number, media in enumerate(entry.get('media') or []):
                        uri, mime = media.get('uri'), media.get('mime_type') or ''
                        image = mime.startswith('image/')
                        asset_kind = 'image_attachment' if image else 'file_attachment'
                        try:
                            original = local_path(uri or '')
                            path = upload(home, sid, original)
                        except ValueError:
                            loss(index, asset_kind, 'sensitive', part=f'/{number}')
                            continue
                        name = names.get(original)
                        asset, reason = attach({'path': str(path), 'name': portable_name(name) if name else path.name,
                                                'mime': mime, 'image': image, 'mode': 'historical-upload'})
                        if asset:
                            assets.append(asset)
                            if not name:
                                loss(index, 'antigravity_attachment_display_name', 'missing_file',
                                     action='textified', part=f'/{number}')
                        else:
                            loss(index, asset_kind, reason, part=f'/{number}')
                    turns.append({'user': {'ts': entry['created_at'], 'text': request or '[附件]',
                                           'attachments': assets}, 'items': []})
                elif kind == 'PLANNER_RESPONSE' and source == 'MODEL' and turns:
                    if content:
                        turns[-1]['items'].append({'kind': 'message', 'ts': entry['created_at'], 'text': content})
                    if entry.get('thinking'):
                        loss(index, 'antigravity_reasoning')
                    if entry.get('tool_calls'):
                        loss(index, 'antigravity_tool_calls')
                else:
                    loss(index, 'antigravity_' + str(kind), 'harness_injected' if kind == 'USER_INPUT' else 'unsupported_by_target')
    after = log.stat() if log.is_file() else None
    log_changed = (before is None) != (after is None)
    if before is not None and after is not None:
        log_changed = (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
    if seen != count or log_changed:
        raise ValueError('Antigravity transcript does not match the saved step count; retry from a stable source: ' + sid)
    if not turns:
        raise ValueError('Antigravity transcript has no visible user messages: ' + sid)
    return {'schema': 'agent-transcript/v1', 'source': {'agent': 'antigravity', 'session_id': sid},
            'title': title or turns[0]['user']['text'][:60], 'project': {'cwd': str(project)},
            'turns': turns, 'losses': losses}
