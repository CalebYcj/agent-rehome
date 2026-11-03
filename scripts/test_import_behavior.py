"""Frozen pre-refactor native output oracle; capture is an explicit maintenance action."""
import argparse,base64,contextlib,copy,datetime as dt,gc,hashlib,io,json,re,runpy,sqlite3,sys,tempfile,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import agent_rehome as r,project_rehome as p
from platform_paths import sqlite_read_uri

SCRIPTS=Path(__file__).resolve().parent
SOURCE_IDS=['12345678-1234-4567-8123-123456789012','aaaaaaaa-1234-4567-8123-123456789012']
TS='2026-11-01T00:00:00Z'
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j9YQAAAAASUVORK5CYII=')

def normalize(value,root,redact_ids=True):
    if isinstance(value,dict):return {key:normalize(item,root,redact_ids) for key,item in value.items()}
    if isinstance(value,(tuple,list)):return [normalize(item,root,redact_ids) for item in value]
    if not isinstance(value,str):return value
    value=value.replace(root.as_uri(),'file:///<ROOT>')
    value=value.replace(re.sub(r'[^a-zA-Z0-9_-]','-',str(root)),'<ROOT-ENC>')
    for variant in sorted({str(root),str(root).lower(),root.as_posix(),root.as_posix().lower()},key=len,reverse=True):value=value.replace(variant,'<ROOT>')
    if '<ROOT>' in value:value=value.replace('\\\\?\\','').replace('\\','/')
    return re.sub(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b',lambda match:'uuid-'+hashlib.sha256(match.group().encode()).hexdigest()[:16],value) if redact_ids else value

def hashed(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()

def database(home):
    home.mkdir(parents=True)
    with contextlib.closing(sqlite3.connect(home/'state_5.sqlite')) as db:
        db.executescript((SCRIPTS/'fixtures/codex_schema.sql').read_text(encoding='utf-8'))
        db.execute('insert into projects values(?,?,?,?,?,?)',('existing-project','keep','{}',0,1,1))
        db.execute('insert into project_roots values(?,?,?)',('existing-project',0,'/fixture/unrelated'))
        db.execute('insert into threads(id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,sandbox_policy,approval_mode,cli_version,first_user_message,memory_mode) values(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('existing-thread','existing.jsonl',1,1,'fixture','fixture','/fixture/unrelated','keep','{}','fixture','fixture','keep','enabled'))
        db.commit()
    (home/'session_index.jsonl').write_text(json.dumps({'id':'existing-thread','thread_name':'keep','updated_at':TS})+'\n',encoding='utf-8')

def bundle(source='claude',large=False):
    turns=[{'user':{'ts':TS,'text':'synthetic request'},'items':[
        {'kind':'message','ts':TS,'text':'historical commentary','phase':'commentary'},
        {'kind':'tool','name':'Bash','args':{'command':'echo fixture'},'input':'echo fixture','output':'x'*70000 if large else 'fixture','ts':TS,'completed_ts':'2026-11-01T00:00:01Z'},
        {'kind':'tool','name':'Read','args':{'file_path':'fixture.txt'},'input':'{}','output':'historical file','is_error':True,'ts':'2026-11-01T00:00:02Z'},
        {'kind':'message','ts':'2026-11-01T00:00:03Z','text':'historical final','phase':'final_answer'}]}]
    if large:turns.append({'user':{'ts':'2026-11-01T00:00:04Z','text':'last request'},'items':[{'kind':'message','ts':'2026-11-01T00:00:05Z','text':'last answer'}]})
    return {'schema':'agent-transcript/v1','source':{'agent':source,'session_id':SOURCE_IDS[0],'path':'fixture'},'title':'behavior fixture','project':{'cwd':'old'},'turns':turns}

def snapshot(root,home,project):
    result={'jsonl':{},'sqlite':{}}
    def location(path):return normalize(str(path),root).replace('/home/','/<TARGET-DATA>/')
    for base in (home/'sessions',home/'projects',project/'.rehome/history'):
        for path in sorted(base.rglob('*.jsonl')) if base.exists() else []:
            records=[normalize(json.loads(line),root) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
            result['jsonl'][location(path)]={'records':len(records),'sha256':hashed(records)}
    index=home/'session_index.jsonl'
    if index.exists():result['index']=[normalize(json.loads(line),root) for line in index.read_text(encoding='utf-8').splitlines() if line.strip()]
    for path in sorted(home.rglob('*')):
        if not path.is_file() or 'state_5.sqlite' not in path.name:continue
        tables={}
        with contextlib.closing(sqlite3.connect(sqlite_read_uri(path),uri=True)) as db:
            for name in ('threads','projects','project_roots'):
                columns=[row[1] for row in db.execute('pragma table_info('+name+')')]
                rows=[dict(zip(columns,row)) for row in db.execute('select * from '+name+' order by 1,2')]
                normalized=[]
                for row in rows:
                    item=normalize(row,root)
                    if name=='threads' and row['id']!='existing-thread':
                        assert row['preview']==row['first_user_message'][:200]
                        # Validate real truncation first, then remove temporary-path-length effects.
                        item['preview']=item['first_user_message'][:200]
                    normalized.append(hashed(item))
                tables[name]={'rows':normalized}  # Each digest includes every column name and value.
        result['sqlite'][location(path)]=tables
    return result

def capture():
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory).resolve();original_uuid5=uuid.uuid5;clock=[0];random=[0]
        class Clock(dt.datetime):
            @classmethod
            def now(cls,tz=None):
                clock[0]+=1
                return cls(2026,11,3,tzinfo=dt.timezone.utc)+dt.timedelta(microseconds=clock[0])
        def uuid5(namespace,name):return original_uuid5(namespace,normalize(name,root,False))
        def uuid4():
            random[0]+=1
            return original_uuid5(r.NS,'fixture/random/'+str(random[0]))
        def args(project,home,to,budget=64000):
            return argparse.Namespace(cwd=str(project),target_home=str(home),to=to,dry_run=False,model='fixture-model',claude_model='fixture-model',claude_version='0.0.0-test',no_desktop=True,desktop_registry=None,new_copy=False,codex_context_budget=budget)
        result={}
        with patch.object(dt,'datetime',Clock),patch.object(uuid,'uuid5',uuid5),patch.object(uuid,'uuid4',uuid4),contextlib.redirect_stdout(io.StringIO()):
            for name,to,large in [('codex-single','codex',False),('codex-long','codex',True),('claude-single','claude',False)]:
                work=root/name;project=work/'project';project.mkdir(parents=True);home=work/'home'
                if to=='codex':database(home)
                data=bundle('claude' if to=='codex' else 'codex',large)
                if name=='codex-single':data['title']=''  # Preserve the legacy first-user-title fallback too.
                if not large:
                    image=work/'image.png';image.write_bytes(PNG)
                    data['turns'][0]['user']['attachments']=[{'image':True,'mime':'image/png','local_path':str(image)}]
                imported=r.import_bundle(copy.deepcopy(data),args(project,home,to,12000 if large else 64000))
                result[name]=snapshot(root,home,project)
                result[name]['context']={key:imported['context'][key] for key in ('policy','budget','prefix_turns','retained_turns')}
                if large:assert imported['context']['prefix_turns']>0
            work=root/'codex-project';source=work/'source';source.mkdir(parents=True);(source/'note.txt').write_text('fixture project',encoding='utf-8')
            source_home=work/'source-home';folder=source_home/'projects'/p.re.sub(r'[^a-zA-Z0-9_-]','-',str(source));folder.mkdir(parents=True)
            for sid in SOURCE_IDS:
                rows=[{'type':'user','sessionId':sid,'cwd':str(source),'version':'0.0.0-test','timestamp':TS,'message':{'content':[{'type':'text','text':'project request'},{'type':'image','source':{'type':'base64','media_type':'image/png','data':base64.b64encode(PNG).decode()}}]}},
                      {'type':'assistant','timestamp':'2026-11-01T00:00:01Z','message':{'content':[{'type':'text','text':'project answer'}]}}]
                (folder/(sid+'.jsonl')).write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows),encoding='utf-8')
            package=work/'package';p.pack('claude',source,package,source_home)
            home=work/'home';database(home);target=work/'target';state=p.restore(package,target,'codex',home,True,model='fixture-model')
            assert len(state['sessions'])==2
            result['codex-project']=snapshot(root,home,target)
        gc.collect()  # Close unreferenced legacy project-query connections before Windows temp cleanup.
        return result

if __name__=='__main__':
    capture_path=Path(sys.argv[sys.argv.index('--capture')+1]) if '--capture' in sys.argv else None
    initial_argv=list(sys.argv);initial_backend={key:value for key,value in vars(r.backend).items() if not key.startswith('__')};actual=capture()
    if capture_path:
        capture_path.write_text('"""WIN-S2 oracle captured before removing the legacy backend adapter. Do not regenerate implicitly."""\nEXPECTED = '+repr(actual)+'\n',encoding='utf-8')
        print('Captured pre-refactor baseline:',capture_path)
    else:
        expected=runpy.run_path(str(SCRIPTS/'fixtures/import_behavior.py'))['EXPECTED']
        assert actual==expected,'Native output differs from frozen pre-refactor oracle: '+json.dumps(actual,ensure_ascii=False)
        assert sys.argv==initial_argv,'Import mutated process command-line arguments'
        assert {key:value for key,value in vars(r.backend).items() if not key.startswith('__')}==initial_backend,'Import mutated backend module globals'
        print('PASS: frozen native outputs/index/SQLite rows/backups for Codex single/project/long compaction and Claude import; no argv mutation')
