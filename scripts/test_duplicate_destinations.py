"""A migrated attachment may also be a project file: one destination, one copy."""
import contextlib,hashlib,io,json,re,shutil,sqlite3,sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import project_rehome as p

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory).resolve();source=root/'source';source.mkdir()
    data=b'synthetic attachment\n';sha=hashlib.sha256(data).hexdigest();rel='.rehome/attachments/'+sha+'.md'
    attachment=source/rel;attachment.parent.mkdir(parents=True);attachment.write_bytes(data)
    home=root/'claude-source';folder=home/'projects'/re.sub(r'[^a-zA-Z0-9_-]','-',str(source));folder.mkdir(parents=True)
    sid='12345678-1234-4567-8123-123456789012';ts='2026-11-01T00:00:00Z'
    rows=[{'type':'user','uuid':'fixture-user','timestamp':ts,'cwd':str(source),'sessionId':sid,'message':{'content':'Review '+str(attachment)}},
        {'type':'attachment','timestamp':ts,'attachment':{'type':'file','filename':str(attachment),'content':{'file':{'content':data.decode()}}}},
        {'type':'assistant','timestamp':ts,'message':{'content':[{'type':'text','text':'Historical acknowledgement.'}]}}]
    (folder/(sid+'.jsonl')).write_text('\n'.join(json.dumps(row) for row in rows)+'\n',encoding='utf-8')
    package=root/'package'
    with contextlib.redirect_stdout(io.StringIO()):p.pack('claude',source,package,home)
    manifest=p.load_manifest(package)
    assert len(manifest['files'])==len(manifest['attachments'])==1
    for to in ('codex','claude'):
        target_home=root/(to+'-data');target_home.mkdir();dest=root/(to+'-target');target=dest/rel
        if to=='codex':
            with contextlib.closing(sqlite3.connect(target_home/'state_5.sqlite')) as db:
                db.executescript((Path(__file__).parent/'fixtures/codex_schema.sql').read_text(encoding='utf-8'))
        kwargs=dict(home=target_home,no_desktop=True,convert=to=='claude',model='fixture-model',claude_model='fixture-model',claude_version='0.0.0-test')
        with contextlib.redirect_stdout(io.StringIO()):preview=p.restore(package,dest,to,dry_run=True,**kwargs)
        assert not dest.exists() and preview['deduplicated'][0]['source_count']==2
        copy=shutil.copy2;digest=p.r.digest
        with patch.object(p.shutil,'copy2',wraps=copy) as copies,patch.object(p.r,'digest',wraps=digest) as hashes,contextlib.redirect_stdout(io.StringIO()):state=p.restore(package,dest,to,**kwargs)
        assert len([call for call in copies.call_args_list if Path(call.args[1])==target])==1
        assert len([call for call in hashes.call_args_list if Path(call.args[0])==target])==1
        assert target.read_bytes()==data and len(list((dest/'.rehome/attachments').iterdir()))==1
        assert [f['path'] for f in state['files']].count(rel)==1
        record=state['deduplicated'][0]
        assert record['path']==rel and record['sha256']==sha and record['source_count']==2 and record['skipped_copies']==1
        assert set(record['source_paths'])=={'project/'+rel,'attachments/'+sha+'.md'}
        assert json.loads((dest/'.rehome/restore.json').read_text(encoding='utf-8'))['deduplicated']==state['deduplicated']
        canonical=json.loads(next((dest/'.rehome/exchange').rglob('*.json')).read_text(encoding='utf-8'))
        user=next(event for event in canonical['events'] if event['kind']=='user_message')
        assert user['attachments'][0]['local_path']==str(target)
        assert str(attachment) not in user['text'] and (target.as_posix() in user['text'] or str(target) in user['text'])
    # Both entries remain individually valid but disagree about the shared destination.
    bad=root/'different-content';shutil.copytree(package,bad);changed=p.load_manifest(bad)
    entry=changed['files'][0];(bad/entry['path']).write_bytes(b'different valid bytes\n')
    entry['sha256']=p.r.digest(bad/entry['path']);entry['bytes']=(bad/entry['path']).stat().st_size
    p.r.dump(bad/'manifest.json',changed)  # Supported v1 fixture avoids bypassing v2 hash checks.
    for to in ('codex','claude'):
        for dry_run in (True,False):
            dest=root/(to+'-conflict-'+str(dry_run))
            try:
                with contextlib.redirect_stdout(io.StringIO()):p.restore(bad,dest,to,home=root/(to+'-data'),no_desktop=True,convert=to=='claude',dry_run=dry_run)
            except ValueError as error:
                assert 'project/'+rel in str(error) and 'attachments/'+sha+'.md' in str(error)
            else:raise AssertionError('Conflicting content accepted')
            assert not dest.exists()
print('PASS: repeated project attachment, dry/live Codex and Claude conversion, unique copies/references, conflicting hashes rejected before writes')
