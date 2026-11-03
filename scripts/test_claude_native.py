"""Native relocation invariants, using synthetic histories and blank data homes."""
import argparse,copy,json,re,sys,tempfile,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import claude_native as n,agent_rehome as r,project_rehome as p

def fail(fn,fragment):
    try:fn()
    except ValueError as error:assert fragment.lower() in str(error).lower(),str(error)
    else:raise AssertionError('Unsafe native operation accepted')

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);source_home=root/'source-home';folder=source_home/'projects'/'fixture';folder.mkdir(parents=True)
    sid=str(uuid.uuid4());file=folder/(sid+'.jsonl')
    rows=[{'type':'custom-title','sessionId':sid,'customTitle':'原生合成测试'},
        {'type':'user','sessionId':sid,'cwd':'old project','version':'0.0.0-source','timestamp':'2026-11-01T00:00:00Z','message':{'content':'正文 old project 不变\u2028段落分隔符保留'}},
        {'type':'assistant','cwd':'old project','message':{'model':'fixture-model','content':[{'type':'thinking','thinking':'保留思考字节'},
            {'type':'tool_use','id':'call','name':'Bash','input':{'command':'echo old project','cwd':'nested remains'}}]}},
        {'type':'user','cwd':'old project','message':{'content':[{'type':'tool_result','tool_use_id':'call','content':'原输出 old project'}]}},
        {'type':'system','subtype':'compact_boundary','cwd':'old project','compactMetadata':{'trigger':'auto'}},
        {'type':'user','isCompactSummary':True,'cwd':'old project','message':{'content':'来源已有的摘要'}}]
    data=b'\xef\xbb\xbf'+('\r\n'.join(json.dumps(row,ensure_ascii=False,indent=None) for row in rows)+'\r\n\r\n').encode('utf-8')
    file.write_bytes(data);sub=folder/sid/'subagents';sub.mkdir(parents=True)
    aux=b'{"type":"assistant", "cwd" : "old project", "message":{"content":"side text"}}\r\n';(sub/'agent-a.jsonl').write_bytes(aux)
    memory=folder/'memory';memory.mkdir();(memory/'MEMORY.md').write_text('project memory',encoding='utf-8')
    checkpoint_bytes=b'{"cwd":"checkpoint content remains old project"}\r\n'
    (memory/'notes.jsonl').write_bytes(checkpoint_bytes)
    checkpoints=source_home/'file-history'/sid;checkpoints.mkdir(parents=True);(checkpoints/'checkpoint').write_text('old source',encoding='utf-8')
    (checkpoints/'source.jsonl').write_bytes(checkpoint_bytes)
    source_registry=root/'source-registry';source_registry.mkdir()
    (source_registry/'local_source.json').write_text(json.dumps({'cliSessionId':sid,'title':'来源标题','model':'source-model','effort':'high','permissionMode':'bypassPermissions','access_token':'never-copy'}),encoding='utf-8')
    snap=n.snapshot(file,source_home,True,True,source_registry)
    package=root/'package';n.pack(snap,package);loaded=n.load(package)
    dest=root/'dest';dest.mkdir();home=root/'target-home';registry=root/'target-registry'
    args=argparse.Namespace(cwd=str(dest),target_home=str(home),to='claude',dry_run=True,no_desktop=False,desktop_registry=str(registry))
    n.restore(loaded,args);assert not home.exists() and not registry.exists()
    args.dry_run=False;result=n.restore(loaded,args)
    target=next(home.glob('projects/*/'+sid+'.jsonl'));new=target.read_bytes()
    # Canonicalize only the allowed cwd span on both sides: every remaining byte matches.
    assert n.rewrite_cwd(new,str(dest.resolve()),'comparison')==n.rewrite_cwd(data,'old project','comparison')
    assert new==n.rewrite_cwd(data,'old project',str(dest.resolve())) and new.startswith(b'\xef\xbb\xbf') and new.endswith(b'\r\n\r\n')
    assert file.read_bytes()==data and (target.with_suffix('')/'subagents/agent-a.jsonl').read_bytes()==n.rewrite_cwd(aux,'old project',str(dest.resolve()))
    assert (target.parent/'memory/MEMORY.md').read_text()=='project memory'
    assert (home/'file-history'/sid/'checkpoint').read_text()=='old source'
    assert (home/'file-history'/sid/'source.jsonl').read_bytes()==checkpoint_bytes
    assert (target.parent/'memory/notes.jsonl').read_bytes()==checkpoint_bytes
    assert new.count(b'compact_boundary')==data.count(b'compact_boundary')==1
    assert result['id']==sid and result['source_version']=='0.0.0-source' and result['losses_summary']=={}
    rec=json.loads(Path(result['desktop_registry']).read_text(encoding='utf-8'))
    assert rec['title']=='来源标题' and rec['model']=='source-model' and rec['effort']=='high' and rec['permissionMode']=='default'
    assert not n.FORBIDDEN_KEYS.intersection(rec) and 'access_token' not in json.dumps(rec)
    backup=json.loads((Path(result['backup'])/'backup.json').read_text());assert all(not item['existed'] for item in backup.values())
    fail(lambda:n.restore(loaded,args),'session ID already exists')
    # Different ID, same project memory: all preflighted before creating its main JSONL.
    other=str(uuid.uuid4());otherfile=folder/(other+'.jsonl');otherfile.write_text(json.dumps(dict(rows[1],sessionId=other)),encoding='utf-8')
    other_snapshot=n.snapshot(otherfile,source_home,True)
    fail(lambda:n.restore(other_snapshot,args),'memory file already exists')
    assert not list(home.glob('projects/*/'+other+'.jsonl'))
    bad=copy.deepcopy(loaded);bad['files'][0]['data']+=b'changed'
    args.target_home=str(root/'bad-home');args.no_desktop=True
    fail(lambda:n.restore(bad,args),'changed after snapshot');assert not Path(args.target_home).exists()
    secret='sk-'+'x'*24
    otherfile.write_text(json.dumps(dict(rows[1],sessionId=other,message={'content':secret})),encoding='utf-8')
    fail(lambda:n.snapshot(otherfile,source_home),'credential')
    fail(lambda:n.check_payload(b'{"type":"user","hasTrustDialogAccepted":true}','test.jsonl',True),'trust')
    # Entry points choose native relocation by default, never the converting writer.
    argv=['agent_rehome','transfer','--from','claude:'+str(file),'--to','claude','--cwd',str(dest),'--target-home',str(root/'cli-home'),'--no-desktop','--dry-run']
    with patch.object(sys,'argv',argv),patch.object(r,'import_bundle',side_effect=AssertionError('conversion used')):r.main()
    with patch.object(sys,'argv',['agent_rehome','transfer','--from','codex:'+sid,'--to','codex','--cwd',str(dest)]):
        fail(r.main,'ReHome Desktop')
    # Whole project: two native chats, shared memory copied once; no target version needed.
    otherfile.write_text(json.dumps(dict(rows[1],sessionId=other)),encoding='utf-8')
    project=root/'source-project';project.mkdir();(project/'main.txt').write_text('source code',encoding='utf-8')
    project_data=n.rewrite_cwd(data,'old project',str(project.resolve()));file.write_bytes(project_data)
    otherfile.write_bytes(n.rewrite_cwd(otherfile.read_bytes(),'old project',str(project.resolve())))
    (sub/'agent-a.jsonl').write_bytes(n.rewrite_cwd(aux,'old project',str(project.resolve())))
    packed=root/'project-package'
    p.pack('claude',project,packed,source_home,[{'snapshot':str(file),'title':'one'},{'snapshot':str(otherfile),'title':'two'}],native=True,include_memory=True,include_checkpoints=True,source_desktop_registry=source_registry)
    for session_id,title in ((sid,'one'),(other,'two')):
        native_manifest=json.loads((packed/'sessions'/session_id/'raw-native/manifest.json').read_text(encoding='utf-8'))
        assert native_manifest['title']==title,'Explicit inventory title must reach native package before packing'
    restored=root/'restored';project_home=root/'project-home'
    project_registry=root/'project-registry'
    preview=p.restore(packed,restored,'claude',project_home,False,dry_run=True,desktop_registry=str(project_registry))
    assert preview['native'] and not restored.exists() and not project_home.exists()
    assert not project_registry.exists()
    state=p.restore(packed,restored,'claude',project_home,False,desktop_registry=str(project_registry))
    assert {item['id'] for item in state['sessions']}=={sid,other} and state['losses_summary']=={}
    assert {item['id']:item['title'] for item in state['sessions']}=={sid:'one',other:'two'}
    registrations=[json.loads(path.read_text(encoding='utf-8')) for path in project_registry.glob('local_*.json')]
    assert {item['cliSessionId']:item['title'] for item in registrations}=={sid:'one',other:'two'},'Restored desktop titles must match inventory'
    assert (restored/'main.txt').read_text()=='source code'
    restored_raw=next(project_home.glob('projects/*/'+sid+'.jsonl')).read_bytes()
    assert restored_raw==n.rewrite_cwd(project_data,str(project.resolve()),str(restored.resolve()))
    assert len(list(project_home.glob('projects/*/memory/MEMORY.md')))==1
    assert state['status']=='files-verified-native-resume-pending'
    # A collision in any session blocks the entire project before even its files are created.
    fail(lambda:p.restore(packed,root/'blocked','claude',project_home,True),'session ID already exists')
    assert not (root/'blocked').exists()
    # Untitled sessions get the first visible user text as sidebar title, never the raw session ID.
    untitled=folder/(str(uuid.uuid4())+'.jsonl')
    untitled.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in [{'type':'user','isMeta':True,'message':{'content':'<command-name>x</command-name>'}},
        {'type':'user','message':{'content':[{'type':'text','text':'没有自定义标题的会话'}]}}]),encoding='utf-8')
    assert n.snapshot(untitled,source_home)['title']=='没有自定义标题的会话'
    for text,title in [
        ('http://example.com/x 打开','打开'),
        ('https://example.com/x','未命名会话'),
        ('x://example.com/x 打开','打开'),
        ('C:\\only.txt','only.txt'),
        ('C:/fixture/folder/','folder'),
        ('/tmp/fixture/only.txt','only.txt'),
        ('C:\\','未命名会话'),
        ('/','未命名会话'),
        ('选项 A / B 哪个好','选项 A / B 哪个好'),
        ('标记 abc:/def 保持原样','标记 abc:/def 保持原样'),
        ('标记 1C:\\fixture 保持原样','标记 1C:\\fixture 保持原样'),
        ('请检查项目： C:\\fixture\\very long folder\\file.txt，保留历史。','请检查项目'),
        ('请检查项目： C:/fixture/very long folder/file.txt','请检查项目'),
        ('查看目录 /tmp/very long folder/file.txt 的历史。','查看目录'),
        ('alpha '+('b'*70),'alpha'),
        ('普通完整标题。','普通完整标题'),
        ('字'*70,'字'*60),
    ]:
        untitled.write_text(json.dumps({'type':'user','message':{'content':text}},ensure_ascii=False),encoding='utf-8')
        assert n.snapshot(untitled,source_home)['title']==title,(text,n.snapshot(untitled,source_home)['title'])
    # Explicit source titles retain priority and do not go through fallback shaping.
    explicit_title='http://example.com/title C:\\fixture\\title'
    untitled.write_text('\n'.join(json.dumps(row,ensure_ascii=False) for row in [
        {'type':'custom-title','customTitle':explicit_title},
        {'type':'user','message':{'content':'C:\\only.txt'}},
    ]),encoding='utf-8')
    assert n.snapshot(untitled,source_home)['title']==explicit_title
    title_registry=root/'title-registry';title_registry.mkdir()
    registry_title='来源登记标题 / 保持原样'
    (title_registry/'local_title.json').write_text(json.dumps({'cliSessionId':untitled.stem,'title':registry_title}),encoding='utf-8')
    assert n.snapshot(untitled,source_home,source_registry=title_registry)['title']==registry_title
print('PASS: byte-preserving native relocation, BOM/CRLF, thinking/tools/compaction, sidecars, memory/checkpoints, safe registration, dry-run/collisions/secrets, routing, two-session native project')
