"""Host-independent cases for macOS/POSIX paths and copied Windows histories."""
import argparse, json, os, sqlite3, sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from platform_paths import storage_path,path_key,portable_name,portable_suffix,remap_text,sqlite_read_uri,source_rollout
from doctor import inspect
import codex_backend as backend
import project_rehome as projects
import make_smoke_bundle
from unittest.mock import patch

assert storage_path('/tmp/中文 project','darwin')=='/tmp/中文 project'
assert storage_path('/tmp/中文 project','linux')=='/tmp/中文 project'
assert storage_path('C:\\fixture\\工程','win32')=='\\\\?\\C:\\fixture\\工程'
assert storage_path('\\\\server\\share\\project','win32')=='\\\\?\\UNC\\server\\share\\project'
assert path_key('\\\\?\\C:\\FIXTURE\\p')==path_key('c:/fixture/p')
assert path_key('/tmp/Project')!=path_key('/tmp/project')
assert portable_name('C:\\fixture\\图片.png')=='图片.png'
assert portable_suffix('C:\\fixture\\图片.png')=='.png'
assert remap_text('C:/fixture/p/a.md and C:\\fixture\\p\\a.md','C:\\fixture\\p','/tmp/new')=='/tmp/new/a.md and /tmp/new/a.md'
assert remap_text('C:/fixture/project-other/a','C:/fixture/project','/tmp/new')=='C:/fixture/project-other/a'
try: storage_path('C:\\fixture','darwin')
except ValueError: pass
else: raise AssertionError('Foreign destination accepted')

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);dbpath=root/'中文 # % ? data.sqlite'
    # A question mark is illegal in Windows filenames; URI escaping still gets tested for #/%/Unicode.
    if os.name=='nt': dbpath=root/'中文 # % data.sqlite'
    db=sqlite3.connect(dbpath);db.execute('create table example(value text)');db.commit();db.close()
    db=sqlite3.connect(sqlite_read_uri(dbpath),uri=True);assert db.execute('select count(*) from example').fetchone()[0]==0;db.close()
    assert '%23' in sqlite_read_uri(dbpath) and '%25' in sqlite_read_uri(dbpath)
    rollout=root/'sessions/2000/01/01/fixture.jsonl';rollout.parent.mkdir(parents=True);rollout.write_text('{}')
    assert source_rollout(root,'C:\\old\\sessions\\2000\\01\\01\\fixture.jsonl')==rollout.resolve()
    with patch.object(sys,'platform','darwin'):
        assert backend.long_path('/tmp/project')=='/tmp/project'
    report=inspect(root,system='darwin',codex_home=root/'cx',claude_home=root/'ch')
    assert report['read_only'] and not report['native_resume_verified']
    assert len(report['claude']['desktop_candidates'])==2
    assert not (root/'Library').exists(), 'diagnostics must not initialize application directories'
    source=root/'source';source.mkdir();(source/'run.sh').write_text('echo fixture\n')
    (source/'.DS_Store').write_text('excluded metadata')
    package=root/'package';projects.pack('claude',source,package,root/'empty-source-home',format_version=1)
    manifest=json.loads((package/'manifest.json').read_text(encoding='utf-8'))
    assert len(manifest['files'])==1
    manifest['files'][0]['permissions']=0o755
    (package/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    restored=root/'restored';projects.restore(package,restored,'claude',root/'empty-dest-home',True)
    if os.name!='nt': assert (restored/'run.sh').stat().st_mode & 0o777==0o755
    manifest['files'][0]['permissions']=0o4755
    (package/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    try: projects.restore(package,root/'unsafe','claude',root/'empty-dest-home',True)
    except ValueError as error: assert 'permissions' in str(error)
    else: raise AssertionError('Special permission bits accepted')
    assert not (root/'unsafe').exists()
    for long in (False,True):
        output=root/('long.json' if long else 'short.json')
        with patch.object(sys,'argv',['make_smoke_bundle',str(output),*(['--long'] if long else [])]): make_smoke_bundle.main()
        bundle=json.loads(output.read_text(encoding='utf-8'));projects.r.validate(bundle)
        assert len(bundle['turns'])==(10 if long else 1)
print('PASS: POSIX/Windows storage, UNC, foreign names, case-sensitive POSIX paths, escaped SQLite URI, copied rollouts, read-only macOS candidates')
