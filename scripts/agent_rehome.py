"""Portable visible-history transfer; no GUI dependency. Python 3.10+."""
from platform_paths import sqlite_read_uri
from rollout_io import source_bytes
from contextlib import closing
import mimetypes
import argparse, datetime as dt, hashlib, json, os, re, shutil, sqlite3, sys, uuid
from pathlib import Path
import codex_backend as backend
from cli_output import print,configure
import codex_native
import exchange
from user_next_steps import add_next_steps,package_next_steps
from project_io import digest,inline_image
from claude_context import DEFAULT_BUDGET, POLICY_VERSION, estimate_records, plan_context, source_compaction_hint
NS = uuid.UUID('6f1c2a9e-4b7d-4c1e-9a3f-c1a0dec0de01')
def now(): return dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z')
def read(p):
    return [json.loads(line.decode('utf-8-sig')) for line in source_bytes(p).splitlines() if line.strip()]
def dump(p, obj):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.rehome-tmp')
    with tmp.open('w',encoding='utf-8',newline='\n') as stream: json.dump(obj,stream,ensure_ascii=False,indent=2)
    os.replace(tmp,p)
def locate(agent, session, home):
    p=Path(session)
    if p.is_file(): return p
    if agent=='codex' and (Path(home)/'state_5.sqlite').exists():
        with closing(sqlite3.connect(sqlite_read_uri(Path(home)/'state_5.sqlite'),uri=True)) as db:
            paths=[row[0] for row in db.execute('select rollout_path from threads where id=?',(session,))]
        if paths:
            from platform_paths import source_rollout
            return source_rollout(home,paths[0])
    hits=list(Path(home).glob('projects/*/'+session+'.jsonl')) if agent=='claude' else [path for folder in ('sessions','archived_sessions') for pattern in ('*'+session+'.jsonl','*'+session+'.jsonl.zst') for path in (Path(home)/folder).rglob(pattern)]
    if len(hits)!=1: raise ValueError(f'会话匹配 {len(hits)} 个，请提供明确的 jsonl 路径')
    return hits[0]
def content(v):
    if isinstance(v,str): return v
    return '\n'.join(x.get('text','') for x in (v or []) if isinstance(x,dict) and x.get('type','').lower() in ('text','input_text','output_text'))
TOOL_INPUT_LIMIT, TOOL_OUTPUT_LIMIT = 4000, 3000
def clip(s, n): s=s or ''; return s if len(s)<=n else s[:n]+f'\n…[已截断，原长 {len(s)} 字符]'
def codex_user_text(text):
    """Codex prefixes attachments as '# Files mentioned by the user' ... '## My request:'; keep the request, list files briefly.
    Ambient UI blocks (e.g. <in-app-browser-context>) are hidden in Codex's UI and dropped; question-card answers become one line."""
    text=re.sub(r'<in-app-browser-context\b[^>]*>.*?</in-app-browser-context>\s*','',text,flags=re.S)
    def answer(m):
        try: items=json.loads(m.group(1))
        except ValueError: return m.group(0)
        return '\n'.join(f"回答「{x.get('question','')}」：{x.get('answer','')}" for x in items)
    cleaned=re.sub(r'<send_user_message_question_reply>\s*(.*?)\s*</send_user_message_question_reply>',answer,text,flags=re.S)
    if cleaned!=text: text=cleaned.strip()
    if re.match(r'\s*## My request[^\n]*:',text): text=re.sub(r'\A\s*## My request[^\n]*:\s*\n?','',text).strip()
    m=re.match(r'\s*# Files mentioned by the user:\s*\n(.*?)\n## My request[^\n]*:\s*\n?(.*)\Z',text,re.S)
    if not m: return text
    files=re.findall(r'^## (.+?): (.+)$',m.group(1),re.M)
    head='附件：'+'、'.join(f'{n}（{p}）' for n,p in files)+'\n\n' if files else ''
    return head+m.group(2).strip()
def codex_legacy_rows(rows):
    """Project old visible events into the UI reader; match duplicate occurrences, not text sets."""
    if not any(row.get('type')=='event_msg' and (row.get('payload') or {}).get('type') in ('user_message','agent_message') for row in rows):return rows
    from collections import defaultdict,deque
    outputs={};new_messages=defaultdict(deque);new_turn_messages=defaultdict(deque);new_calls={};new_tools=defaultdict(deque);replaced=set();substitutions={}
    def signature(item):return item.get('type'),codex_user_text(content(item.get('content'))) if item.get('type')=='UserMessage' else content(item.get('content'))
    for n,row in enumerate(rows):
        q=row.get('payload') or {};kind=q.get('type')
        if row.get('type')=='response_item' and kind in ('function_call_output','custom_tool_call_output'):
            outputs[q.get('call_id')]=(row,q.get('output'))
        if row.get('type')=='event_msg' and kind=='web_search_end':outputs[q.get('call_id')]=(row,q.get('results') or q.get('output'))
        if row.get('type')=='event_msg' and kind=='item_completed':
            item=q.get('item') or {}
            if item.get('type') in ('UserMessage','AgentMessage'):
                new_messages[(row.get('timestamp'),signature(item))].append(n)
                if q.get('turn_id'):new_turn_messages[(q['turn_id'],signature(item))].append(n)
            elif item.get('id'):
                new_calls[item['id']]=n
                if item.get('type')=='CommandExecution':
                    cmd=item.get('command') or [];cmd=cmd[-1] if len(cmd)>=3 and cmd[-2] in ('-Command','-c','/c') else ' '.join(cmd) if isinstance(cmd,list) else str(cmd)
                    args={'command':cmd};out=item.get('aggregated_output') or ''
                elif item.get('type')=='McpToolCall':args=item.get('arguments') or {};out=content((item.get('result') or {}).get('content'))
                else:continue
                new_tools[(row.get('timestamp'),json.dumps(args,sort_keys=True,ensure_ascii=False),out)].append(n)
    projected={}
    for n,row in enumerate(rows):
        q=row.get('payload') or {};kind=q.get('type');item=None
        if row.get('type')=='event_msg' and kind in ('user_message','agent_message'):
            text=q.get('message') or ''
            if not text and kind=='user_message' and (q.get('images') or q.get('local_images')):text='[用户上传图片]'
            item={'type':'UserMessage' if kind=='user_message' else 'AgentMessage','content':[{'type':'text','text':text}],'phase':q.get('phase')}
            matches=new_turn_messages[(q.get('turn_id'),signature(item))]
            while matches and matches[0] in replaced:matches.popleft()
            if not matches:matches=new_messages[(row.get('timestamp'),signature(item))]
            while matches and (matches[0] in replaced or (q.get('turn_id') and rows[matches[0]]['payload'].get('turn_id') not in (None,q['turn_id']))):matches.popleft()
            if matches:
                index=matches.popleft();replaced.add(index);substitutions[n]=rows[index];continue
        elif row.get('type')=='response_item' and kind in ('function_call','custom_tool_call','web_search_call'):
            call=q.get('call_id') or q.get('id')
            if call in new_calls:
                index=new_calls[call];replaced.add(index);substitutions[n]=rows[index];continue
            raw=q.get('arguments') if kind=='function_call' else q.get('input') if kind=='custom_tool_call' else q.get('action',{})
            try:args=json.loads(raw) if isinstance(raw,str) else raw
            except ValueError:args={'input':raw}
            if not isinstance(args,dict):args={'input':args}
            result=outputs.get(call);out=result[1] if result else ''
            if not isinstance(out,str):out=json.dumps(out,ensure_ascii=False) if out is not None else ''
            matches=new_tools[(row.get('timestamp'),json.dumps(args,sort_keys=True,ensure_ascii=False),out)]
            while matches and matches[0] in replaced:matches.popleft()
            if matches:
                index=matches.popleft();replaced.add(index);substitutions[n]=rows[index];continue
            item={'type':'LegacyTool','name':q.get('name') or 'web_search','args':args,'input':raw if isinstance(raw,str) else json.dumps(raw,ensure_ascii=False),
                'output':out,'completed_ts':result[0].get('timestamp') if result else None,'status':q.get('status'),
                'missing_result':result is None,'call_id':call}
        if item:projected[n]=dict(row,type='event_msg',payload={'type':'item_completed','item':item})
    return [substitutions.get(n,projected.get(n,row)) for n,row in enumerate(rows) if n not in replaced]

DELEGATION = re.compile(
    r'<codex_delegation>\s*<source_thread_id>([0-9a-fA-F-]{36})</source_thread_id>'
    r'\s*<input>(.*?)</input>\s*</codex_delegation>', re.DOTALL)
DELEGATION_TOOLS = {'create_thread', 'send_message_to_thread'}


def codex_delegations(rows):
    """Find delegated turn inputs and the matching display copies of their receipts."""
    inputs, copies = {}, set()
    start = None
    first_output = None
    human = False

    def finish(end):
        if human or first_output is None:
            return
        receipt = rows[first_output]['payload']
        if receipt.get('namespace') != 'codex_app' or receipt.get('name') not in DELEGATION_TOOLS:
            return
        output = receipt.get('output')
        match = DELEGATION.fullmatch(output.strip()) if isinstance(output, str) else None
        if not match or not match[2].strip():
            return
        try:
            source = str(uuid.UUID(match[1]))
        except ValueError:
            return
        inputs[first_output] = (source, match[2])
        for index in range(first_output + 1, end):
            item = rows[index].get('payload', {}).get('item') or {}
            if (item.get('type') == 'FunctionCallOutput' and item.get('namespace') == 'codex_app'
                    and item.get('name') == receipt['name'] and item.get('output') == output):
                copies.add(index)

    for index, row in enumerate(rows):
        payload = row.get('payload') or {}
        record, kind = row.get('type'), payload.get('type')
        if record == 'event_msg' and kind in ('task_started', 'task_complete', 'turn_aborted'):
            if start is not None:
                finish(index)
            start = index if kind == 'task_started' else None
            first_output, human = None, False
        elif start is not None:
            if record == 'event_msg':
                human |= kind == 'user_message' or (kind == 'item_completed'
                    and (payload.get('item') or {}).get('type') == 'UserMessage')
            elif record == 'response_item' and kind == 'function_call_output' and first_output is None:
                first_output = index
    if start is not None:
        finish(len(rows))
    return inputs, copies


def export_codex(rows, sid, home, full_tools=False):
    """Read the UI layer (event_msg/item_completed) — exactly what the Codex sidebar shows, without harness-injected context."""
    title=backend.indexed_title(home,sid)
    turns=[]
    limit=lambda text,n: text if full_tools else clip(text,n)
    rows = codex_legacy_rows(rows)
    delegated, receipt_copies = codex_delegations(rows)
    for index, r in enumerate(rows):
        if index in delegated:
            source, text = delegated[index]
            turns.append({'user':{'ts':r.get('timestamp') or now(),
                'text':f'委派输入，来源线程 {source}\n\n{text}',
                'source_thread_id':source,'_raw_ref':r.get('_raw_ref')},'items':[]})
            continue
        if index in receipt_copies:
            continue
        q=r.get('payload',{})
        if r.get('type')!='event_msg' or q.get('type')!='item_completed': continue
        it=q.get('item',{}); kind=it.get('type'); ts=r.get('timestamp') or now()
        if kind=='UserMessage':
            text=codex_user_text(content(it.get('content')))
            if not text.strip() and any(x.get('type')=='local_image' for x in it.get('content',[])): text='[用户上传图片]'
            # Image/file-only turns are real user turns too.
            turns.append({'user':{'ts':ts,'text':text,'_raw_ref':r.get('_raw_ref')},'items':[]})
            continue
        if not turns: continue
        if kind=='AgentMessage':
            text=content(it.get('content'))
            if text.strip(): turns[-1]['items'].append({'kind':'message','ts':ts,'text':text,'phase':it.get('phase'),'_raw_ref':r.get('_raw_ref')})
        elif kind=='CommandExecution':
            cmd=it.get('command') or []
            cmd=cmd[-1] if len(cmd)>=3 and cmd[-2] in ('-Command','-c','/c') else ' '.join(cmd) if isinstance(cmd,list) else str(cmd)
            turns[-1]['items'].append({'kind':'tool','ts':ts,'name':'shell','input':limit(cmd,TOOL_INPUT_LIMIT),
                                       'args':{'command':cmd},'status':it.get('status'),'exit_code':it.get('exit_code'),
                                       'output':limit(it.get('aggregated_output') or '',TOOL_OUTPUT_LIMIT),'is_error':it.get('status')=='failed' or it.get('exit_code') not in (None,0),'_raw_ref':r.get('_raw_ref')})
        elif kind=='McpToolCall':
            args=it.get('arguments') or {}; res=it.get('result') or {}
            turns[-1]['items'].append({'kind':'tool','ts':ts,'name':f"mcp__{it.get('server','mcp')}__{it.get('tool','tool')}",
                                       'description':args.get('title','') if isinstance(args,dict) else '',
                                       'input':limit(json.dumps(args,ensure_ascii=False),TOOL_INPUT_LIMIT),
                                       'args':args if isinstance(args,dict) else {'input':args},
                                       'output':limit(content(res.get('content')) if isinstance(res,dict) else str(res),TOOL_OUTPUT_LIMIT),
                                       'is_error':bool(isinstance(res,dict) and res.get('isError')),'_raw_ref':r.get('_raw_ref')})
        elif kind=='LegacyTool':
            turns[-1]['items'].append({'kind':'tool','ts':ts,'name':it['name'],'args':it['args'],
                'input':limit(it['input'],TOOL_INPUT_LIMIT),'output':limit(it['output'],TOOL_OUTPUT_LIMIT),
                'status':it.get('status'),'is_error':it.get('status')=='failed','completed_ts':it['completed_ts'],'_raw_ref':r.get('_raw_ref')})
        elif kind not in ('Reasoning','ContextCompaction'):
            # Preserve visible patch/image/extension/agent activity as historical cards.
            args={k:v for k,v in it.items() if k not in ('id','type')}
            turns[-1]['items'].append({'kind':'tool','ts':ts,'name':'Codex_'+str(kind),'args':args,
                'input':limit(json.dumps(args,ensure_ascii=False),TOOL_INPUT_LIMIT),
                'output':limit(it.get('stdout') or it.get('output') or '(历史界面事件)',TOOL_OUTPUT_LIMIT),
                'is_error':it.get('status')=='failed','_raw_ref':r.get('_raw_ref')})
    return turns,title
def desktop_next_step(args):
    """The desktop's next-step box is visible conversation, not a hidden receipt."""
    recap=args.get('recap') or '';ask=args.get('ask') or ''
    labels=[x.get('label','') if isinstance(x,dict) else x for x in args.get('actions') or []]
    labels=[x for x in labels if isinstance(x,str) and x.strip()]
    if not recap and not ask:return None
    lines=['下一步：'+recap]
    if ask:lines.append('问：'+ask+('（选项：'+' / '.join(labels)+'）' if labels else ''))
    return '\n'.join(lines)

def export_claude(rows,full_tools=False):
    title=None; results={}
    limit=lambda text,n:text if full_tools else clip(text,n)
    for r in rows:
        if r.get('type')=='custom-title': title=r.get('customTitle') or title
        c=(r.get('message') or {}).get('content')
        if r.get('type')=='user' and isinstance(c,list) and not r.get('isSidechain') and not r.get('isMeta'):
            for x in c:
                if x.get('type')=='tool_result': results[x.get('tool_use_id')]=(content(x.get('content')),bool(x.get('is_error')),r.get('timestamp'))
    turns=[];next_steps=[]
    def flush_next_steps():
        if turns and next_steps:
            # The original final answer and the next-step box are both visible.
            # Otherwise Codex would hide the original answer as commentary.
            for item in reversed(turns[-1]['items']):
                if item['kind']=='message':
                    item.setdefault('phase','final_answer');break
            turns[-1]['items'].extend(next_steps)
        next_steps.clear()
    for r in rows:
        if r.get('type') not in ('user','assistant') or r.get('isMeta') or r.get('isSidechain') or r.get('isCompactSummary'): continue
        ts=r.get('timestamp') or now(); c=(r.get('message') or {}).get('content')
        if r['type']=='user':
            text,delegation,_=exchange.claude_user_projection(c)
            if not text.strip() and isinstance(c,list) and any(x.get('type')=='image' for x in c): text='[用户上传图片]'
            if text.lstrip().startswith('<task-notification>'):
                # harness background-task notice, not a user bubble: keep it inside the current turn
                m=re.search(r'<summary>(.*?)</summary>',text,re.S)
                if turns: turns[-1]['items'].append({'kind':'message','ts':ts,'text':'（后台任务通知）'+(m.group(1).strip() if m else ''),'_raw_ref':r.get('_raw_ref')})
            elif text.strip():
                flush_next_steps()
                turns.append({'user':{'ts':ts,'text':text,'_raw_ref':r.get('_raw_ref'),**delegation},'items':[]})
        elif turns:
            for block,x in enumerate(c or []):
                ref=dict(r['_raw_ref'],block=block) if r.get('_raw_ref') else None
                if x.get('type')=='text' and x.get('text','').strip(): turns[-1]['items'].append({'kind':'message','ts':ts,'text':x['text'],'_raw_ref':ref})
                elif x.get('type')=='tool_use':
                    if x.get('name')=='mcp__ccd_turn__wrap_up':
                        text=desktop_next_step(x.get('input') or {})
                        if text:next_steps.append({'kind':'message','ts':ts,'text':text,'phase':'final_answer','provenance':'claude-desktop-next-step','_raw_ref':ref})
                        continue
                    if x.get('name','').startswith('mcp__ccd_turn__'):continue
                    args=x.get('input') or {}; out,err,completed=results.get(x.get('id'),('',False,None))
                    turns[-1]['items'].append({'kind':'tool','ts':ts,'name':x.get('name','tool'),'description':args.get('description',''),
                                               'input':limit(args.get('command') if isinstance(args.get('command'),str) else json.dumps(args,ensure_ascii=False),TOOL_INPUT_LIMIT),
                                               'args':args,'output':limit(out,TOOL_OUTPUT_LIMIT),'is_error':err,'completed_ts':completed,'_raw_ref':ref})
    flush_next_steps()
    return turns,title
def export(agent, session, home, full_tools=False):
    p=locate(agent,session,home); rows=read(p)
    refs=exchange.raw_refs(p,rows)
    for row,ref in zip(rows,refs):row['_raw_ref']=ref
    meta=next((r['payload'] for r in rows if r.get('type')=='session_meta'),{})
    sid=meta.get('id') or meta.get('session_id') or next((r.get('sessionId') for r in rows if r.get('sessionId')),None) or p.stem
    cwd=meta.get('cwd') or next((r.get('cwd') for r in rows if r.get('cwd')),'')
    turns,title=export_claude(rows,full_tools) if agent=='claude' else export_codex(rows,sid,home,full_tools)
    if not turns: raise ValueError('没有可迁移的可见对话')
    source={'agent':agent,'session_id':sid,'path':str(p),'exported_at':now()}
    source['agent_version']=meta.get('cli_version') if agent=='codex' else next((row['version'] for row in reversed(rows) if row.get('version')),None)
    for field in ('forked_from','subagent_of'):
        value=meta.get(field) or next((row[field] for row in rows if row.get(field)),None)
        if value is not None:source[field]=value
    if agent=='codex':
        source['compaction_hint']=source_compaction_hint(rows)
        delegated_count=sum('source_thread_id' in turn['user'] for turn in turns)
        if delegated_count:
            source['delegated_input_count']=delegated_count
    else:
        delegated_count=sum('source_session_name' in turn['user'] for turn in turns)
        if delegated_count:
            source['delegated_input_count']=delegated_count
        boundaries=[x for x in rows if x.get('subtype')=='compact_boundary' and not x.get('isSidechain')]
        source['compaction_hint']={'count':len(boundaries),'timestamp':boundaries[-1].get('timestamp') if boundaries else None,'has_encrypted_compaction':False}
        calls=[x for row in rows if row.get('type')=='assistant' and not row.get('isMeta') and not row.get('isSidechain') for x in row.get('message',{}).get('content',[]) if isinstance(x,dict) and x.get('type')=='tool_use']
        source['converted_desktop_wrapups']=sum(x.get('name')=='mcp__ccd_turn__wrap_up' and bool(desktop_next_step(x.get('input') or {})) for x in calls)
        source['filtered_desktop_turn_calls']=sum(x.get('name','').startswith('mcp__ccd_turn__') and (x.get('name')!='mcp__ccd_turn__wrap_up' or not desktop_next_step(x.get('input') or {})) for x in calls)
    extras,losses=exchange.audit_source(agent,rows,refs)
    if not full_tools:
        for n,turn in enumerate(turns):
            for j,item in enumerate(turn['items']):
                if item['kind']=='tool' and any('…[已截断，原长 ' in item.get(field,'') for field in ('input','output')):
                    losses.append({'event':f'turn/{n}/items/{j}','raw_ref':item.get('_raw_ref'),'kind':'tool_text_limit','reason':'unsupported_by_target','action':'summarized','stage':'diagnostic-export'})
    return exchange.upgrade_v1({'schema':'agent-transcript/v1','source':source,'title':title or turns[0]['user']['text'][:60],
        'project':{'cwd':cwd},'turns':turns,'losses':losses,'_nonconversation_events':extras})
def validate(b):
    if b.get('schema')==exchange.SCHEMA:
        exchange.validate(b);return validate(exchange.to_v1(b))
    if b.get('schema')!='agent-transcript/v1' or b['source']['agent'] not in ('claude','codex'): raise ValueError('不支持的对话包')
    uuid.UUID(b['source']['session_id'])
    if not b['turns']: raise ValueError('空对话包')
    for n,t in enumerate(b['turns']):
        backend.to_ms(t['user']['ts'])
        if not isinstance(t['user']['text'],str): raise ValueError('消息必须是文本')
        for j,i in enumerate(t['items']):
            if i['kind']=='message' and isinstance(i['text'],str): pass
            elif i['kind']=='tool' and isinstance(i.get('name'),str) and isinstance(i.get('input',''),str) and isinstance(i.get('output',''),str): pass
            elif any(x.get('event')==(i.get('id') or f'turn/{n}/items/{j}') and x.get('reason') in exchange.REASONS and x.get('action') in exchange.ACTIONS for x in b.get('losses',[])): pass
            else: raise ValueError('不支持的历史项；需要明确对应的损失条目')
            backend.to_ms(i['ts'])
CLAUDE_NATIVE_TOOLS={'Bash','Read','Write','Edit','Glob','Grep','WebFetch','WebSearch','NotebookEdit','PowerShell'}
def claude_tool_use(i):
    if i['name'] in CLAUDE_NATIVE_TOOLS and isinstance(i.get('args'),dict): return i['name'],i['args']
    if i['name']=='shell': return 'Bash',{'command':i.get('input',''),'description':i.get('description','')}
    name=re.sub(r'[^a-zA-Z0-9_-]','_',i['name'])[:64]
    if isinstance(i.get('args'),dict): return name,i['args']
    try: args=json.loads(i.get('input') or '{}')
    except ValueError: args={'input':i.get('input','')}
    return name,args if isinstance(args,dict) else {'input':args}
def desktop_registry_dir(a):
    """Claude desktop (Code tab) lists sessions from claude-code-sessions/<org>/<account>/local_*.json, not from projects/*.jsonl."""
    if getattr(a,'no_desktop',False): return None
    if getattr(a,'desktop_registry',None): return Path(a.desktop_registry)
    if a.target_home: return None  # custom home: only register when the directory is given explicitly
    if sys.platform=='darwin':
        # MAC-C1 verified this layout on macOS 14.8.9 / Claude desktop 4.4212.0.
        base=Path.home()/'Library/Application Support/Claude/claude-code-sessions'
        pattern='*/*/local_*.json'
    elif sys.platform=='win32':
        base=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'Claude-Data'
        pattern='*/claude-code-sessions/*/*/local_*.json'
    else:return None
    dirs={f.parent for f in base.glob(pattern)}
    return max(dirs,key=lambda d:max(f.stat().st_mtime for f in d.glob('local_*.json'))) if dirs else None
def desktop_model(a):
    d=desktop_registry_dir(a)
    for f in sorted(d.glob('local_*.json') if d else [],key=lambda f:f.stat().st_mtime,reverse=True):
        try:
            m=json.loads(f.read_text(encoding='utf-8')).get('model')
            if m: return m
        except (OSError,ValueError): continue
def register_desktop(b, a, sid, cwd, save=None):
    d=desktop_registry_dir(a)
    if not d: return None
    existing=sorted(d.glob('local_*.json'),key=lambda f:f.stat().st_mtime)
    for f in existing:
        try:
            if json.loads(f.read_text(encoding='utf-8')).get('cliSessionId')==sid: return str(f)
        except (OSError,ValueError): continue
    latest={}
    if existing:
        try: latest=json.loads(existing[-1].read_text(encoding='utf-8'))
        except (OSError,ValueError): pass
    local='local_'+str(uuid.uuid5(NS,'desktop/'+sid)); target=d/(local+'.json')
    if target.exists(): raise ValueError('Desktop registration ID collision; refusing to overwrite')
    if a.dry_run: return str(target)
    if save: save(target)
    ms=int(dt.datetime.now().timestamp()*1000)
    rec={'sessionId':local,'cliSessionId':sid,'cwd':cwd,'originCwd':cwd,'gitAnchorsFolderRealpath':cwd,'createdAt':ms,'lastActivityAt':ms,'lastTurnEdgeAt':ms,
         'isArchived':False,'title':b['title'],'titleSource':'user','permissionMode':'default','completedTurns':len(b['turns'])}
    for k in ('model','effort'):
        if latest.get(k): rec[k]=latest[k]
    dump(target,rec); return str(target)
def build_claude_history(b,a,sid,cwd):
    """Build full native history first. Context selection never changes these bodies."""
    from target_settings import claude_settings
    model,a.claude_version=claude_settings(Path(a.target_home or Path.home()/'.claude'),
        getattr(a,'claude_model',None),getattr(a,'claude_version',None),desktop_model(a))
    rows=[];groups=[];parent=None
    def add(role,ts,body,stop='end_turn'):
        nonlocal parent
        uid=str(uuid.uuid4());msg={'role':role,'content':body}
        if role=='assistant': msg.update(id='msg_'+uid.replace('-',''),type='message',model=model,stop_reason=stop,stop_sequence=None,usage={'input_tokens':0,'output_tokens':0})
        rows.append({'type':role,'uuid':uid,'parentUuid':parent,'sessionId':sid,'cwd':cwd,'version':a.claude_version,'isSidechain':False,'userType':'external','timestamp':ts,'message':msg});parent=uid
    for t in b['turns']:
        start=len(rows);body=[{'type':'text','text':t['user']['text']}]
        for att in t['user'].get('attachments',[]):
            if att.get('image'):
                path=Path(att['local_path']);body.append({'type':'image','source':{'type':'base64','media_type':att.get('mime') or mimetypes.guess_type(path)[0] or 'image/png','data':inline_image(path)}})
        add('user',t['user']['ts'],body if len(body)>1 else t['user']['text'])
        for i in t['items']:
            if i['kind']=='message':add('assistant',i['ts'],[{'type':'text','text':i['text']}])
            else:
                name,args=claude_tool_use(i);tid='toolu_'+uuid.uuid4().hex[:24]
                add('assistant',i['ts'],[{'type':'tool_use','id':tid,'name':name,'input':args}],'tool_use')
                add('user',i['ts'],[{'type':'tool_result','tool_use_id':tid,'content':i.get('output') or '(无输出)','is_error':bool(i.get('is_error'))}])
        groups.append(rows[start:])
    rows.append({'type':'custom-title','sessionId':sid,'customTitle':b['title']})
    return rows,groups

def compact_claude_history(rows,groups,plan,sid,cwd,version):
    if not plan['prefix_turns']:return rows
    cut=sum(len(g) for g in groups[:plan['prefix_turns']]);stamp=now()
    bid=str(uuid.uuid4());summary_id=str(uuid.uuid4())
    common={'sessionId':sid,'cwd':cwd,'version':version,'isSidechain':False,'userType':'external','timestamp':stamp}
    boundary={'type':'system','subtype':'compact_boundary','content':'Conversation compacted','level':'info',
        'uuid':bid,'parentUuid':None,'logicalParentUuid':rows[cut-1]['uuid'],**common,
        'compactMetadata':{'trigger':'manual','preTokens':plan['original_estimated_tokens'],
            'postTokens':plan['estimated_tokens'],'messagesSummarized':cut,'userContext':'Imported historical data; no automatic task continuation'},
        'rehomeContextPolicy':POLICY_VERSION}
    summary={'type':'user','uuid':summary_id,'parentUuid':bid,'isCompactSummary':True,
        'summarizeMetadata':{'messagesSummarized':cut,'direction':'up_to'},**common,
        'message':{'role':'user','content':plan['summary']}}
    tail=rows[cut:]
    if tail and 'uuid' in tail[0]:tail=[dict(tail[0],parentUuid=summary_id),*tail[1:]]
    result=rows[:cut]+[boundary,summary]+tail
    if estimate_records(result[cut+1:])>plan['budget']:raise ValueError('写入前上下文预算核对失败')
    return result

def import_bundle(b, a):
    validate(b)
    if b['source']['agent']==a.to and not getattr(a,'convert',False):
        if a.to=='codex': raise ValueError('Codex→Codex requires a --native package; --convert is diagnostics only.')
        raise ValueError('Claude→Claude: use native transfer or a --native package; converted history requires explicit --convert.')
    canonical=exchange.upgrade_v1(b);b=exchange.to_v1(canonical);losses=list(b.get('losses',[]))
    cwd=str(Path(a.cwd).resolve())
    if not Path(cwd).is_dir(): raise ValueError('目标项目目录不存在')
    home=Path(a.target_home or Path.home()/('.codex' if a.to=='codex' else '.claude')).resolve()
    from target_settings import codex_model,claude_settings
    if a.to=='codex': a.model=codex_model(home,getattr(a,'model',None))
    else:
        a.claude_model,a.claude_version=claude_settings(home,getattr(a,'claude_model',None),
            getattr(a,'claude_version',None),desktop_model(a))
    notices=[]
    if a.to=='claude' and not getattr(a,'no_desktop',False) and not desktop_registry_dir(a):
        notices.append('Claude desktop registration unavailable (known layouts: Windows and the MAC-C1 macOS sample). '
            'History can be resumed in Claude Code CLI; use --desktop-registry for a verified layout. Sidebar visibility is not verified.')
    fingerprint={'title':b['title'],'turns':b['turns'],'losses':losses,'extensions':b.get('_nonconversation_events',[])}
    if a.to=='claude':fingerprint['context_policy']={'version':POLICY_VERSION,'budget':getattr(a,'claude_context_budget',DEFAULT_BUDGET)}
    else:fingerprint['context_policy']={'version':codex_native.POLICY_VERSION,'budget':getattr(a,'codex_context_budget',DEFAULT_BUDGET)}
    bundle_hash=hashlib.sha256(json.dumps(fingerprint,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    key=('claude/' if b['source']['agent']=='claude' and a.to=='codex' else b['source']['agent']+'/')+b['source']['session_id']
    if getattr(a,'new_copy',False):
        # Source moved on since the last import: keep the old copy untouched, add a dated snapshot as a new session.
        key+='/snapshot/'+bundle_hash[:16]; b=dict(b,title=f"{b['title']} · 快照 {dt.datetime.now().strftime('%m-%d %H:%M')}")
    sid=str(uuid.uuid5(NS,key))
    for turn in b['turns']:
        user=turn['user']
        if 'source_session_name' in user:
            label='委派输入，来源会话 '+user['source_session_name']
            background=user.get('delegated_background')
            user['text']=label+'\n\n'+user['text']+('\n\n（委派背景，来自启动器）\n'+background if background else '')
    manifest=home/'rehome-imports'/f'{a.to}-{sid}.json'
    old=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else None
    if old:
        if old.get('bundle_hash')!=bundle_hash: raise ValueError('来源历史已变化；已有导入保持原样。如需带上新内容，加 --new-copy 导入为新会话')
        for p,h in old['files'].items():
            if not Path(p).exists() or digest(p)!=h: raise ValueError('目标历史已变化或续聊，拒绝覆盖')
        if old['cwd']!=cwd: raise ValueError('已有导入绑定其他路径，拒绝自动移动')
        reg=None; registration_written=False
        if a.to=='claude':
            probe=argparse.Namespace(**vars(a));probe.dry_run=True
            reg=register_desktop(b,probe,sid,cwd)
            if reg and not a.dry_run and not Path(reg).exists():
                registry_backup=home/'rehome-backups'/('registration-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
                dump(registry_backup/'backup.json',{reg:{'existed':False,'backup':None}})
                reg=register_desktop(b,a,sid,cwd)
                registration_written=bool(reg)
        result={'status':'already-imported','id':sid,'desktop_registry':reg,'context':old.get('context'),'warnings':notices,'losses_summary':old.get('losses_summary',exchange.loss_summary(losses))}
        if registration_written and not getattr(a,'project_restore',False):
            add_next_steps(result,a.to,cwd,[b['title']])
        print(json.dumps(result,ensure_ascii=False)); return result
    hits=list(home.glob(('sessions/**/rollout-*'+sid+'.jsonl*') if a.to=='codex' else ('projects/*/'+sid+'.jsonl')))
    if hits: raise ValueError('存在未受本工具管理的同 ID 会话，拒绝覆盖')
    context=None
    if a.to=='claude':
        history,groups=build_claude_history(b,a,sid,cwd)
        plan=plan_context(b,groups,getattr(a,'claude_context_budget',DEFAULT_BUDGET))
        context={k:v for k,v in plan.items() if k!='summary'}
        archive_path=Path(cwd)/'.rehome/history'/(sid+'.jsonl') if plan['prefix_turns'] else None
        context_report_path=Path(cwd)/'.rehome/context'/(sid+'.json')
    else:
        native_rollout=codex_native.build_rollout(sid,b,cwd,a.model,getattr(a,'codex_context_budget',DEFAULT_BUDGET))
        context=native_rollout.context_plan
        archive_path=Path(cwd)/'.rehome/history/codex'/(sid+'.jsonl')
        context_report_path=Path(cwd)/'.rehome/context/codex'/(sid+'.json')
    loss_report=Path(cwd)/'.rehome/losses'/a.to/(sid+'.json')
    exchange_archive=Path(cwd)/'.rehome/exchange'/a.to/(sid+'.json')
    if (archive_path and archive_path.exists()) or context_report_path.exists() or loss_report.exists() or exchange_archive.exists():raise ValueError('历史归档或上下文报告已存在，拒绝覆盖；目标尚未写入')
    if context and context.get('prefix_turns'):
        losses.append({'event':'target-context','kind':'target_context','reason':'unsupported_by_target','action':'summarized','stage':'derived-context','count':context['prefix_turns']})
    print(json.dumps({'target':a.to,'id':sid,'cwd':cwd,'turns':len(b['turns']),'dry_run':a.dry_run,'context':context,
                      'desktop_registry':register_desktop(b,a,sid,cwd) if a.to=='claude' and a.dry_run else None,'warnings':notices,'losses_summary':exchange.loss_summary(losses)},ensure_ascii=False))
    if a.dry_run: return
    stamp=dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f'); backup=home/'rehome-backups'/stamp
    backup.mkdir(parents=True)
    before={}
    def save(p):
        p=Path(p); exists=p.exists(); dest=backup/(str(len(before))+'-'+p.name)
        if exists:
            if p.suffix=='.sqlite':
                with closing(sqlite3.connect(sqlite_read_uri(p),uri=True)) as db, closing(sqlite3.connect(dest)) as out: db.backup(out)
            else: shutil.copy2(p,dest)
        before[str(p)]={'existed':exists,'backup':str(dest) if exists else None}
        dump(backup/'backup.json',before)
    if a.to=='claude':
        project=re.sub(r'[^a-zA-Z0-9_-]','-',cwd)
        target=home/'projects'/project/(sid+'.jsonl'); save(target)
        def write_rows(path,rows):
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('w',encoding='utf-8') as f:
                for row in rows:f.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
        archive=None
        if plan['prefix_turns']:
            archive=archive_path
            save(archive);write_rows(archive,history)
            context['archive']=str(archive)
        rows=compact_claude_history(history,groups,plan,sid,cwd,a.claude_version)
        write_rows(target,rows)
        files=[target]
        if archive:files.append(archive)
        report=context_report_path
        save(report);dump(report,context);files.append(report)
        # The desktop app rewrites its registry entry on use, so it is tracked but not hashed.
        reg=register_desktop(b,a,sid,cwd,save)
    else:
        reg=None
        db=home/'state_5.sqlite'
        if not db.exists(): raise ValueError('目标 Codex 尚未初始化，先运行一次 Codex')
        with closing(sqlite3.connect(sqlite_read_uri(db),uri=True)) as check:
            required={'threads': 'id rollout_path created_at updated_at source model_provider cwd title sandbox_policy approval_mode tokens_used has_user_event archived cli_version first_user_message memory_mode model reasoning_effort created_at_ms updated_at_ms thread_source preview recency_at recency_at_ms history_mode name project_id originator', 'projects':'id name metadata position created_at_ms updated_at_ms','project_roots':'project_id position path'}
            for table,cols in required.items():
                actual={row[1] for row in check.execute('pragma table_info('+table+')')}
                if not set(cols.split()) <= actual: raise ValueError('目标数据库格式不兼容：'+table)
        save(db); save(home/'session_index.jsonl')
        first=b['turns'][0]['user'];last_ts=(b['turns'][-1]['items'] or [b['turns'][-1]['user']])[-1]['ts']
        backend.write_codex_thread(home,sid,native_rollout,cwd,b['title'],a.model,
            first_ts=first['ts'],last_ts=last_ts,first_user_message=first['text'])
        files=list(home.glob('sessions/**/rollout-*'+sid+'.jsonl'))
        if len(files)!=1: raise ValueError('写入后 rollout 数量不正确')
        archive=archive_path;report=context_report_path
        save(archive);archive.parent.mkdir(parents=True,exist_ok=True)
        with archive.open('w',encoding='utf-8') as f:
            for row in native_rollout.history_archive_lines:f.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
        context['archive']=str(archive);save(report);dump(report,context);files.extend([archive,report])
    dump(backup/'backup.json',before)
    save(exchange_archive);dump(exchange_archive,canonical);files.append(exchange_archive)
    loss_report=Path(cwd)/'.rehome/losses'/a.to/(sid+'.json');save(loss_report);dump(loss_report,{'losses':losses,'losses_summary':exchange.loss_summary(losses)});files.append(loss_report)
    dump(manifest,{'id':sid,'cwd':cwd,'bundle_hash':bundle_hash,'source':b['source'],'files':{str(p):digest(p) for p in files},'desktop_registry':reg,'backup':str(backup),'context':context,'losses_summary':exchange.loss_summary(losses)})
    result={'status':'written','id':sid,'backup':str(backup),'desktop_registry':reg,'context':context,'warnings':notices,'losses_summary':exchange.loss_summary(losses),'losses_report':str(loss_report),
            'next':'重启 Claude 桌面版后在侧边栏打开' if reg else ('未找到 Claude 桌面版登记目录，只能用 CLI resume' if a.to=='claude' else 'native resume still required')}
    if not getattr(a,'project_restore',False) and not getattr(a,'no_desktop',False) and (reg or a.to=='codex'):
        add_next_steps(result,a.to,cwd,[b['title']])
    print(json.dumps(result,ensure_ascii=False));return result
def main():
    configure()
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='command',required=True)
    for name in ('export','transfer','import'):
        q=sub.add_parser(name)
        if name!='import':
            q.add_argument('--from',dest='source',required=True,help='claude:<id/path> 或 codex:<id/path>'); q.add_argument('--source-home')
            q.add_argument('--native',action='store_true',help='Export private same-agent native directory package')
            q.add_argument('--include-memory',action='store_true');q.add_argument('--include-checkpoints',action='store_true')
            q.add_argument('--source-desktop-registry')
        if name=='export': q.add_argument('--out',required=True)
        else:
            q.add_argument('--convert',action='store_true',help='Explicitly allow lossy same-agent conversion for diagnostics')
            if name=='import': q.add_argument('bundle')
            q.add_argument('--to',choices=['claude','codex'],required=True); q.add_argument('--cwd',required=True); q.add_argument('--target-home'); q.add_argument('--dry-run',action='store_true'); q.add_argument('--model',help='Target Codex model; detected from target config/history when omitted'); q.add_argument('--claude-version',help='Target Claude Code version; detected from target history when omitted')
            q.add_argument('--desktop-registry',help='Claude 桌面版 claude-code-sessions/<org>/<account> 目录；默认自动查找'); q.add_argument('--no-desktop',action='store_true',help='不登记到 Claude 桌面版')
            q.add_argument('--claude-model',help='写入 Claude 历史的模型名；默认沿用桌面版最近会话的模型'); q.add_argument('--new-copy',action='store_true',help='来源已更新时，另存为新会话（旧导入不动）')
            q.add_argument('--fast-forward',action='store_true',help='Native Claude only: append unchanged-prefix history in the existing project')
            q.add_argument('--claude-context-budget',type=int,default=DEFAULT_BUDGET,help='Claude 恢复上下文的保守估算预算（默认 64000）；完整历史另行保留')
            q.add_argument('--codex-context-budget',type=int,default=DEFAULT_BUDGET,help='Codex 恢复上下文的保守估算预算（默认 64000）')
    a=p.parse_args()
    if getattr(a,'fast_forward',False) and (a.to!='claude' or a.convert or a.new_copy):raise ValueError('--fast-forward requires native Claude and is mutually exclusive with --new-copy/--convert')
    if a.command=='import':
        if Path(a.bundle).is_dir():
            import claude_native,codex_relocate
            schema=json.loads((Path(a.bundle)/'manifest.json').read_text(encoding='utf-8'))['schema']
            module=codex_relocate if schema==codex_relocate.SCHEMA else claude_native
            module.restore(module.load(a.bundle),a);return
        b=json.loads(Path(a.bundle).read_text(encoding='utf-8-sig'))
    else:
        agent,session=a.source.split(':',1)
        if agent not in ('claude','codex'): raise ValueError('来源必须是 claude 或 codex')
        home=Path(a.source_home or Path.home()/('.claude' if agent=='claude' else '.codex'))
        native=a.native or (a.command=='transfer' and agent==a.to and not a.convert)
        if native:
            import claude_native,codex_relocate
            module=claude_native if agent=='claude' else codex_relocate
            snap=module.snapshot(locate(agent,session,home),home,a.include_memory,a.include_checkpoints,a.source_desktop_registry)
            if a.command=='export':module.pack(snap,a.out);print(a.out);print(json.dumps({'user_next_steps':package_next_steps(a.out)},ensure_ascii=False))
            else:module.restore(snap,a)
            return
        b=export(agent,session,a.source_home or Path.home()/('.claude' if agent=='claude' else '.codex'),full_tools=True)
    if a.command=='export': validate(b); dump(a.out,b); print(a.out); print(json.dumps({'user_next_steps':package_next_steps(a.out)},ensure_ascii=False))
    else:
        if a.fast_forward:raise ValueError('--fast-forward requires a native Claude directory package or transfer')
        import_bundle(b,a)
if __name__=='__main__':
    try: main()
    except (ValueError,KeyError,sqlite3.Error) as e: sys.exit(str(e))
