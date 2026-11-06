"""Codex native relocation. Never serialize conversation bodies or restore active permissions."""
import datetime as dt
import json, os, sqlite3, time, uuid
from pathlib import Path
from contextlib import closing
import claude_native as c
from platform_paths import sqlite_read_uri, storage_path
from rollout_io import source_bytes
import codex_backend as backend
from cli_output import print

SCHEMA='codex-native/v1'
NS=uuid.UUID('6f1c2a9e-4b7d-4c1e-9a3f-c1a0dec0de01')
LOCK_WAIT_SECONDS=2.0


def members(text,start=0):
    """Object member value spans; reject duplicate keys instead of rewriting ambiguously."""
    decoder=json.JSONDecoder();pos=start+1;result={}
    while True:
        while text[pos].isspace() or text[pos]==',':pos+=1
        if text[pos]=='}':return result
        key,end=decoder.raw_decode(text,pos);pos=end
        if key in result:raise ValueError('Duplicate native metadata key')
        while text[pos].isspace():pos+=1
        if text[pos]!=':':raise ValueError('Invalid native metadata')
        pos+=1
        while text[pos].isspace():pos+=1
        value,end=decoder.raw_decode(text,pos);result[key]=(pos,end,value);pos=end


def metadata(data):
    rows=[json.loads(line) for line in data.decode('utf-8-sig').split('\n') if line.strip()]
    metas=[row['payload'] for row in rows if row.get('type')=='session_meta']
    if len(metas)!=1:raise ValueError('Native rollout must contain exactly one session_meta')
    meta=metas[0]
    if not isinstance(meta,dict):raise ValueError('Invalid native session metadata')
    uuid.UUID(meta['id'])
    # Paginated parents require ordinal/byte-offset preservation across multiple files.
    # Refuse before packaging/writing rather than silently dropping the inherited prefix.
    if any(meta.get(key) is not None for key in ('history_base','forked_from_ordinal_exclusive')):
        raise ValueError('Unsupported paginated lineage; export with ReHome including required ancestors')
    return meta,rows


def rollout_stamp(meta,rows):
    timestamp=meta.get('timestamp') or rows[0].get('timestamp')
    if not isinstance(timestamp,str) or not timestamp:raise ValueError('Native rollout timestamp is required')
    try:stamp=dt.datetime.fromisoformat(timestamp.replace('Z','+00:00'))
    except ValueError as error:raise ValueError('Invalid native rollout timestamp') from error
    if stamp.tzinfo is None:raise ValueError('Native rollout timestamp requires timezone')
    return stamp


def rewrite(data,source,cwd,sid):
    meta,_=metadata(data)
    if meta['id']!=source['session_id']:raise ValueError('Native identity mismatch')
    root,aliases=c.source_roots(source);roots=sorted(set([root,*aliases]),key=len,reverse=True)
    bom=b'\xef\xbb\xbf' if data.startswith(b'\xef\xbb\xbf') else b'';output=[]
    for line in data[len(bom):].decode('utf-8').split('\n'):
        if not line.strip():output.append(line);continue
        start=line.index('{');outer=members(line,start);kind=outer.get('type',(0,0,None))[2]
        spans=[]
        payload=outer.get('payload',(0,0,{}))[2]
        owned_event=kind=='event_msg' and isinstance(payload,dict) and payload.get('thread_id')==source['session_id']
        settings=owned_event and payload.get('type')=='thread_settings_applied'
        if (kind in ('session_meta','turn_context') or owned_event) and 'payload' in outer:
            fields=members(line,outer['payload'][0])
            for key,(a,b,value) in fields.items():
                mapped=value
                if key=='cwd' and (kind in ('session_meta','turn_context') or settings):
                    if not isinstance(value,str):raise ValueError('Native cwd must be a string')
                    mapped=next((m for old in roots if (m:=c.relocate_cwd(value,old,cwd)) is not None),value)
                elif (key in ('id','session_id') and kind=='session_meta') or (key=='thread_id' and owned_event):
                    if value==source['session_id']:mapped=sid
                elif key in ('runtime_workspace_roots','runtimeWorkspaceRoots','workspace_roots','workspaceRoots') and (kind in ('session_meta','turn_context') or settings):
                    if not isinstance(value,list) or any(not isinstance(v,str) for v in value):raise ValueError('Invalid native workspace roots')
                    mapped=list(dict.fromkeys(m for v in value for old in roots if (m:=c.relocate_cwd(v,old,cwd)) is not None))
                if mapped!=value:spans.append((a,b,json.dumps(mapped,ensure_ascii=False)))
            # Only metadata values change; arbitrary whitespace, CRLF and body encodings survive.
        for a,b,value in reversed(spans):line=line[:a]+value+line[b:]
        output.append(line)
    return bom+'\n'.join(output).encode('utf-8')


def snapshot(source,home,*unused):
    source=Path(source);home=Path(home)
    if source.is_symlink():raise ValueError('Native rollout symlink refused')
    data=source_bytes(source);c.check_payload(data,source.name,jsonl=True)
    meta,rows=metadata(data);sid=meta['id'];record={}
    rollout_stamp(meta,rows)
    if not isinstance(meta.get('cwd'),str) or not meta['cwd']:raise ValueError('Native source cwd is required')
    database=home/'state_5.sqlite'
    if database.exists():
        with closing(sqlite3.connect(sqlite_read_uri(database),uri=True)) as db:
            db.row_factory=sqlite3.Row
            row=db.execute('select * from threads where id=?',(sid,)).fetchone()
            if row:record=dict(row)
    if any(record.get(key) is not None for key in ('history_base','forked_from_ordinal_exclusive')):
        raise ValueError('Unsupported paginated lineage in database')
    # Only portable descriptive columns are exported; no runtime permissions or configuration.
    allowed=('title','model','model_provider','reasoning_effort','created_at','updated_at','created_at_ms','updated_at_ms',
             'first_user_message','preview','cli_version','tokens_used','history_mode','archived','has_user_event')
    record={key:record[key] for key in allowed if key in record}
    first_user=''
    for row in rows:
        if row.get('type')!='event_msg':continue
        payload=row.get('payload',{});item=payload.get('item',{})
        if payload.get('type')=='item_completed' and item.get('type')=='UserMessage':
            first_user='\n'.join(block.get('text','') for block in item.get('content',[]) if block.get('type')=='text').strip()
        elif payload.get('type')=='user_message':first_user=str(payload.get('message') or '').strip()
        if first_user:break
    return {'schema':SCHEMA,'source':{'agent':'codex','session_id':sid,'cwd':meta.get('cwd',''),'version':meta.get('cli_version')},
        'title':backend.indexed_title(home,sid) or record.get('title') or first_user[:60] or sid,'thread':record,'turns':sum(row.get('type')=='event_msg' and
            (row.get('payload',{}).get('type')=='user_message' or row.get('payload',{}).get('item',{}).get('type')=='UserMessage') for row in rows),
        'files':[{'path':'raw/rollout.jsonl','sha256':c.sha(data),'data':data}],
        'limitations':['Paginated lineage is refused; legacy fork provenance is retained.',
            'Generated images and other external file references are not collected; historical body paths remain unchanged.']}


def pack(snap,directory):
    directory=Path(directory)
    if directory.exists():raise ValueError('Native package directory must be new')
    directory.mkdir(parents=True);item=snap['files'][0];path=c.safe(directory,item['path']);path.parent.mkdir();path.write_bytes(item['data'])
    manifest={key:value for key,value in snap.items() if key!='files'}
    manifest['files']=[{key:value for key,value in item.items() if key!='data'}]
    (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')


def load(directory):
    directory=Path(directory);snap=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if snap.get('schema')!=SCHEMA or snap['source']['agent']!='codex':raise ValueError('Unsupported native Codex package')
    if len(snap['files'])!=1 or snap['files'][0]['path']!='raw/rollout.jsonl':raise ValueError('Unexpected native payload inventory')
    item=snap['files'][0];data=c.safe(directory,item['path']).read_bytes()
    if c.sha(data)!=item['sha256']:raise ValueError('Native package hash mismatch')
    c.check_payload(data,'rollout.jsonl',jsonl=True);meta,_=metadata(data)
    if meta['id']!=snap['source']['session_id']:raise ValueError('Native identity mismatch')
    c.source_roots(snap['source']);item['data']=data;return snap


def plan(snap,a):
    if a.to!='codex':raise ValueError('Native Codex packages require a Codex target')
    home=Path(a.target_home or Path.home()/'.codex').resolve();cwd=str(Path(a.cwd).resolve())
    if not Path(cwd).is_dir() and not getattr(a,'allow_new_project',False):raise ValueError('Target project must exist')
    data=snap['files'][0]['data'];meta,rows=metadata(data)
    if c.sha(data)!=snap['files'][0]['sha256']:raise ValueError('Native payload changed')
    old=snap['source']['session_id'];uuid.UUID(old)
    if not snap['source'].get('cwd'):raise ValueError('Native source cwd is required')
    sid=str(uuid.uuid5(NS,'native-copy/'+old+'/'+cwd+'/'+c.sha(data))) if getattr(a,'new_copy',False) else old
    stamp=rollout_stamp(meta,rows)
    relative=stamp.strftime('sessions/%Y/%m/%d/rollout-%Y-%m-%dT%H-%M-%S-')+sid+'.jsonl'
    path=c.safe(home,relative)
    for folder in ('sessions','archived_sessions'):
        if any((home/folder).rglob('*'+sid+'.jsonl*')):raise ValueError('Native ID conflict; refusing overwrite; use explicit --new-copy')
    database=home/'state_5.sqlite'
    if not database.is_file():raise ValueError('Initialize target Codex database first')
    with closing(sqlite3.connect(sqlite_read_uri(database),uri=True,timeout=LOCK_WAIT_SECONDS)) as db:
        if db.execute('select 1 from threads where id=?',(sid,)).fetchone():raise ValueError('Native ID conflict; refusing overwrite; use explicit --new-copy')
    index=home/'session_index.jsonl'
    if index.is_symlink() or database.is_symlink():raise ValueError('Native target database/index symlink refused')
    if index.exists() and any(json.loads(line).get('id')==sid for line in index.read_text(encoding='utf-8').splitlines() if line.strip()):
        raise ValueError('Native ID conflict in session index')
    output=rewrite(data,snap['source'],cwd,sid)
    return home,cwd,[(path,output)],None


def _file_id(stat):return stat.st_dev,stat.st_ino


def _verify_append(index,original,block,receipt):
    current=index.read_bytes()
    if _file_id(index.stat())!=receipt['file_id'] or not current.startswith(original or b'') or current.count(block)!=1:
        raise ValueError('Session index changed during append; database transaction will roll back')
    # Concurrent foreign appends after our complete block are safe and retained.
    offset=current.index(block)
    if offset<len(original or b''):raise ValueError('Session index append is not after its original prefix')
    return current


def _append_index(index,original,additions,receipt):
    """One O_APPEND write; never replace/truncate existing index bytes on success."""
    if (index.read_bytes() if index.exists() else None)!=original:raise ValueError('Session index changed before append')
    block=(b'\n' if original and not original.endswith(b'\n') else b'')+additions
    flags=os.O_WRONLY|os.O_APPEND|getattr(os,'O_BINARY',0)
    if original is None:flags|=os.O_CREAT|os.O_EXCL
    fd=os.open(index,flags,0o600)
    try:
        stat=os.fstat(fd)
        if stat.st_size!=len(original or b'') or _file_id(index.stat())!=_file_id(stat):raise ValueError('Session index changed before append')
        receipt.update(file_id=_file_id(stat),block=block,attempted=True)
        if os.write(fd,block)!=len(block):raise OSError('Incomplete session index append; inspect backup manifest')
        os.fsync(fd)
    finally:os.close(fd)
    return _verify_append(index,original,block,receipt)


def _compensate_index(index,receipt):
    """Remove only an intact unique owned EOF block; never discard a foreign suffix."""
    if not receipt.get('attempted'):return 'not-appended'
    try:
        with index.open('r+b') as stream:
            if _file_id(os.fstat(stream.fileno()))!=receipt['file_id']:return 'manual-review-file-replaced'
            current=stream.read();block=receipt['block']
            if not current.endswith(block) or current.count(block)!=1:return 'manual-review-owned-block-not-at-eof-or-incomplete'
            # Recheck immediately before truncation. No whole-file rewrite/restoration.
            if os.fstat(stream.fileno()).st_size!=len(current):return 'manual-review-concurrent-append'
            stream.seek(-len(block),os.SEEK_END)
            if stream.read()!=block:return 'manual-review-owned-tail-changed'
            stream.truncate(len(current)-len(block));stream.flush();os.fsync(stream.fileno())
        return 'owned-eof-block-removed'
    except OSError:return 'manual-review-compensation-io-error'


def restore_many(pairs):
    """One SQLite transaction for all threads. Compensate only our own index/files on failure."""
    import agent_rehome as r
    plans=[(snap,a,plan(snap,a)) for snap,a in pairs]
    homes={str(item[2][0]) for item in plans}
    if len(homes)!=1:raise ValueError('Native batch must use one target home')
    results=[]
    for snap,a,(home,cwd,writes,_) in plans:
        sid=metadata(writes[0][1])[0]['id']
        results.append({'mode':'codex-native','status':'preview' if a.dry_run else 'written','id':sid,'source_id':snap['source']['session_id'],
            'cwd':cwd,'title':snap['title'],'desktop_registry':None,'context':'unchanged-native-history',
            'losses_summary':{},'limitations':snap.get('limitations',[]),'output_sha256':c.sha(writes[0][1]),'thread_binding_required':[sid],
            'runtime_policy_note':'workspace-write/on-request are import defaults before App loading only; runtime policy follows the target App current user settings. Source permissions are not activated.'})
    if len({result['id'] for result in results})!=len(results):raise ValueError('Duplicate native batch ID')
    if all(a.dry_run for _,a,_ in plans):return results
    if any(a.dry_run for _,a,_ in plans):raise ValueError('Mixed native preview/write batch')
    home=plans[0][2][0];database=home/'state_5.sqlite';index=home/'session_index.jsonl'
    backup=home/'rehome-backups'/('codex-native-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f'));backup.mkdir(parents=True)
    original=index.read_bytes() if index.exists() else None;written=[];receipt={}
    with closing(sqlite3.connect(database,timeout=LOCK_WAIT_SECONDS)) as db:
        if original is not None:(backup/'session_index.jsonl').write_bytes(original)
        journal={'status':'prepared','ids':[x['id'] for x in results],
            'files':[{'path':str(path),'sha256':c.sha(data)} for _,_,(_,_,writes,_) in plans for path,data in writes],
            'index_before_bytes':len(original or b''),'index_before_sha256':c.sha(original or b''),
            'recovery':'Never replace shared DB/index wholesale. Compensate only intact owned EOF append bytes; foreign suffixes require manual review.'}
        r.dump(backup/'manifest.json',journal)
        try:
            deadline=time.monotonic()+LOCK_WAIT_SECONDS
            def backup_progress(status,remaining,total):
                if time.monotonic()>deadline:raise TimeoutError('SQLite backup lock wait timed out')
            with closing(sqlite3.connect(backup/'state_5.sqlite')) as target:db.backup(target,progress=backup_progress,sleep=0.05)
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('SQLite lock wait timed out before transaction')
            db.execute('pragma busy_timeout='+str(max(1,int(remaining*1000))))
            db.execute('begin immediate')
            columns={row[1] for row in db.execute('pragma table_info(threads)')}
            for (snap,a,(_,cwd,writes,_)),result in zip(plans,results):
                sid=result['id'];path,data=writes[0]
                if db.execute('select 1 from threads where id=?',(sid,)).fetchone():raise ValueError('Concurrent native ID conflict')
                # Independent runtime defaults; historical permissions remain historical bytes.
                ms=int(dt.datetime.now().timestamp()*1000);record=dict(snap.get('thread',{}))
                record={key:value for key,value in record.items() if key in ('title','model','model_provider','reasoning_effort','created_at','updated_at','created_at_ms','updated_at_ms','first_user_message','preview','cli_version','tokens_used','history_mode','archived','has_user_event')}
                record.update(id=sid,rollout_path=str(path),cwd=storage_path(cwd),title=snap['title'],name=snap['title'],
                    project_id=backend.ensure_project(db,cwd,Path(cwd).name),source='vscode',thread_source='user',originator='codex_work_desktop',
                    sandbox_policy='{"type":"workspace-write"}',approval_mode='on-request',memory_mode='disabled')
                defaults={'created_at':ms//1000,'updated_at':ms//1000,'created_at_ms':ms,'updated_at_ms':ms,'tokens_used':0,
                    'has_user_event':1,'archived':0,'cli_version':snap['source'].get('version') or '', 'first_user_message':'',
                    'model_provider':'openai','history_mode':'legacy','recency_at':ms//1000,'recency_at_ms':ms}
                for key,value in defaults.items():record.setdefault(key,value)
                record={key:value for key,value in record.items() if key in columns}
                keys=list(record);db.execute('insert into threads ('+','.join(keys)+') values ('+','.join('?' for _ in keys)+')',[record[key] for key in keys])
                path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('xb') as stream:
                    written.append((path,data));stream.write(data)
            additions=b''.join((json.dumps({'id':result['id'],'thread_name':result['title'],'updated_at':r.now()},ensure_ascii=False)+'\n').encode() for result in results)
            journal['status']='files-written';journal['index_append_sha256']=c.sha(additions);journal['index_append_bytes']=len(additions);r.dump(backup/'manifest.json',journal)
            current=_append_index(index,original,additions,receipt)
            journal['status']='index-appended';journal['index_after_sha256']=c.sha(current);r.dump(backup/'manifest.json',journal)
            _verify_append(index,original,receipt['block'],receipt)
            db.commit()
        except BaseException:
            db.rollback()
            compensation=_compensate_index(index,receipt);journal['index_compensation']=compensation
            for path,data in reversed(written):
                if path.exists() and path.read_bytes()==data:path.unlink()
            journal['status']='rolled-back' if not compensation.startswith('manual-review') and not any(path.exists() for path,_ in written) else 'database-rolled-back-files-need-review'
            r.dump(backup/'manifest.json',journal);raise
    journal['status']='committed';r.dump(backup/'manifest.json',journal)
    for result in results:result['backup']=str(backup)
    return results


def restore(snap,a):
    result=restore_many([(snap,a)])[0]
    if not a.dry_run:
        ids=[result['id']]
        if getattr(a,'no_desktop',False):registration={'registered':False,'thread_binding_required':ids,'next':'Use native project tools to register/associate these chats.'}
        else:
            from codex_project_registry import register
            home=Path(a.target_home or Path.home()/'.codex')
            with closing(sqlite3.connect(sqlite_read_uri(home/'state_5.sqlite'),uri=True)) as db:
                pid=db.execute('select project_id from threads where id=?',(ids[0],)).fetchone()[0]
            registration=register(home,result['cwd'],pid,Path(result['cwd']).name,ids)
            registration.setdefault('thread_binding_required',ids)
        result['desktop_project_registry']=registration
        if not registration.get('registered') and not getattr(a,'no_desktop',False):
            from user_next_steps import add_next_steps
            add_next_steps(result,'codex',result['cwd'],[snap['title']])
    print(json.dumps(result,ensure_ascii=False));return result
