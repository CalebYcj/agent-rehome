"""Batch: list every project, pack them all in one go, restore them all under one root."""
import contextlib, io, json, sqlite3, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import batch_rehome as b, project_rehome as p

TS = '2026-11-01T00:00:00Z'
def crow(typ, kind, **data): return {'timestamp': TS, 'type': typ, 'payload': dict(type=kind, **data)}
def quiet(call):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer): value = call()
    return value, buffer.getvalue()

with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp).resolve()
    # ---- Codex: two projects with history, one whose folder is gone, two folders sharing a name ----
    home = d / 'codex'; home.mkdir()
    projects = [d / 'work' / 'ledger', d / 'work' / 'blog', d / 'other' / 'ledger', d / 'gone']
    for proj in projects[:3]:
        proj.mkdir(parents=True); (proj / 'readme.md').write_text('项目 ' + proj.name, encoding='utf-8')
    with contextlib.closing(sqlite3.connect(home / 'state_5.sqlite')) as db:
        db.executescript((Path(__file__).parent / 'fixtures/codex_schema.sql').read_text(encoding='utf-8'))
        n = 0
        for i, proj in enumerate(projects):
            for k in range(2 if i == 0 else 1):
                n += 1; sid = f'{n:08d}-1234-4567-8123-123456789012'
                path = home / 'sessions' / f'rollout-{sid}.jsonl'; path.parent.mkdir(parents=True, exist_ok=True)
                rows = [crow('session_meta', 'meta', id=sid, cwd=str(proj), cli_version='0.140.0'),
                        crow('event_msg', 'user_message', message=f'{proj.name} 问题 {k}'),
                        crow('event_msg', 'agent_message', message=f'{proj.name} 回答 {k}')]
                path.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in rows) + '\n', encoding='utf-8')
                db.execute('insert into threads(id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,sandbox_policy,approval_mode,archived,cli_version,first_user_message,memory_mode) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (sid, str(path), 1, 1000 + n, 'fixture', 'fixture', str(proj), 't', '{}', 'fixture', 0, 'fixture', 'q', 'enabled'))
        db.commit()
    listed = b.inventory('codex', home)
    assert len(listed) == 4 and listed[0]['project'] == str(projects[3]), 'Newest first'
    by = {x['project']: x for x in listed}
    assert by[str(projects[0])]['sessions'] == 2 and by[str(projects[3])]['exists'] is False
    assert b._names([str(x) for x in projects[:3]]) == ['ledger', 'blog', 'ledger-2']

    # Dry run writes nothing.
    out = d / 'batch'
    record, _ = quiet(lambda: b.batch_pack('codex', out, 'claude', home, dry_run=True))
    assert not out.exists() and record['summary']['planned'] == 3 and record['summary']['skipped'] == 1

    record, text = quiet(lambda: b.batch_pack('codex', out, 'claude', home))
    assert record['summary'] == {'packed': 3, 'planned': 0, 'skipped': 1, 'failed': 0}, record['summary']
    assert json.loads(text.strip().splitlines()[-1])['user_next_steps']['first_message'].endswith(str(out))
    saved = json.loads((out / 'batch.json').read_text(encoding='utf-8'))
    assert saved['native'] is False and 'user_next_steps' not in saved
    names = {x['project']: x for x in saved['projects']}
    assert names[str(projects[0])]['conversations'] == 2
    assert {names[str(projects[0])]['package'], names[str(projects[2])]['package']} == {'ledger', 'ledger-2'}, 'Newest keeps the plain name'
    assert names[str(projects[3])]['reason'] == 'project directory no longer exists'
    assert len(p.load_manifest(out / names[str(projects[0])]['package'])['conversations']) == 2
    try: quiet(lambda: b.batch_pack('codex', out, 'claude', home))
    except ValueError as e: assert 'new directory' in str(e)
    else: raise AssertionError('Existing batch output accepted')
    try: quiet(lambda: b.batch_pack('codex', d / 'nope', 'claude', home, projects=[d / 'missing']))
    except ValueError as e: assert 'No conversations' in str(e)
    else: raise AssertionError('Unknown project accepted')
    one, _ = quiet(lambda: b.batch_pack('codex', d / 'one', 'claude', home, projects=[projects[1]]))
    assert [x['name'] for x in one['projects']] == ['blog']

    # Restore all into one new root, without desktop registration.
    M = {'claude_model': 'claude-test-model', 'claude_version': '0.0.0-test'}
    root = d / 'restored'
    plan, _ = quiet(lambda: b.batch_restore(out, 'claude', root, d / 'claude-home', dry_run=True, no_desktop=True, **M))
    assert plan['summary']['planned'] == 3 and not root.exists(), (plan['summary'], [x.get('reason') for x in plan['projects']], root.exists())
    done, _ = quiet(lambda: b.batch_restore(out, 'claude', root, d / 'claude-home', no_desktop=True, **M))
    assert done['summary'] == {'restored': 3, 'planned': 0, 'failed': 0}, done
    for name in ('ledger', 'blog', 'ledger-2'):
        assert (root / name / 'readme.md').is_file() and (root / name / '.rehome/restore.json').is_file()
    assert {x['conversations'] for x in done['projects']} == {2, 1}
    assert (root / 'rehome-batch-restore.json').is_file() and done['user_next_steps']['options'][0] == '已重启，继续'
    assert any(str(root) in line and '只需一次' in line for line in done['user_next_steps']['instructions']), 'Trust the root once'
    sessions = list((d / 'claude-home' / 'projects').glob('*/*.jsonl'))
    assert len(sessions) == 4
    again, _ = quiet(lambda: b.batch_restore(out, 'claude', root, d / 'claude-home', no_desktop=True, **M))
    assert again['summary']['failed'] == 3 and all('already exists' in x['reason'] for x in again['projects'])
    try: quiet(lambda: b.batch_restore(out, 'claude', out / 'inside', d / 'claude-home', no_desktop=True, **M))
    except ValueError as e: assert 'outside' in str(e)
    else: raise AssertionError('Root inside batch accepted')

    # ---- Receiver-only move: read the source data folder directly, pack next to ROOT, restore into ROOT ----
    moved = d / 'moved'
    preview, _ = quiet(lambda: b.batch_move('codex', 'claude', moved, source_home=home, target_home=d / 'claude-move', dry_run=True, no_desktop=True, **M))
    assert preview['route'] == 'receiver-only' and preview['pack_summary']['planned'] == 3 and not moved.exists()
    assert not (d / 'moved-rehome-package').exists(), 'Dry run writes nothing'
    done, _ = quiet(lambda: b.batch_move('codex', 'claude', moved, source_home=home, target_home=d / 'claude-move', no_desktop=True, **M))
    assert done['summary'] == {'restored': 3, 'planned': 0, 'failed': 0}, done.get('summary')
    assert (d / 'moved-rehome-package' / 'batch.json').is_file() and (moved / 'rehome-batch-move.json').is_file()
    assert [x['reason'] for x in done['skipped_at_pack']] == ['project directory no longer exists']
    assert done['user_next_steps']['options'][0] == '已重启，继续' and 'package_note' in done
    assert len(list((d / 'claude-move' / 'projects').glob('*/*.jsonl'))) == 4
    for bad in (moved, d / 'x'):
        try: quiet(lambda: b.batch_move('codex', 'claude', bad, package=bad / 'pkg' if bad != moved else None, source_home=home, no_desktop=True, **M))
        except ValueError as e: assert 'new directory' in str(e) or 'separate' in str(e), e
        else: raise AssertionError('Unsafe move accepted')

    # ---- Compressed rollouts (.jsonl.zst on disk, plain path in the DB) are found before anything is written ----
    zh_home = d / 'codex-zst'; zh_home.mkdir()
    zproj = d / 'zproj'; zproj.mkdir(); (zproj / 'a.txt').write_text('x', encoding='utf-8')
    with contextlib.closing(sqlite3.connect(zh_home / 'state_5.sqlite')) as db:
        db.executescript((Path(__file__).parent / 'fixtures/codex_schema.sql').read_text(encoding='utf-8'))
        rollout = zh_home / 'sessions' / 'rollout-z.jsonl'; rollout.parent.mkdir()
        (rollout.parent / 'rollout-z.jsonl.zst').write_bytes(b'\x28\xb5\x2f\xfd')
        db.execute('insert into threads(id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,sandbox_policy,approval_mode,archived,cli_version,first_user_message,memory_mode) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (f'{99:08d}-1234-4567-8123-123456789012', str(rollout), 1, 1, 'fixture', 'fixture', str(zproj), 't', '{}', 'fixture', 0, 'fixture', 'q', 'enabled'))
        db.commit()
    assert b.inventory('codex', zh_home)[0]['compressed'] == 1
    from unittest.mock import patch as _patch
    with _patch.object(b, 'zstd_decoder', return_value=None):
        plan, _ = quiet(lambda: b.batch_move('codex', 'claude', d / 'zmoved', source_home=zh_home, dry_run=True, no_desktop=True, **M))
        assert plan['decoder_needed']['compressed_conversations'] == 1 and 'zstandard' in plan['decoder_needed']['agent_next']
        try: quiet(lambda: b.batch_move('codex', 'claude', d / 'zmoved', source_home=zh_home, no_desktop=True, **M))
        except ValueError as e: assert '什么都没写入' in str(e)
        else: raise AssertionError('Compressed history packed without a decoder')
    assert not (d / 'zmoved').exists() and not (d / 'zmoved-rehome-package').exists()
    with _patch.object(b, 'zstd_decoder', return_value='zstandard'):
        plan, _ = quiet(lambda: b.batch_move('codex', 'claude', d / 'zmoved', source_home=zh_home, dry_run=True, no_desktop=True, **M))
    assert 'decoder_needed' not in plan

    # ---- Claude: list reads the cwd inside each session, ignores mismatched folders ----
    ch = d / 'claude-src'
    for proj, count in ((projects[0], 2), (projects[1], 1)):
        folder = ch / 'projects' / p.re.sub(r'[^a-zA-Z0-9_-]', '-', str(proj)); folder.mkdir(parents=True)
        for k in range(count):
            sid = f'{k:08d}-aaaa-4567-8123-123456789012'
            rows = [{'type': 'user', 'uuid': 'u', 'parentUuid': None, 'sessionId': sid, 'cwd': str(proj), 'timestamp': TS, 'message': {'role': 'user', 'content': 'hi'}},
                    {'type': 'assistant', 'uuid': 'a', 'parentUuid': 'u', 'sessionId': sid, 'cwd': str(proj), 'timestamp': TS, 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'ok'}]}}]
            (folder / (sid + '.jsonl')).write_text('\n'.join(json.dumps(x) for x in rows) + '\n', encoding='utf-8')
    stray = ch / 'projects' / 'unrelated'; stray.mkdir()
    (stray / 'x.jsonl').write_text(json.dumps({'type': 'user', 'cwd': str(projects[0])}) + '\n', encoding='utf-8')
    claude = {x['project']: x['sessions'] for x in b.inventory('claude', ch)}
    assert claude == {str(projects[0]): 2, str(projects[1]): 1}, claude
    native, _ = quiet(lambda: b.batch_pack('claude', d / 'native', 'claude', ch))
    assert native['native'] is True and native['summary']['packed'] == 2
    # Two Chinese-named projects collapse to one Claude folder; each pack keeps only its own sessions.
    zh = [d / 'zh' / '个人博客', d / 'zh' / '周报脚本']
    ch2 = d / 'claude-zh'
    for i, proj in enumerate(zh):
        proj.mkdir(parents=True); (proj / 'a.txt').write_text(proj.name, encoding='utf-8')
        folder = ch2 / 'projects' / p.re.sub(r'[^a-zA-Z0-9_-]', '-', str(proj)); folder.mkdir(parents=True, exist_ok=True)
        sid = f'{i:08d}-bbbb-4567-8123-123456789012'
        rows = [{'type': 'user', 'uuid': 'u', 'parentUuid': None, 'sessionId': sid, 'cwd': str(proj), 'timestamp': TS, 'message': {'role': 'user', 'content': proj.name}},
                {'type': 'assistant', 'uuid': 'a', 'parentUuid': 'u', 'sessionId': sid, 'cwd': str(proj), 'timestamp': TS, 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'ok'}]}}]
        (folder / (sid + '.jsonl')).write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in rows) + '\n', encoding='utf-8')
    assert len(list((ch2 / 'projects').iterdir())) == 1, 'Fixture must share one folder'
    zh_batch, _ = quiet(lambda: b.batch_pack('claude', d / 'zh-batch', 'codex', ch2))
    for item in zh_batch['projects']:
        assert item['conversations'] == 1, item
        conv = p.load_manifest(d / 'zh-batch' / item['package'])['conversations']
        assert Path(item['project']).name in json.dumps(conv, ensure_ascii=False)
    assert b.inventory('claude', d / 'empty') == [] and b.inventory('codex', d / 'empty') == []
    # Codex asks for trust once per project: warn before restoring, then list what still waits on the user.
    from unittest.mock import patch
    regs = iter([{'registered': False, 'project_id': 'p1', 'thread_binding_required': ['t1']},
                 {'registered': False, 'pending': True, 'thread_binding_required': ['t2']}])
    def fake(pkg, dest, to, home, dry_run=False, **kw):
        if not dry_run: Path(dest).mkdir(parents=True)
        if dry_run:
            return {'sessions': [{'title': 'x'}]}
        registry = next(regs)
        return {'sessions': [{'title': 'x', 'id': registry['thread_binding_required'][0]}],
                'desktop_project_registry': registry}
    with patch.object(b.pr, 'restore', fake):
        plan, _ = quiet(lambda: b.batch_restore(d / 'zh-batch', 'codex', d / 'cx', d / 'cxh', dry_run=True))
        assert '共 2 次' in plan['user_notice'], plan
        done, _ = quiet(lambda: b.batch_restore(d / 'zh-batch', 'codex', d / 'cx', d / 'cxh'))
    assert [x['codex_project'] for x in done['projects']] == ['registered', 'pending'], done['projects']
    steps = done['user_next_steps']
    assert steps['pending_trust'] == [done['projects'][1]['target']]
    assert done['sidebar_status'] == 'verification_required'
    assert [x['sidebar']['thread_ids'] for x in done['projects']] == [['t1'], ['t2']]
    assert [x['sidebar']['folder_open_pending'] for x in done['projects']] == [False, True]
    receipt = json.loads((d / 'cx' / 'rehome-batch-restore.json').read_text(encoding='utf-8'))
    assert receipt['projects'][0]['sidebar']['project_path'] == done['projects'][0]['target']
    assert 'move_thread_to_project' in done['agent_next']
print('PASS: batch list (Claude/Codex), dry run, pack all with skip/collision names, restore all under one root, refusals')
