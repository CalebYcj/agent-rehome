import sys,tempfile,json,argparse,base64
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
