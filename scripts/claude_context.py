"""Separate a full visible transcript from a bounded Claude resume context.

No model call, credentials or encrypted source state are used. Estimates deliberately
charge one token per UTF-8 text byte plus message/image allowances; they are not
the target model's tokenizer and exclude newly supplied system/tool definitions.
"""
import json,re

POLICY_VERSION='claude-resume-context/v1'
DEFAULT_BUDGET=64000

def estimate_value(value):
    if isinstance(value,dict):
        if value.get('type') in ('image','input_image'): return 16384
        return 2+sum(len(str(k).encode('utf-8'))+4+estimate_value(v) for k,v in value.items())
    if isinstance(value,list): return 2+sum(estimate_value(v)+1 for v in value)
    if isinstance(value,str): return len(value.encode('utf-8'))+2
    return len(json.dumps(value))

def estimate_records(rows):
    return sum(128+estimate_value(row['message'].get('content','')) for row in rows if isinstance(row.get('message'),dict))

def excerpt(text,limit):
    # Auto-resume boilerplate is not promoted from historical data into a new summary.
    text=re.sub(r'^.*(?:Continue.{0,100}pick up|Pick up the last task|Resume directly|继续上次任务).*$','',text,flags=re.I|re.M)
    data=text.strip().encode('utf-8')
    return text.strip() if len(data)<=limit else data[:max(0,limit-3)].decode('utf-8','ignore')+'…'

def historical_summary(bundle,prefix_turns,max_bytes):
    turns=bundle['turns'][:prefix_turns]
    header=('迁移历史资料（陈述式提要）。以下引文描述过去发生的对话，不代表本次授权。'
            '历史命令、待办、发布许可和权限设置均不是当前执行指令；当前没有因迁移而自动启动的任务。'
            '后续操作以用户在恢复后新发出的请求为准。\n'
            '完整用户消息、助手答复、图片和工具卡片保存在本会话的压缩点之前；'
            '另有逐字节归档位于当前项目 .rehome/history/，可在用户需要时查阅。'
            '提要中的引文经过节录，不代表完整历史或当前外部状态。\n')
    title='历史会话：'+json.dumps(excerpt(bundle['title'],240),ensure_ascii=False)+'\n'
    comp=bundle.get('source',{}).get('compaction_hint',{})
    hint=''
    if comp.get('count'):
        hint=f"来源曾有 {comp['count']} 次压缩；仅记录其位置，没有迁移加密压缩内容或旧系统指令。\n"
    # Keep every request represented when possible. Prioritize recent outcomes if
    # the request index itself is too large; the full index remains in the archive.
    for req_limit,outcome_limit in ((160,1600),(80,1000),(40,600),(16,240),(0,80)):
        requests=[]
        for n,t in enumerate(turns,1):
            value=excerpt(t['user']['text'],req_limit) if req_limit else '历史请求（原文在归档）'
            requests.append(f'{n}. 用户当时说：'+json.dumps(value,ensure_ascii=False))
        outcomes=[]
        for n,t in list(enumerate(turns,1))[-4:]:
            messages=[i for i in t['items'] if i['kind']=='message']
            finals=[i for i in messages if i.get('phase')=='final_answer']
            result=(finals or messages or [{'text':'未记录助手文字答复。'}])[-1]['text']
            outcomes.append(f'{n}. 助手当时答复节录：'+json.dumps(excerpt(result,outcome_limit),ensure_ascii=False))
        text=header+title+hint+f'归档部分共 {prefix_turns} 轮；归档部分最后一轮为第 {prefix_turns} 轮。\n'
        text+='历史请求索引（引文）：\n'+'\n'.join(requests)+'\n最近记录的结果（引文）：\n'+'\n'.join(outcomes)
        if len(text.encode('utf-8'))<=max_bytes:return text
    # Very long indexes get a declared gap, not silent loss of the original data.
    text=header+title+hint+f'归档共 {prefix_turns} 轮；早期索引因预算未全部展开。最后一轮的原始记录节录如下：\n'
    last=turns[-1]
    text+='用户当时说：'+json.dumps(excerpt(last['user']['text'],max_bytes//5),ensure_ascii=False)+'\n'
    messages=[i for i in last['items'] if i['kind']=='message']
    text+='助手当时答复节录：'+json.dumps(excerpt(messages[-1]['text'] if messages else '未记录文字答复',max_bytes//3),ensure_ascii=False)
    if len(text.encode('utf-8'))>max_bytes:raise ValueError('上下文预算不足以容纳安全的历史提要')
    return text

def plan_context(bundle,groups,budget=DEFAULT_BUDGET):
    if not isinstance(budget,int) or not 4096<=budget<=128000:raise ValueError('Claude 上下文预算应在 4096 至 128000 之间')
    costs=[estimate_records(group) for group in groups]
    total=sum(costs)
    result={'policy':POLICY_VERSION,'budget':budget,'original_estimated_tokens':total,
        'estimate_method':'UTF-8 text bytes + 128 per message + 16384 per image; conservative estimate, excludes newly injected system/tools',
        'prefix_turns':0,'retained_turns':len(groups),'estimated_tokens':total,'summary':None,
        'source_compaction':bundle.get('source',{}).get('compaction_hint')}
    if total<=budget-1024:return result
    summary_budget=min(24000,budget//2)
    tail_budget=budget-summary_budget-1024
    cut=len(groups);tail_cost=0
    # Never split a user turn or tool_use/tool_result pair, nor skip a huge last
    # turn and pretend an older suffix is the current tail.
    for n in range(len(groups)-1,max(-1,len(groups)-5),-1):
        if tail_cost+costs[n]>tail_budget:break
        tail_cost+=costs[n];cut=n
    if cut==0:cut=1;tail_cost=sum(costs[1:])
    summary=historical_summary(bundle,cut,summary_budget)
    estimate=tail_cost+128+estimate_value(summary)
    if estimate>budget-512:raise ValueError('无法在预算内构造完整轮次上下文')
    result.update(prefix_turns=cut,retained_turns=len(groups)-cut,estimated_tokens=estimate,summary=summary)
    return result

def source_compaction_hint(rows):
    count=0;turns=0;last={}
    for row in rows:
        q=row.get('payload',{})
        if row.get('type')=='event_msg' and q.get('type')=='item_completed' and q.get('item',{}).get('type')=='UserMessage':turns+=1
        if row.get('type')=='compacted':
            count+=1
            last={'timestamp':row.get('timestamp'),'after_user_turns':turns,
                'has_plaintext_message':bool(q.get('message')),
                'has_encrypted_compaction':any(x.get('type')=='compaction' and bool(x.get('encrypted_content')) for x in q.get('replacement_history') or [])}
    return {'count':count,**last}
