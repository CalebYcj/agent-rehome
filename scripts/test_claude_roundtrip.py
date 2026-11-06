"""Synthetic Claude copies and prefix-only append, never real agent data."""
import argparse, contextlib, copy, io, json, re, subprocess, sys, tempfile, uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import claude_native as n
import project_rehome as p
import claude_fast_forward as f

def refuses(fn, fragment):
    try: fn()
    except ValueError as error: assert fragment in str(error), str(error)
    else: raise AssertionError('Unsafe operation accepted')

with tempfile.TemporaryDirectory() as directory, patch.object(f,'process_rows',return_value=[]):
    root=Path(directory).resolve();source=root/'source';source.mkdir();home=root/'target-home'
    sid=str(uuid.uuid4());u=str(uuid.uuid4());a=str(uuid.uuid4())
    rows=[{'type':'user','uuid':u,'sessionId':sid,'cwd':str(source),'message':{'content':'literal '+sid}},
          {'type':'assistant','uuid':a,'parentUuid':u,'sessionId':sid,'cwd':str(source),'message':{'content':[{'type':'text','text':'unchanged '+sid}]}}]
    def encoded(records): return ('\r\n'.join(json.dumps(x,ensure_ascii=False) for x in records)+'\r\n').encode()
    path=source/(sid+'.jsonl');path.write_bytes(encoded(rows))
    side=source/sid/'tool-results';side.mkdir(parents=True);(side/'binary.png').write_bytes(b'\x89\xfffixture')
    (side/'sub.jsonl').write_bytes(encoded([{'sessionId':sid,'cwd':str(source),'nested':{'sessionId':sid},'message':'literal '+sid}]))
    source_home=root/'source-home';checkpoint=source_home/'file-history'/sid/'checkpoint.bin';checkpoint.parent.mkdir(parents=True);checkpoint.write_bytes(b'\xffcheckpoint')
    snap=n.snapshot(path,source_home,include_checkpoints=True);original=root/'original';original.mkdir()
    args=argparse.Namespace(to='claude',cwd=str(original),target_home=str(home),no_desktop=True,dry_run=False,new_copy=False,fast_forward=False)
    first=n.restore(snap,args);main=next(home.glob('projects/*/'+sid+'.jsonl'));before=main.read_bytes()
    refuses(lambda:n.restore(snap,args),sid)
    refuses(lambda:n.restore(snap,args),str(main.parent))
    copy_dest=root/'copied';copy_dest.mkdir();copy_args=copy.copy(args);copy_args.cwd=str(copy_dest);copy_args.new_copy=True
    copied=n.restore(snap,copy_args);new_sid=copied['id'];assert new_sid!=sid and main.read_bytes()==before
    new_main=next(home.glob('projects/*/'+new_sid+'.jsonl'))
    expected=next(data for path,data in n.payload_writes(snap,home,str(copy_dest),new_sid,new_main.parent) if path==new_main)
    copied_bytes=new_main.read_bytes()
    assert copied_bytes.startswith(expected)
    assert json.loads(copied_bytes[len(expected):])=={
        'type':'custom-title','sessionId':new_sid,'customTitle':snap['title']+' · 新副本 [copied]'}
    assert all(json.loads(line)['sessionId']==new_sid for line in copied_bytes.splitlines())
    copy_snapshot=n.snapshot(new_main,home,include_checkpoints=True)
    again=copy.copy(copy_args);again.cwd=str(root/'again');Path(again.cwd).mkdir()
    new_copy_id=n.restore(copy_snapshot,again)['id']
    new_copy_path=next(home.glob('projects/*/'+new_copy_id+'.jsonl'))
    assert json.loads(new_copy_path.read_bytes().splitlines()[-1])['customTitle']==snap['title']+' · 新副本 [again]'
    copy_ff=copy.copy(copy_args);copy_ff.new_copy=False;copy_ff.fast_forward=True;copy_ff.dry_run=True
    assert n.restore(copy_snapshot,copy_ff)['append_lines']==0
    # A clean peer can lack only the generated title without diverging.
    assert f.append_start(f.records(copied_bytes),f.records(expected))[0]==len(rows)
    assert ('literal '+sid).encode() in new_main.read_bytes()
    assert (new_main.with_suffix('')/'tool-results/binary.png').read_bytes()==b'\x89\xfffixture'
    assert (home/'file-history'/new_sid/'checkpoint.bin').read_bytes()==b'\xffcheckpoint'
    sub=[json.loads(x) for x in (new_main.with_suffix('')/'tool-results/sub.jsonl').read_bytes().splitlines()][0]
    assert sub['sessionId']==sub['nested']['sessionId']==new_sid and sub['message']=='literal '+sid
    # Desktop IDs follow the copied native identity; checkpoint bytes remain opaque.
    registry=root/'registry';registry_args=copy.copy(copy_args);registry_args.cwd=str(root/'registry-copy');Path(registry_args.cwd).mkdir()
    registry_args.no_desktop=False;registry_args.desktop_registry=str(registry)
    registered=n.restore(snap,registry_args)
    registration=json.loads(Path(registered['desktop_registry']).read_text(encoding='utf-8'))
    assert registration['cliSessionId']==registered['id']!=sid
    registered_main=next(home.glob('projects/*/'+registered['id']+'.jsonl'))
    assert json.loads(registered_main.read_bytes().splitlines()[-1])['customTitle']==registration['title']
    # Incoming history is the original plus two rows, with different source cwd.
    incoming_root=root/'incoming';incoming_root.mkdir();incoming_rows=copy.deepcopy(rows)
    for row in incoming_rows: row['cwd']=str(incoming_root)
    incoming_rows.extend([{'type':'user','uuid':str(uuid.uuid4()),'parentUuid':a,'sessionId':sid,'cwd':str(incoming_root),'message':{'content':'new turn'}},
                          {'type':'assistant','uuid':str(uuid.uuid4()),'sessionId':sid,'cwd':str(incoming_root),'message':{'content':[{'type':'text','text':'new answer'}]}}])
    incoming_file=incoming_root/(sid+'.jsonl');incoming_file.write_bytes(encoded(incoming_rows))
    incoming_side=incoming_root/sid/'tool-results';incoming_side.mkdir(parents=True)
    (incoming_side/'binary.png').write_bytes(b'\x89\xfffixture')
    (incoming_side/'new.txt').write_bytes(b'new sidecar')
    incoming=n.snapshot(incoming_file,root/'incoming-home')
    ff=copy.copy(args);ff.fast_forward=True;ff.dry_run=True;ff.cwd=str(copy_dest)
    assert re.findall(f.RESUME,f'claude --resume={sid}')==[sid]
    assert re.findall(f.RESUME,f'claude.exe --resume "{sid}"')==[sid]
    assert not re.findall(f.RESUME,f'claude --resume={sid[:-1]} --resume {sid}extra')
    for command in (f'claude -r {sid}',f'claude -r={sid}',f'claude.exe -r={sid}',
                    f'"C:/Program Files/x/claude.exe" -r={sid}',
                    f'node "/fixture/claude code/cli.js" -r "{sid}"',
                    f'node /opt/node_modules/@anthropic-ai/claude-code/cli.js -r {sid}',
                    f'node /usr/local/bin/claude -r {sid}',
                    '/Users' f'/x/Library/Application Support/Claude/claude-code/2.1.317/claude -r {sid}',
                    f'/Applications/Claude Desktop.app/Contents/MacOS/claude -r {sid}',
                    f'claude --model x -r {sid}'):
        assert list(f.command_sessions(command))==[sid]
    for command in (f'grep -r {sid} /claude/cli.js',f'grep -r {sid}',f'rm -r {sid}',
                    f'grep -r {sid} /home' '/x/.claude',f'claude -r {sid}extra'):
        assert not list(f.command_sessions(command))
    assert list(f.command_sessions(f'claude -r {u}'))==[u]
    assert list(f.command_sessions(f'grep -r {sid} CLAUDE -r {u}'))==[u]
    backup_count=len(list((home/'rehome-backups').iterdir()))
    for dry_run in (True,False):
        probe=copy.copy(ff)
        probe.dry_run=dry_run
        with patch.object(f,'process_rows',return_value=[('claude.exe',12,sid),('claude',12,sid)]):
            refuses(lambda:n.restore(incoming,probe),'有 1 个进程')
        assert main.read_bytes()==before and len(list((home/'rehome-backups').iterdir()))==backup_count
        for error in (FileNotFoundError(),PermissionError(),subprocess.TimeoutExpired('fixture',1)):
            with patch.object(f,'process_rows',side_effect=error):
                if dry_run:
                    unavailable=n.restore(incoming,probe)
                    assert unavailable['live_process_check']=='unavailable' and unavailable['warnings']
                else:
                    refuses(lambda:n.restore(incoming,probe),'快进写入已停止')
    with patch.object(f,'process_rows',return_value=[('claude',13,sid[:-1]),('claude',14,u),('other',15,u)]):
        assert n.restore(incoming,ff)['live_process_check']=='clear'
    assert main.read_bytes()==before and len(list((home/'rehome-backups').iterdir()))==backup_count
    for flag in ('--session-id=', '--session-id '):
        assert re.findall(f.RESUME,f'node cli.js {flag}{sid}')==[sid]
    assert re.findall(f.RESUME,f'node cli.js --resume {sid}')==[sid]
    assert n.restore(incoming,ff)['live_process_check']=='clear' and not (home/'sessions').exists()
    processes=home/'sessions'
    processes.mkdir()
    key=processes/'12.key'
    key.write_bytes(b'not a session process record')
    record=processes/'12.json'
    record.write_text(json.dumps({'pid':12,'sessionId':sid}),encoding='utf-8')
    open_path=Path.open
    def forbid_keys(path,*values,**kwargs):
        assert path.suffix!='.key'
        return open_path(path,*values,**kwargs)
    with patch.object(Path,'open',forbid_keys):
        for process_snapshot,expected in (
            ([('node',12,sid)],['command_line','session_file']),
            ([('process',12,None)],['session_file']),
            ([('node',13,sid)],['command_line']),
        ):
            output=io.StringIO()
            with patch.object(f,'process_rows',return_value=process_snapshot),contextlib.redirect_stdout(output):
                refuses(lambda:n.restore(incoming,ff),'有 1 个进程')
            assert json.loads(output.getvalue())['live_process_sources']==expected
        assert n.restore(incoming,ff)['live_process_check']=='clear'  # Stale PID record.
        record.write_text(json.dumps({'pid':12,'sessionId':u}),encoding='utf-8')
        with patch.object(f,'process_rows',return_value=[('process',12,None)]):
            assert n.restore(incoming,ff)['live_process_check']=='clear'
        record.write_text('{invalid fixture',encoding='utf-8')
        assert n.restore(incoming,ff)['live_process_check']=='unavailable'
        probe=copy.copy(ff)
        probe.dry_run=False
        refuses(lambda:n.restore(incoming,probe),'快进写入已停止')
    assert main.read_bytes()==before and len(list((home/'rehome-backups').iterdir()))==backup_count
    record.unlink()
    maintenance={'type':'tools-used','sessionId':sid,'cwd':str(original)}
    for local_only in ({'type':'unknown'}, {'type':'tools-used','uuid':u}, {'type':'user','uuid':str(uuid.uuid4())}):
        main.write_bytes(before+encoded([local_only]))
        refuses(lambda:n.restore(incoming,ff),'diverg')
    before+=encoded([maintenance])
    main.write_bytes(before)
    from claude_fast_forward import append_start
    first,last=rows
    for kind in ('tools-used','last-prompt','cost-state','mode'):
        local={'type':kind,'sessionId':sid,'mode':'default'}
        if kind!='mode':local.pop('mode')
        remote={'type':'last-prompt','sessionId':sid,'extra':'fixture'}
        start,skipped=append_start(list(enumerate([first,local,last])),list(enumerate([first,remote,last])))
        assert start==3 and skipped=={kind:1}
    preview=n.restore(incoming,ff)
    assert preview['skipped_local_maintenance']=={'tools-used':1}
    assert preview['append_lines']==2 and preview['cwd']==str(original) and main.read_bytes()==before
    assert not (main.with_suffix('')/'tool-results/new.txt').exists()
    branch=copy.deepcopy(incoming);branch['files'][0]['data']=encoded([dict(incoming_rows[0],message={'content':'diverged'}),*incoming_rows[1:]])
    branch['files'][0]['sha256']=n.sha(branch['files'][0]['data'])
    refuses(lambda:n.restore(branch,ff),'diverg')
    ff.dry_run=False;result=n.restore(incoming,ff)
    assert result['append_lines']==2 and main.read_bytes().startswith(before)
    all_rows=[json.loads(x) for x in main.read_bytes().splitlines()]
    assert len(all_rows)==5 and all(row['cwd']==str(original) for row in all_rows)
    assert (main.with_suffix('')/'tool-results/new.txt').read_bytes()==b'new sidecar'
    assert (Path(result['backup'])/'history-before.jsonl').read_bytes()==before
    assert n.restore(incoming,ff)['status']=='unchanged'
    side_conflict=copy.deepcopy(incoming)
    next(item for item in side_conflict['files'] if item['relative'].endswith('binary.png'))['data']=b'\xffdifferent'
    item=next(item for item in side_conflict['files'] if item['relative'].endswith('binary.png'));item['sha256']=n.sha(item['data'])
    refuses(lambda:n.restore(side_conflict,ff),'sidecar divergence')
    # Whole-project CLI path reports the in-place native cwd separately from copied project files.
    project_package=root/'project-package'
    p.pack('claude',incoming_root,project_package,root/'incoming-home',[{'snapshot':str(incoming_file),'title':'fixture'}],native=True)
    preview=p.restore(project_package,root/'preview-project','claude',home,True,fast_forward=True,dry_run=True)
    assert preview['native_operations'][0]['append_lines']==0 and not (root/'preview-project').exists()
    state=p.restore(project_package,root/'restored-project','claude',home,True,fast_forward=True)
    assert state['sessions'][0]['cwd']==str(original) and state['sessions'][0]['status']=='unchanged'
    # A live append between validation and open is preserved, never replaced by a backup.
    concurrent=copy.copy(args);concurrent.target_home=str(root/'concurrent-home')
    n.restore(snap,concurrent);concurrent.fast_forward=True
    concurrent_main=next(Path(concurrent.target_home).glob('projects/*/'+sid+'.jsonl'))
    saved=concurrent_main.read_bytes();foreign=b'{"type":"system","message":"concurrent fixture"}\n'
    real_open=f.os.open
    def changed_open(path,flags,*values,**keywords):
        with concurrent_main.open('ab') as stream:stream.write(foreign)
        return real_open(path,flags,*values,**keywords)
    with patch.object(f.os,'open',side_effect=changed_open):refuses(lambda:n.restore(incoming,concurrent),'changed before append')
    assert concurrent_main.read_bytes()==saved+foreign
    journal=next((Path(concurrent.target_home)/'rehome-backups').glob('claude-native-fast-forward-*/journal.json'))
    assert json.loads(journal.read_text())['status']=='partial-write-needs-review'
    ff.new_copy=True;refuses(lambda:n.restore(incoming,ff),'mutually exclusive')
print('PASS: readable conflict, copied IDs/sidecars, original preserved, prefix append, branch refusal, preview')
