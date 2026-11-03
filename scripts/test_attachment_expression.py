"""Native Codex file references and conservative Claude links keep image/file access."""
import base64,contextlib,hashlib,io,json,re,sqlite3,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import project_rehome as p,exchange as x
from codex_native import build_rollout

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j9YQAAAAASUVORK5CYII=')
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory).resolve();source=root/'source';source.mkdir();notes=source/'notes.md';notes.write_text('historical file content',encoding='utf-8')
    home=root/'claude-source';folder=home/'projects'/re.sub(r'[^a-zA-Z0-9_-]','-',str(source));folder.mkdir(parents=True)
    sid='12345678-1234-4567-8123-123456789012';ts='2026-11-01T00:00:00Z'
    rows=[{'type':'user','sessionId':sid,'cwd':str(source),'uuid':'u1','timestamp':ts,'message':{'content':[{'type':'text','text':'keep this image'},{'type':'image','source':{'type':'base64','media_type':'image/png','data':base64.b64encode(PNG).decode()}}]}},
        {'type':'assistant','timestamp':ts,'message':{'content':[{'type':'text','text':'received'}]}},
        {'type':'user','sessionId':sid,'cwd':str(source),'uuid':'u2','timestamp':'2026-11-01T00:01:00Z','message':{'content':'@notes.md keep this file'}},
        {'type':'attachment','parentUuid':'u2','timestamp':'2026-11-01T00:01:00Z','attachment':{'type':'file','filename':str(notes),'content':{'type':'text','file':{'content':'historical file content'}}}}]
    rows.extend({'type':'attachment','attachment':{'type':('environment','total_tokens_reminder','deferred_tools')[n%3]}} for n in range(266))
    file=folder/(sid+'.jsonl');file.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
    package=root/'package'
    with contextlib.redirect_stdout(io.StringIO()):p.pack('claude',source,package,home)
    manifest=p.load_manifest(package);losses=manifest['conversations'][0]['losses']
    assert sum(loss['kind']=='file_attachment' for loss in losses)==1
    assert sum(loss['reason']=='harness_injected' for loss in losses)==266
    special=rows[:1]+[{'type':'attachment','attachment':{'type':'compact_file_reference'}},{'type':'attachment','attachment':{'type':'future_unknown'}}]
    _,audit=x.audit_source('claude',special,[{'file':'fixture','line':n,'sha256':'fixture'} for n in range(len(special))])
    assert any(loss['kind']=='file_attachment' for loss in audit)
    assert any(loss['kind']=='attachment_future_unknown' and loss['reason']=='unsupported_by_target' for loss in audit)
    for target in ('codex','claude'):
        dest=root/(target+'-project');target_home=root/(target+'-data');target_home.mkdir()
        if target=='codex':
            with contextlib.closing(sqlite3.connect(target_home/'state_5.sqlite')) as db:db.executescript((Path(__file__).parent/'fixtures/codex_schema.sql').read_text(encoding='utf-8'))
        with contextlib.redirect_stdout(io.StringIO()):state=p.restore(package,dest,target,target_home,True,convert=target=='claude',model='fixture-model',claude_model='fixture-model',claude_version='0.0.0-test')
        attachment=next((dest/'.rehome/attachments').glob('*.md'));assert attachment.read_text(encoding='utf-8')=='historical file content'
        if target=='codex':
            rollout=next(target_home.glob('sessions/**/*.jsonl'));history=p.r.read(rollout)
            users=[row['payload']['item'] for row in history if row.get('type')=='event_msg' and row.get('payload',{}).get('item',{}).get('type')=='UserMessage']
            image_path=next(item['path'] for item in users[0]['content'] if item.get('type')=='local_image');assert Path(image_path).read_bytes()==PNG
            text=users[1]['content'][0]['text'];assert text.startswith('# Files mentioned by the user:\n') and '## notes.md: '+attachment.as_posix() in text and '## My request:\n' in text
            provider=[row['payload'] for row in history if row.get('type')=='response_item' and row.get('payload',{}).get('role')=='user']
            assert provider[1]['content'][0]['text']==text
            assert base64.b64decode(provider[0]['content'][1]['image_url'].split(',',1)[1])==PNG
            assert '迁移附件（历史数据）' not in json.dumps(users,ensure_ascii=False)
        else:
            history=p.r.read(next(target_home.glob('projects/*/*.jsonl')));users=[row for row in history if row.get('type')=='user']
            image=next(block for block in users[0]['message']['content'] if block.get('type')=='image');assert base64.b64decode(image['source']['data'])==PNG
            assert attachment.as_posix() in users[1]['message']['content']
            assert not any(row.get('type')=='attachment' or row.get('renderedRole')=='system' for row in history),'Do not forge native Read/system caches'
print('PASS: native Codex UI/provider file header, image bytes unchanged, Claude fallback access, true files vs 266 harness attachments')
