"""Budgeted native compaction keeps the full transcript and whole tool pairs."""
import argparse,base64,copy,json,sys,tempfile,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import agent_rehome as r
from claude_context import estimate_records,plan_context

def args(project,home,budget=12000):
    return argparse.Namespace(cwd=str(project),target_home=str(home),to='claude',dry_run=False,
        model='codex-test-model',claude_model='claude-test-model',claude_version='0.0.0-test',no_desktop=True,claude_context_budget=budget)

with tempfile.TemporaryDirectory() as td:
    d=Path(td);project=d/'project';project.mkdir();home=d/'claude'
    turns=[]
    for n in range(12):
        turns.append({'user':{'ts':f'2026-11-01T00:00:{n:02d}Z','text':f'用户请求 {n}'},'items':[
            {'kind':'tool','name':'shell','input':'历史命令 '+str(n),'output':'big '*10000,'ts':f'2026-11-01T00:00:{n:02d}Z'},
            {'kind':'message','text':f'第 {n} 轮历史结果；尚未发布。','ts':f'2026-11-01T00:00:{n:02d}Z'}]})
    # Last turn fits; all the giant previous calls must remain outside model context.
    turns[-1]['items']=turns[-1]['items'][1:]
    b={'schema':'agent-transcript/v1','source':{'agent':'codex','session_id':str(uuid.uuid4())},
       'title':'长会话','project':{'cwd':'old'},'turns':turns}
    r.import_bundle(copy.deepcopy(b),args(project,home))
    target=next((home/'projects').glob('*/*.jsonl'));rows=r.read(target)
    boundaries=[(n,x) for n,x in enumerate(rows) if x.get('subtype')=='compact_boundary']
    assert len(boundaries)==1
    index,boundary=boundaries[0]
    assert boundary['parentUuid'] is None and boundary['logicalParentUuid']==rows[index-1]['uuid']
    summary=rows[index+1]
    assert summary['isCompactSummary'] and summary['parentUuid']==boundary['uuid']
    assert '不代表本次授权' in summary['message']['content']
    assert 'pick up the last task' not in summary['message']['content']
    assert estimate_records(rows[index+1:])<=12000
    users=[x for x in rows if x.get('type')=='user' and not x.get('isCompactSummary') and isinstance(x['message']['content'],str)]
    assert len(users)==12
    uses=[c for x in rows if x.get('type')=='assistant' for c in x['message']['content'] if c['type']=='tool_use']
    results=[c for x in rows if x.get('type')=='user' and isinstance(x['message']['content'],list) for c in x['message']['content'] if c['type']=='tool_result']
    assert len(uses)==len(results)==11 and all(len(c['content'])==40000 for c in results)
    active_uuids={x.get('uuid') for x in rows[index:]}
    assert all(x.get('parentUuid') in active_uuids or x.get('parentUuid') is None for x in rows[index:] if 'uuid' in x)
    archive=next((project/'.rehome/history').glob('*.jsonl'));archived=r.read(archive)
    assert not any(x.get('subtype')=='compact_boundary' for x in archived)
    assert sum(x.get('type')=='assistant' for x in archived)==sum(x.get('type')=='assistant' for x in rows)
    before=target.read_bytes();r.import_bundle(copy.deepcopy(b),args(project,home));assert target.read_bytes()==before
    # Even an oversized final turn produces a bounded summary, never a chopped tool pair.
    b['source']['session_id']=str(uuid.uuid4());b['turns'][-1]['items']=copy.deepcopy(b['turns'][0]['items'])
    r.import_bundle(copy.deepcopy(b),args(project,home))
    other=next(p for p in (home/'projects').glob('*/*.jsonl') if p!=target)
    rr=r.read(other);bi=next(n for n,x in enumerate(rr) if x.get('subtype')=='compact_boundary')
    assert estimate_records(rr[bi+1:])<=12000
    assert not any(c.get('type')=='tool_use' for x in rr[bi+1:] for c in x.get('message',{}).get('content',[]) if isinstance(c,dict))
    assert '最后一轮' in rr[bi+1]['message']['content']
    # Short messages need no synthetic compaction, nor a fake human message.
    tiny=copy.deepcopy(b);tiny['source']['session_id']=str(uuid.uuid4());tiny['turns']=copy.deepcopy(turns[-1:]);tiny['turns'][0]['items']=[]
    r.import_bundle(tiny,args(project,home));small=next(p for p in (home/'projects').glob('*/*.jsonl') if p not in (target,other))
    assert not any(x.get('isCompactSummary') for x in r.read(small))
    # A policy change cannot silently reuse or overwrite a previously imported thread.
    try:r.import_bundle(copy.deepcopy(b),args(project,home,14000))
    except ValueError:pass
    else:raise AssertionError('changed budget silently accepted')
    # Compact summaries are metadata, never new real user turns on re-export.
    exported=r.exchange.to_v1(r.export('claude',str(target),home))
    assert len(exported['turns'])==12
print('PASS: context budget, native boundary chain, complete history/archive/tool pairs, neutral summary, oversized-last-turn fallback, short chats, policy guards, re-export')
