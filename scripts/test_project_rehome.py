import sys,tempfile,json,argparse,base64,sqlite3
from contextlib import closing
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import project_rehome as p, agent_rehome as r
with tempfile.TemporaryDirectory() as tmp:
 d=Path(tmp).resolve(); source=d/'source'; source.mkdir(); (source/'hello.txt').write_text('中文 project',encoding='utf-8'); (source/'.env').write_text('DO_NOT_COPY'); (source/'.rehome').mkdir(); (source/'.rehome/restore.json').write_text('{"old":true}')
 ch=d/'claude'; enc=p.re.sub(r'[^a-zA-Z0-9_-]','-',str(source)); folder=ch/'projects'/enc;folder.mkdir(parents=True)
 sid='12345678-1234-4567-8123-123456789012'; ts='2026-11-01T00:00:00Z'
 png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j9YQAAAAASUVORK5CYII=')
 rows=[{'type':'user','uuid':'u','timestamp':ts,'cwd':str(source),'sessionId':sid,'message':{'content':[{'type':'image','source':{'type':'base64','media_type':'image/png','data':base64.b64encode(png).decode()}}]}},{'type':'assistant','timestamp':ts,'message':{'content':[{'type':'text','text':'看到了图片'}]}}]
 rows.append({'type':'user','uuid':'u2','timestamp':'2026-11-01T00:00:02Z','cwd':str(source),'sessionId':sid,'message':{'content':'[文件]('+source.as_posix()+'/hello.txt)'}})
 rows[0]['message']['content'].append(json.loads(json.dumps(rows[0]['message']['content'][0])))
 (folder/(sid+'.jsonl')).write_text('\n'.join(json.dumps(x) for x in rows),encoding='utf-8')
 pack=d/'pack';p.pack('claude',source,pack,ch); m=p.load_manifest(pack)
 assert len(m['conversations'])==1 and m['conversations'][0]['turns'][0]['user']['attachments'][0]['image']
 assert len(m['attachments'])==1 and len(m['conversations'][0]['turns'][0]['user']['attachments'])==2,'Repeated image bytes must use one asset and retain both occurrences'
 assert not (pack/'project/.env').exists()
 assert not (pack/'project/.rehome/restore.json').exists()
 target=d/'target';p.restore(pack,target,'claude',d/'dest-home',True,claude_model='claude-test-model',claude_version='0.0.0-test',convert=True)
 assert (target/'hello.txt').read_text(encoding='utf-8')=='中文 project'
 dest=next((d/'dest-home/projects').glob('*/*.jsonl')); rr=r.read(dest)
 assert rr[0]['message']['content'][1]['type']=='image'
 assert base64.b64decode(rr[0]['message']['content'][1]['source']['data'])==png
 assert any(target.as_posix()+'/hello.txt' in str(x.get('message',{}).get('content','')) for x in rr)
 assert not any(source.as_posix()+'/hello.txt' in str(x.get('message',{}).get('content','')) for x in rr)
 assert not (target/'.rehome/NEXT_STEPS.md').exists()
 assert 'user_next_steps' not in json.loads((target/'.rehome/restore.json').read_text(encoding='utf-8'))
 reg=d/'registry';reg.mkdir()
 desktop=d/'desktop-target'
 options={'claude_model':'claude-test-model','claude_version':'0.0.0-test','convert':True,'desktop_registry':str(reg)}
 preview=p.restore(pack,desktop,'claude',d/'desktop-home',dry_run=True,**options)
 assert 'user_next_steps' not in preview and not desktop.exists()
 result=p.restore(pack,desktop,'claude',d/'desktop-home',**options)
 steps=result['user_next_steps']
 assert steps['options']==['已重启，继续','稍后再说'] and steps['session_titles']
 guide=(desktop/'.rehome/NEXT_STEPS.md').read_text(encoding='utf-8')
 for text in ('重启 Claude','Cmd+Q','托盘','信任此文件夹',str(desktop),steps['first_message'],steps['session_titles'][0]):
  assert text in guide
 assert json.loads((desktop/'.rehome/restore.json').read_text(encoding='utf-8'))['user_next_steps']==steps
 for registered in (False,True):
  codex_home=d/f'codex-home-{registered}';codex_home.mkdir()
  with closing(sqlite3.connect(codex_home/'state_5.sqlite')) as db:
   db.executescript((Path(__file__).parent/'fixtures/codex_schema.sql').read_text(encoding='utf-8'))
  codex_target=d/f'codex-target-{registered}'
  with patch('codex_project_registry.register',return_value={'registered':registered}):
   codex=p.restore(pack,codex_target,'codex',codex_home,model='synthetic-model')
  assert ('user_next_steps' in codex) is not registered
  guide=codex_target/'.rehome/NEXT_STEPS.md'
  assert guide.exists() is not registered
  if not registered:
   assert '信任此文件夹' in guide.read_text(encoding='utf-8')
   assert codex['user_next_steps']['options'][0]=='已打开，继续'
 blank=d/'blank-title'; buffer=__import__('io').StringIO()
 with __import__('contextlib').redirect_stdout(buffer):
  p.pack('claude',source,blank,ch,[{'snapshot':str(folder/(sid+'.jsonl')),'title':'  '}],native=True)
 assert json.loads(buffer.getvalue().splitlines()[-1])['empty_titles']==1
 loaded=p.load_manifest(blank)['conversations'][0]['title']
 assert loaded.strip() and loaded!='  '
 assert p.restore_title('  ',sid,'fixture question')=='fixture question'
 assert p.restore_title('',sid)==sid[:8]
 assert p.restore_title('example · 新副本 [old]',sid,destination=d/'fresh')=='example · 新副本 [fresh]'
 copied=p.restore(blank,d/'fresh','claude',d/'copy-home',True,new_copy=True)
 assert copied['sessions'][0]['title'].endswith(' · 新副本 [fresh]')
 (pack/'project/hello.txt').write_text('tampered')
 try: p.restore(pack,d/'bad','claude',d/'dest-home2',True,convert=True)
 except ValueError as e: assert 'integrity' in str(e)
 else: raise AssertionError('tamper accepted')
 assert not (d/'bad').exists()
 for rel in ('../evil','C:/evil','/evil','a\\b'):
  try:p.safe(d,rel)
  except ValueError:pass
  else:raise AssertionError('unsafe path accepted')
# Image bytes in this test are synthetic.
print('PASS: project files, excluded credentials, image-only user, image byte roundtrip, path containment, tamper refusal before import')
