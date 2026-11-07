"""agent-exchange/v2 canonical events and an explicit v1 writer adapter."""
import copy, hashlib, html, json, platform, re, uuid
from pathlib import Path, PurePosixPath
from project_io import digest as file_digest

SCHEMA='agent-exchange/v2'
NS=uuid.UUID('6f1c2a9e-4b7d-4c1e-9a3f-c1a0dec0de01')
INPUT_KINDS={'user_message','delegated_input'}
KINDS=INPUT_KINDS|{'assistant_message','tool_call','tool_result','reasoning','compaction','notice','ext'}
REASONS={'unsupported_by_target','encrypted','harness_injected','sensitive','missing_file'}
ACTIONS={'dropped','textified','summarized','kept_raw_only'}
CLAUDE_HARNESS_ATTACHMENTS={'environment','model','deferred_tools','deferred_tools_delta','deferred_tools_record',
    'agent_listing_delta','mcp_instructions_delta','skill_listing','auto_mode','auto_mode_exit','total_tokens_reminder',
    'session_context','date','credential_org','remote_session_change','prompt_snapshot','silent_turn_reminder',
    'queued_command','command_permissions','edited_text_file','invoked_skills','hook_additional_context','instructions',
    'nested_memory','thinking_drop'}


CLAUDE_REMINDER = re.compile(r'<system-reminder>.*?</system-reminder>', re.DOTALL)
CLAUDE_CROSS_SESSION = re.compile(r'<cross-session-message\b([^>]*)>(.*?)</cross-session-message>', re.DOTALL)
CLAUDE_LAUNCH = re.compile(
    r'Background \(from the session that started this one\):\s*(.*?)\n[ \t]*Task:[ \t]*\n?(.*)', re.DOTALL)


def claude_user_projection(content):
    text = content if isinstance(content, str) else '\n'.join(
        block.get('text', '') for block in content or [] if block.get('type') == 'text')
    text, removed = CLAUDE_REMINDER.subn('', text)
    cross = CLAUDE_CROSS_SESSION.fullmatch(text.strip())
    if cross:
        name = re.search(r"""(?:^|\s)from-name=(["'])(.*?)\1""", cross[1], re.DOTALL)
        return cross[2].strip(), {'source_session_name': html.unescape(name[2]) if name else '未命名会话'}, removed
    launch = CLAUDE_LAUNCH.fullmatch(text.strip())
    if launch:
        return launch[2].strip(), {'source_session_name': '启动会话', 'delegated_background': launch[1].strip()}, removed
    return text.strip() if removed else text, {}, removed


def digest(data): return hashlib.sha256(data).hexdigest()


def loss_summary(losses):
    result={}
    for item in losses:
        if item.get('resolved_by'): continue
        key=item['kind']+':'+item['reason']+':'+item['action']
        result[key]=result.get(key,0)+1
    return result


def raw_refs(path,rows):
    from rollout_io import source_bytes
    lines=[(n,line) for n,line in enumerate(source_bytes(path).splitlines(),1) if line.strip()]
    if len(lines)!=len(rows) or any(json.loads(line.decode('utf-8-sig'))!=row for (_,line),row in zip(lines,rows)):
        raise ValueError('Source changed during export; retry from a stable snapshot')
    return [{'file':Path(path).name,'line':n,'sha256':digest(line)} for n,line in lines]


def audit_source(agent,rows,refs):
    """Account for every intentionally omitted/degraded source category, without copying credentials."""
    events=[];losses=[]
    receipt_copies=set()
    if agent=='codex':
        from agent_rehome import codex_delegations
        _,receipt_copies=codex_delegations(rows)
    def add(n,kind,reason,action,event_kind='ext',data=None,branch='main',block=None):
        ref=dict(refs[n]);ref.update({'block':block} if block is not None else {})
        identity=str(uuid.uuid5(NS,json.dumps([ref,kind,branch],sort_keys=True)))
        event={'id':identity,'kind':event_kind,'ts':rows[n].get('timestamp'),'turn_id':None,'branch':branch,
            'raw_ref':ref,'data':data or {'source_kind':kind}}
        if event_kind=='ext':event.update(agent=agent,type=kind)
        if event_kind=='reasoning':event['visibility']='encrypted' if reason=='encrypted' else 'omitted'
        if event_kind=='compaction':event.update(origin='native',summary_visible=False,covers_until=None)
        events.append(event)
        losses.append({'event':identity,'raw_ref':ref,'kind':kind,'reason':reason,'action':action,'stage':'source-or-target-projection'})
    tool_results={block.get('tool_use_id') for row in rows if row.get('type')=='user' and not row.get('isSidechain') and not row.get('isMeta') for block in ((row.get('message') or {}).get('content') or []) if isinstance(block,dict) and block.get('type')=='tool_result'}
    codex_results={(row.get('payload') or {}).get('call_id') for row in rows if (row.get('payload') or {}).get('type') in ('function_call_output','custom_tool_call_output','web_search_end')}
    for n,row in enumerate(rows):
        if agent=='claude':
            for flag,reason in [('isMeta','harness_injected'),('isSidechain','unsupported_by_target'),('isCompactSummary','harness_injected')]:
                if row.get(flag):
                    data={'source_kind':row.get('type'),'flag':flag}
                    # Preserve side-branch text in a source extension; never activate it.
                    if flag=='isSidechain':data['content']=copy.deepcopy((row.get('message') or {}).get('content'))
                    add(n,flag,reason,'dropped',data=data,branch=str(row.get('agentId') or 'sidechain') if flag=='isSidechain' else 'main')
            typ=row.get('type','unknown')
            if typ in ('file-history-snapshot','file-history','queue-operation'):
                add(n,typ,'unsupported_by_target','dropped')
            elif typ=='attachment':
                attachment_type=(row.get('attachment') or {}).get('type','unknown')
                if attachment_type in ('file','compact_file_reference'):add(n,'file_attachment','unsupported_by_target','dropped',data={'source_kind':'attachment','attachment_type':attachment_type})
                elif attachment_type in CLAUDE_HARNESS_ATTACHMENTS:add(n,'attachment_'+attachment_type,'harness_injected','dropped',event_kind='notice')
                else:add(n,'attachment_'+str(attachment_type),'unsupported_by_target','dropped')
            elif typ=='system' and row.get('subtype')=='compact_boundary':
                add(n,'native_compaction','unsupported_by_target','dropped',event_kind='compaction')
            elif typ in ('system','progress','summary'):
                add(n,typ,'unsupported_by_target','kept_raw_only')
            elif typ not in ('user','assistant','custom-title'):
                add(n,typ,'unsupported_by_target','dropped')
            content=(row.get('message') or {}).get('content')
            if typ=='user' and not any(row.get(flag) for flag in ('isMeta','isSidechain','isCompactSummary')):
                _,_,removed=claude_user_projection(content)
                for index in range(removed):
                    add(n,'user_system_reminder','harness_injected','dropped',block=index)
            if isinstance(content,str) and content.lstrip().startswith('<task-notification>'):
                add(n,'task_notification','harness_injected','textified',event_kind='notice')
            for j,block in enumerate(content if isinstance(content,list) else []):
                typ=block.get('type','unknown')
                if typ in ('thinking','redacted_thinking'):
                    add(n,typ,'encrypted' if typ=='redacted_thinking' else 'unsupported_by_target','dropped',event_kind='reasoning',block=j)
                elif typ=='tool_use' and block.get('name','').startswith('mcp__ccd_turn__'):
                    wrap=block['name']=='mcp__ccd_turn__wrap_up'
                    add(n,block['name'],'unsupported_by_target','textified' if wrap else 'dropped',
                        event_kind='notice',data={'source_kind':block['name'],'args':block.get('input',{})} if wrap else None,block=j)
                elif typ=='tool_use' and block.get('id') not in tool_results:
                    add(n,'missing_tool_result','missing_file','textified',block=j)
                elif typ in ('image','attachment','document','file'):
                    add(n,'image_attachment' if typ=='image' else 'file_attachment','unsupported_by_target','kept_raw_only' if typ=='image' else 'dropped',block=j)
                elif typ not in ('text','tool_use','tool_result'):
                    add(n,'content_'+typ,'unsupported_by_target','dropped',block=j)
        else:
            payload=row.get('payload') or {};typ=row.get('type')
            if typ=='compacted':
                encrypted='encrypted_content' in json.dumps(payload)
                add(n,'compacted','encrypted' if encrypted else 'unsupported_by_target','dropped',event_kind='compaction')
            elif typ=='turn_context':
                add(n,'turn_context','unsupported_by_target','kept_raw_only',data={k:payload[k] for k in ('model','effort') if k in payload})
            elif typ=='response_item':
                if payload.get('type') in ('reasoning','encrypted_reasoning'):
                    add(n,'provider_reasoning','encrypted' if payload.get('encrypted_content') else 'unsupported_by_target','dropped',event_kind='reasoning')
                elif payload.get('role') in ('user','developer','system'):
                    add(n,'provider_context','harness_injected','dropped')
                elif payload.get('type') not in ('message','function_call','function_call_output','custom_tool_call','custom_tool_call_output','web_search_call'):
                    add(n,'provider_'+str(payload.get('type','unknown')),'unsupported_by_target','dropped')
                if payload.get('type') in ('function_call','custom_tool_call','web_search_call'):
                    call=payload.get('call_id') or payload.get('id')
                    matched=bool(call and call in codex_results)
                    if not matched:add(n,'missing_tool_result','missing_file','textified')
            elif typ=='event_msg' and payload.get('type')=='item_completed':
                item=payload.get('item') or {};kind=item.get('type')
                if kind in ('Reasoning','ContextCompaction'):
                    add(n,kind,'unsupported_by_target','dropped',event_kind='reasoning' if kind=='Reasoning' else 'compaction')
                elif kind=='UserMessage':
                    from agent_rehome import codex_user_text,content
                    original=content(item.get('content'))
                    if codex_user_text(original)!=original:
                        add(n,'user_message_normalization','harness_injected','textified')
                    for j,block in enumerate(item.get('content',[])):
                        if block.get('type')=='local_image':add(n,'image_attachment','unsupported_by_target','kept_raw_only',block=j)
                        elif block.get('type') not in ('text','Text'):add(n,'user_content_'+block.get('type','unknown'),'unsupported_by_target','dropped',block=j)
                elif n not in receipt_copies and kind not in ('AgentMessage','CommandExecution','McpToolCall'):
                    add(n,str(kind),'unsupported_by_target','textified')
            elif typ=='event_msg':
                kind=payload.get('type','unknown')
                if kind in ('agent_reasoning','agent_reasoning_raw_content','agent_reasoning_delta'):
                    add(n,kind,'unsupported_by_target','dropped',event_kind='reasoning')
                elif kind=='user_message' and (payload.get('images') or payload.get('local_images')):
                    add(n,'image_attachment','unsupported_by_target','kept_raw_only')
                elif kind not in ('user_message','agent_message','task_started','task_complete','turn_aborted','token_count','patch_apply_begin','patch_apply_end','web_search_begin','web_search_end','exec_command_begin','exec_command_end','exec_command_output_delta','agent_message_delta','agent_reasoning_delta','agent_reasoning_section_break'):
                    add(n,'event_'+str(kind),'unsupported_by_target','kept_raw_only')
            elif typ!='session_meta':add(n,'record_'+str(typ),'unsupported_by_target','kept_raw_only')
    return events,losses


def upgrade_v1(bundle):
    if bundle.get('schema')==SCHEMA: validate(bundle);return copy.deepcopy(bundle)
    if bundle.get('schema')!='agent-transcript/v1': raise ValueError('Unsupported transcript schema')
    sid=bundle['source']['session_id'];uuid.UUID(sid)
    result={'schema':SCHEMA,'type':'session','source':copy.deepcopy(bundle['source']),
        'title':bundle['title'],'project':copy.deepcopy(bundle.get('project',{})),
        'session':{'id':sid,'branches':[{'id':'main','forked_from':None}],'forked_from':bundle.get('source',{}).get('forked_from'),
            'subagent_of':bundle.get('source',{}).get('subagent_of')},
        'events':[],'losses':copy.deepcopy(bundle.get('losses',[]))}
    for n,turn in enumerate(bundle['turns']):
        turn_id=str(uuid.uuid5(NS,sid+f'/turn/{n}'))
        def emit(kind,data,at,ref=None,identity=None):
            identity=identity or str(uuid.uuid5(NS,sid+f'/event/{len(result["events"])}'))
            result['events'].append({'id':identity,'parent_id':result['events'][-1]['id'] if result['events'] else None,
                'seq':len(result['events']),'ts':at,'turn_id':turn_id,'branch':'main','kind':kind,
                'raw_ref':copy.deepcopy(ref) if ref else None,**data})
        user=turn['user']
        data={'text':user['text'],'attachments':copy.deepcopy(user.get('attachments',[]))}
        data.update({key:user[key] for key in ('source_thread_id','source_session_name','delegated_background') if key in user})
        emit('delegated_input' if {'source_thread_id','source_session_name'} & data.keys() else 'user_message',
             data,user['ts'],user.get('_raw_ref'))
        for j,item in enumerate(turn['items']):
            ref=item.get('_raw_ref');at=item['ts']
            if item['kind']=='message':emit('assistant_message',{'text':item['text'],'phase':item.get('phase')},at,ref)
            elif item['kind']=='tool':
                call=str(uuid.uuid5(NS,turn_id+f'/call/{j}'))
                emit('tool_call',{'call_id':call,'name':item['name'],'raw_name':item['name'],'args':copy.deepcopy(item.get('args',{})),
                    'input_text':item.get('input',''),'description':item.get('description','')},at,ref)
                emit('tool_result',{'call_id':call,'output':item.get('output',''),'is_error':bool(item.get('is_error')),
                    'status':item.get('status') or ('failed' if item.get('is_error') else 'unknown'),'exit_code':item.get('exit_code'),
                    'completion_time_known':bool(item.get('completed_ts'))},item.get('completed_ts') or at,ref)
            else:
                identity=item.get('id') or f'turn/{n}/items/{j}'
                emit(item['kind'],{'data':copy.deepcopy(item)},at,ref,identity)
    for item in bundle.get('_nonconversation_events',[]):
        event=copy.deepcopy(item);event['seq']=len(result['events']);event['parent_id']=None
        result['events'].append(event)
        branch=event.get('branch','main')
        if branch!='main' and not any(x['id']==branch for x in result['session']['branches']):result['session']['branches'].append({'id':branch,'forked_from':None})
    result['losses_summary']=loss_summary(result['losses']);validate(result);return result


def covered(event,losses):
    return any(loss.get('event')==event['id'] or (event.get('raw_ref') is not None and loss.get('raw_ref')==event['raw_ref']) for loss in losses)


def validate(bundle):
    if bundle.get('schema')!=SCHEMA or bundle.get('type')!='session': raise ValueError('Expected v2 session')
    if bundle['source']['agent'] not in ('claude','codex'): raise ValueError('Agent adapter is not implemented')
    uuid.UUID(bundle['source']['session_id']);seen=set();calls={};results=set()
    branches={x['id'] for x in bundle['session']['branches']}
    if 'main' not in branches:raise ValueError('Missing main branch')
    losses=bundle.get('losses')
    if not isinstance(losses,list): raise ValueError('v2 requires an explicit losses list')
    for loss in losses:
        if loss.get('reason') not in REASONS or loss.get('action') not in ACTIONS or not loss.get('kind'): raise ValueError('Invalid loss record')
        if not loss.get('event') and not loss.get('raw_ref'): raise ValueError('Loss record needs event/raw_ref')
    for n,event in enumerate(bundle.get('events',[])):
        if event.get('seq')!=n or event.get('id') in seen or not event.get('id'): raise ValueError('Invalid event order/identity')
        if event.get('parent_id') is not None and event['parent_id'] not in seen: raise ValueError('Unresolved event parent')
        seen.add(event['id']);kind=event.get('kind')
        if event.get('branch') not in branches:raise ValueError('Undeclared event branch')
        # A shared raw_ref is not enough for an unknown kind: another kind's loss on that line must not cover it.
        if kind not in KINDS and not any(loss.get('event')==event['id'] or (event.get('raw_ref') is not None and loss.get('raw_ref')==event['raw_ref'] and loss.get('kind')==kind) for loss in losses):
            raise ValueError('Unknown event kind without matching loss record')
        if (kind in ('reasoning','compaction','notice','ext') or event.get('branch','main')!='main') and not covered(event,losses):
            raise ValueError('Projected extension/branch requires a matching loss record')
        if kind in INPUT_KINDS|{'assistant_message'} and not isinstance(event.get('text'),str): raise ValueError('Message text must be a string')
        if kind=='delegated_input':
            if 'source_thread_id' in event:
                uuid.UUID(event['source_thread_id'])
            elif not isinstance(event.get('source_session_name'),str) or not event['source_session_name']:
                raise ValueError('Delegated input requires source attribution')
            if 'delegated_background' in event and not isinstance(event['delegated_background'],str):
                raise ValueError('Invalid delegated background')
        if kind=='tool_call':
            if not event.get('call_id') or event['call_id'] in calls: raise ValueError('Missing/duplicate call ID')
            if not isinstance(event.get('name'),str) or not isinstance(event.get('args',{}),dict):raise ValueError('Invalid tool call payload')
            calls[event['call_id']]=event
        if kind=='tool_result':
            call=event.get('call_id')
            if call not in calls or calls[call].get('branch')!=event['branch'] or call in results:raise ValueError('Unpaired/duplicate tool result')
            if not isinstance(event.get('output',''),str) or (event.get('exit_code') is not None and type(event['exit_code']) is not int):raise ValueError('Invalid tool result payload')
            results.add(call)
        ref=event.get('raw_ref')
        if ref is not None and (not isinstance(ref.get('line'),int) or ref['line']<1 or not isinstance(ref.get('sha256'),str) or len(ref['sha256'])!=64):raise ValueError('Invalid raw_ref')
    if any(call not in results and not covered(event,losses) for call,event in calls.items()):raise ValueError('Missing result requires a matching loss record')
    if bundle.get('losses_summary')!=loss_summary(losses):raise ValueError('Loss summary mismatch')


def to_v1(bundle):
    if bundle.get('schema')=='agent-transcript/v1': return copy.deepcopy(bundle)
    validate(bundle);turns=[];calls={};extras=[]
    for event in bundle['events']:
        kind=event['kind'];ref=event.get('raw_ref')
        if event.get('branch','main')!='main' or kind not in INPUT_KINDS|{'assistant_message','tool_call','tool_result'}:
            extras.append(copy.deepcopy(event));continue
        if kind in INPUT_KINDS:
            user={'ts':event['ts'],'text':event['text'],'attachments':copy.deepcopy(event.get('attachments',[])),'_raw_ref':ref}
            if kind=='delegated_input':
                user.update({key:event[key] for key in ('source_thread_id','source_session_name','delegated_background') if key in event})
            turns.append({'user':user,'items':[]})
        elif kind=='assistant_message':
            if not turns: raise ValueError('Assistant event without a user turn')
            turns[-1]['items'].append({'kind':'message','ts':event['ts'],'text':event['text'],'phase':event.get('phase'),'_raw_ref':ref})
        elif kind=='tool_call':
            if not turns: raise ValueError('Tool event without a user turn')
            item={'kind':'tool','ts':event['ts'],'name':event['name'],'args':copy.deepcopy(event.get('args',{})),
                'input':event.get('input_text',''),'description':event.get('description',''),'output':'','is_error':False,'_raw_ref':ref}
            calls[event['call_id']]=item;turns[-1]['items'].append(item)
        else:
            item=calls[event['call_id']];item.update(output=event.get('output',''),is_error=bool(event.get('is_error')),
                completed_ts=event['ts'] if event.get('completion_time_known',True) else None,status=event.get('status'),exit_code=event.get('exit_code'))
    return {'schema':'agent-transcript/v1','source':copy.deepcopy(bundle['source']),'title':bundle['title'],
        'project':copy.deepcopy(bundle.get('project',{})),'turns':turns,'losses':copy.deepcopy(bundle['losses']),
        'losses_summary':loss_summary(bundle['losses']),'_nonconversation_events':extras}


def safe(root,relative):
    p=PurePosixPath(relative)
    if not p.parts or p.is_absolute() or '..' in p.parts or ':' in relative or '\\' in relative: raise ValueError('Unsafe exchange reference')
    result=Path(root).joinpath(*p.parts).resolve()
    if not result.is_relative_to(Path(root).resolve()):raise ValueError('Exchange reference escapes package')
    return result


def write_project(root,legacy,native=None):
    """Persist canonical event/loss streams; no inline session or attachment payloads."""
    root=Path(root);refs=[];all_losses=[]
    legacy={**legacy,'attachments':copy.deepcopy(legacy['attachments'])}
    for b in legacy['conversations']:
        for turn in b['turns']:
            for attachment in turn['user'].get('attachments',[]):
                for asset in legacy['attachments']:
                    if asset['sha256']==attachment['sha256']:
                        asset.update({k:attachment[k] for k in ('image','mime') if k in attachment})
    for b in legacy['conversations']:
        canonical=upgrade_v1(b);sid=canonical['session']['id'];base=f'sessions/{sid}'
        for event in canonical['events']:
            if event['kind'] in INPUT_KINDS:
                event['attachments']=[{'ref':a['sha256'],**{k:a[k] for k in ('name','original','mode','image','mime') if k in a}} for a in event.get('attachments',[])]
        # Keeping attachment bytes is distinct from reproducing its native UI block.
        # Do not clear every loss on a line merely because one attachment recovered.
        canonical['losses_summary']=loss_summary(canonical['losses'])
        events_path=safe(root,base+'/events.jsonl')
        losses_path=safe(root,base+'/losses.json')
        events_path.parent.mkdir(parents=True,exist_ok=True)
        with events_path.open('w',encoding='utf-8',newline='\n') as stream:
            for event in canonical['events']:
                json.dump(event,stream,ensure_ascii=False,separators=(',',':'))
                stream.write('\n')
        with losses_path.open('w',encoding='utf-8',newline='\n') as stream:
            json.dump(canonical['losses'],stream,ensure_ascii=False,indent=2)
        meta={k:v for k,v in canonical.items() if k not in ('events','losses','schema','type')}
        refs.append({'id':sid,'metadata':meta,'events':{'path':base+'/events.jsonl','sha256':file_digest(events_path)},
            'losses':{'path':base+'/losses.json','sha256':file_digest(losses_path)},'branches':[{'id':x['id'],'events_ref':base+'/events.jsonl'} for x in canonical['session']['branches']],
            **({'native':native[sid]} if native and sid in native else {})})
        all_losses.extend(canonical['losses'])
    for n,skip in enumerate(legacy.get('skipped',[])):
        all_losses.append({'event':f'project-skipped/{n}','kind':'project_attachment' if 'attachment' in skip else 'project_session','reason':'sensitive' if 'credential' in skip.get('reason','') else 'missing_file','action':'dropped'})
    manifest={'schema':SCHEMA,'type':'project','source':{'agent':legacy['source_agent'],'os':platform.system()},
        'created_at':legacy['created_at'],'project':{'name':Path(legacy['source_project']).name,'root_hint':legacy['source_project'],'files':legacy['files']},
        'attachments':legacy['attachments'],'sessions':refs,'losses_summary':loss_summary(all_losses),
        'project_losses':all_losses[-len(legacy.get('skipped',[])):] if legacy.get('skipped') else [],'skipped':legacy.get('skipped',[]),'exclusions':legacy.get('exclusions',[])}
    if legacy.get('surroundings'):manifest['surroundings']=legacy['surroundings']
    if 'file_references' in legacy:manifest['file_references']=legacy['file_references']
    with (root/'manifest.json').open('w',encoding='utf-8',newline='\n') as stream:
        json.dump(manifest,stream,ensure_ascii=False,indent=2)
    return manifest


def read_project(root):
    root=Path(root);m=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    if m.get('schema')=='agent-project/v1':
        m.setdefault('losses_summary',loss_summary([loss for b in m['conversations'] for loss in b.get('losses',[])]))
        return m
    if m.get('schema')!=SCHEMA or m.get('type')!='project':raise ValueError('Unsupported project package')
    assets={a['sha256']:a for a in m['attachments']};bundles=[];losses=[];native={};ids=set()
    for entry in m['sessions']:
        if entry['id'] in ids:raise ValueError('Duplicate project session reference')
        ids.add(entry['id']);parts={}
        for name in ('events','losses'):
            path=safe(root,entry[name]['path'])
            if file_digest(path)!=entry[name]['sha256']:raise ValueError('Exchange stream hash mismatch')
            with path.open(encoding='utf-8',newline='\n') as stream:
                parts[name]=[json.loads(line) for line in stream if line.strip()] if name=='events' else json.load(stream)
        b={'schema':SCHEMA,'type':'session',**copy.deepcopy(entry['metadata']),**parts}
        if b['session']['id']!=entry['id'] or b['source']['session_id']!=entry['id']:raise ValueError('Session reference identity mismatch')
        if b['source']['agent']!=m['source']['agent']:raise ValueError('Project source agent mismatch')
        expected=[{'id':x['id'],'events_ref':entry['events']['path']} for x in b['session']['branches']]
        if entry['branches']!=expected:raise ValueError('Branch reference mismatch')
        for event in b['events']:
            if event['kind'] in INPUT_KINDS:
                try:event['attachments']=[{**copy.deepcopy(assets[x['ref']]),**{k:x[k] for k in ('name','original','mode','image','mime') if k in x}} for x in event.get('attachments',[])]
                except KeyError:raise ValueError('Unresolved attachment reference')
        validate(b);bundles.append(to_v1(b));losses.extend(b['losses'])
        if entry.get('native'):native[entry['id']]=entry['native']
    losses.extend(m.get('project_losses',[]))
    if loss_summary(losses)!=m['losses_summary']:raise ValueError('Project loss summary mismatch')
    return {'schema':'agent-project/v1','source_agent':m['source']['agent'],'source_project':m['project']['root_hint'],
        'files':m['project']['files'],'attachments':m['attachments'],'conversations':bundles,'skipped':m.get('skipped',[]),
        'losses_summary':m['losses_summary'],'native_sessions':native,'surroundings':m.get('surroundings',{}),
        **({'file_references':m['file_references']} if 'file_references' in m else {})}
