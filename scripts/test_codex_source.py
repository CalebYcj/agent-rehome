"""Legacy events, mixed UI histories, optional zstd and indexed/archived project sources."""
import copy,contextlib,io,json,sqlite3,sys,tempfile,types
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import agent_rehome as r,project_rehome as project,rollout_io as rio

SID='12345678-1234-4567-8123-123456789012'
TS='2026-11-01T00:00:00Z'
def row(typ,kind,**data):return {'timestamp':TS,'type':typ,'payload':dict(type=kind,**data)}
def frame(data):
    # A real single-segment zstd frame containing one uncompressed final block.
    return bytes.fromhex('28b52ffd')+b'\xa0'+len(data).to_bytes(4,'little')+((len(data)<<3)|1).to_bytes(3,'little')+data
def write(path,rows,compressed=False):
    path.parent.mkdir(parents=True,exist_ok=True)
    data=('\n'.join(json.dumps(item,ensure_ascii=False) for item in rows)+'\n').encode('utf-8')
    path.write_bytes(frame(data) if compressed else data)
    return data

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);home=root/'data';home.mkdir();source=root/'source';source.mkdir()
    rows=[row('session_meta','meta',id=SID,cwd=str(source),cli_version='0.140.0-alpha.2'),
        row('response_item','message',role='developer',content=[{'type':'input_text','text':'harness only'}]),
        row('event_msg','user_message',message='historical request'),
        row('response_item','message',role='user',content=[{'type':'input_text','text':'AGENTS injection'}]),
        row('response_item','reasoning',encrypted_content='synthetic opaque'),
        row('response_item','function_call',name='shell',call_id='call1',arguments='{"command":"echo history"}'),
        row('response_item','function_call_output',call_id='call1',output='history'),
        row('response_item','custom_tool_call',name='apply_patch',call_id='call2',input='historical patch'),
        row('response_item','custom_tool_call_output',call_id='call2',output='historical result'),
        row('response_item','web_search_call',id='call3',action={'type':'search','query':'synthetic query'}),
        row('event_msg','web_search_end',call_id='call3',results=[{'title':'synthetic result'}]),
        row('event_msg','agent_message',message='historical answer'),
        row('event_msg','future_unknown',value='opaque'),
        row('event_msg','user_message',message='historical request'),
        row('event_msg','agent_message',message='second answer')]
    file=home/'sessions'/('old-'+SID+'.jsonl');write(file,rows)
    result=r.export('codex',str(file),home,True);turns=r.exchange.to_v1(result)['turns']
    assert len(turns)==2 and [t['user']['text'] for t in turns]==['historical request']*2
    tools=[item for item in turns[0]['items'] if item['kind']=='tool']
    assert [item['name'] for item in tools]==['shell','apply_patch','web_search']
    assert [item['output'] for item in tools][:2]==['history','historical result']
    assert 'synthetic result' in tools[2]['output']
    assert all(item['status']=='unknown' and not item.get('exit_code') for item in tools)
    assert any(event['kind']=='reasoning' and event['visibility']=='encrypted' for event in result['events'])
    assert any(loss['kind']=='event_future_unknown' for loss in result['losses'])
    assert 'AGENTS injection' not in json.dumps(turns) and 'harness only' not in json.dumps(turns)
    mixed=copy.deepcopy(rows)
    mixed.insert(3,row('event_msg','item_completed',turn_id='synthetic-turn',item={'type':'UserMessage','content':[{'type':'text','text':'historical request'}]}))
    mixed.append(row('event_msg','item_completed',item={'type':'AgentMessage','content':[{'type':'text','text':'second answer'}]}))
    mixed.insert(8,row('event_msg','item_completed',item={'type':'CommandExecution','id':'call1','command':['bash','-c','echo history'],'aggregated_output':'history','status':'completed','exit_code':0}))
    mixed_turns,_=r.export_codex(mixed,SID,home,True)
    assert len(mixed_turns)==2 and len([i for t in mixed_turns for i in t['items'] if i['kind']=='tool'])==3
    assert len([i for t in mixed_turns for i in t['items'] if i['kind']=='message'])==2
    separate=copy.deepcopy(rows[:3]);later=row('event_msg','item_completed',item={'type':'UserMessage','content':[{'type':'text','text':'historical request'}]});later['timestamp']='2026-11-01T00:01:00Z';separate.append(later)
    assert len(r.export_codex(separate,SID,home,True)[0])==2,'Different real turns with repeated text must not collapse'
    orphan=rows+[row('response_item','function_call',name='unknown_tool',call_id='no-result',arguments='{}')]
    write(file,orphan);assert any(loss['kind']=='missing_tool_result' for loss in r.export('codex',str(file),home)['losses'])
    write(file,rows)
    compressed_rows=copy.deepcopy(rows);compressed_rows[0]['payload']['id']='aaaaaaaa-1234-4567-8123-123456789012'
    compressed=home/'archived_sessions'/'no-prefix.jsonl.zst';plain=write(compressed,compressed_rows,True);before=compressed.read_bytes()
    try:
        assert rio.source_bytes(compressed)==plain
        print('PASS: real synthetic zstd decompression')
    except ValueError as error:
        if '需要解压器' not in str(error):raise
        print('SKIP real zstd decompression: no optional decoder installed; mocked order/error tests still run')
    def unavailable(name):raise ImportError(name)
    with patch.object(rio.importlib,'import_module',side_effect=unavailable),patch.object(rio.shutil,'which',return_value=None):
        try:r.read(compressed)
        except ValueError as error:assert 'pip install zstandard' in str(error) and '3.14' in str(error)
        else:raise AssertionError('Missing decoder silently accepted')
    # Exercise the CLI fallback with a mocked process; tests never launch external commands.
    with patch.object(rio.importlib,'import_module',side_effect=unavailable),patch.object(rio.shutil,'which',return_value='fixture-zstd'),patch.object(rio.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout=plain)) as call:
        assert rio.source_bytes(compressed)==plain
        assert call.call_args.args[0]==['fixture-zstd','-d','-c'] and call.call_args.kwargs['input']==before
    # Explicitly exercise the second-choice Python module without requiring it installed.
    class Reader(io.BytesIO):pass
    fallback=types.SimpleNamespace(ZstdDecompressor=lambda:types.SimpleNamespace(stream_reader=lambda stream:Reader(stream.read()[12:])))
    def second_choice(name):
        if name=='compression.zstd':raise ImportError(name)
        assert name=='zstandard';return fallback
    with patch.object(rio.importlib,'import_module',side_effect=second_choice):assert rio.source_bytes(compressed)==plain
    decoder=types.SimpleNamespace(decompress=lambda data:data[12:])
    def corrupt(data):raise RuntimeError('synthetic corrupt frame')
    with patch.object(rio.importlib,'import_module',return_value=types.SimpleNamespace(decompress=corrupt)),patch.object(rio.shutil,'which') as fallback_command:
        try:rio.source_bytes(compressed)
        except ValueError as error:assert '解压失败' in str(error)
        else:raise AssertionError('Corrupt zstd silently accepted')
        fallback_command.assert_not_called()
    with patch.object(rio.importlib,'import_module',return_value=decoder) as imports:
        assert rio.source_bytes(compressed)==plain;imports.assert_called_once_with('compression.zstd')
        archived=home/'archived_sessions'/('archived-'+SID+'.jsonl.zst');archived.write_bytes(before)
        file.unlink();assert r.locate('codex',SID,home)==archived
        archived.unlink();write(file,rows)
        with contextlib.closing(sqlite3.connect(home/'state_5.sqlite')) as db:
            db.executescript((Path(__file__).parent/'fixtures/codex_schema.sql').read_text(encoding='utf-8'))
            for sid,path,archived in [(SID,file,0),('aaaaaaaa-1234-4567-8123-123456789012',compressed,1)]:
                db.execute('insert into threads(id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,sandbox_policy,approval_mode,archived,cli_version,first_user_message,memory_mode) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,str(path),1,1,'fixture','fixture',str(source),'fixture','{}','fixture',archived,'fixture','fixture','enabled'))
            db.commit()
        assert r.locate('codex','aaaaaaaa-1234-4567-8123-123456789012',home)==compressed
        assert r.locate('codex',SID,home)==file
        out=root/'package'
        with contextlib.redirect_stdout(io.StringIO()):project.pack('codex',source,out,home)
        manifest=project.load_manifest(out)
        assert len(manifest['conversations'])==2 and not manifest['skipped']
        assert len(r.exchange.to_v1(r.export('codex',str(compressed),home))['turns'])==2
    assert compressed.read_bytes()==before
print('PASS: legacy tools/reasoning/losses, mixed dedup, zstd order/error, archived/indexed project pack')
