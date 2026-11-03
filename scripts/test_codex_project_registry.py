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

# Native sidebar membership can succeed while runtime cwd drifts after continuation.
import sqlite3
from contextlib import closing
from check_codex_binding import inspect
with tempfile.TemporaryDirectory() as directory:
 home=Path(directory);rollout=home/'rollout.jsonl';target='/fixture/project'
 rollout.write_text(json.dumps({'type':'session_meta','payload':{'id':'fixture-thread','cwd':target}})+'\n')
 with closing(sqlite3.connect(home/'state_5.sqlite')) as db:
  db.execute('create table threads(id text,cwd text,rollout_path text,project_id text)')
  db.execute('insert into threads values(?,?,?,?)',('fixture-thread',target,str(rollout),'sidebar-id'))
  db.commit()
 before=rollout.read_bytes();assert inspect(home,'fixture-thread',target)['binding_matches']
 with closing(sqlite3.connect(home/'state_5.sqlite')) as db:
  db.execute('update threads set cwd=?',('/fixture/new-chat',));db.commit()
 result=inspect(home,'fixture-thread',target)
 assert not result['binding_matches'] and result['session_meta_cwd_matches']
 assert not result['native_project_membership_verified'] and not result['continuation_persistence_verified']
 assert rollout.read_bytes()==before
 # Correcting the current database alone must not erase the observed historical drift.
 with closing(sqlite3.connect(home/'state_5.sqlite')) as db:
  db.execute('update threads set cwd=?',(target,));db.commit()
 with rollout.open('a') as stream:
  stream.write(json.dumps({'type':'turn_context','payload':{'cwd':'/fixture/new-chat'}})+'\n')
 result=inspect(home,'fixture-thread',target)
 assert result['binding_matches'] and result['latest_recorded_context_cwd_matches'] is False
 assert not result['continuation_persistence_verified']
 # A supported alternate session identifier and a copied data root still work.
 copied=home/'copied/sessions/2000/01/01/fixture.jsonl';copied.parent.mkdir(parents=True)
 copied.write_text(json.dumps({'type':'session_meta','payload':{'session_id':'fixture-thread','cwd':target}})+'\n')
 copied_home=home/'copied'
 with closing(sqlite3.connect(copied_home/'state_5.sqlite')) as db:
  db.execute('create table threads(id text,cwd text,rollout_path text,project_id text)')
  db.execute('insert into threads values(?,?,?,?)',('fixture-thread',target,'C:\\fixture\\sessions\\2000\\01\\01\\fixture.jsonl','unverified-id'));db.commit()
 assert inspect(copied_home,'fixture-thread',target)['binding_matches']
 # Conflicting IDs cannot be treated as the selected thread even with a correct cwd.
 copied.write_text(json.dumps({'type':'session_meta','payload':{'id':'other-thread','session_id':'fixture-thread','cwd':target}})+'\n')
 assert not inspect(copied_home,'fixture-thread',target)['binding_matches']
print('PASS: continuation cwd drift detected without treating project IDs as native membership proof')
