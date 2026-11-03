"""Codex project inventory accepts lexical and resolved project-root spellings."""
import contextlib,io,json,os,sqlite3,sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import project_rehome as p
from platform_paths import storage_path

@contextlib.contextmanager
def directory_alias(alias,target):
    try:alias.symlink_to(target,target_is_directory=True)
    except OSError as error:
        if os.name!='nt' or getattr(error,'winerror',None) not in (5,1314):raise
        alias.mkdir();original=Path.resolve
        def resolve(path,*args,**kwargs):return original(target/path.relative_to(alias),*args,**kwargs) if path.is_relative_to(alias) else original(path,*args,**kwargs)
        with patch.object(Path,'resolve',resolve):yield
    else:yield

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory).resolve();real=root/'physical';real.mkdir();(real/'file.md').write_text('fixture')
    alias=root/'linked';home=root/'data';home.mkdir()
    with directory_alias(alias,real),contextlib.closing(sqlite3.connect(home/'state_5.sqlite')) as db:
        db.executescript((Path(__file__).parent/'fixtures/codex_schema.sql').read_text(encoding='utf-8'))
        for index,cwd in enumerate((str(alias),str(real),str(alias)+'-unrelated')):
            sid=f'12345678-1234-4567-8123-{index:012d}'
            file=home/'sessions'/(sid+'.jsonl');file.parent.mkdir(exist_ok=True)
            rows=[{'type':'session_meta','payload':{'id':sid,'cwd':cwd,'cli_version':'fixture'}},
                {'type':'event_msg','timestamp':'2026-11-01T00:00:00Z','payload':{'type':'user_message','message':'historical alias fixture'}}]
            file.write_text('\n'.join(json.dumps(row) for row in rows),encoding='utf-8')
            stored=storage_path(cwd).upper() if os.name=='nt' else cwd
            db.execute('insert into threads(id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,sandbox_policy,approval_mode,cli_version,first_user_message,memory_mode) values(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (sid,str(file),1,1,'fixture','fixture',stored,'fixture','{}','fixture','fixture','fixture','enabled'))
        db.commit()
        with contextlib.redirect_stdout(io.StringIO()):p.pack('codex',alias,root/'package',home)
        manifest=p.load_manifest(root/'package')
        assert len(manifest['conversations'])==2,'Lexical Codex cwd was omitted'
        assert not manifest['skipped'] and len(manifest['files'])==1
print('PASS: Codex lexical/resolved project roots, Windows prefix/case rules, unrelated boundary')
