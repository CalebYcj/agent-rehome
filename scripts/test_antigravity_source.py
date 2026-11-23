"""Exercise Antigravity project discovery and conversion in a disposable data root."""
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
import exchange
import antigravity_stage
import project_rehome


STAMP = '2026-11-21T07:37:57Z'


def field(number, value):
    data = value.encode() if isinstance(value, str) else value
    size = len(data)
    length = bytes([size]) if size < 128 else bytes([size % 128 + 128, size // 128])
    tag = number * 8 + 2
    return (bytes([tag]) if tag < 128 else bytes([tag % 128 + 128, tag // 128])) + length + data


class AntigravitySourceTest(unittest.TestCase):
    def test_project_conversion_preserves_only_the_selected_chats(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            root = Path(directory).resolve()
            home, project, out = (root / name for name in ('storage', '项目 A', 'portable'))
            home.mkdir()
            project.mkdir()
            (home / 'conversations').mkdir()
            (project / 'README.md').write_text('# sample', encoding='utf-8')
            (project / '.agent').mkdir()
            (project / '.agent/hooks.json').write_text('{}', encoding='utf-8')
            first, second, unrelated, nested = [str(uuid.uuid4()) for _ in range(4)]
            with closing(sqlite3.connect(home / 'conversation_summaries.db')) as db, db:
                db.execute('''CREATE TABLE conversation_summaries (
                    conversation_id TEXT PRIMARY KEY, title TEXT, step_count INTEGER,
                    workspace_uris TEXT, status TEXT, project_id TEXT,
                    parent_conversation_id TEXT, not_fully_idle INTEGER)''')
                db.executemany('INSERT INTO conversation_summaries VALUES (?,?,?,?,?,?,?,?)', [
                    (sid, title, count, json.dumps([workspace.as_uri()]), 'CASCADE_RUN_STATUS_IDLE',
                     'project-id', parent, 0)
                    for sid, title, count, workspace, parent in (
                        (first, '带附件', 5, project, ''), (second, '第二条', 2, project, ''),
                        (unrelated, '旁边的项目', 2, root / 'unrelated', ''),
                        (nested, '子 Agent', 1, project, first))])
            foreign = f'/old-profile/.gemini/antigravity/brain/{first}/.user_uploaded/media_123_a1b2.txt'
            image_uri = f'/old-profile/.gemini/antigravity/brain/{first}/.user_uploaded/media_456_b2c3.png'
            note = home / 'brain' / first / '.user_uploaded' / 'media_123_a1b2.txt'
            note.parent.mkdir(parents=True)
            note.write_bytes(b'historical txt')
            (note.parent / 'media_456_b2c3.png').write_bytes(b'historical png bytes')
            with closing(sqlite3.connect(home / 'conversations' / f'{first}.db')) as db, db:
                db.execute('CREATE TABLE steps (idx INTEGER, step_type INTEGER, step_format INTEGER, step_payload BLOB)')
                items = (field(9, field(4, '合成 文档.txt') + field(5, foreign))
                         + field(9, field(4, '合成 图片.png') + field(5, image_uri)))
                db.execute('INSERT INTO steps VALUES (0,14,0,?)', (field(19, field(2, '首轮内容') + items),))

            def row(index, typ, source, content, **extra):
                return dict(step_index=index, type=typ, source=source, created_at=STAMP,
                            content=content, status='DONE', **extra)

            def write(sid, rows):
                path = home / 'brain' / sid / '.system_generated/logs/transcript.jsonl'
                path.parent.mkdir(parents=True)
                path.write_text(''.join(json.dumps(x) + '\n' for x in rows), encoding='utf-8')

            write(first, [row(0, 'USER_INPUT', 'USER_EXPLICIT',
                              '<USER_REQUEST>\n首轮内容\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\n隐藏正文\n</ADDITIONAL_METADATA>',
                              media=[{'uri': foreign, 'mime_type': 'text/plain'},
                                     {'uri': image_uri, 'mime_type': 'image/png'},
                                     {'uri': str(project / 'README.md'), 'mime_type': 'text/plain'}]),
                          row(1, 'PLANNER_RESPONSE', 'MODEL', '第一条回复', thinking='内部推理'),
                          row(2, 'RUN_COMMAND', 'MODEL', 'hidden tool body'),
                          row(3, 'USER_INPUT', 'USER_EXPLICIT', '<USER_REQUEST>\n次轮内容\n</USER_REQUEST>'),
                          row(4, 'PLANNER_RESPONSE', 'MODEL', '第二条回复')])
            write(second, [row(0, 'USER_INPUT', 'USER_EXPLICIT', '<USER_REQUEST>\n另一个问题\n</USER_REQUEST>'),
                           row(1, 'PLANNER_RESPONSE', 'MODEL', '另一个答案')])
            project_rehome.pack('antigravity', project, out, home)
            result = exchange.read_project(out)
            self.assertEqual(result['source_agent'], 'antigravity')
            self.assertEqual({chat['title'] for chat in result['conversations']}, {'带附件', '第二条'})
            self.assertEqual([f['path'] for f in result['files']], ['project/README.md'])
            chat = next(chat for chat in result['conversations'] if chat['title'] == '带附件')
            self.assertEqual([turn['user']['text'] for turn in chat['turns']], ['首轮内容', '次轮内容'])
            self.assertEqual([turn['items'][0]['text'] for turn in chat['turns']], ['第一条回复', '第二条回复'])
            attachments = chat['turns'][0]['user']['attachments']
            self.assertEqual([item['name'] for item in attachments], ['合成 文档.txt', '合成 图片.png'])
            self.assertEqual([item['image'] for item in attachments], [False, True])
            self.assertEqual((out / attachments[0]['path']).read_bytes(), b'historical txt')
            self.assertEqual((out / attachments[1]['path']).read_bytes(), b'historical png bytes')
            self.assertIn(('file_attachment', 'sensitive'),
                          {(loss['kind'], loss['reason']) for loss in chat['losses']})
            self.assertNotIn('内部推理', json.dumps(chat, ensure_ascii=False))
            self.assertNotIn('隐藏正文', json.dumps(chat, ensure_ascii=False))
            self.assertNotIn('hidden tool body', json.dumps(chat, ensure_ascii=False))

            workspace, profile = root / 'new-project', root / 'isolated-antigravity'
            staged = antigravity_stage.stage(out, workspace, profile)
            self.assertFalse(staged['native_sidebar_verified'])
            self.assertEqual({s['title'] for s in staged['sessions']}, {'带附件', '第二条'})
            project_def = staged['project_registration']['project']
            self.assertEqual(project_def['projectResources']['resources'][0]['folderUri'],
                             antigravity_stage.workspace_uri(workspace))
            self.assertEqual({c['conversationId'] for c in project_def['projectConversations']['conversations']},
                             {s['id'] for s in staged['sessions']})
            restored = next(s for s in staged['sessions'] if s['title'] == '带附件')
            with closing(sqlite3.connect(restored['file'])) as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (1,))
                self.assertEqual([x[0] for x in db.execute('SELECT step_type FROM steps ORDER BY idx')], [14, 15, 14, 15])
            uploaded = profile / 'brain' / restored['id'] / '.user_uploaded'
            self.assertEqual({path.read_bytes() for path in uploaded.iterdir()}, {b'historical png bytes', b'historical txt'})
            with self.assertRaisesRegex(ValueError, 'new staging profile'):
                antigravity_stage.stage(out, root / 'other', profile)
            self.assertFalse((root / 'other').exists())

            desktop = root / 'desktop-gemini/antigravity'
            desktop.mkdir(parents=True)
            project_path = desktop.parent / 'config/projects' / (project_def['id'] + '.json')
            project_path.parent.mkdir(parents=True)
            desktop_project = {key:value for key,value in project_def.items() if key != 'projectConversations'}
            project_path.write_text(json.dumps(desktop_project), encoding='utf-8')
            cache = desktop / 'agyhub_summaries_proto.pb'
            unrelated_cache = field(1, field(1, unrelated) + field(2, field(1, 'Existing title')))
            cache.write_bytes(unrelated_cache)
            index = desktop / 'conversation_summaries.db'
            with closing(sqlite3.connect(index)) as db, db:
                db.execute('''CREATE TABLE conversation_summaries (
                    conversation_id TEXT PRIMARY KEY, title TEXT, preview TEXT, step_count INTEGER,
                    last_modified_time TEXT, workspace_uris TEXT, status TEXT, source TEXT, project_id TEXT,
                    nesting_depth INTEGER, parent_conversation_id TEXT, not_fully_idle INTEGER, killed INTEGER,
                    last_user_input_time TEXT, last_user_input_step_index INTEGER, app_data_dir TEXT, raw_summary BLOB)''')
            self.assertEqual(antigravity_desktop.register(workspace, desktop, desktop_project['id'])['status'], 'ready')
            self.assertFalse((desktop / 'conversations').exists())
            with patch.object(antigravity_desktop, 'runtime_open', return_value=True):
                with self.assertRaisesRegex(ValueError, 'Close the Antigravity Desktop window'):
                    antigravity_desktop.register(workspace, desktop, desktop_project['id'], apply=True)
            self.assertFalse((desktop / 'rehome-backups').exists())
            with patch.object(antigravity_desktop, 'runtime_open', return_value=False):
                desktop_result = antigravity_desktop.register(workspace, desktop, desktop_project['id'], apply=True)
            self.assertEqual(desktop_result['status'], 'registered-offline')
            self.assertTrue(cache.read_bytes().startswith(unrelated_cache))
            self.assertEqual(antigravity_desktop.summary_ids(cache.read_bytes()), {unrelated,*desktop_result['sessions']})
            self.assertEqual(json.loads(project_path.read_text(encoding='utf-8'))['projectConversations'],
                             project_def['projectConversations'])
            self.assertTrue(Path(desktop_result['backup']).is_relative_to(desktop))
            self.assertFalse(desktop_result['desktop_visible'])
            before_resume = root / 'before-resume'
            project_rehome.pack('antigravity', workspace, before_resume, desktop)
            chats_before = exchange.read_project(before_resume)['conversations']
            self.assertEqual(next(b for b in chats_before if b['title'] == '带附件')['turns'][1]['items'][0]['text'], '第二条回复')
            for native in staged['sessions']:
                sid, previous = native['id'], native['steps']
                log = desktop / 'brain' / sid / '.system_generated/logs/transcript.jsonl'
                log.parent.mkdir(parents=True)
                tail = [row(previous, 'USER_INPUT', 'USER_EXPLICIT', '<USER_REQUEST>\n续聊新问题\n</USER_REQUEST>'),
                        row(previous + 1, 'PLANNER_RESPONSE', 'MODEL', '原生追加答复')]
                log.write_text(''.join(json.dumps(event) + '\n' for event in tail), encoding='utf-8')
                with closing(sqlite3.connect(index)) as db, db:
                    db.execute('UPDATE conversation_summaries SET step_count=? WHERE conversation_id=?', (previous + 2,sid))
            returned = root / 'returned'
            project_rehome.pack('antigravity', workspace, returned, desktop)
            again = exchange.read_project(returned)
            loaded = next(item for item in again['conversations'] if item['title'] == '带附件')
            self.assertEqual([turn['user']['text'] for turn in loaded['turns']], ['首轮内容','次轮内容','续聊新问题'])
            self.assertEqual([turn['items'][0]['text'] for turn in loaded['turns']],
                             ['第一条回复','第二条回复','原生追加答复'])
            self.assertEqual([item['name'] for item in loaded['turns'][0]['user']['attachments']],
                             ['合成 文档.txt','合成 图片.png'])
            self.assertEqual([entry['path'] for entry in again['files']], ['project/README.md'])

            with closing(sqlite3.connect(home / 'conversation_summaries.db')) as db, db:
                db.execute('UPDATE conversation_summaries SET not_fully_idle=1 WHERE conversation_id=?', (first,))
            blocked = root / 'blocked'
            with self.assertRaisesRegex(ValueError, 'still running'):
                project_rehome.pack('antigravity', project, blocked, home)
            self.assertFalse(blocked.exists())


if __name__ == '__main__':
    unittest.main(argv=[__file__])
