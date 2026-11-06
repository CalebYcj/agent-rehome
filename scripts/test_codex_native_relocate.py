"""Native bytes, identity/lineage refusal, batch compensation and public routing."""
import argparse,copy,json,sqlite3,sys,tempfile,uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import codex_relocate as n,project_rehome as p,agent_rehome as r

def home(path):
    path.mkdir()
    with closing(sqlite3.connect(path/'state_5.sqlite')) as db:db.executescript((Path(__file__).parent/'fixtures/codex_schema.sql').read_text())
    return path

def refuses(fn,fragment):
    try:fn()
    except ValueError as error:assert fragment in str(error),str(error)
    else:raise AssertionError('Unsafe operation accepted')

with tempfile.TemporaryDirectory() as directory:
    # plan() resolves target roots; use the same identity for byte-reversal assertions.
    # macOS /var -> /private/var (or Windows junction TMP) otherwise mixes two roots.
    root=Path(directory).resolve();source_home=home(root/'source-home');target_home=home(root/'target-home')
    source_project=root/'source';source_project.mkdir();(source_project/'main.txt').write_text('fixture')
    dest=root/'dest';dest.mkdir();sid=str(uuid.uuid4());ts='2026-11-01T00:00:00Z'
    ancestor=str(uuid.uuid4())
    rows=[{'type':'session_meta','payload':{'id':sid,'session_id':sid,'forked_from_id':ancestor,'cwd':str(source_project),'cli_version':'0.166.0','timestamp':ts}},
        {'type':'turn_context','payload':{'cwd':str(source_project/'sub'),'instructions':'body unchanged'}},
        {'type':'response_item','payload':{'type':'reasoning','encrypted_content':'opaque/+==','summary':[{'text':'private fixture'}]}},
        {'type':'compacted','payload':{'message':'fixture compacted','encrypted_content':'opaque2=='}},
        {'type':'event_msg','payload':{'type':'item_completed','thread_id':sid,'item':{'type':'UserMessage','content':[{'type':'text','text':str(source_project)}]}}},
        {'type':'event_msg','payload':{'type':'thread_settings_applied','thread_id':sid,'cwd':str(source_project),'runtime_workspace_roots':[str(source_project)]}},
        {'type':'response_item','payload':{'type':'function_call','call_id':'fixture','arguments':json.dumps({'cwd':'unchanged','session_id':sid})}},
        {'type':'response_item','payload':{'type':'function_call_output','call_id':'fixture','output':'original output '+sid}}]
    data=b'\xef\xbb\xbf'+('\r\n'.join(json.dumps(row,ensure_ascii=False) for row in rows)+'\r\n\r\n').encode()
    file=source_home/('rollout-'+sid+'.jsonl');file.write_bytes(data)
    snap=n.snapshot(file,source_home);package=root/'session-package';n.pack(snap,package);loaded=n.load(package)
    assert snap['title']==str(source_project)[:60]
    args=argparse.Namespace(to='codex',target_home=str(target_home),cwd=str(dest),dry_run=True,new_copy=False)
    n.restore(loaded,args);assert not (target_home/'sessions').exists()
    args.dry_run=False;result=n.restore(loaded,args);output=next((target_home/'sessions').rglob('*.jsonl')).read_bytes()
    assert (target_home/'sessions/2026/11/01'/('rollout-2026-11-01T00-00-00-'+sid+'.jsonl')).is_file()
    assert n.rewrite(output,dict(snap['source'],cwd=str(dest)),str(source_project),sid)==data
    assert output==n.rewrite(data,snap['source'],str(dest),sid)
    # A noncanonical request is accepted, but its stored metadata uses the resolved cwd.
    alias_args=copy.copy(args);alias_args.target_home=str(home(root/'alias-target-home'))
    alias_args.cwd=str(dest/'..'/dest.name)
    _,canonical_cwd,alias_writes,_=n.plan(loaded,alias_args)
    assert canonical_cwd==str(dest.resolve()) and alias_writes[0][1]==output
    assert n.rewrite(alias_writes[0][1],dict(snap['source'],cwd=canonical_cwd),str(source_project),sid)==data
    assert file.read_bytes()==data
    assert n.metadata(output)[0]['id']==n.metadata(output)[0]['session_id']==sid
    missing=copy.deepcopy(snap);missing_rows=copy.deepcopy(rows);missing_rows[0]['payload'].pop('timestamp')
    missing['files'][0]['data']=''.join(json.dumps(row)+'\n' for row in missing_rows).encode();missing['files'][0]['sha256']=n.c.sha(missing['files'][0]['data'])
    probe=copy.copy(args);probe.target_home=str(source_home)
    refuses(lambda:n.plan(missing,probe),'timestamp is required')
    missing_rows[0]['timestamp']=ts
    missing['files'][0]['data']=''.join(json.dumps(row)+'\n' for row in missing_rows).encode();missing['files'][0]['sha256']=n.c.sha(missing['files'][0]['data'])
    assert n.plan(missing,probe)[2][0][0].parent==source_home/'sessions/2026/11/01'
    with closing(sqlite3.connect(target_home/'state_5.sqlite')) as db:
        assert db.execute('select id,approval_mode,memory_mode from threads').fetchone()==(sid,'on-request','disabled')
    refuses(lambda:n.restore(loaded,args),'ID conflict')
    args.new_copy=True;copy_result=n.restore(loaded,args);assert copy_result['id']!=sid
    copied=n.metadata(next((target_home/'sessions').rglob('*'+copy_result['id']+'.jsonl')).read_bytes())[1]
    assert copied[4]['payload']['thread_id']==copy_result['id'] and copied[4]['payload']['item']==rows[4]['payload']['item']
    assert copied[0]['payload']['id']==copied[0]['payload']['session_id']==copy_result['id']
    assert copied[0]['payload']['forked_from_id']==ancestor and copied[6:]==rows[6:]
    # Only a metadata identity equal to this source is owned by the copied thread.
    foreign=copy.deepcopy(rows);foreign[0]['payload']['session_id']=ancestor
    assert n.metadata(n.rewrite(json.dumps(foreign[0]).encode(),snap['source'],str(dest),copy_result['id']))[0]['session_id']==ancestor
    # Shared index reader: last matching row wins, including a blank row fallback.
    (source_home/'session_index.jsonl').write_text(''.join(json.dumps(entry)+'\n' for entry in [
        {'id':sid,'thread_name':'older fixture title'},{'id':str(uuid.uuid4()),'thread_name':'unrelated'},
        {'id':sid,'thread_name':'latest fixture title'}]),encoding='utf-8')
    assert n.snapshot(file,source_home)['title']=='latest fixture title'
    assert r.export_codex(rows,sid,source_home)[1]=='latest fixture title'
    # Source database title is lower priority; copied DB thread row is harmless test data.
    database_title='database fixture title'
    with closing(sqlite3.connect(source_home/'state_5.sqlite')) as db:
        with closing(sqlite3.connect(target_home/'state_5.sqlite')) as target:
            columns=[column[1] for column in target.execute('pragma table_info(threads)')]
            record=list(target.execute('select * from threads where id=?',(sid,)).fetchone());record[columns.index('title')]=database_title
        db.execute('insert into threads values ('+','.join('?' for _ in record)+')',record);db.commit()
    assert n.snapshot(file,source_home)['title']=='latest fixture title'
    (source_home/'session_index.jsonl').write_text(json.dumps({'id':sid,'thread_name':''})+'\n',encoding='utf-8')
    assert n.snapshot(file,source_home)['title']==database_title
    with closing(sqlite3.connect(source_home/'state_5.sqlite')) as db:db.execute('delete from threads');db.commit()
    (source_home/'session_index.jsonl').unlink()
    assert n.snapshot(file,source_home)['title']==str(source_project)[:60]
    empty=source_home/'empty-title.jsonl';empty.write_text(json.dumps(rows[0]),encoding='utf-8')
    assert n.snapshot(empty,source_home)['title']==sid
    # Cross-platform component mapping preserves nested cwd without touching body strings.
    for old,new,sub in [('C:/fixture/root','/fixture/target','C:/fixture/root/sub'),('/fixture/root','D:\\fixture\\target','/fixture/root/sub')]:
        raw=json.dumps({'type':'session_meta','payload':{'id':sid,'cwd':sub}}).encode()
        mapped=n.metadata(n.rewrite(raw,{'session_id':sid,'cwd':old},new,sid))[0]['cwd']
        assert mapped.replace('\\','/')==new.replace('\\','/')+'/sub'
    bad=copy.deepcopy(rows);bad[0]['payload']['history_base']={'thread_id':str(uuid.uuid4()),'end_ordinal_exclusive':2,'end_byte_offset':10}
    refuses(lambda:n.metadata(json.dumps(bad[0]).encode()),'lineage')
    # Actual compressed source branch calls the shared decoder; no decompressed reserialization.
    compressed=source_home/'rollout.jsonl.zst';compressed.write_bytes(b'fake compressed fixture')
    with patch('codex_relocate.source_bytes',return_value=data) as decode:
        assert n.snapshot(compressed,source_home)['files'][0]['data']==data;decode.assert_called_once_with(compressed)
    # Failure in index replacement rolls back BOTH session inserts and files; existing rows/index survive.
    failed_home=home(root/'failed-home');(failed_home/'session_index.jsonl').write_bytes(b'{"id":"existing"}\n')
    args.target_home=str(failed_home);args.new_copy=False
    second=copy.deepcopy(snap);second_id=str(uuid.uuid4());second['source']['session_id']=second_id
    second['files'][0]['data']=n.rewrite(data,snap['source'],str(source_project),second_id);second['files'][0]['sha256']=n.c.sha(second['files'][0]['data'])
    with patch('codex_relocate._append_index',side_effect=OSError('injected index failure')):
        try:n.restore_many([(snap,args),(second,args)])
        except OSError:pass
        else:raise AssertionError('failure was swallowed')
    with closing(sqlite3.connect(failed_home/'state_5.sqlite')) as db:assert db.execute('select count(*) from threads').fetchone()[0]==0
    assert not list((failed_home/'sessions').rglob('*.jsonl')) and (failed_home/'session_index.jsonl').read_bytes()==b'{"id":"existing"}\n'
    with patch('codex_project_registry.live_home',return_value=True),patch('codex_project_registry.desktop_running',return_value=True),patch('codex_project_registry.native_project',return_value={'registered':False,'thread_binding_required':[sid]}) as native:
        running_result=n.restore(snap,args);native.assert_called_once()
        assert running_result['desktop_project_registry']['thread_binding_required']==[sid]
    # Whole-project native path never invokes the lossy exporter; blank visible streams are valid.
    project_package=root/'project-package';target=home(root/'project-home')
    with patch.object(r,'export',side_effect=AssertionError('lossy export used')):
        p.pack('codex',source_project,project_package,source_home,[{'snapshot':str(file),'title':'fixture'}],native=True)
    for dry_run in (True,False):
        destination=root/f'native-conversion-{dry_run}'
        target_claude=root/f'claude-conversion-home-{dry_run}'
        refuses(lambda:p.restore(project_package,destination,'claude',target_claude,True,
                                 convert=True,dry_run=dry_run),'Repack without --native')
        assert not destination.exists() and not target_claude.exists()
    empty=p.load_manifest(project_package)
    empty['native_sessions']={}
    with patch.object(p,'load_manifest',return_value=empty):
        refuses(lambda:p.restore(project_package,root/'empty-conversion','claude',root/'empty-home',True,
                                 convert=True),'空对话包')
    assert not (root/'empty-conversion').exists() and not (root/'empty-home').exists()
    p.restore(project_package,root/'project-target','codex',target,True)
    state=json.loads((root/'project-target/.rehome/restore.json').read_text())
    assert len(state['sessions'])==1 and state['mode']=='codex-native'
    with patch.object(sys,'argv',['project_rehome','restore',str(project_package),'--native','--to','codex','--cwd',str(root/'cli-native-preview'),'--target-home',str(target),'--new-copy','--dry-run']):p.main()
    assert not (root/'cli-native-preview').exists()
    preview=p.pack('claude',source_project,root/'preview-no-write',source_home,dry_run=True)
    assert preview['files']==1 and preview['bytes']==7 and not (root/'preview-no-write').exists()
    with patch('project_io.shutil.disk_usage',return_value=argparse.Namespace(free=6)):
        refuses(lambda:p.pack('claude',source_project,root/'too-large',source_home,allow_large=True),'short by')
        assert not (root/'too-large').exists()
print('PASS: native bytes, encrypted/compacted/reasoning, path mapping, ID refusal/copy, zst decoder, lineage refusal, batch rollback, project routing')
