"""Isolated DSH v4 frame, sidebar registry and portable round-trip regression."""
import base64
import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

import agent_rehome
import dsh_native
import dsh_source
import exchange
import project_rehome
import workbuddy_native
import workbuddy_receive
from project_io import measure


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jCesAAAAASUVORK5CYII=')
STAMP = '2026-11-21T01:00:00Z'


def asset(root, path, data):
    dest = root / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    hash_value, size = measure([data])
    return {'path': path, 'sha256': hash_value, 'bytes': size}


class DeepSeekExchangeTest(unittest.TestCase):
    def test_project_key_uses_utf16(self):
        self.assertEqual(dsh_source.project_key(r'C:\迁移😀\x y'), '--C-~8FC1~79FB~D83D~DE00-x~0020y--')

    def test_project_native_roundtrip(self):
        try:
            zstd = dsh_source.zstd_module()
        except ValueError as error:
            self.skipTest(str(error))
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp).resolve()
            home, package, cwd = (root / name for name in ('storage', 'exchange', '恢复项目'))
            (home / 'sessions').mkdir(parents=True)
            (home / 'storages/session_projcache/sessions').mkdir(parents=True)
            registry = home / 'storages/workspace.json'
            registry.write_text(json.dumps({'unit': {'name': 'workspace', 'version': 2},
                'global': {'initialized': True, 'workspaceIds': [], 'archivedSessionIds': [], 'pinnedSessionIds': []},
                'tables': {'workspaces': {}}}), encoding='utf-8')
            self.assertEqual(dsh_native.probe(home)['workspace_registry'], 'initialized-v2')
            self.assertFalse(dsh_native.probe(home)['v4_log_name_seen'])
            project_file = asset(package, 'project/README.md', b'# Example\n')
            note = asset(package, 'attachments/f.txt', b'example attachment')
            picture = asset(package, 'attachments/f.png', PNG)
            attachments = [{**note, 'name': '说明.txt', 'image': False},
                           {**picture, 'name': '图片.png', 'image': True, 'mime': 'image/png'}]
            b = {'schema': 'agent-transcript/v1',
                 'source': {'agent': 'codex', 'session_id': str(uuid.uuid4())},
                 'title': '试验聊天', 'project': {}, 'losses': [], 'turns': [{
                     'user': {'ts': STAMP, 'text': 'remember the test token', 'attachments': attachments},
                     'items': [{'kind': 'message', 'ts': STAMP, 'text': 'token remembered'}],
                 }, {
                     'user': {'ts': STAMP, 'text': 'second turn with the same timestamp'},
                     'items': [{'kind': 'message', 'ts': STAMP, 'text': 'second reply'}],
                 }]}
            exchange.write_project(package, {'source_agent': 'codex', 'created_at': STAMP,
                'source_project': str(root), 'files': [project_file], 'attachments': [note, picture],
                'conversations': [b]})
            result = dsh_native.restore(package, cwd, home)
            self.assertTrue(dsh_native.probe(home)['v4_log_name_seen'])
            self.assertEqual(dsh_native.probe(home)['runtime_acceptance'], 'unverified')
            chat, = result['sessions']
            log = Path(chat['log'])
            decoder = (zstd.ZstdDecompressor() if hasattr(zstd, 'CompressionParameter')
                       else zstd.ZstdDecompressor().decompressobj())
            first = decoder.decompress(log.read_bytes())
            self.assertEqual(first.count(b'\n'), 1)
            self.assertTrue(decoder.unused_data)
            header, *events = dsh_source.read_log(log)
            self.assertEqual(header['cwd'], str(cwd))
            self.assertEqual([event['seq'] for event in events], list(range(len(events))))
            self.assertEqual([event['data']['stream'] for event in events
                              if event['type'] == 'assistant/message'], [[], []])
            backup = root / 'registry-before.json'
            self.assertEqual(dsh_native.register(cwd, home, backup)['registered'], 1)
            self.assertEqual(dsh_native.register(cwd, home, root / 'unused.json')['registered'], 0)
            self.assertFalse(json.loads(backup.read_text())['global']['workspaceIds'])
            restored, = json.loads(registry.read_text(encoding='utf-8'))['tables']['workspaces'].values()
            self.assertEqual(restored['sessionIds'], [chat['id']])
            cache = home / f'storages/session_projcache/sessions/{chat["id"]}.json'
            self.assertEqual(json.loads(cache.read_text(encoding='utf-8'))['record']['rows']['title']['val'], b['title'])
            packed = root / 'returned'
            project_rehome.pack('dsh', cwd, packed, home)
            reloaded = exchange.read_project(packed)
            self.assertEqual([item['path'] for item in reloaded['files']], ['project/README.md'])
            self.assertEqual({item['sha256'] for item in reloaded['attachments']}, {note['sha256'], picture['sha256']})
            turn, second = reloaded['conversations'][0]['turns']
            self.assertFalse(second['user']['attachments'])
            self.assertEqual(turn['user']['text'], 'remember the test token')
            self.assertIn('说明.txt', {item['name'] for item in turn['user']['attachments']})
            self.assertEqual(turn['items'][0]['text'], 'token remembered')

            codex_home = root / 'codex-home'
            codex_home.mkdir()
            with contextlib.closing(sqlite3.connect(codex_home / 'state_5.sqlite')) as db:
                db.executescript((Path(__file__).parent / 'fixtures/codex_schema.sql').read_text(encoding='utf-8'))
            claude_registry = root / 'claude-registry'
            claude_registry.mkdir()
            for agent, target_home in [('codex', codex_home), ('claude', root / 'claude-home')]:
                out = project_rehome.restore(packed, root / f'{agent}-project', agent, target_home,
                    agent == 'codex', model='fixture', claude_model='fixture', claude_version='0.0.0-test',
                    desktop_registry=claude_registry if agent == 'claude' else None)
                self.assertEqual(len(out['sessions']), 1)
                self.assertEqual(out['sessions'][0]['attachments'], 2)
            claude_return = root / 'claude-return'
            project_rehome.pack('claude', root / 'claude-project', claude_return, root / 'claude-home')
            claude_turn, claude_second = exchange.read_project(claude_return)['conversations'][0]['turns']
            self.assertEqual({item['sha256'] for item in claude_turn['user']['attachments']},
                             {note['sha256'], picture['sha256']})
            self.assertFalse(claude_second['user']['attachments'])
            buddy = root / 'workbuddy-project'
            prepared = workbuddy_receive.prepare(packed, buddy)
            prepared_chat = json.loads((buddy / prepared['chats'][0]['path']).read_text(encoding='utf-8'))
            rows, omitted = workbuddy_native.project_history(prepared_chat, str(buddy), chat['id'][8:],
                                                            blob_root=root / 'workbuddy-blobs')
            self.assertEqual(len(rows), 4)
            self.assertFalse(omitted)


if __name__ == '__main__':
    unittest.main(argv=[__file__])
