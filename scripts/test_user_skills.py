"""User-level Skills travel in the package and are installed only on --apply, never overwriting."""
import contextlib, io, json, os, sqlite3, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import user_skills as us, batch_rehome as b

def skill(root, name, body='用法说明', extra=None):
    folder = root / name; folder.mkdir(parents=True)
    (folder / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: {name} 的说明\n---\n{body}\n', encoding='utf-8')
    for relative, text in (extra or {}).items():
        path = folder / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding='utf-8')
    return folder
def quiet(call):
    with contextlib.redirect_stdout(io.StringIO()): return call()

with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp).resolve()
    # ---- Claude source ----
    claude = d / 'src' / '.claude'; croot = claude / 'skills'
    skill(croot, 'notes', '用 TodoWrite 记录', {'scripts/run.py': 'print(1)', '__pycache__/x.pyc': 'junk', '.git/config': 'x'})
    skill(croot, 'plain')
    skill(croot, 'leaky', extra={'key.txt': 'sk-' + 'a' * 30})
    skill(croot, us.SELF)
    skill(croot, '.system-thing')
    (croot / 'not-a-skill').mkdir(); (croot / 'not-a-skill' / 'readme.md').write_text('x', encoding='utf-8')
    (croot / 'loose.md').write_text('x', encoding='utf-8')
    assert us.roots('claude', claude) == [croot]

    found, skipped = us.inventory('claude', claude)
    assert [x['name'] for x in found] == ['notes', 'plain'], found
    assert skipped == [{'name': 'leaky', 'reason': 'possible-secret', 'path': 'key.txt'}], skipped
    notes = found[0]
    assert notes['files'] == 2 and notes['has_scripts'] and notes['mentions'] == 1 and notes['description'] == 'notes 的说明'
    assert not found[1]['has_scripts']
    assert [x['name'] for x in us.inventory('claude', claude, allow_secrets=True)[0]] == ['leaky', 'notes', 'plain']
    assert [x['name'] for x in us.inventory('claude', claude, only=['plain'])[0]] == ['plain']

    package = d / 'pkg'; package.mkdir()
    packed = us.pack('claude', package, claude)
    assert packed['status'] == 'packed' and (package / us.DIRNAME / 'notes' / 'scripts' / 'run.py').is_file()
    assert not (package / us.DIRNAME / 'notes' / '__pycache__').exists() and not (package / us.DIRNAME / 'notes' / '.git').exists()
    assert not (package / us.DIRNAME / 'leaky').exists() and not (package / us.DIRNAME / us.SELF).exists()
    assert 'source' not in json.loads((package / us.DIRNAME / us.MANIFEST).read_text(encoding='utf-8'))['skills'][0]
    try: us.pack('claude', package, claude)
    except OSError: pass
    else: raise AssertionError('Second pack into the same folder accepted')
    assert us.pack('claude', d / 'empty', d / 'nothing')['status'] == 'none' and not (d / 'empty').exists()

    # ---- Install into Codex: goes to .agents/skills, existing names are kept ----
    codex = d / 'dst' / '.codex'; codex.mkdir(parents=True)
    agents = d / 'dst' / '.agents' / 'skills'
    assert us.roots('codex', codex) == [agents, codex / 'skills']
    mine = skill(codex / 'skills', 'plain', '我自己的版本')
    preview = us.install(package, 'codex', codex)
    assert preview['status'] == 'planned' and [x['name'] for x in preview['install']] == ['notes'], preview
    assert preview['skipped'] == [{'name': 'plain', 'reason': 'target-skill-exists', 'path': str(mine)}]
    assert any('scripts' in w and 'notes' in w for w in preview['warnings']) and any('unchanged' in w for w in preview['warnings'])
    assert not agents.exists(), 'Preview must not write'
    done = us.install(package, 'codex', codex, apply=True)
    assert done['status'] == 'installed' and done['installed'] == [str(agents / 'notes')]
    assert (agents / 'notes' / 'scripts' / 'run.py').read_text(encoding='utf-8') == 'print(1)'
    assert '我自己的版本' in (mine / 'SKILL.md').read_text(encoding='utf-8'), 'Existing Skill must stay untouched'
    assert json.loads((Path(done['record']) / 'installed.json').read_text(encoding='utf-8'))['installed'] == done['installed']
    again = us.install(package, 'codex', codex, apply=True)
    assert again['status'] == 'nothing_to_install' and {'name': 'notes', 'reason': 'already-installed', 'path': str(agents / 'notes')} in again['skipped']

    # --only picks; a tampered package is refused before anything is written.
    other = d / 'dst2' / '.claude'
    picked = us.install(package, 'claude', other, apply=True, only=['plain'])
    assert picked['installed'] == [str(other / 'skills' / 'plain')] and not (other / 'skills' / 'notes').exists()
    assert not any('unchanged' in w for w in picked['warnings']), 'Same agent needs no cross-agent warning'
    (package / us.DIRNAME / 'notes' / 'SKILL.md').write_text('changed', encoding='utf-8')
    try: us.install(package, 'claude', d / 'dst3' / '.claude', apply=True)
    except ValueError as e: assert 'checksum' in str(e)
    else: raise AssertionError('Tampered package accepted')
    assert not (d / 'dst3').exists()

    # ---- Codex source: both folders are read, .agents wins on a duplicate name ----
    chome = d / 'csrc' / '.codex'
    skill(chome / 'skills', 'old-place'); skill(chome / 'skills', 'twice', '旧位置')
    skill(d / 'csrc' / '.agents' / 'skills', 'twice', '新位置')
    found, skipped = us.inventory('codex', chome)
    assert [x['name'] for x in found] == ['twice', 'old-place'] and skipped[0]['reason'] == 'duplicate-name'
    cpkg = d / 'cpkg'; cpkg.mkdir(); us.pack('codex', cpkg, chome)
    assert '新位置' in (cpkg / us.DIRNAME / 'twice' / 'SKILL.md').read_text(encoding='utf-8')

    # A linked Skill folder is reported, not followed.
    try:
        os.symlink(croot / 'plain', croot / 'linked', target_is_directory=True)
    except (OSError, NotImplementedError):
        pass
    else:
        assert {'name': 'linked', 'reason': 'linked-folder'} in us.inventory('claude', claude)[1]

    # ---- Batch: Skills ride along with a move and wait for approval ----
    proj = d / 'work' / 'ledger'; proj.mkdir(parents=True); (proj / 'readme.md').write_text('项目', encoding='utf-8')
    with contextlib.closing(sqlite3.connect(chome / 'state_5.sqlite')) as db:
        db.executescript((Path(__file__).parent / 'fixtures/codex_schema.sql').read_text(encoding='utf-8'))
        sid = '12345678-1234-4567-8123-123456789012'
        path = chome / 'sessions' / f'rollout-{sid}.jsonl'; path.parent.mkdir(parents=True)
        rows = [{'timestamp': '2026-11-01T00:00:00Z', 'type': t, 'payload': dict(type=k, **v)} for t, k, v in (
            ('session_meta', 'meta', {'id': sid, 'cwd': str(proj), 'cli_version': '0.140.0'}),
            ('event_msg', 'user_message', {'message': '问题'}), ('event_msg', 'agent_message', {'message': '回答'}))]
        path.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in rows) + '\n', encoding='utf-8')
        db.execute('insert into threads(id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,sandbox_policy,approval_mode,archived,cli_version,first_user_message,memory_mode) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (sid, str(path), 1, 1000, 'fixture', 'fixture', str(proj), 't', '{}', 'fixture', 0, 'fixture', 'q', 'enabled'))
        db.commit()
    target = d / 'tgt' / '.claude'; target.mkdir(parents=True)
    dry = quiet(lambda: b.batch_move('codex', 'claude', d / 'moved', source_home=chome, target_home=target, dry_run=True, no_desktop=True))
    assert dry['user_skills']['names'] == ['twice', 'old-place'] and dry['user_skills_found'] == 2 and not (d / 'moved').exists()
    moved = quiet(lambda: b.batch_move('codex', 'claude', d / 'moved', source_home=chome, target_home=target, no_desktop=True))
    assert moved['user_skills']['status'] == 'planned' and 'user_skills.py install' in moved['user_skills_next'], moved.get('user_skills')
    assert not (target / 'skills').exists(), 'A move must not install Skills by itself'
    assert us.install(d / 'moved-rehome-package', 'claude', target, apply=True)['status'] == 'installed'
    assert (target / 'skills' / 'twice' / 'SKILL.md').is_file()
    off = quiet(lambda: b.batch_move('codex', 'claude', d / 'moved2', source_home=chome, target_home=target, no_desktop=True, user_skills=False))
    assert 'user_skills' not in off and not (d / 'moved2-rehome-package' / us.DIRNAME).exists()
print('user skills ok')
