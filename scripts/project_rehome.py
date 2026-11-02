"""Project snapshots: files, portable conversations and historical attachment copies."""
import argparse,base64,copy,hashlib,json,mimetypes,os,re,shutil,sqlite3,uuid
from pathlib import Path,PurePosixPath
from platform_paths import path_key,portable_name,portable_suffix,remap_text,sqlite_read_uri,source_rollout
import agent_rehome as r
SKIP_DIRS={'.git','node_modules','.venv','venv','__pycache__','.next','target','dist','AppData','.codex','.claude','.ssh','.cache','__MACOSX','.AppleDouble'}
SKIP_FILES={'.env','.npmrc','.pypirc','credentials.json','auth.json','settings.local.json','.DS_Store'}
LOCAL_ARTIFACT_SUFFIXES={'.exe','.dll','.pdb','.dmg','.zip','.gz','.zst','.rehome','.sqlite','.sqlite3','.db','.wal','.shm','.bin'}
PROFILE_DIRS={'appdata','webview','ebwebview','user data','oneauth','browser','browser-profile'}
def safe(root,rel):
    q=PurePosixPath(rel)
    if q.is_absolute() or '..' in q.parts or not q.parts or ':' in rel or '\\' in rel: raise ValueError('Unsafe package path: '+rel)
    p=root.joinpath(*q.parts).resolve()
    if not p.is_relative_to(root.resolve()): raise ValueError('Path escapes package')
    return p

def files(root):
    for base,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=[d for d in dirs if d.lower() not in {s.lower() for s in SKIP_DIRS}|PROFILE_DIRS and not (Path(base)/d).is_symlink() and not (getattr((Path(base)/d).lstat(),'st_file_attributes',0) & 1024)]
        for name in names:
            p=Path(base)/name
            if name.lower() in {s.lower() for s in SKIP_FILES}|{'cookies','login data','web data','local state'} or name.startswith('.env.') or p.is_symlink(): continue
            if p.suffix.lower() in ('.key','.pem','.p12','.pfx'): continue
            if '.codex-local' in p.relative_to(root).parts and p.suffix.lower() in LOCAL_ARTIFACT_SUFFIXES: continue
            if p.relative_to(root).as_posix()=='.rehome/restore.json': continue
            yield p

def pack(agent,project,out,home,selected_sessions=None):
    project=project.resolve(); out=out.resolve()
    if out.exists() or out.is_relative_to(project): raise ValueError('Package must be new and outside source project')
    out.mkdir(parents=True); entries=[]; assets=[]; skipped=[]
    def add_bytes(data,name,original,mode):
        sha=hashlib.sha256(data).hexdigest(); ext=portable_suffix(name)[:16]; rel=f'attachments/{sha}{ext}'
        dest=safe(out,rel); dest.parent.mkdir(exist_ok=True); dest.write_bytes(data)
        item={'path':rel,'sha256':sha,'bytes':len(data),'original':original,'name':portable_name(name),'mode':mode}
        assets.append(item); return item
    for p in files(project):
        rel='project/'+p.relative_to(project).as_posix(); target=safe(out,rel); target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,target)
        entry={'path':rel,'sha256':r.digest(target),'bytes':target.stat().st_size}
        if os.name!='nt': entry['permissions']=p.stat().st_mode & 0o777
        entries.append(entry)
    if selected_sessions is not None:
        sessions=[Path(x['snapshot']) for x in selected_sessions]
    elif agent=='claude':
        enc=re.sub(r'[^a-zA-Z0-9_-]','-',str(project)); sessions=sorted((home/'projects'/enc).glob('*.jsonl'))
    else:
        sessions=[]
        with sqlite3.connect(sqlite_read_uri(home/"state_5.sqlite"),uri=True) as db:
            for path,cwd in db.execute('select rollout_path,cwd from threads where archived=0'):
                if path_key(cwd)==path_key(project): sessions.append(source_rollout(home,path))
    bundles=[]
    for src in sessions:
        rows=r.read(src)
        if agent=='codex':
            meta=next((x['payload'] for x in rows if x.get('type')=='session_meta'),{})
            if meta.get('cli_version') in ('claude-import','claude-to-codex-proof'): raise ValueError('Refusing imported Claude history as native Codex source')
        try: b=r.export(agent,str(src),home,full_tools=True)
        except ValueError as e: skipped.append({'session':src.name,'reason':str(e)}); continue
        if selected_sessions is not None:
            b['title']=next(x['title'] for x in selected_sessions if Path(x['snapshot'])==src)
        byts={t['user']['ts']:t for t in b['turns']}; current=None; pending=[]
        def attach(a):
            if current is None: pending.append(a)
            else: current['user'].setdefault('attachments',[]).append(a)
        if agent=='claude':
            for row in rows:
                if row.get('isSidechain') or row.get('isMeta'): continue
                ts=row.get('timestamp'); c=row.get('message',{}).get('content')
                if row.get('type')=='user' and ts in byts:
                    current=byts[ts]
                    for a in pending: attach(a)
                    pending=[]
                    if isinstance(c,list):
                        for x in c:
                            if x.get('type')=='image':
                                source=x.get('source',{}); mt=source.get('media_type','image/png')
                                if source.get('type')=='base64':
                                    data=base64.b64decode(source['data'],validate=True); a=add_bytes(data,'image'+(mimetypes.guess_extension(mt) or '.png'),'', 'embedded-image'); a=dict(a,mime=mt,image=True); attach(a)
                                else: skipped.append({'session':src.name,'attachment':'remote image','reason':'not downloaded'})
                if row.get('type')=='attachment' and row.get('attachment',{}).get('type')=='file':
                    a=row['attachment']; original=a.get('filename',''); f=a.get('content',{}).get('file',{})
                    if isinstance(f.get('content'),str): data=f['content'].encode('utf-8'); mode='historical-text-snapshot'
                    elif Path(original).is_file(): data=Path(original).read_bytes(); mode='current-file'
                    else: skipped.append({'session':src.name,'attachment':original,'reason':'file unavailable'}); continue
                    item=add_bytes(data,original,original,mode); attach(item)
        else:
            # Recover image bytes by the exact turn ID. Read only image blocks here;
            # all transcript text still comes exclusively from UI item_completed.
            embedded={}
            for row in rows:
                q=row.get('payload',{})
                if row.get('type')!='response_item' or q.get('role')!='user': continue
                tid=q.get('internal_chat_message_metadata_passthrough',{}).get('turn_id')
                if not tid: continue
                for x in q.get('content',[]):
                    if x.get('type')=='input_image' and isinstance(x.get('image_url'),str):
                        match=re.fullmatch(r'data:([^;]+);base64,(.*)',x['image_url'],re.S)
                        if match: embedded.setdefault(tid,[]).append((match.group(1),match.group(2)))
            for row in rows:
                q=row.get('payload',{}); it=q.get('item',{})
                if row.get('type')!='event_msg' or q.get('type')!='item_completed' or it.get('type')!='UserMessage' or row.get('timestamp') not in byts: continue
                current=byts[row['timestamp']]
                local_images=[x for x in it.get('content',[]) if x.get('type')=='local_image']
                image_bytes=embedded.get(q.get('turn_id'),[])
                image_index=0
                for x in it.get('content',[]):
                    if x.get('type')=='local_image':
                        p=Path(x['path'])
                        if p.is_file(): attach(dict(add_bytes(p.read_bytes(),p.name,str(p),'current-file'),mime=mimetypes.guess_type(p)[0] or 'image/png',image=True))
                        elif len(image_bytes)==len(local_images):
                            mt,data=image_bytes[image_index]
                            attach(dict(add_bytes(base64.b64decode(data,validate=True),p.name,str(p),'historical-embedded-image'),mime=mt,image=True))
                        else: skipped.append({'session':src.name,'attachment':str(p),'reason':'file unavailable'})
                        image_index+=1
                    elif x.get('type','').lower()=='text':
                        # File labels are in the UI UserMessage header, not response_item harness context.
                        text=x.get('text','')
                        header=text.split('## My request',1)[0] if '# Files mentioned by the user:' in text else ''
                        for name,original in re.findall(r'^## (.+?): (.+)$',header,re.M):
                            original=original.strip(); p=Path(original)
                            if p.suffix.lower() in ('.png','.jpg','.jpeg','.webp','.gif') and any(z.get('type')=='local_image' and os.path.normcase(z.get('path',''))==os.path.normcase(original) for z in it.get('content',[])): continue
                            if portable_name(original) in SKIP_FILES or portable_name(original).startswith('.env.'):
                                skipped.append({'session':src.name,'attachment':original,'reason':'credential/config exclusion'}); continue
                            if p.is_file(): attach(add_bytes(p.read_bytes(),p.name,original,'current-file'))
                            else: skipped.append({'session':src.name,'attachment':original,'reason':'file unavailable'})
        if pending: skipped.append({'session':src.name,'reason':'attachment has no visible user turn','count':len(pending)})
        bundles.append(b)
    manifest={'schema':'agent-project/v1','source_agent':agent,'source_project':str(project),'created_at':r.now(),'files':entries,'attachments':assets,'conversations':bundles,'skipped':skipped,'exclusions':sorted(SKIP_DIRS|SKIP_FILES),'note':'No credentials, installed dependencies or agent internal states; historical text attachments may be partial excerpts.'}
    r.dump(out/'manifest.json',manifest)
    print(json.dumps({'package':str(out),'files':len(entries),'bytes':sum(x['bytes'] for x in entries),'conversations':len(bundles),'attachments':len(assets),'skipped':skipped},ensure_ascii=False))

def restore(package,dest,to,home=None,no_desktop=False,title_suffix=' · 迁移副本',claude_context_budget=r.DEFAULT_BUDGET,codex_context_budget=r.DEFAULT_BUDGET,model=None,claude_model=None,claude_version=None,desktop_registry=None):
    package=package.resolve(); dest=dest.resolve(); m=json.loads((package/'manifest.json').read_text(encoding='utf-8'))
    if m.get('schema')!='agent-project/v1': raise ValueError('Unsupported project package')
    if dest.exists(): raise ValueError('Target must be a new directory; never merge with existing project')
    # Verify all bytes and paths before touching a target agent.
    for f in m['files']+m['attachments']:
        p=safe(package,f['path'])
        if not p.is_file() or r.digest(p)!=f['sha256']: raise ValueError('Package integrity check failed: '+f['path'])
        if 'permissions' in f and (type(f['permissions']) is not int or not 0<=f['permissions']<=0o777): raise ValueError('Unsafe file permissions')
    for b in m['conversations']:
        r.validate(b)
        for t in b['turns']:
            for a in t['user'].get('attachments',[]):
                if a not in m['attachments'] and not any(a['path']==x['path'] and a['sha256']==x['sha256'] for x in m['attachments']): raise ValueError('Unlisted attachment')
    # Resolve target settings before creating files or partially importing a project.
    from target_settings import codex_model,claude_settings
    target_home=Path(home) if home else Path.home()/('.codex' if to=='codex' else '.claude')
    if m['conversations']:
        if to=='codex': model=codex_model(target_home.resolve(),model)
        else:
            probe=argparse.Namespace(target_home=str(home) if home else None,no_desktop=no_desktop,desktop_registry=desktop_registry)
            claude_model,claude_version=claude_settings(target_home,claude_model,claude_version,r.desktop_model(probe))
    dest.mkdir(parents=True); restored=[]
    for f in m['files']+m['attachments']:
        rel=f['path'][8:] if f['path'].startswith('project/') else '.rehome/'+f['path']
        p=safe(dest,rel); p.parent.mkdir(parents=True,exist_ok=True)
        if p.exists(): raise ValueError('Restored file collision on this filesystem: '+rel)
        shutil.copy2(safe(package,f['path']),p)
        if os.name!='nt' and 'permissions' in f: p.chmod(f['permissions'])
        restored.append({'path':rel,'sha256':f['sha256']})
    state={'schema':'agent-project-restore/v1','package':str(package),'target':str(dest),'to':to,'files':restored,'sessions':[],'status':'importing'}
    r.dump(dest/'.rehome/restore.json',state)
    for original in m['conversations']:
        b=copy.deepcopy(original); origin_id=b['source']['session_id']
        b['source']['original_session_id']=origin_id
        # Namespace imports by destination, avoiding collisions with existing live/test chats.
        b['source']['session_id']=str(uuid.uuid5(r.NS,'project/'+m['source_project']+'/'+origin_id+'/'+str(dest)))
        suffix=' · 项目迁移测试'
        while b['title'].endswith(suffix): b['title']=b['title'][:-len(suffix)]
        b['title']+=title_suffix; b['project']['cwd']=str(dest)
        for t in b['turns']:
            att=t['user'].get('attachments',[])
            for a in att:
                a['local_path']=str(safe(dest,'.rehome/'+a['path']))
                if a.get('original'): t['user']['text']=remap_text(t['user']['text'],a['original'],a['local_path'])
            if att: t['user']['text']+='\n\n迁移附件（历史数据）：\n'+'\n'.join(f"[{a['name']}]({Path(a['local_path']).as_posix()})" for a in att)
            t['user']['text']=remap_text(t['user']['text'],m['source_project'],dest.as_posix())
        a=argparse.Namespace(cwd=str(dest),to=to,target_home=str(home) if home else None,dry_run=False,model=model,claude_version=claude_version,claude_model=claude_model,new_copy=False,desktop_registry=desktop_registry,no_desktop=no_desktop,claude_context_budget=claude_context_budget,codex_context_budget=codex_context_budget)
        imported=r.import_bundle(b,a)
        sid=str(uuid.uuid5(r.NS,b['source']['agent']+'/'+b['source']['session_id']))
        state['sessions'].append({'source_id':origin_id,'id':sid,'title':b['title'],'turns':len(b['turns']),'attachments':sum(len(t['user'].get('attachments',[])) for t in b['turns']),'context':imported.get('context'),'desktop_registry':imported.get('desktop_registry')}); r.dump(dest/'.rehome/restore.json',state)
    for f in restored:
        if r.digest(safe(dest,f['path']))!=f['sha256']: raise ValueError('Restored file mismatch: '+f['path'])
    if to=='codex' and state['sessions']:
        from codex_project_registry import register
        target_home=Path(home) if home else Path.home()/'.codex'
        database_path=target_home/'state_5.sqlite'
        with sqlite3.connect(sqlite_read_uri(database_path),uri=True) as db:
            pid=db.execute('select project_id from threads where id=?',(state['sessions'][0]['id'],)).fetchone()[0]
            name=db.execute('select name from projects where id=?',(pid,)).fetchone()[0]
        if no_desktop:
            state['desktop_project_registry']={'registered':False,'next':'Add the restored folder in Codex APP, then associate the imported chats. Native sidebar verification is pending.'}
        else:
            state['desktop_project_registry']=register(target_home,str(dest),pid,name,[t['id'] for t in state['sessions']])
    state['status']='files-verified-native-resume-pending'; r.dump(dest/'.rehome/restore.json',state)
    print(json.dumps(state,ensure_ascii=False))
def main():
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('pack'); p.add_argument('--from',dest='agent',choices=['claude','codex'],required=True);p.add_argument('--project',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--source-home',type=Path);p.add_argument('--sessions-json',type=Path,help='Explicit native project inventory with snapshot paths and titles')
    p=sub.add_parser('restore');p.add_argument('package',type=Path);p.add_argument('--cwd',type=Path,required=True);p.add_argument('--to',choices=['claude','codex'],required=True);p.add_argument('--target-home',type=Path);p.add_argument('--no-desktop',action='store_true')
    p.add_argument('--model');p.add_argument('--claude-model');p.add_argument('--claude-version');p.add_argument('--desktop-registry')
    p.add_argument('--claude-context-budget',type=int,default=r.DEFAULT_BUDGET)
    p.add_argument('--codex-context-budget',type=int,default=r.DEFAULT_BUDGET)
    a=ap.parse_args()
    if a.mode=='pack': pack(a.agent,a.project,a.out,a.source_home or Path.home()/('.claude' if a.agent=='claude' else '.codex'),json.loads(a.sessions_json.read_text(encoding='utf-8')) if a.sessions_json else None)
    else: restore(a.package,a.cwd,a.to,a.target_home,a.no_desktop,claude_context_budget=a.claude_context_budget,codex_context_budget=a.codex_context_budget,model=a.model,claude_model=a.claude_model,claude_version=a.claude_version,desktop_registry=a.desktop_registry)
if __name__=='__main__': main()
