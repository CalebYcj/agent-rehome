"""Portable visible-history transfer; no GUI dependency. Python 3.10+."""
from platform_paths import sqlite_read_uri
from contextlib import closing
import base64, mimetypes
import argparse, datetime as dt, hashlib, json, os, re, shutil, sqlite3, sys, uuid
from pathlib import Path
import codex_backend as backend
import codex_native
from claude_context import DEFAULT_BUDGET, POLICY_VERSION, estimate_records, plan_context, source_compaction_hint
NS = uuid.UUID('6f1c2a9e-4b7d-4c1e-9a3f-c1a0dec0de01')
def now(): return dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z')
def read(p):
    if str(p).endswith('.zst'): raise ValueError('先把 .zst 解压为 .jsonl；源文件保持不变')
    with open(p, encoding='utf-8-sig') as f: return [json.loads(l) for l in f if l.strip()]
def dump(p, obj):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.rehome-tmp'); tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8'); os.replace(tmp,p)
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def locate(agent, session, home):
    p=Path(session)
    if p.is_file(): return p
    hits=list(Path(home).glob(('projects/*/' if agent=='claude' else 'sessions/**/rollout-*')+session+('.jsonl' if agent=='claude' else '.jsonl*')))
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
def export_codex(rows, sid, home, full_tools=False):
    """Read the UI layer (event_msg/item_completed) — exactly what the Codex sidebar shows, without harness-injected context."""
    title=None; idx=Path(home)/'session_index.jsonl'
    if idx.exists(): title=next((x.get('thread_name') for x in reversed(read(idx)) if x.get('id')==sid),None)
    turns=[]
    limit=lambda text,n: text if full_tools else clip(text,n)
    for r in rows:
        q=r.get('payload',{})
        if r.get('type')!='event_msg' or q.get('type')!='item_completed': continue
        it=q.get('item',{}); kind=it.get('type'); ts=r.get('timestamp') or now()
        if kind=='UserMessage':
            text=codex_user_text(content(it.get('content')))
            if not text.strip() and any(x.get('type')=='local_image' for x in it.get('content',[])): text='[用户上传图片]'
            # Image/file-only turns are real user turns too.
            turns.append({'user':{'ts':ts,'text':text},'items':[]})
            continue
        if not turns: continue
        if kind=='AgentMessage':
            text=content(it.get('content'))
            if text.strip(): turns[-1]['items'].append({'kind':'message','ts':ts,'text':text,'phase':it.get('phase')})
        elif kind=='CommandExecution':
            cmd=it.get('command') or []
            cmd=cmd[-1] if len(cmd)>=3 and cmd[-2] in ('-Command','-c','/c') else ' '.join(cmd) if isinstance(cmd,list) else str(cmd)
            turns[-1]['items'].append({'kind':'tool','ts':ts,'name':'shell','input':limit(cmd,TOOL_INPUT_LIMIT),
                                       'output':limit(it.get('aggregated_output') or '',TOOL_OUTPUT_LIMIT),'is_error':it.get('status')=='failed' or it.get('exit_code') not in (None,0)})
        elif kind=='McpToolCall':
            args=it.get('arguments') or {}; res=it.get('result') or {}
            turns[-1]['items'].append({'kind':'tool','ts':ts,'name':f"mcp__{it.get('server','mcp')}__{it.get('tool','tool')}",
                                       'description':args.get('title','') if isinstance(args,dict) else '',
                                       'input':limit(json.dumps(args,ensure_ascii=False),TOOL_INPUT_LIMIT),
                                       'args':args if isinstance(args,dict) else {'input':args},
                                       'output':limit(content(res.get('content')) if isinstance(res,dict) else str(res),TOOL_OUTPUT_LIMIT),
                                       'is_error':bool(isinstance(res,dict) and res.get('isError'))})
        elif kind not in ('Reasoning','ContextCompaction'):
            # Preserve visible patch/image/extension/agent activity as historical cards.
            args={k:v for k,v in it.items() if k not in ('id','type')}
            turns[-1]['items'].append({'kind':'tool','ts':ts,'name':'Codex_'+str(kind),'args':args,
                'input':limit(json.dumps(args,ensure_ascii=False),TOOL_INPUT_LIMIT),
                'output':limit(it.get('stdout') or it.get('output') or '(历史界面事件)',TOOL_OUTPUT_LIMIT),
                'is_error':it.get('status')=='failed'})
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
        if r.get('type')=='user' and isinstance(c,list):
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
            text=c if isinstance(c,str) else '\n'.join(x.get('text','') for x in c or [] if x.get('type')=='text')
            if not text.strip() and isinstance(c,list) and any(x.get('type')=='image' for x in c): text='[用户上传图片]'
            if text.lstrip().startswith('<task-notification>'):
                # harness background-task notice, not a user bubble: keep it inside the current turn
                m=re.search(r'<summary>(.*?)</summary>',text,re.S)
                if turns: turns[-1]['items'].append({'kind':'message','ts':ts,'text':'（后台任务通知）'+(m.group(1).strip() if m else '')})
            elif text.strip():
                flush_next_steps()
                turns.append({'user':{'ts':ts,'text':text},'items':[]})
        elif turns:
            for x in c or []:
                if x.get('type')=='text' and x.get('text','').strip(): turns[-1]['items'].append({'kind':'message','ts':ts,'text':x['text']})
                elif x.get('type')=='tool_use':
                    if x.get('name')=='mcp__ccd_turn__wrap_up':
                        text=desktop_next_step(x.get('input') or {})
                        if text:next_steps.append({'kind':'message','ts':ts,'text':text,'phase':'final_answer','provenance':'claude-desktop-next-step'})
                        continue
                    if x.get('name','').startswith('mcp__ccd_turn__'):continue
                    args=x.get('input') or {}; out,err,completed=results.get(x.get('id'),('',False,None))
                    turns[-1]['items'].append({'kind':'tool','ts':ts,'name':x.get('name','tool'),'description':args.get('description',''),
                                               'input':limit(args.get('command') if isinstance(args.get('command'),str) else json.dumps(args,ensure_ascii=False),TOOL_INPUT_LIMIT),
                                               'args':args,'output':limit(out,TOOL_OUTPUT_LIMIT),'is_error':err,'completed_ts':completed})
    flush_next_steps()
    return turns,title
def export(agent, session, home, full_tools=False):
    p=locate(agent,session,home); rows=read(p)
    meta=next((r['payload'] for r in rows if r.get('type')=='session_meta'),{})
    sid=meta.get('id') or meta.get('session_id') or next((r.get('sessionId') for r in rows if r.get('sessionId')),None) or p.stem
    cwd=meta.get('cwd') or next((r.get('cwd') for r in rows if r.get('cwd')),'')
    turns,title=export_claude(rows,full_tools) if agent=='claude' else export_codex(rows,sid,home,full_tools)
    if not turns: raise ValueError('没有可迁移的可见对话')
    source={'agent':agent,'session_id':sid,'path':str(p),'exported_at':now()}
    if agent=='codex': source['compaction_hint']=source_compaction_hint(rows)
    else:
        boundaries=[x for x in rows if x.get('subtype')=='compact_boundary' and not x.get('isSidechain')]
        source['compaction_hint']={'count':len(boundaries),'timestamp':boundaries[-1].get('timestamp') if boundaries else None,'has_encrypted_compaction':False}
        calls=[x for row in rows if row.get('type')=='assistant' and not row.get('isMeta') and not row.get('isSidechain') for x in row.get('message',{}).get('content',[]) if isinstance(x,dict) and x.get('type')=='tool_use']
        source['converted_desktop_wrapups']=sum(x.get('name')=='mcp__ccd_turn__wrap_up' and bool(desktop_next_step(x.get('input') or {})) for x in calls)
        source['filtered_desktop_turn_calls']=sum(x.get('name','').startswith('mcp__ccd_turn__') and (x.get('name')!='mcp__ccd_turn__wrap_up' or not desktop_next_step(x.get('input') or {})) for x in calls)
    return {'schema':'agent-transcript/v1','source':source,'title':title or turns[0]['user']['text'][:60],'project':{'cwd':cwd},'turns':turns}
def validate(b):
    if b.get('schema')!='agent-transcript/v1' or b['source']['agent'] not in ('claude','codex'): raise ValueError('不支持的对话包')
    uuid.UUID(b['source']['session_id'])
    if not b['turns']: raise ValueError('空对话包')
    for t in b['turns']:
        backend.to_ms(t['user']['ts'])
        if not isinstance(t['user']['text'],str): raise ValueError('消息必须是文本')
        for i in t['items']:
            if i['kind']=='message' and isinstance(i['text'],str): pass
            elif i['kind']=='tool' and isinstance(i.get('name'),str) and isinstance(i.get('input',''),str) and isinstance(i.get('output',''),str): pass
            else: raise ValueError('不支持的历史项')
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
    if os.name!='nt': return None  # Other desktop layouts have not been verified.
    base=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'Claude-Data'
    dirs={f.parent for f in base.glob('*/claude-code-sessions/*/*/local_*.json')}
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
                path=Path(att['local_path']);body.append({'type':'image','source':{'type':'base64','media_type':att.get('mime') or mimetypes.guess_type(path)[0] or 'image/png','data':base64.b64encode(path.read_bytes()).decode()}})
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
    validate(b); cwd=str(Path(a.cwd).resolve())
    if not Path(cwd).is_dir(): raise ValueError('目标项目目录不存在')
    home=Path(a.target_home or Path.home()/('.codex' if a.to=='codex' else '.claude')).resolve()
    from target_settings import codex_model,claude_settings
    if a.to=='codex': a.model=codex_model(home,getattr(a,'model',None))
    else:
        a.claude_model,a.claude_version=claude_settings(home,getattr(a,'claude_model',None),
            getattr(a,'claude_version',None),desktop_model(a))
    notices=[]
    if a.to=='claude' and not getattr(a,'no_desktop',False) and not desktop_registry_dir(a):
        notices.append('Claude desktop registration unavailable (auto-detection tested only on Windows). '
            'History can be resumed in Claude Code CLI; use --desktop-registry for a verified layout. Sidebar visibility is not verified.')
    fingerprint={'title':b['title'],'turns':b['turns']}
    if a.to=='claude':fingerprint['context_policy']={'version':POLICY_VERSION,'budget':getattr(a,'claude_context_budget',DEFAULT_BUDGET)}
    else:fingerprint['context_policy']={'version':codex_native.POLICY_VERSION,'budget':getattr(a,'codex_context_budget',DEFAULT_BUDGET)}
    bundle_hash=hashlib.sha256(json.dumps(fingerprint,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    key=('claude/' if b['source']['agent']=='claude' and a.to=='codex' else b['source']['agent']+'/')+b['source']['session_id']
    if getattr(a,'new_copy',False):
        # Source moved on since the last import: keep the old copy untouched, add a dated snapshot as a new session.
        key+='/snapshot/'+bundle_hash[:16]; b=dict(b,title=f"{b['title']} · 快照 {dt.datetime.now().strftime('%m-%d %H:%M')}")
    sid=str(uuid.uuid5(NS,key))
    manifest=home/'rehome-imports'/f'{a.to}-{sid}.json'
    old=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else None
    if old:
        if old.get('bundle_hash')!=bundle_hash: raise ValueError('来源历史已变化；已有导入保持原样。如需带上新内容，加 --new-copy 导入为新会话')
        for p,h in old['files'].items():
            if not Path(p).exists() or digest(p)!=h: raise ValueError('目标历史已变化或续聊，拒绝覆盖')
        if old['cwd']!=cwd: raise ValueError('已有导入绑定其他路径，拒绝自动移动')
        reg=None
        if a.to=='claude':
            probe=argparse.Namespace(**vars(a));probe.dry_run=True
            reg=register_desktop(b,probe,sid,cwd)
            if reg and not a.dry_run and not Path(reg).exists():
                registry_backup=home/'rehome-backups'/('registration-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
                dump(registry_backup/'backup.json',{reg:{'existed':False,'backup':None}})
                reg=register_desktop(b,a,sid,cwd)
        result={'status':'already-imported','id':sid,'desktop_registry':reg,'context':old.get('context'),'warnings':notices}
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
    if (archive_path and archive_path.exists()) or context_report_path.exists():raise ValueError('历史归档或上下文报告已存在，拒绝覆盖；目标尚未写入')
    print(json.dumps({'target':a.to,'id':sid,'cwd':cwd,'turns':len(b['turns']),'dry_run':a.dry_run,'context':context,
                      'desktop_registry':register_desktop(b,a,sid,cwd) if a.to=='claude' and a.dry_run else None,'warnings':notices},ensure_ascii=False))
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
        # Preserve the locally verified rollout/database writer, with strict wrapper guards.
        save(db); save(home/'session_index.jsonl')
        turns=[{'user':(t['user']['ts'],t['user']['text']),'agent':[(i['ts'],i['text']) for i in t['items'] if i['kind']=='message']} for t in b['turns']]
        backend.find_session=lambda _: str(Path(b['source']['session_id']+'.jsonl'))
        last_ts=(b['turns'][-1]['items'] or [b['turns'][-1]['user']])[-1]['ts']
        backend.parse_claude=lambda *_: (turns,b['title'],turns[0]['user'][0],last_ts)
        backend.target_thread_id=sid
        backend.import_attachments=[t['user'].get('attachments',[]) for t in b['turns']]
        sys.argv=['codex_backend',b['source']['session_id'],'--cwd',cwd,'--codex-home',str(home),'--model',a.model]
        previous_builder=backend.build_rollout
        backend.build_rollout=lambda *_:native_rollout
        try:backend.main()
        finally:backend.build_rollout=previous_builder
        files=list(home.glob('sessions/**/rollout-*'+sid+'.jsonl'))
        if len(files)!=1: raise ValueError('写入后 rollout 数量不正确')
        archive=archive_path;report=context_report_path
        save(archive);archive.parent.mkdir(parents=True,exist_ok=True)
        with archive.open('w',encoding='utf-8') as f:
            for row in native_rollout.history_archive_lines:f.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
        context['archive']=str(archive);save(report);dump(report,context);files.extend([archive,report])
    dump(backup/'backup.json',before)
    dump(manifest,{'id':sid,'cwd':cwd,'bundle_hash':bundle_hash,'source':b['source'],'files':{str(p):digest(p) for p in files},'desktop_registry':reg,'backup':str(backup),'context':context})
    result={'status':'written','id':sid,'backup':str(backup),'desktop_registry':reg,'context':context,'warnings':notices,
            'next':'重启 Claude 桌面版后在侧边栏打开' if reg else ('未找到 Claude 桌面版登记目录，只能用 CLI resume' if a.to=='claude' else 'native resume still required')}
    print(json.dumps(result,ensure_ascii=False));return result
def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='command',required=True)
    for name in ('export','transfer','import'):
        q=sub.add_parser(name)
        if name!='import':
            q.add_argument('--from',dest='source',required=True,help='claude:<id/path> 或 codex:<id/path>'); q.add_argument('--source-home')
        if name=='export': q.add_argument('--out',required=True)
        else:
            if name=='import': q.add_argument('bundle')
            q.add_argument('--to',choices=['claude','codex'],required=True); q.add_argument('--cwd',required=True); q.add_argument('--target-home'); q.add_argument('--dry-run',action='store_true'); q.add_argument('--model',help='Target Codex model; detected from target config/history when omitted'); q.add_argument('--claude-version',help='Target Claude Code version; detected from target history when omitted')
            q.add_argument('--desktop-registry',help='Claude 桌面版 claude-code-sessions/<org>/<account> 目录；默认自动查找'); q.add_argument('--no-desktop',action='store_true',help='不登记到 Claude 桌面版')
            q.add_argument('--claude-model',help='写入 Claude 历史的模型名；默认沿用桌面版最近会话的模型'); q.add_argument('--new-copy',action='store_true',help='来源已更新时，另存为新会话（旧导入不动）')
            q.add_argument('--claude-context-budget',type=int,default=DEFAULT_BUDGET,help='Claude 恢复上下文的保守估算预算（默认 64000）；完整历史另行保留')
            q.add_argument('--codex-context-budget',type=int,default=DEFAULT_BUDGET,help='Codex 恢复上下文的保守估算预算（默认 64000）')
    a=p.parse_args()
    if a.command=='import': b=json.loads(Path(a.bundle).read_text(encoding='utf-8-sig'))
    else:
        agent,session=a.source.split(':',1)
        if agent not in ('claude','codex'): raise ValueError('来源必须是 claude 或 codex')
        b=export(agent,session,a.source_home or Path.home()/('.claude' if agent=='claude' else '.codex'),full_tools=True)
    if a.command=='export': validate(b); dump(a.out,b); print(a.out)
    else: import_bundle(b,a)
if __name__=='__main__':
    try: main()
    except (ValueError,KeyError,sqlite3.Error) as e: sys.exit(str(e))
