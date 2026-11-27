import sys,json,tempfile,argparse,base64
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import agent_rehome as r,project_rehome as p
with tempfile.TemporaryDirectory() as td:
 d=Path(td); project=d/'source';project.mkdir();(project/'doc.md').write_text('附件全文',encoding='utf-8')
 for name in ('target','dist','node_modules'):
  (project/name).mkdir();(project/name/'junk').write_text('exclude')
 sid='12345678-1234-4567-8123-123456789012';ts='2026-11-01T00:00:00Z'
 def event(item):return {'timestamp':ts,'type':'event_msg','payload':{'type':'item_completed','item':item,'turn_id':'turn-a'}}
 rows=[{'type':'session_meta','payload':{'id':sid,'cli_version':'0.166.0','cwd':str(project)}},
 {'type':'response_item','payload':{'role':'user','content':[{'type':'input_text','text':'# AGENTS.md instructions'}]}},
 event({'type':'UserMessage','content':[{'type':'text','text':f'# Files mentioned by the user:\n\n## doc.md: {project.as_posix()}/doc.md\n\n## My request:\n看文件'}]}),
 event({'type':'McpToolCall','server':'a','tool':'b','arguments':{'long':'x'*5000},'result':{'content':[{'type':'text','text':'y'*5000}]}}),
 event({'type':'FileChange','changes':{'a':'diff'}}),event({'type':'UserMessage','content':[]})]
 src=d/'source.jsonl';src.write_text(''.join(json.dumps(x)+'\n' for x in rows))
 turns,_=r.export_codex(rows,sid,d,True)
 assert len(turns)==2 and 'AGENTS.md' not in turns[0]['user']['text']
 assert len(turns[0]['items'][0]['output'])==5000
 assert r.claude_tool_use(turns[0]['items'][0])[1]['long']=='x'*5000
 # Deleted clipboard images are recovered from their exact model turn, never model text.
 png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j9YQAAAAASUVORK5CYII=')
 rows[2]['payload']['item']['content'].append({'type':'local_image','path':str(d/'missing.png')})
 rows.insert(2,{'type':'response_item','payload':{'role':'user','internal_chat_message_metadata_passthrough':{'turn_id':'turn-a'},'content':[{'type':'input_text','text':'HARNESS_MUST_NOT_IMPORT'},{'type':'input_image','image_url':'data:image/png;base64,'+base64.b64encode(png).decode()}]}})
 src.write_text(''.join(json.dumps(x)+'\n' for x in rows))
 package=d/'package';p.pack('codex',project,package,d,[{'snapshot':str(src),'title':'测试 · 项目迁移测试'}])
 m=p.load_manifest(package)
 assert len(m['files'])==1 and len(m['attachments'])==2
 assert any((package/a['path']).read_bytes()==png for a in m['attachments'])
 assert any((package/a['path']).read_bytes()=='附件全文'.encode() for a in m['attachments'])
 dest=d/'dest';p.restore(package,dest,'claude',d/'home',True,claude_model='claude-test-model',claude_version='0.0.0-test')
 state=json.loads((dest/'.rehome/restore.json').read_text(encoding='utf-8'))
 assert state['sessions'][0]['title'].count(' · 迁移副本')==1
 rr=r.read(next((d/'home/projects').glob('*/*.jsonl')))
 assert sum(c.get('type')=='tool_use' for row in rr for c in row.get('message',{}).get('content',[]) if isinstance(c,dict))==2
 rows[0]['payload']['cli_version']='claude-import';src.write_text(''.join(json.dumps(x)+'\n' for x in rows))
 try:p.pack('codex',project,d/'bad',d,[{'snapshot':str(src),'title':'bad'}])
 except ValueError:pass
 else:raise AssertionError('imported source accepted')

# Continued imported Codex history (with live runtime events) is packable for return trips.
with tempfile.TemporaryDirectory() as td2:
 d2=Path(td2); proj2=d2/'proj'; proj2.mkdir(); (proj2/'a.txt').write_text('ok',encoding='utf-8')
 sid2='aaaaaaaa-1234-4567-8123-123456789012'; ts2='2026-11-24T00:00:00Z'
 r2=[
  {'type':'session_meta','payload':{'id':sid2,'cli_version':'claude-import','cwd':str(proj2)}},
  {'timestamp':ts2,'type':'event_msg','payload':{'type':'item_completed','item':{'type':'UserMessage','content':[{'type':'text','text':'hi'}]},'turn_id':'t1'}},
  {'timestamp':ts2,'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'hello'}]}},
  {'timestamp':ts2,'type':'event_msg','payload':{'type':'token_count','info':{}}},
 ]
 rp=d2/'rollout.jsonl'; rp.write_text(''.join(json.dumps(x)+'\n' for x in r2),encoding='utf-8')
 import sqlite3
 dbp=d2/'state_5.sqlite'; c=sqlite3.connect(str(dbp))
 c.execute('create table projects(id text,name text)'); c.execute('create table project_roots(project_id text,position integer,path text)')
 c.execute('create table threads(id text,rollout_path text,cwd text,project_id text)')
 c.execute('insert into projects values(?,?)',('p1','proj'))
 c.execute('insert into project_roots values(?,?,?)',('p1',0,str(proj2)))
 c.execute('insert into threads values(?,?,?,?)',(sid2,str(rp),'/other/new-chat','p1'))
 c.commit(); c.close()
 pkg2=d2/'pkg2'; p.pack('codex',proj2,pkg2,d2)
 assert len(p.load_manifest(pkg2)['conversations'])==1
print('PASS: explicit native sources, cache exclusion, UI-only turns, full tool data, file attachment, native cards, one suffix, imported-source rejection')
