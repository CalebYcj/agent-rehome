"""Stale database .jsonl paths must resolve compressed sources for ID and project use."""
import contextlib,io,json,sqlite3,sys,tempfile,types
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import agent_rehome as r,project_rehome as project,rollout_io
from platform_paths import source_rollout

SID='12345678-1234-4567-8123-123456789012'
ARCHIVED='aaaaaaaa-1234-4567-8123-123456789012'
TS='2026-11-01T00:00:00Z'
def compressed(path,sid,cwd):
    rows=[{'type':'session_meta','payload':{'id':sid,'cwd':str(cwd)}},
        {'type':'event_msg','timestamp':TS,'payload':{'type':'user_message','message':'synthetic historical request'}}]
    data=('\n'.join(json.dumps(row) for row in rows)+'\n').encode()
    frame=bytes.fromhex('28b52ffd')+b'\xa0'+len(data).to_bytes(4,'little')+((len(data)<<3)|1).to_bytes(3,'little')+data
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(frame)

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory).resolve();home=root/'data';source=root/'project';source.mkdir()
    originals=[home/'sessions'/'date'/('restored-'+SID+'.jsonl'),home/'archived_sessions'/('archived-'+ARCHIVED+'.jsonl')]
    for path,sid in zip(originals,(SID,ARCHIVED)):compressed(Path(str(path)+'.zst'),sid,source)
    with contextlib.closing(sqlite3.connect(home/'state_5.sqlite')) as db:
        db.executescript((Path(__file__).parent/'fixtures/codex_schema.sql').read_text(encoding='utf-8'))
        for archived,(path,sid) in enumerate(zip(originals,(SID,ARCHIVED))):
            db.execute('insert into threads(id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,sandbox_policy,approval_mode,archived,cli_version,first_user_message,memory_mode) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (sid,str(path),1,1,'fixture','fixture',str(source),'fixture','{}','fixture',archived,'fixture','fixture','enabled'))
        db.commit()
    decoder=types.SimpleNamespace(decompress=lambda data:data[12:])
    with patch.object(rollout_io.importlib,'import_module',return_value=decoder):
        for sid,path in zip((SID,ARCHIVED),originals):
            assert r.locate('codex',sid,home)==Path(str(path)+'.zst')
            assert len(r.exchange.to_v1(r.export('codex',sid,home,True))['turns'])==1
        with contextlib.redirect_stdout(io.StringIO()):project.pack('codex',source,root/'package',home)
        manifest=project.load_manifest(root/'package')
        assert len(manifest['conversations'])==2 and not manifest['skipped']
    # Copied data roots: old machine paths, including Windows paths on POSIX, are never read.
    for path in originals:
        relative=path.relative_to(home).as_posix()
        assert source_rollout(home,'X:/old-data/'+relative)==Path(str(path)+'.zst')
    assert source_rollout(home,'X:/obsolete/elsewhere/'+originals[0].name)==Path(str(originals[0])+'.zst')
    # Relative stored paths are relative to the chosen data root, not the process cwd.
    assert source_rollout(home,originals[0].relative_to(home))==Path(str(originals[0])+'.zst')
    def ambiguous(stored):
        try:source_rollout(home,stored)
        except ValueError as error:assert 'ambiguous' in str(error).lower() and '.zst' in str(error)
        else:raise AssertionError('Compressed/uncompressed pair accepted ambiguously')
    originals[0].write_text('{}\n',encoding='utf-8')
    ambiguous(originals[0]);ambiguous(str(originals[0])+'.zst')
    ambiguous('X:/old-data/'+originals[0].relative_to(home).as_posix())
    ambiguous('X:/obsolete/elsewhere/'+originals[0].name)
    try:r.locate('codex',SID,home)
    except ValueError as error:assert 'ambiguous' in str(error).lower()
    else:raise AssertionError('ID lookup bypassed ambiguity guard')
    try:
        with contextlib.redirect_stdout(io.StringIO()):project.pack('codex',source,root/'ambiguous-package',home)
    except ValueError as error:assert 'ambiguous' in str(error).lower()
    else:raise AssertionError('Project pack bypassed ambiguity guard')
    originals[0].unlink()
    assert source_rollout(home,originals[0])==Path(str(originals[0])+'.zst')
print('PASS: stale DB paths, archived export/project pack, relocation, basename fallback and pair ambiguity')
