"""A finished project pack tells the user what to do next; images are reported as carried."""
import contextlib, io, json, sys, tempfile, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_rehome
import exchange
import project_rehome as p
from user_next_steps import package_next_steps

steps = package_next_steps('D:/pack')
assert steps['package_path'] == 'D:/pack' and 'D:/pack' in steps['first_message']
assert 'U 盘' in steps['other_computer'] and 'Python 3.10+' in steps['other_computer'] and steps['privacy']

with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp); home = d / 'home'; source = d / 'source'; source.mkdir()
    (source / 'a.txt').write_text('hello', encoding='utf-8')
    sid = str(uuid.uuid4()); cwd = str(source)
    folder = home / 'projects' / 'x'; folder.mkdir(parents=True)
    rows = [{'type': 'user', 'uuid': 'u1', 'parentUuid': None, 'sessionId': sid, 'cwd': cwd, 'timestamp': '2026-01-01T00:00:00Z', 'message': {'role': 'user', 'content': 'hi'}},
            {'type': 'assistant', 'uuid': 'a1', 'parentUuid': 'u1', 'sessionId': sid, 'cwd': cwd, 'timestamp': '2026-01-01T00:00:01Z', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'ok'}]}}]
    session = folder / (sid + '.jsonl')
    session.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
    out = d / 'pack'; buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        p.pack('claude', source, out, home, [{'snapshot': str(session), 'title': 't'}])
    final = json.loads(buffer.getvalue().strip().splitlines()[-1])
    assert final['user_next_steps']['package_path'] == str(out)
    assert str(out) in final['user_next_steps']['first_message']
    single = d / 'single.json'; buffer = io.StringIO(); argv = sys.argv
    sys.argv = ['agent_rehome.py', 'export', '--from', 'claude:' + str(session), '--source-home', str(home), '--out', str(single)]
    try:
        with contextlib.redirect_stdout(buffer):
            agent_rehome.main()
    finally:
        sys.argv = argv
    lines = buffer.getvalue().strip().splitlines()
    assert lines[0] == str(single), 'The first output line stays the package path'
    assert json.loads(lines[1])['user_next_steps']['package_path'] == str(single)

ref = [{'file': 'f', 'line': 1, 'sha256': '0' * 64}]
image = {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'image', 'source': {}}, {'type': 'document'}]}}
_, losses = exchange.audit_source('claude', [image], ref)
actions = {x['kind']: x['action'] for x in losses}
assert actions['image_attachment'] == 'kept_raw_only' and actions['file_attachment'] == 'dropped'
codex = {'type': 'event_msg', 'payload': {'type': 'user_message', 'images': ['x']}}
_, losses = exchange.audit_source('codex', [codex], ref)
assert [x['action'] for x in losses if x['kind'] == 'image_attachment'] == ['kept_raw_only']
print('package next steps ok')
