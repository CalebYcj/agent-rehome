import json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import codex_project_registry as r
with tempfile.TemporaryDirectory() as t:
 h=Path(t);p=h/'.codex-global-state.json';old={'local-projects':{'old':{'rootPaths':['old']}},'other':{'keep':1},'thread-project-assignments':{'old-thread':{'projectId':'old'}}};p.write_text(json.dumps(old));before=p.read_bytes()
 r.live_home=lambda _:True;r.desktop_running=lambda:True
 called=[];original_native=r.native_project
 r.native_project=lambda home,cwd,ids: (called.append((str(home),cwd,ids)) or {'registered':False,'project_created':True,'project_id':'native-id','thread_binding_required':ids})
 result=r.register(h,'new','legacy-pid','测试',['t1','t2'])
 assert result['project_created'] and result['project_id']=='native-id' and called
 assert p.read_bytes()==before, 'live desktop must not be edited directly'
 r.native_project=original_native;r.live_home=lambda _:False
 result=r.register(h,'new','pid','测试',['t1','t2']);state=json.loads(p.read_text(encoding='utf-8'))
 assert state['other']==old['other'] and state['thread-project-assignments']['old-thread']==old['thread-project-assignments']['old-thread']
 assert state['thread-project-assignments']['t1']['projectId']=='pid'
 assert json.loads((Path(result['backup'])/p.name).read_text())==old
 assert r.register(h,'new','pid','测试',['t1','t2'])['changed']==False
 assert r.native_project(h,'new',['t1','t2'])['registered']==True
 try:r.register(h,'wrong','pid','测试',[])
 except ValueError:pass
 else:raise AssertionError('conflicting root accepted')
print('PASS: live registration delegates to native entry without rewriting state; native id recognition; offline preservation, backup, conflict refusal, idempotency')
