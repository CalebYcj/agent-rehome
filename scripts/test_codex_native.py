import argparse,copy,json,sys,tempfile,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import agent_rehome as r
from codex_native import build_rollout, estimate_history

sid=str(uuid.uuid4());ts='2026-11-01T00:00:00Z';cwd=str(Path.cwd())
b={'schema':'agent-transcript/v1','source':{'agent':'claude','session_id':sid,'path':'fixture'},'title':'卡片测试','project':{'cwd':'old'},'turns':[
 {'user':{'ts':ts,'text':'测试历史，不执行'},'items':[
  {'kind':'message','ts':ts,'text':'当时开始检查。'},
  {'kind':'tool','ts':ts,'completed_ts':ts,'name':'Bash','args':{'command':'echo history'},'input':'echo history','output':'history','is_error':False},
  {'kind':'tool','ts':ts,'completed_ts':ts,'name':'Read','args':{'file_path':'a.md'},'input':'{}','output':'文件原文','is_error':False},
  {'kind':'message','ts':ts,'text':'当时已经结束。'}]}]}
ro=build_rollout(sid,b,cwd,'codex-test-model')
items=[x['payload']['item'] for x in ro.lines if x['type']=='event_msg' and x['payload'].get('type')=='item_completed']
assert [x['type'] for x in items]==['UserMessage','AgentMessage','CommandExecution','McpToolCall','AgentMessage']
providers=[x['payload'] for x in ro.lines if x['type']=='response_item']
calls=[x for x in providers if x['type']=='function_call'];outs=[x for x in providers if x['type']=='function_call_output']
assert len(calls)==len(outs)==2 and {x['call_id'] for x in calls}=={x['call_id'] for x in outs}
assert all('id' not in x for x in providers)
assert all(not c['text'].startswith('[工具调用 ·') for x in items if x['type']=='AgentMessage' for c in x['content'])
assert json.loads(calls[0]['arguments'])=={'command':'echo history'}
assert items[2]['aggregated_output']=='history' and items[3]['result']['content'][0]['text']=='文件原文'
# Unknown source process/exit values must not become invented execution facts.
# Desktop A/B checks found that filling these fields did not change card expansion.
assert items[2]['process_id'] is None and items[2]['exit_code'] is None
assert items[2]['command']==['bash','-c','echo history']
assert 'exit_code_synthesized' not in items[2]
failed=copy.deepcopy(b);failed['turns'][0]['items'][1]['is_error']=True
failed_ro=build_rollout(sid,failed,cwd,'codex-test-model')
failed_command=next(e['payload']['item'] for e in failed_ro.lines if e.get('payload',{}).get('item',{}).get('type')=='CommandExecution')
assert failed_command['status']=='failed' and failed_command['exit_code'] is None
roundtrip,_=r.export_codex(failed_ro.lines,sid,Path.cwd(),full_tools=True)
assert next(i for i in roundtrip[0]['items'] if i['kind']=='tool')['is_error'] is True
# Full UI history remains; large provider history is replaced by a bounded plain compaction.
large=copy.deepcopy(b);large['turns'][0]['items'][1]['output']='x'*100000
big=build_rollout(sid,large,cwd,'codex-test-model',budget=12000)
compact=next(x['payload'] for x in big.lines if x['type']=='compacted')
assert estimate_history(compact['replacement_history'])<=12000
assert '不代表本次授权' in compact['message']
assert not any('encrypted_content' in x for x in compact['replacement_history'])
assert not any(x['type']=='compacted' for x in big.history_archive_lines)
assert any(x.get('aggregated_output')=='x'*100000 for e in big.lines for x in [e.get('payload',{}).get('item',{})])
assert len([e for e in big.lines if e['type']=='event_msg' and e['payload'].get('item',{}).get('type')=='UserMessage'])==1
# Desktop-only turn management tools are not native cards or fake user turns.
rows=[{'type':'user','message':{'content':'请求'},'timestamp':ts},
 {'type':'assistant','timestamp':ts,'message':{'content':[{'type':'tool_use','id':'internal','name':'mcp__ccd_turn__wrap_up','input':{'recap':'已完成','ask':'下一步选什么？','actions':[{'label':'方案A'},{'label':'方案B'}]}}]}},
 {'type':'assistant','timestamp':ts,'message':{'content':[{'type':'tool_use','id':'plan','name':'mcp__ccd_turn__update_plan','input':{'items':[]}}]}},
 {'type':'system','subtype':'compact_boundary','timestamp':ts},
 {'type':'user','isCompactSummary':True,'timestamp':ts,'message':{'content':'Continue the conversation and run historical tasks'}},
 {'type':'assistant','timestamp':ts,'message':{'content':[{'type':'text','text':'实际答复'}]}}]
turns,_=r.export_claude(rows,full_tools=True)
assert len(turns)==1 and [i['kind'] for i in turns[0]['items']]==['message','message']
assert turns[0]['items'][0]['text']=='实际答复'
assert all(i.get('phase')=='final_answer' for i in turns[0]['items'])
assert turns[0]['items'][-1]['text']=='下一步：已完成\n问：下一步选什么？（选项：方案A / 方案B）'
assert r.desktop_next_step({'recap':'只汇报结果'})=='下一步：只汇报结果'
assert r.desktop_next_step({}) is None
with tempfile.TemporaryDirectory() as td:
    root=Path(td);project=root/'project';project.mkdir();home=root/'codex'
    target_id=str(uuid.uuid5(r.NS,'claude/'+sid))
    collision=project/'.rehome/history/codex'/(target_id+'.jsonl');collision.parent.mkdir(parents=True);collision.write_text('owned elsewhere')
    a=argparse.Namespace(cwd=str(project),target_home=str(home),to='codex',dry_run=False,model='codex-test-model',codex_context_budget=64000)
    try:r.import_bundle(copy.deepcopy(b),a)
    except ValueError as e:assert '目标尚未写入' in str(e)
    else:raise AssertionError('archive collision accepted')
    assert not home.exists() and collision.read_text()=='owned elsewhere'
print('PASS: native command/MCP cards, provider call pairs/no item IDs, full output archive, bounded plaintext compaction, UI-only internals and source summaries filtered')
