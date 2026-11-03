"""Declared source-root aliases relocate without resolving historical cwd values."""
import argparse,json,os,re,sys,tempfile,uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import claude_native as n,project_rehome as p

mac_rows=[{'cwd':'/var/fixture/project/中文'},{'cwd':'/private/var/fixture/project/中文/ep01'}]
mac_data=''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in mac_rows).encode('utf-8')
mapped=n.rewrite_cwd(mac_data,'/private/var/fixture/project','/target',aliases=['/var/fixture/project'])
assert [json.loads(line)['cwd'] for line in mapped.decode('utf-8').splitlines()]==['/target/中文','/target/中文/ep01']
assert json.loads(n.rewrite_cwd(b'{"cwd":"/src/link/child"}','/src','/target',aliases=['/src/link']))['cwd']=='/target/child'

@contextmanager
def directory_alias(alias,target):
    try:alias.symlink_to(target,target_is_directory=True)
    except OSError as error:
        if os.name!='nt' or getattr(error,'winerror',None) not in (5,1314):raise
        alias.mkdir();original=Path.resolve
        def resolve(path,*args,**kwargs):
            return original(target/path.relative_to(alias),*args,**kwargs) if path.is_relative_to(alias) else original(path,*args,**kwargs)
        with patch.object(Path,'resolve',resolve):yield
    else:yield

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);project=root/'real-project';project.mkdir();(project/'file.txt').write_text('fixture',encoding='utf-8')
    alias=root/'alias-project';home=root/'source-home';sid=str(uuid.uuid4());other=str(uuid.uuid4())
    with directory_alias(alias,project):
        lexical=Path(os.path.abspath(alias));physical=alias.resolve();outside=str(lexical)+'2/outside'
        folder=home/'projects'/re.sub(r'[^a-zA-Z0-9_-]','-',str(lexical));folder.mkdir(parents=True)
        rows=[{'type':'user','sessionId':sid,'cwd':str(lexical/'中文'),'version':'0.0.0-test','timestamp':'2026-11-01T00:00:00Z','message':{'content':'synthetic alias project'}},
              {'type':'assistant','cwd':str(physical/'中文/ep01'),'message':{'content':[{'type':'text','text':'historical output'}]}},
              {'type':'system','cwd':outside}]
        source=folder/(sid+'.jsonl');raw=''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows).encode('utf-8');source.write_bytes(raw)
        sub=folder/sid/'subagents';sub.mkdir(parents=True)
        (sub/'agent.jsonl').write_text(json.dumps({'type':'assistant','cwd':str(physical/'中文/ep01/assets'),'message':{'content':'side'}}),encoding='utf-8')
        # Auto-discovery must inventory sessions under both root spellings.
        second=home/'projects'/re.sub(r'[^a-zA-Z0-9_-]','-',str(physical));second.mkdir(parents=True,exist_ok=True)
        (second/(other+'.jsonl')).write_text(json.dumps(dict(rows[0],sessionId=other,cwd=str(physical))),encoding='utf-8')
        package=root/'package';p.pack('claude',alias,package,home,native=True)
        legacy=p.load_manifest(package);assert len(legacy['conversations'])==2
        directory=package/'sessions'/sid/'raw-native';snap=n.load(directory)
        assert snap['source']['cwd']==str(physical)
        assert set(snap['source']['cwd_aliases'])=={str(lexical),str(physical)}
        target=root/'target';args=argparse.Namespace(cwd=str(target),target_home=str(root/'target-home'),to='claude',dry_run=True,no_desktop=True,desktop_registry=None,allow_new_project=True)
        preview=n.restore(snap,args);assert preview['outside_cwd_rows']==1 and not target.exists()
        # Restore cannot query old directories, including on another computer.
        resolve=Path.resolve
        def reject_old(path,*args,**kwargs):
            if path.is_relative_to(lexical) or path.is_relative_to(physical):raise AssertionError('Historical source path resolved during restore')
            return resolve(path,*args,**kwargs)
        with patch.object(Path,'resolve',reject_old):state=p.restore(package,target,'claude',root/'target-home',True)
        output=next((root/'target-home').glob('projects/*/'+sid+'.jsonl'))
        actual=[json.loads(line) for line in output.read_text(encoding='utf-8').splitlines()]
        assert actual[0]['cwd']==str(target.resolve()/'中文')
        assert actual[1]['cwd']==str(target.resolve()/'中文/ep01') and actual[2]['cwd']==outside
        assert json.loads((output.with_suffix('')/'subagents/agent.jsonl').read_text(encoding='utf-8'))['cwd']==str(target.resolve()/'中文/ep01/assets')
        assert (target/'file.txt').read_text()=='fixture' and len(state['sessions'])==2
        # Alias validation cannot silently admit malformed manifest fields.
        invalid=dict(snap,source=dict(snap['source'],cwd_aliases='not-a-list'))
        try:n.plan(invalid,args)
        except ValueError as error:assert 'alias' in str(error).lower()
        else:raise AssertionError('Malformed cwd aliases accepted')
print('PASS: linked project root, original/resolved aliases and inventory, outside boundary, no restore-time source resolution, child paths, alias validation')
