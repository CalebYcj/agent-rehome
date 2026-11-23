"""Read WorkBuddy desktop histories into the portable conversation format."""
import datetime as dt
import html
import json
import re
import uuid
from pathlib import Path

import exchange
from platform_paths import path_key, windows_path

REMINDER = re.compile(r'<system-reminder\b[^>]*>.*?</system-reminder>', re.S)
QUERY = re.compile(r'<user_query>(.*?)</user_query>', re.S)
FILES = re.compile(r'<attached_files>(.*?)</attached_files>', re.S)
FILE_PATH = re.compile(r'<file\s+path="([^"]+)"')
FILE_REFERENCE = re.compile(r'^\s*@"[^"]+"')


def timestamp(row):
    return dt.datetime.fromtimestamp(row['timestamp'] / 1000, dt.timezone.utc).isoformat()


def text_value(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

def tool_images(output):
    if isinstance(output, dict) and output.get('type') == 'text':
        try:
            output = json.loads(output.get('text', ''))
        except (TypeError, ValueError):
            return ()
    if not isinstance(output, list):
        return ()
    return (block for block in output if isinstance(block, dict)
            and block.get('type') == 'image_blob_ref')


def belongs_to(rows, project):
    first = next((row for row in rows if row.get('type') == 'message'
                  and row.get('role') == 'user' and row.get('cwd')), None)
    return bool(first and path_key(first['cwd']) == path_key(project))


def project_slug(project):
    source_path = re.sub(r'^([a-zA-Z]):(?=[\\/])', r'\1', str(project))
    if not windows_path(project):
        source_path = source_path.lstrip('/')
    return re.sub(r'[^a-zA-Z0-9_.-]', '-', source_path)


def project_sessions(home, project, read):
    files = []
    # Distinct paths can share the same WorkBuddy folder encoding.
    directory_key = project_slug(project).casefold()
    for folder in sorted((home / 'projects').iterdir()):
        if folder.name.casefold() == directory_key:
            files.extend(path for path in sorted(folder.glob('*.jsonl'))
                         if belongs_to(read(path), project))
    return files


def user_text(blocks):
    visible, attachments, stripped = [], [], False
    image_names = sorted({block['original_filename'] for block in blocks
                          if block.get('type') == 'image_blob_ref'
                          and block.get('original_filename')}, key=len, reverse=True)
    image_reference = (re.compile(r'^\s*@image#\d+:(?:' + '|'.join(map(re.escape,image_names)) + ')')
                       if image_names else None)
    for block in blocks:
        kind = block.get('type')
        if kind == 'image_blob_ref':
            attachments.append({'path': block.get('blob_path'), 'name': block.get('original_filename'),
                                'image': True, 'mime': block.get('mime')})
        elif kind == 'input_text':
            value = block.get('text', '')
            if value.startswith('<image_local_path>'):
                stripped = True
                continue
            query = QUERY.search(value) if REMINDER.match(value) else None
            if query:
                for reminder in REMINDER.finditer(value[:query.start()]):
                    for file_list in FILES.findall(reminder[0]):
                        attachments.extend({'path': html.unescape(path), 'image': False}
                                           for path in FILE_PATH.findall(file_list))
                value = query[1]
                while match := (FILE_REFERENCE.match(value)
                                or (image_reference and image_reference.match(value))):
                    value = value[match.end():]
                stripped = True
            elif REMINDER.match(value):
                value = REMINDER.sub('', value)
                stripped = True
            if value.strip():
                visible.append(value.strip())
    return '\n'.join(visible), attachments, stripped


def export(path, rows, project, attach):
    if not belongs_to(rows, project):
        raise ValueError('WorkBuddy session cwd does not match the source project')
    refs = exchange.raw_refs(path, rows)
    messages = [row for row in rows if row.get('type') == 'message']
    session_id = messages[0]['sessionId']
    uuid.UUID(session_id)
    if any(row.get('sessionId') != session_id for row in messages):
        raise ValueError('Mixed WorkBuddy session IDs in one source file')
    title = next((row['aiTitle'] for row in reversed(rows) if row.get('aiTitle')), None)
    turns, losses, calls = [], [], {}
    branchable = {'message', 'reasoning', 'function_call', 'function_call_result'}
    events = [(i, row) for i, row in enumerate(rows) if row.get('type') in branchable]
    indexed = {row['id']: (i, row) for i, row in events if row.get('id')}
    lineage = set()
    if events and len(indexed) == len(events) and any(row.get('parentId') for _, row in events):
        i, node = events[-1]
        while i not in lineage:
            lineage.add(i)
            parent = indexed.get(node.get('parentId'))
            if not parent:
                break
            i, node = parent
        if node.get('parentId') or not any(index in lineage and row.get('role') == 'user'
                                          for index, row in events):
            raise ValueError('WorkBuddy history has a missing parent or cycle')

    def loss(i, kind, reason='unsupported_by_target'):
        losses.append({'raw_ref': refs[i], 'kind': kind, 'reason': reason, 'action': 'dropped'})

    for i, row in enumerate(rows):
        kind = row.get('type')
        if lineage and kind in branchable and i not in lineage:
            loss(i, 'inactive_branch')
            continue
        if kind == 'message' and row.get('role') == 'user':
            blocks = row.get('content', [])
            text, attachments, stripped = user_text(blocks)
            if stripped:
                loss(i, 'workbuddy_context', 'harness_injected')
            for block in blocks:
                if block.get('type') not in ('input_text', 'image_blob_ref'):
                    loss(i, 'unknown_user_block')
            assets = []
            for item in attachments:
                asset, reason = attach(item)
                if asset:
                    assets.append(asset)
                else:
                    loss(i, 'image_attachment' if item['image'] else 'file_attachment', reason)
            if text or assets:
                turns.append({'user': {'ts': timestamp(row), 'text': text or '[附件]',
                                       'attachments': assets, '_raw_ref': refs[i]}, 'items': []})
        elif kind == 'message' and row.get('role') == 'assistant' and turns:
            for block in row.get('content', []):
                if block.get('type') == 'output_text' and block.get('text'):
                    turns[-1]['items'].append({'kind': 'message', 'ts': timestamp(row),
                                              'text': block['text'], '_raw_ref': refs[i]})
                else:
                    loss(i, 'unknown_assistant_block')
        elif kind == 'function_call' and turns:
            args = row.get('arguments', {})
            try:
                parsed = json.loads(args) if isinstance(args, str) else args
            except ValueError:
                parsed = None
            if not isinstance(parsed, dict):
                loss(i, 'tool_arguments')
                parsed = {}
            item = {'kind': 'tool', 'ts': timestamp(row), 'name': row['name'], 'args': parsed,
                    'input': text_value(args), '_raw_ref': refs[i]}
            turns[-1]['items'].append(item)
            calls.setdefault(row['callId'], []).append((i, turns[-1], item))
        elif kind == 'function_call_result' and calls.get(row.get('callId')):
            _, turn, item = calls[row['callId']].pop(0)
            status = row.get('status')
            result = row.get('output')
            item.update(output=text_value(result), is_error=status in ('incomplete', 'failed', 'error'),
                        status={'completed': 'completed', 'incomplete': 'failed', 'failed': 'failed',
                                'error': 'failed'}.get(status, 'unknown'), completed_ts=timestamp(row))
            if item['name'] == 'ViewImage':
                for block in tool_images(result):
                    asset, reason = attach({'path': block.get('blob_path'), 'image': True,
                                            'mime': block.get('mime'), 'mode': 'tool-result'})
                    if not asset:
                        loss(i, 'tool_image_attachment', reason)
                        continue
                    assets = turn['user']['attachments']
                    if not any(existing['sha256'] == asset['sha256'] for existing in assets):
                        assets.append(asset)
        elif kind not in ('ai-title', 'session-meta'):
            loss(i, str(kind or 'unknown'))
    for remaining in calls.values():
        for i, turn, item in remaining:
            turn['items'].remove(item)
            loss(i, 'unpaired_tool_call')
    if not turns:
        raise ValueError('WorkBuddy history has no visible conversation')
    return {'schema': 'agent-transcript/v1', 'source': {'agent': 'workbuddy', 'session_id': session_id},
            'title': title or turns[0]['user']['text'][:60], 'project': {'cwd': str(project)},
            'turns': turns, 'losses': losses}
