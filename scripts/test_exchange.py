"""Canonical v2 events, loss accounting, directory references and v1 compatibility."""
import argparse,copy,json,sys,tempfile,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import exchange as x,agent_rehome as r,project_rehome as p

def rejected(fn):
    try:fn()
    except ValueError:return
    raise AssertionError('Invalid exchange data accepted')

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);sid=str(uuid.uuid4());ts='2026-11-01T00:00:00Z'
    rows=[{'type':'user','timestamp':ts,'sessionId':sid,'message':{'content':'合成主线\u2028段落分隔符'}},
        {'type':'assistant','timestamp':ts,'message':{'content':[{'type':'thinking','thinking':'internal'}, {'type':'redacted_thinking','data':'opaque'}, {'type':'text','text':'回答'}]}},
        {'type':'assistant','isSidechain':True,'agentId':'branch-a','timestamp':ts,'message':{'content':[{'type':'text','text':'侧支'}]}},
        {'type':'user','isMeta':True,'timestamp':ts,'message':{'content':'meta'}},
        {'type':'user','isCompactSummary':True,'timestamp':ts,'message':{'content':'summary'}},
        {'type':'file-history-snapshot','snapshot':{}},
        {'type':'system','subtype':'compact_boundary'},
        {'type':'assistant','timestamp':ts,'message':{'content':[{'type':'tool_use','name':'mcp__ccd_turn__update_plan','input':{}}]}},
        {'type':'user','message':{'content':[{'type':'document','source':{}}]}}]
    file=root/(sid+'.jsonl');file.write_text('\n'.join(json.dumps(row) for row in rows),encoding='utf-8')
    altered=copy.deepcopy(rows);altered[0]['message']['content']='source raced'
    rejected(lambda:x.raw_refs(file,altered))
    bundle=r.export('claude',str(file),root,True);assert bundle['schema']==x.SCHEMA
    kinds=[item['kind'] for item in bundle['losses']]
    for kind in ('thinking','redacted_thinking','isSidechain','isMeta','isCompactSummary','file-history-snapshot','native_compaction','mcp__ccd_turn__update_plan','file_attachment'):assert kinds.count(kind)==1,kinds
    assert len(bundle['losses'])==9 and all(item['raw_ref']['line']>0 for item in bundle['losses'])
    assert any(e['branch']=='branch-a' for e in bundle['events']) and len(x.to_v1(bundle)['turns'])==1
    assert any(e['kind']=='reasoning' and e['visibility']=='encrypted' for e in bundle['events'])
    unknown=copy.deepcopy(bundle);unknown['events'].append({'id':'unknown','seq':len(unknown['events']),'parent_id':None,'kind':'future','ts':ts,'branch':'main','raw_ref':None})
    rejected(lambda:x.validate(unknown))
    unknown['losses'].append({'event':'unknown','kind':'future','reason':'unsupported_by_target','action':'dropped'});unknown['losses_summary']=x.loss_summary(unknown['losses']);x.validate(unknown)
    # An unknown kind may not borrow another kind's loss through a shared raw_ref.
    borrowed=next(l for l in bundle['losses'] if l.get('raw_ref'));sneaky=copy.deepcopy(bundle)
    sneaky['events'].append({'id':'sneaky','seq':len(sneaky['events']),'parent_id':None,'kind':'future','ts':ts,'branch':'main','raw_ref':borrowed['raw_ref']})
    rejected(lambda:x.validate(sneaky))
    unaccounted=copy.deepcopy(bundle);unaccounted['losses']=[];unaccounted['losses_summary']={};rejected(lambda:x.validate(unaccounted))
    codexsid=str(uuid.uuid4());codex=root/('rollout-'+codexsid+'.jsonl')
    event=lambda item:{'type':'event_msg','timestamp':ts,'payload':{'type':'item_completed','item':item}}
    codexrows=[{'type':'session_meta','payload':{'id':codexsid}},event({'type':'UserMessage','content':[{'type':'text','text':'hello'}]}),event({'type':'Reasoning'}),event({'type':'ContextCompaction'}),{'type':'compacted','payload':{'encrypted_content':'opaque'}},event({'type':'AgentMessage','content':[{'type':'text','text':'world'}]})]
    codex.write_text('\n'.join(json.dumps(row) for row in codexrows),encoding='utf-8')
    cb=r.export('codex',str(codex),root,True)
    assert {a['kind'] for a in cb['losses']}=={'Reasoning','ContextCompaction','compacted'}
    assert any(a['reason']=='encrypted' for a in cb['losses'])
    # v1 upgrade has stable IDs and unknown completion stays unknown.
    legacy=x.to_v1(bundle);a=x.upgrade_v1(legacy);b=x.upgrade_v1(legacy)
    assert a==b and x.to_v1(a)==legacy
    project=root/'project';project.mkdir();(project/'main.txt').write_text('fixture',encoding='utf-8')
    # Canonical project streams, explicit loss digest, branch refs and exact read/write roundtrip.
    package=root/'package';p.pack('claude',project,package,root,[{'snapshot':str(file),'title':'test'}])
    manifest=json.loads((package/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['schema']==x.SCHEMA and 'conversations' not in manifest
    assert manifest['sessions'][0]['events']['path'].endswith('/events.jsonl') and manifest['losses_summary']
    projected=p.load_manifest(package);again=root/'again';again.mkdir();x.write_project(again,dict(projected,created_at=ts))
    assert p.load_manifest(again)['conversations']==projected['conversations']
    dest=root/'dest';home=root/'target'
    state=p.restore(package,dest,'claude',home,True,convert=True,claude_model='fixture',claude_version='0.0.0-test')
    assert state['losses_summary']==manifest['losses_summary'] and state['sessions'][0]['losses_summary']
    # Old v1 package still restores when same-agent conversion is explicitly requested.
    v1=root/'v1';p.pack('claude',project,v1,root,[{'snapshot':str(file),'title':'test'}],format_version=1)
    p.restore(v1,root/'v1-dest','claude',root/'v1-home',True,convert=True,claude_model='fixture',claude_version='0.0.0-test')
    rejected(lambda:p.restore(package,root/'no-convert','claude',root/'unused',True))
    assert not (root/'no-convert').exists()
    stream=package/manifest['sessions'][0]['events']['path'];stream.write_bytes(stream.read_bytes()+b'\n')
    rejected(lambda:p.load_manifest(package))
print('PASS: v2 losses/refs/branches, encrypted compaction, unknown-event refusal, deterministic v1 adapter, v2 project roundtrip, result loss summary, v1 restore, hash tamper refusal')
