"""Append integrity, scoped compensation, bounded locking and online/offline parity."""
import argparse,json,sqlite3,sys,tempfile,time,uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import codex_relocate as n

def failure(fn,error=ValueError):
    try:fn()
    except error:pass
    else:raise AssertionError('Expected failure')

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);project=root/'project';project.mkdir();sid=str(uuid.uuid4())
    data=(json.dumps({'type':'session_meta','payload':{'id':sid,'session_id':sid,'cwd':str(project),'timestamp':'2026-11-01T00:00:00Z'}})+'\n').encode()
    snap={'schema':n.SCHEMA,'source':{'agent':'codex','session_id':sid,'cwd':str(project)},'title':'runtime fixture','thread':{},'files':[{'data':data,'sha256':n.c.sha(data)}]}
    old=b'{"id":"unrelated","thread_name":"keep"}\r\n'
    def setup(name):
        home=root/name;home.mkdir()
        with closing(sqlite3.connect(home/'state_5.sqlite')) as db:db.executescript((Path(__file__).parent/'fixtures/codex_schema.sql').read_text())
        (home/'session_index.jsonl').write_bytes(old)
        return home,argparse.Namespace(to='codex',cwd=str(project),target_home=str(home),dry_run=False,new_copy=False,no_desktop=True)
    def empty(home):
        with closing(sqlite3.connect(home/'state_5.sqlite')) as db:assert db.execute('select count(*) from threads').fetchone()[0]==0
        assert not list((home/'sessions').rglob('*.jsonl'))
    for online in (False,True):
        home,args=setup('online' if online else 'offline')
        with patch('codex_project_registry.desktop_running',return_value=online):result=n.restore(snap,args)
        content=(home/'session_index.jsonl').read_bytes()
        assert content.startswith(old) and json.loads(content[len(old):])['id']==sid
        assert result['desktop_project_registry']['thread_binding_required']==[sid]
        assert json.loads((Path(result['backup'])/'manifest.json').read_text())['status']=='committed'
    # A writer changes the prefix before our append. Refuse without restoring its bytes.
    home,args=setup('changed-before');real_append=n._append_index
    def changed_before(index,original,additions,receipt):
        index.write_bytes(b'{"id":"foreign-change"}\n');return real_append(index,original,additions,receipt)
    with patch.object(n,'_append_index',side_effect=changed_before):failure(lambda:n.restore(snap,args))
    empty(home);assert (home/'session_index.jsonl').read_bytes()==b'{"id":"foreign-change"}\n'
    # Prefix mutation after append: remove only our intact EOF block, retaining foreign prefix.
    home,args=setup('changed-after');real_verify=n._verify_append;mutated=[False]
    def changed_after(index,original,block,receipt):
        if not mutated[0]:
            index.write_bytes(index.read_bytes().replace(b'keep',b'edit',1));mutated[0]=True
        return real_verify(index,original,block,receipt)
    with patch.object(n,'_verify_append',side_effect=changed_after):failure(lambda:n.restore(snap,args))
    empty(home);assert (home/'session_index.jsonl').read_bytes()==old.replace(b'keep',b'edit')
    journal=json.loads(next((home/'rehome-backups').glob('*/manifest.json')).read_text())
    assert journal['status']=='rolled-back' and journal['index_compensation']=='owned-eof-block-removed'
    # A concurrent append after our complete row is accepted without touching it.
    home,args=setup('foreign-append');foreign=b'{"id":"foreign-tail"}\n';added=[False]
    def append_foreign(index,original,block,receipt):
        if not added[0]:
            with index.open('ab') as stream:stream.write(foreign)
            added[0]=True
        return real_verify(index,original,block,receipt)
    with patch.object(n,'_verify_append',side_effect=append_foreign):n.restore(snap,args)
    assert (home/'session_index.jsonl').read_bytes().startswith(old) and (home/'session_index.jsonl').read_bytes().endswith(foreign)
    # If rollback is necessary AND foreign bytes follow ours, do not truncate foreign data.
    home,args=setup('unsafe-compensation');added[0]=False
    def corrupt_with_foreign(index,original,block,receipt):
        if not added[0]:index.write_bytes(index.read_bytes().replace(b'keep',b'edit',1)+foreign);added[0]=True
        return real_verify(index,original,block,receipt)
    with patch.object(n,'_verify_append',side_effect=corrupt_with_foreign):failure(lambda:n.restore(snap,args))
    empty(home);assert (home/'session_index.jsonl').read_bytes().endswith(foreign)
    assert json.loads(next((home/'rehome-backups').glob('*/manifest.json')).read_text())['status']=='database-rolled-back-files-need-review'
    # Reserved writer lock: bounded wait, no rollout/index mutation; backup/journal retained.
    home,args=setup('locked')
    with closing(sqlite3.connect(home/'state_5.sqlite')) as lock:
        lock.execute('begin immediate');start=time.monotonic()
        with patch.object(n,'LOCK_WAIT_SECONDS',0.08):failure(lambda:n.restore(snap,args),(sqlite3.OperationalError,TimeoutError))
        assert time.monotonic()-start<1.5;lock.rollback()
    empty(home);assert (home/'session_index.jsonl').read_bytes()==old
print('PASS: online/offline append, pre/post mutation, scoped EOF compensation, foreign suffix preservation, bounded lock timeout')
