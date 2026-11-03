import importlib.util, sys, tempfile, sqlite3, json, argparse
from pathlib import Path
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root/'scripts')); import agent_rehome as r
with tempfile.TemporaryDirectory() as tmp:
    d=Path(tmp); project=d/'project'; project.mkdir(); ch=d/'claude'; cx=d/'codex'; cx.mkdir()
    target=sqlite3.connect(cx/'state_5.sqlite')
    target.executescript((root/'scripts/fixtures/codex_schema.sql').read_text(encoding='utf-8'))
    target.commit(); target.close()
    b={'schema':'agent-transcript/v1','source':{'agent':'codex','session_id':'12345678-1234-4567-8123-123456789012','path':'fixture'},'title':'双向验证','project':{'cwd':'old'},'turns':[{'user':{'ts':'2026-11-01T00:00:00Z','text':'synthetic-fixture-token'},'items':[{'kind':'message','ts':'2026-11-01T00:00:01Z','text':'保留项目上下文'}]}]}
    reg=d/'desktop'/'org'/'acct'; reg.mkdir(parents=True)
    (reg/'local_existing.json').write_text(json.dumps({'sessionId':'local_existing','cliSessionId':'other','model':'claude-test-model','effort':'medium'}),encoding='utf-8')
    args=lambda to,home: argparse.Namespace(cwd=str(project),target_home=str(home),to=to,dry_run=False,model='codex-test-model',claude_version='0.0.0-test',desktop_registry=str(reg),no_desktop=False,convert=True)
    r.import_bundle(b,args('claude',ch))
    cp=next(ch.glob('projects/*/*.jsonl')); rows=r.read(cp)
    assert rows[0]['parentUuid'] is None and rows[1]['parentUuid']==rows[0]['uuid']
    regs=[json.loads(f.read_text(encoding='utf-8')) for f in reg.glob('local_*.json')]
    mine=[x for x in regs if x.get('cliSessionId')==cp.stem]
    assert len(mine)==1 and mine[0]['title']=='双向验证' and mine[0]['model']=='claude-test-model' and mine[0]['cwd']==str(project.resolve())
    # Recreating a missing registry entry on an existing import is also backed up.
    registry_file=reg/(mine[0]['sessionId']+'.json');registry_file.unlink()
    r.import_bundle(b,args('claude',ch))
    backups=[json.loads(p.read_text(encoding='utf-8')) for p in ch.glob('rehome-backups/registration-*/backup.json')]
    assert any(str(registry_file) in record for record in backups)
    assert len(list(reg.glob('local_*.json')))==2, '重复导入不应重复登记'
    b2=r.exchange.to_v1(r.export('claude',str(cp),ch)); assert b2['turns'][0]['user']['text']=='synthetic-fixture-token'
    # Codex ambient UI context and question-card answers: show only what the user typed/chose
    assert r.codex_user_text('<in-app-browser-context source="ambient-ui-state">\nThis block is ambient.\n</in-app-browser-context>\n\n## My request:\n合成测试请求\n')=='合成测试请求'
    assert r.codex_user_text('<send_user_message_question_reply>\n[{"question":"先测哪个？","answer":"当前项目"}]\n</send_user_message_question_reply>\n')=='回答「先测哪个？」：当前项目'
    assert r.codex_user_text('# Files mentioned by the user:\n\n## A.md: C:/p/A.md\n\n## My request:\n做个 skill\n')=='附件：A.md（C:/p/A.md）\n\n做个 skill'
    # background task notifications are not user turns
    tn=[{'type':'user','message':{'content':'迁移暗号'}},{'type':'user','message':{'content':'<task-notification>\n<summary>后台完成</summary>\n</task-notification>'}}]
    tt,_=r.export_claude(tn); assert len(tt)==1 and tt[0]['items'][0]['text']=='（后台任务通知）后台完成', tt
    r.import_bundle(b2,args('codex',cx))
    rollout=next(cx.glob('sessions/**/*.jsonl'))
    b3=r.exchange.to_v1(r.export('codex',str(rollout),cx))
    shape=lambda turns:[(t['user']['text'],[i['text'] for i in t['items']]) for t in turns]
    assert shape(b3['turns'])==shape(b2['turns']), (b3['turns'],b2['turns'])
    # Codex UI-layer fidelity: harness context dropped, attachment header cleaned, tools become native Claude tool cards
    ev=lambda ts,item:{'timestamp':ts,'type':'event_msg','payload':{'type':'item_completed','item':item}}
    fx=d/'codex-src'/'rollout-2026-11-01T01-00-00-aaaaaaaa-1234-4567-8123-123456789012.jsonl'; fx.parent.mkdir()
    fx.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in [
        {'timestamp':'2026-11-01T01:00:00Z','type':'session_meta','payload':{'id':'aaaaaaaa-1234-4567-8123-123456789012','cwd':'C:/old'}},
        {'timestamp':'2026-11-01T01:00:00Z','type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'# AGENTS.md instructions 注入内容'}]}},
        ev('2026-11-01T01:00:01Z',{'type':'UserMessage','content':[{'type':'text','text':'\n# Files mentioned by the user:\n\n## A.md: C:/p/A.md\n\nDistinguish instructions.\n\n## My request:\n做个 skill\n'}]}),
        ev('2026-11-01T01:00:02Z',{'type':'AgentMessage','phase':'commentary','content':[{'type':'Text','text':'先读文件'}]}),
        ev('2026-11-01T01:00:03Z',{'type':'CommandExecution','command':['pwsh.exe','-Command','Get-Content A.md'],'aggregated_output':'x'*5000,'exit_code':0}),
        ev('2026-11-01T01:00:04Z',{'type':'McpToolCall','server':'node_repl','tool':'js','arguments':{'code':'1+1','title':'算一下'},'result':{'content':[{'type':'text','text':'2'}],'isError':False}}),
        ev('2026-11-01T01:00:05Z',{'type':'Reasoning','summary_text':[]}),
        ev('2026-11-01T01:00:06Z',{'type':'AgentMessage','phase':'final_answer','content':[{'type':'Text','text':'完成'}]}),
    ]),encoding='utf-8')
    bc=r.exchange.to_v1(r.export('codex',str(fx),cx))
    assert len(bc['turns'])==1 and bc['turns'][0]['user']['text']=='附件：A.md（C:/p/A.md）\n\n做个 skill', bc['turns'][0]['user']
    assert [i['kind'] for i in bc['turns'][0]['items']]==['message','tool','tool','message'] and '已截断' in bc['turns'][0]['items'][1]['output']
    r.import_bundle(bc,args('claude',ch))
    rows=r.read(next(ch.glob('projects/*/'+str(r.uuid.uuid5(r.NS,'codex/'+bc['source']['session_id']))+'.jsonl')))
    blocks=[(x['type'],x['message']['content'] if isinstance(x['message']['content'],str) else x['message']['content'][0]['type']) for x in rows if x['type'] in ('user','assistant')]
    assert [k for _,k in blocks][1:]==['text','tool_use','tool_result','tool_use','tool_result','text'], blocks
    tu=[x['message']['content'][0] for x in rows if x['type']=='assistant' and x['message']['content'][0]['type']=='tool_use']
    assert tu[0]['name']=='Bash' and tu[0]['input']['command']=='Get-Content A.md' and tu[1]['name']=='mcp__node_repl__js'
    assert all(x['message']['model']=='claude-test-model' for x in rows if x['type']=='assistant')
    # changed source: plain re-import refused, --new-copy adds a separate snapshot session
    bc2=json.loads(json.dumps(bc)); bc2['turns'][0]['items'].append({'kind':'message','ts':'2026-11-01T01:00:07Z','text':'新内容'})
    try: r.import_bundle(bc2,args('claude',ch))
    except ValueError as e: assert '--new-copy' in str(e)
    else: raise AssertionError('来源变化保护失败')
    a2=args('claude',ch); a2.new_copy=True; r.import_bundle(bc2,a2)
    assert len(list(ch.glob('projects/*/*.jsonl')))==3
    # codex -> codex also supported
    r.import_bundle(b,args('codex',cx))
    cp.write_text(cp.read_text(encoding='utf-8')+'\n',encoding='utf-8')
    try: r.import_bundle(b,args('claude',ch))
    except ValueError as e: assert '拒绝覆盖' in str(e)
    else: raise AssertionError('续聊保护失败')
    assert list(cx.glob('rehome-backups/*/backup.json'))
print('PASS: Claude chain, desktop registry (once, inherits model), bidirectional roundtrip, native DB registration, idempotency, modified-target refusal, backups')
