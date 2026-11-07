"""Project snapshots: files, portable conversations and historical attachment copies."""
import argparse,base64,copy,hashlib,json,mimetypes,os,re,shutil,sqlite3,uuid
from pathlib import Path,PurePosixPath
from platform_paths import path_key,portable_name,portable_suffix,remap_text,sqlite_read_uri,source_rollout
import agent_rehome as r
import exchange,claude_native,codex_relocate,project_surroundings
from project_io import CHUNK, chunks, measure, write_checked, check_space, json_bytes, linked
from collections import Counter
from urllib.parse import urlsplit
from cli_output import print,configure
from user_next_steps import NEXT_STEPS,add_next_steps,package_next_steps
SKIP_DIRS={'.git','node_modules','.venv','venv','__pycache__','.next','target','dist','AppData','.codex','.claude','.ssh','.cache','__MACOSX','.AppleDouble'}
SKIP_FILES={'.env','.npmrc','.pypirc','credentials.json','.credentials.json','auth.json','token.json','tokens.json','settings.local.json','.DS_Store'}
LOCAL_ARTIFACT_SUFFIXES={'.exe','.dll','.pdb','.dmg','.zip','.gz','.zst','.rehome','.sqlite','.sqlite3','.db','.wal','.shm','.bin'}
PROFILE_DIRS={'appdata','webview','ebwebview','user data','oneauth','browser','browser-profile'}
INLINE_IMAGE_LIMIT=16*1024**2

def relative_parts(rel):
    q=PurePosixPath(rel)
    if q.is_absolute() or '..' in q.parts or not q.parts or ':' in rel or '\\' in rel: raise ValueError('Unsafe package path: '+rel)
    return q.parts


def safe(root,rel):
    p=root
    for part in relative_parts(rel):
        p=p/part
        if (p.exists() or p.is_symlink()) and linked(p):raise ValueError('Linked package or destination path: '+rel)
    p=p.resolve()
    if not p.is_relative_to(root.resolve()): raise ValueError('Path escapes package')
    return p

def files(root,include_git=False,excluded_dirs=None):
    ignored={s.lower() for s in SKIP_DIRS}|PROFILE_DIRS
    if include_git:ignored.remove('.git')
    for base,dirs,names in os.walk(root,followlinks=False):
        allowed=[]
        for name in dirs:
            directory=Path(base)/name
            if linked(directory):
                if excluded_dirs is not None:excluded_dirs[directory]=False
            elif name.lower() in ignored and not (
                directory.relative_to(root).parts[:3]==('.rehome','surroundings','originals')
                and len(directory.relative_to(root).parts)==4 and name in ('.claude','.codex')):
                if excluded_dirs is not None:excluded_dirs[directory]=True
            else:allowed.append(name)
        dirs[:]=allowed
        for name in names:
            p=Path(base)/name
            if name.lower() in {s.lower() for s in SKIP_FILES}|{'cookies','login data','web data','local state','.git'} or name.lower().startswith('.env.') or linked(p) or not p.is_file(): continue
            if p.suffix.lower() in ('.key','.pem','.p12','.pfx'): continue
            if p.relative_to(root).parts[:3]==('.rehome','surroundings','originals') and project_surroundings.excluded(p.relative_to(root)):continue
            if '.codex-local' in p.relative_to(root).parts and p.suffix.lower() in LOCAL_ARTIFACT_SUFFIXES: continue
            if p.relative_to(root).as_posix() in ('.rehome/restore.json',NEXT_STEPS): continue
            yield p

def directory_bytes(root):
    total=0
    for base,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=[name for name in dirs if not linked(Path(base)/name)]
        for name in names:
            path=Path(base)/name
            if not linked(path) and path.is_file():total+=path.stat().st_size
    return total


def file_preview(project,paths,excluded_dirs):
    top=Counter();extensions=Counter();directories=Counter();sizes={};git_bytes=0
    for path in paths:
        rel=path.relative_to(project);size=path.stat().st_size;sizes[rel.as_posix()]=size
        top[rel.parts[0] if len(rel.parts)>1 else '.']+=size
        extensions[path.suffix.lower() or '(none)']+=size
        for parent in rel.parents:
            if parent.parts:directories[parent.as_posix()]+=size
        if '.git' in (part.lower() for part in rel.parts[:-1]):git_bytes+=size
    exclusions=[]
    for directory,can_scan in sorted(excluded_dirs.items()):
        rel=directory.relative_to(project).as_posix()
        included=sum(size for name,size in sizes.items() if name.startswith(rel+'/')) if directory.name.lower() in ('.claude','.codex') else 0
        exclusions.append({'path':rel,'bytes':max(0,directory_bytes(directory)-included) if can_scan else None})
    largest=sorted(sizes.items(),key=lambda entry:(-entry[1],entry[0]))[:10]
    largest_directories=sorted(directories.items(),key=lambda entry:(-entry[1],entry[0]))[:5]
    return {'files':len(paths),'bytes':sum(sizes.values()),'largest_files':[{'path':path,'bytes':size} for path,size in largest],
            'largest_directories':[{'path':path,'bytes':size} for path,size in largest_directories],
            'bytes_by_top_directory':dict(sorted(top.items())),'bytes_by_extension':dict(sorted(extensions.items())),
            'excluded_directories':exclusions,'git_bytes':git_bytes}


def git_preflight(project,paths):
    for path in paths:
        rel=path.relative_to(project)
        if not any(part.lower()=='.git' for part in rel.parts[:-1]) or path.name.lower() not in ('config','config.worktree'):
            continue
        text=project_surroundings.config_text(path)
        if re.search(r'^\s*\[\s*include(?:if)?\b',text,re.I|re.M):
            raise ValueError('Review and remove external Git config includes before packing: '+rel.as_posix())
        if project_surroundings.PATTERNS['credential'].search(text) or re.search(r'^\s*extraheader\s*=.*authorization\b',text,re.I|re.M):
            raise ValueError('Possible credentials in Git config. Clean it before packing: '+rel.as_posix())
        for match in re.finditer(r'^\s*(?:url|pushurl|insteadof|pushinsteadof)\s*=\s*([^\r\n]+)',text,re.I|re.M):
            value=match.group(1).strip().strip('"')
            if '://' in value:
                url=urlsplit(value)
                if (url.username is not None and not (url.scheme=='ssh' and url.username=='git' and url.password is None)) or url.password is not None or url.query:
                    raise ValueError('Possible credentials in Git remote URL. Clean the source Git config before packing: '+rel.as_posix())


def encoded_chunks(data):
    for offset in range(0,len(data),CHUNK):
        yield data[offset:offset+CHUNK].encode('utf-8')


def decoded_chunks(data):
    for offset in range(0,len(data),CHUNK):
        block=data[offset:offset+CHUNK]
        if '=' in block and offset+CHUNK<len(data):raise ValueError('Invalid embedded base64 padding')
        yield base64.b64decode(block,validate=True)

def restore_title(title, session_id, first_user='', destination=None):
    base=(title or '').strip()
    if destination is not None:
        base=re.sub(r'(?: · (?:迁移副本|项目迁移测试|新副本(?: \[.*?\])?))+$','',base)
    if not base:
        fallback=claude_native.fallback_title(first_user)
        base=session_id[:8] if fallback=='未命名会话' else fallback
    return base if destination is None else f'{base} · 新副本 [{destination.name}]'


def native_title(snap, module, home):
    if (snap.get('title') or '').strip():
        return snap['title']
    sid=snap['source']['session_id']
    if module is codex_relocate:
        _,rows=module.metadata(snap['files'][0]['data'])
        turns,_=r.export_codex(rows,sid,home)
    else:
        raw=next(item['data'] for item in snap['files']
                 if item.get('scope')=='project' and item.get('relative')==sid+'.jsonl')
        rows=[json.loads(line) for line in raw.decode('utf-8-sig').split('\n') if line.strip()]
        turns,_=r.export_claude(rows)
    return restore_title('',sid,turns[0]['user']['text'] if turns else '')


def pack(agent,project,out,home,selected_sessions=None,native=False,include_memory=False,include_checkpoints=False,source_desktop_registry=None,format_version=2,dry_run=False,allow_large=False,allow_secrets_in_config=False,files_mode='copy',include_git=False):
    if native and format_version!=2:raise ValueError('Native project payload requires v2')
    original_project=Path(os.path.abspath(project))
    project=project.resolve(); out=out.resolve()
    source_roots=list(dict.fromkeys((str(original_project),str(project))))
    if out.exists() or out.is_relative_to(project): raise ValueError('Package must be new and outside source project')
    if not project.is_dir():raise ValueError('Source project directory does not exist')
    if files_mode not in ('copy','reference'):raise ValueError('Invalid project file mode')
    excluded_dirs={}
    project_files,agent_skips=project_surroundings.inventory(project,agent,files(project,include_git,excluded_dirs));preview=file_preview(project,project_files,excluded_dirs)
    print(json.dumps({'stage':'project-file-preview',**preview},ensure_ascii=False),flush=True)
    if include_git:git_preflight(project,project_files)
    config_secrets=project_surroundings.secret_preflight(project,project_files,allow_secrets_in_config)
    if dry_run:return preview
    entries=[]; assets=[]; skipped=[]; asset_sources={}; asset_by_hash={}; copy_sources=[]; references=[]
    def add_asset(blocks,name,original,mode):
        sha,size=measure(blocks()); ext=portable_suffix(name)[:16]; rel=f'attachments/{sha}{ext}'
        existing=asset_by_hash.get(sha)
        if existing:return dict(existing,original=original,name=portable_name(name),mode=mode)
        item={'path':rel,'sha256':sha,'bytes':size,'original':original,'name':portable_name(name),'mode':mode}
        assets.append(item);asset_sources[rel]=blocks;asset_by_hash[sha]=item
        return item
    for p in project_files:
        relative=p.relative_to(project).as_posix();sha,size=measure(chunks(p))
        if files_mode=='reference':references.append({'path':relative,'sha256':sha,'bytes':size})
        if files_mode=='reference' and not project_surroundings.bridge_input(relative):continue
        rel='project/'+relative
        entry={'path':rel,'sha256':sha,'bytes':size}
        if os.name!='nt': entry['permissions']=p.stat().st_mode & 0o777
        entries.append(entry)
        copy_sources.append((p,entry))
    if selected_sessions is not None:
        sessions=[Path(x['snapshot']) for x in selected_sessions]
    elif agent=='claude':
        roots=source_roots if native else [str(project)]
        sessions=sorted({session for root in roots for session in (home/'projects'/re.sub(r'[^a-zA-Z0-9_-]','-',root)).glob('*.jsonl')})
    else:
        sessions=[]
        with r.closing(sqlite3.connect(sqlite_read_uri(home/"state_5.sqlite"),uri=True)) as db:
            for path,cwd in db.execute('select rollout_path,cwd from threads'):
                if path_key(cwd) in {path_key(root) for root in source_roots}: sessions.append(source_rollout(home,path))
    bundles=[];native_refs={};native_payloads=[];empty_titles=0
    for index,src in enumerate(sessions):
        requested=selected_sessions[index].get('title') if selected_sessions is not None else None
        if selected_sessions is not None and (not isinstance(requested,str) or not requested.strip()):
            empty_titles+=1
        rows=r.read(src)
        if agent=='codex':
            meta=next((x['payload'] for x in rows if x.get('type')=='session_meta'),{})
            if meta.get('cli_version') in ('claude-import','claude-to-codex-proof'): raise ValueError('Refusing imported Claude history as native Codex source')
        native_module=claude_native if agent=='claude' else codex_relocate
        snap=native_module.snapshot(src,home,include_memory and index==0,include_checkpoints,source_desktop_registry) if native else None
        if snap:
            snap['title']=native_title(snap,native_module,home)
            snap['source']['cwd']=str(project)
            if len(source_roots)>1:snap['source']['cwd_aliases']=source_roots
        def native_bundle():
            return {'schema':'agent-transcript/v1','source':dict(snap['source']),'title':snap['title'],'project':{'cwd':str(project)},'turns':[],'losses':[]}
        if native and agent=='codex':b=native_bundle()
        else:
            try:b=exchange.to_v1(r.export(agent,str(src),home,full_tools=True))
            except ValueError as e:
                if not native:skipped.append({'session':src.name,'reason':str(e)});continue
                # Native histories with no visible main-line turn still belong to the project.
                if str(e)!='没有可迁移的可见对话':raise
                b=native_bundle()
        if isinstance(requested,str) and requested.strip():
            b['title']=requested
            if snap:snap['title']=requested
        if snap:
            relative='sessions/'+snap['source']['session_id']+'/raw-native'
            descriptor={key:value for key,value in snap.items() if key!='files'}
            descriptor['files']=[{key:value for key,value in item.items() if key!='data'}|{'bytes':len(item['data'])}
                                 for item in snap['files']]
            native_payloads.append((native_module,src,descriptor,relative,index==0 and include_memory))
        byts={t['user']['ts']:t for t in b['turns']}; current=None; pending=[]
        def attach(a):
            if current is None: pending.append(a)
            else: current['user'].setdefault('attachments',[]).append(a)
        def add_current(path,original,**metadata):
            if path.name.lower() in {name.lower() for name in SKIP_FILES} or path.name.lower().startswith('.env.'):
                skipped.append({'session':src.name,'attachment':original,'reason':'credential/config exclusion'})
                return
            if files_mode=='reference' and path.resolve().is_relative_to(project):
                skipped.append({'session':src.name,'attachment':original,'reason':'project file referenced by inventory'})
                return
            attach(dict(add_asset(lambda:chunks(path),path.name,original,'current-file'),**metadata))
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
                                    a=add_asset(lambda data=source['data']:decoded_chunks(data),'image'+(mimetypes.guess_extension(mt) or '.png'),'', 'embedded-image'); attach(dict(a,mime=mt,image=True))
                                else: skipped.append({'session':src.name,'attachment':'remote image','reason':'not downloaded'})
                if row.get('type')=='attachment' and row.get('attachment',{}).get('type')=='file':
                    a=row['attachment']; original=a.get('filename',''); f=a.get('content',{}).get('file',{})
                    if isinstance(f.get('content'),str):
                        attach(add_asset(lambda data=f['content']:encoded_chunks(data),original,original,'historical-text-snapshot'))
                    elif Path(original).is_file(): add_current(Path(original),original)
                    else: skipped.append({'session':src.name,'attachment':original,'reason':'file unavailable'}); continue
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
                        if p.is_file(): add_current(p,str(p),mime=mimetypes.guess_type(p)[0] or 'image/png',image=True)
                        elif len(image_bytes)==len(local_images):
                            mt,data=image_bytes[image_index]
                            attach(dict(add_asset(lambda value=data:decoded_chunks(value),p.name,str(p),'historical-embedded-image'),mime=mt,image=True))
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
                            if p.is_file(): add_current(p,original)
                            else: skipped.append({'session':src.name,'attachment':original,'reason':'file unavailable'})
        if pending: skipped.append({'session':src.name,'reason':'attachment has no visible user turn','count':len(pending)})
        bundles.append(b)
    exclusions=(SKIP_DIRS-{'.git'} if include_git else SKIP_DIRS)|SKIP_FILES
    manifest={'schema':'agent-project/v1','source_agent':agent,'source_project':str(project),'created_at':r.now(),'files':entries,'attachments':assets,'conversations':bundles,'skipped':skipped,'exclusions':sorted(exclusions),'note':'Base exclusions have explicit project-agent allowlist exceptions. Known credential filenames excluded; config secret overrides are recorded, not sanitized. No user-level agent installation; historical text attachments may be partial excerpts.'}
    skill_dirs=[]
    for prefix in ('.claude/skills','.agents/skills'):
        base=project/prefix
        if base.is_dir() and not linked(base) and not linked(base.parent):
            for directory,dirs,_ in os.walk(base):
                dirs[:]=[name for name in dirs if not linked(Path(directory)/name) and not project_surroundings.excluded((Path(directory)/name).relative_to(project))]
                skill_dirs.extend((Path(directory)/name).relative_to(project).as_posix() for name in dirs)
    manifest['surroundings']={'skipped':agent_skips,'config_secret_overrides':config_secrets,'skill_directories':skill_dirs}
    if files_mode=='reference':manifest['file_references']={'include_git':include_git,'entries':references}
    native_bytes=sum(item['bytes'] for _,_,snap,_,_ in native_payloads for item in snap['files'])
    estimate=sum(item['bytes']+4096 for item in entries+assets)+native_bytes+2*json_bytes(manifest)
    estimate+=sum(json_bytes(snap)+4096*(len(snap['files'])+1) for _,_,snap,_,_ in native_payloads)
    check_space([(out,estimate)])
    out.mkdir(parents=True)
    for source,entry in copy_sources:
        target=safe(out,entry['path']);target.parent.mkdir(parents=True,exist_ok=True)
        write_checked(target,chunks(source),(entry['sha256'],entry['bytes']))
        shutil.copystat(source,target)
    for item in assets:
        target=safe(out,item['path']);target.parent.mkdir(exist_ok=True)
        write_checked(target,asset_sources[item['path']](),(item['sha256'],item['bytes']))
    for module,source,descriptor,relative,with_memory in native_payloads:
        snap=module.snapshot(source,home,with_memory,include_checkpoints,source_desktop_registry)
        files_now=[{key:value for key,value in item.items() if key!='data'}|{'bytes':len(item['data'])}
                   for item in snap['files']]
        if snap['source']['session_id']!=descriptor['source']['session_id'] or files_now!=descriptor['files']:
            raise ValueError('Native session changed during packing: '+source.name)
        snap={**descriptor,'files':snap['files']}
        directory=safe(out,relative)
        module.pack(snap,directory)
        native_refs[snap['source']['session_id']]={'path':relative,'manifest_sha256':r.digest(directory/'manifest.json')}
    if format_version==1:r.dump(out/'manifest.json',manifest)
    else:exchange.write_project(out,manifest,native_refs)
    print(json.dumps({'package':str(out),'files':len(entries),'bytes':sum(x['bytes'] for x in entries),'conversations':len(bundles),'attachments':len(assets),'empty_titles':empty_titles,'skipped':skipped,'user_next_steps':package_next_steps(out)},ensure_ascii=False))

def load_manifest(package):return exchange.read_project(package)


def compare_references(dest,source_agent,inventory):
    if type(inventory.get('include_git',False)) is not bool:raise ValueError('Invalid reference Git selection')
    expected={}
    for item in inventory['entries']:
        relative=item['path'];relative_parts(relative)
        key=os.path.normcase(relative)
        if key in expected or type(item['bytes']) is not int or item['bytes']<0 or not re.fullmatch('[0-9a-f]{64}',item['sha256']):
            raise ValueError('Invalid project file reference: '+relative)
        expected[key]=item
    actual,_=project_surroundings.inventory(dest,source_agent,files(dest,inventory.get('include_git',False)))
    present={os.path.normcase(path.relative_to(dest).as_posix()):path for path in actual}
    missing=[];different=[]
    for key,item in expected.items():
        path=present.get(key)
        if path is None:missing.append(item['path'])
        elif path.stat().st_size!=item['bytes'] or r.digest(path)!=item['sha256']:different.append(item['path'])
    return {'missing':sorted(missing),'extra':sorted(present[key].relative_to(dest).as_posix() for key in present.keys()-expected.keys()),'different':sorted(different)}


def restore(package,dest,to,home=None,no_desktop=False,title_suffix=' · 迁移副本',claude_context_budget=r.DEFAULT_BUDGET,codex_context_budget=r.DEFAULT_BUDGET,model=None,claude_model=None,claude_version=None,desktop_registry=None,convert=False,dry_run=False,new_copy=False,fast_forward=False,strict_files=False):
    package=package.resolve(); dest=dest.resolve(); m=load_manifest(package)
    if m.get('schema')!='agent-project/v1': raise ValueError('Unsupported project package')
    reference=m.get('file_references')
    if strict_files and reference is None:raise ValueError('--strict-files requires a reference-mode project package')
    reference_report=None
    if reference is not None:
        if not dest.is_dir():raise ValueError('Reference restore requires an existing project directory')
        if package.is_relative_to(dest) or dest.is_relative_to(package):raise ValueError('Reference target and package must be separate directories')
        if safe(dest,'.rehome/restore.json').exists() or safe(dest,'.rehome/restore.json.rehome-tmp').exists():
            raise ValueError('Existing restore receipt; choose a fresh target copy')
        for directory in ('history','context','losses','exchange'):
            path=safe(dest,'.rehome/'+directory+'/'+to)
            if any(parent.exists() and not parent.is_dir() for parent in (path,*path.parents)):
                raise ValueError('Restore metadata directory collides with an existing file')
        if any(f['path'].startswith('project/') and not project_surroundings.bridge_input(f['path'][8:]) for f in m['files']):
            raise ValueError('Reference package contains an ordinary project file payload')
        reference_report=compare_references(dest,m['source_agent'],reference)
        if strict_files and any(reference_report.values()):
            print(json.dumps({'file_references':reference_report},ensure_ascii=False))
            raise ValueError('Reference file inventory differs; strict restore stopped before writing')
    elif dest.exists():raise ValueError('Target must be a new directory; never merge with existing project')
    same=m.get('source_agent')==to and not convert
    native_mode=same
    if fast_forward and (new_copy or to!='claude' or not native_mode):raise ValueError('--fast-forward requires native Claude and is mutually exclusive with --new-copy')
    native_module=claude_native if to=='claude' else codex_relocate
    native_plans=[];planned=set();allocations=[]
    if native_mode:
        for b in m['conversations']:
            sid=b['source']['session_id'];ref=m.get('native_sessions',{}).get(sid)
            if not ref:raise ValueError('Same-agent restore needs project pack --native; --convert is lossy diagnostics only')
            directory=safe(package,ref['path'])
            if r.digest(directory/'manifest.json')!=ref['manifest_sha256']:raise ValueError('Native manifest hash mismatch')
            snap=native_module.load(directory)
            if snap['source']['session_id']!=sid:raise ValueError('Native project session identity mismatch')
            snap['title']=restore_title(native_title(snap,native_module,Path(home) if home else Path.home()/('.'+to)),
                                        sid,destination=dest if new_copy else None)
            args=argparse.Namespace(cwd=str(dest),to=to,target_home=str(home) if home else None,no_desktop=no_desktop,desktop_registry=desktop_registry,dry_run=dry_run,allow_new_project=True,new_copy=new_copy,fast_forward=fast_forward,project_restore=True)
            _,_,writes,_=native_module.plan(snap,args)
            for path,data in writes:
                key=os.path.normcase(str(path.resolve()))
                if key in planned:raise ValueError('Native project destination collision')
                planned.add(key)
                allocations.append((path,len(data)+4096))
                if fast_forward and path.is_file():allocations.append((Path(args.target_home or Path.home()/'.claude'),path.stat().st_size))
            native_plans.append((snap,args))
    # Verify all bytes and paths before touching a target agent.
    file_destinations={}
    for f in m['files']+m['attachments']:
        p=safe(package,f['path'])
        if not p.is_file() or ('bytes' in f and p.stat().st_size!=f['bytes']) or r.digest(p)!=f['sha256']: raise ValueError('Package integrity check failed: '+f['path'])
        if 'permissions' in f and (type(f['permissions']) is not int or not 0<=f['permissions']<=0o777): raise ValueError('Unsafe file permissions')
        rel=f['path'][8:] if f['path'].startswith('project/') else '.rehome/'+f['path']
        key=os.path.normcase(str(safe(dest,rel)))
        if key in file_destinations:
            previous=file_destinations[key]
            if previous['file']['sha256']!=f['sha256']:
                raise ValueError('Conflicting restored file destination: '+previous['file']['path']+' vs '+f['path'])
            previous['source_paths'].append(f['path'])
        else:file_destinations[key]={'file':f,'rel':rel,'source_paths':[f['path']]}
    deduplicated=[{'path':item['rel'],'sha256':item['file']['sha256'],'source_paths':item['source_paths'],
        'source_count':len(item['source_paths']),'skipped_copies':len(item['source_paths'])-1}
        for item in file_destinations.values() if len(item['source_paths'])>1]
    reserved={os.path.normcase(str(dest/rel)) for rel in ('.rehome/restore.json',NEXT_STEPS)}
    if reserved & file_destinations.keys():raise ValueError('Package collides with restore metadata')
    combined=file_destinations.keys()|planned|reserved
    for key in combined:
        if any(os.path.normcase(str(parent)) in combined for parent in Path(key).parents):raise ValueError('Restored file conflicts with a destination directory')
    if file_destinations.keys() & planned:raise ValueError('Project file collides with native history')
    original_files={item['rel']:item['file'] for item in file_destinations.values()}
    payload={rel:safe(package,f['path']) for rel,f in original_files.items() if project_surroundings.bridge_input(rel)}
    bridge_inputs=set(payload)
    surroundings=m.get('surroundings',{})
    payload,surroundings_report=project_surroundings.bridges(payload,m.get('source_agent',''),to,surroundings.get('skipped',[]),surroundings.get('config_secret_overrides',[]),surroundings.get('skill_directories',[]))
    if reference is not None and (dest/'.mcp.json').exists():
        surroundings_report['manual'].append({'path':'.mcp.json','reason':'existing-reference-project-config-preserved'})
    if (payload.keys()-bridge_inputs) & original_files.keys():raise ValueError('Generated surroundings path already exists')
    final_paths=(original_files.keys()-bridge_inputs)|payload.keys()
    # Validate generated paths/directories and their ancestors before creating the target.
    payload_paths={os.path.normcase(str(safe(dest,rel))) for rel in final_paths}
    if payload_paths & (planned|reserved):raise ValueError('Surroundings collide with reserved native/restore metadata')
    combined_paths=payload_paths|planned|reserved
    if any(any(os.path.normcase(str(parent)) in combined_paths for parent in Path(path).parents) for path in combined_paths):raise ValueError('Surroundings file/directory collision')
    for rel in surroundings_report['directories']:
        directory=safe(dest,rel)
        if any(os.path.normcase(str(parent)) in combined_paths for parent in (directory,*directory.parents)):raise ValueError('Skill directory collides with file')
        if directory.exists() and not directory.is_dir():raise ValueError('Skill directory collides with existing file: '+rel)
    write_plan=[]
    for rel in sorted(final_paths):
        f=original_files.get(rel,{})
        source=payload[rel] if rel in payload else safe(package,f['path'])
        if isinstance(source,Path) and f and source==safe(package,f['path']):
            expected=(f['sha256'],source.stat().st_size)
        else:
            expected=measure(project_surroundings.payload_chunks(source))
        target=safe(dest,rel)
        if any(parent.exists() and not parent.is_dir() for parent in target.parents):raise ValueError('Restored file parent is an existing file: '+rel)
        if target.exists():
            if reference is None or not target.is_file():raise ValueError('Restored file collision on this filesystem: '+rel)
            if rel.startswith('.rehome/') and (target.stat().st_size!=expected[1] or r.digest(target)!=expected[0]):
                raise ValueError('Existing restoration asset differs: '+rel)
            surroundings_report['skipped'].append({'path':rel,'reason':'existing-reference-project-file-preserved'})
            continue
        write_plan.append((rel,target,source,expected,f))
        allocations.append((target,expected[1]+4096))
    for b in m['conversations']:
        if not native_mode:
            if (b.get('turns') == [] and m['source_agent']=='codex'
                    and b['source']['session_id'] in m.get('native_sessions',{})):
                raise ValueError('这是 Codex 原生包，不能直接转换。请不带 --native 重新打包，再转换。 '
                                 'This is a native Codex package. Repack without --native before converting.')
            r.validate(b)
        for t in b['turns']:
            for a in t['user'].get('attachments',[]):
                if a not in m['attachments'] and not any(a['path']==x['path'] and a['sha256']==x['sha256'] for x in m['attachments']): raise ValueError('Unlisted attachment')
    # Resolve target settings before creating files or partially importing a project.
    from target_settings import codex_model,claude_settings
    target_home=Path(home) if home else Path.home()/('.codex' if to=='codex' else '.claude')
    if m['conversations'] and not native_mode:
        if to=='codex': model=codex_model(target_home.resolve(),model)
        else:
            probe=argparse.Namespace(target_home=str(home) if home else None,no_desktop=no_desktop,desktop_registry=desktop_registry)
            claude_model,claude_version=claude_settings(target_home,claude_model,claude_version,r.desktop_model(probe))
    if m['conversations']:
        if not native_mode:
            transcript=4*json_bytes(m['conversations'])
            inline_images=sum(a.get('bytes',0) for a in m['attachments'] if a.get('image') and a.get('bytes',0)<=INLINE_IMAGE_LIMIT)
            allocations.extend([(target_home,transcript+4*inline_images),(dest,transcript)])
        if to=='codex':
            copies=(2 if not no_desktop else 1) if native_mode else len(m['conversations'])+1
            for name in ('state_5.sqlite','state_5.sqlite-wal','session_index.jsonl','.codex-global-state.json'):
                path=target_home/name
                if path.is_file():allocations.append((target_home,copies*path.stat().st_size))
    allocations.append((dest/'.rehome/restore.json',2*json_bytes({'files':m['files'],'attachments':m['attachments'],'references':reference_report,'surroundings':surroundings_report})+4096))
    capacity=check_space(allocations)
    if dry_run:
        result={'status':'preview','to':to,'native':native_mode,'sessions':len(m['conversations']),'files':len(m['files']),'losses_summary':{} if native_mode else m.get('losses_summary',{})}
        if deduplicated:result['deduplicated']=deduplicated
        result['surroundings']=surroundings_report
        result['capacity']=capacity
        if reference_report is not None:result['file_references']=reference_report
        if fast_forward:
            import claude_fast_forward
            result['native_operations']=[]
            for snap,args in native_plans:
                _,info=claude_fast_forward.plan(snap,args)
                result['native_operations'].append({'id':snap['source']['session_id'],'append_lines':info['append_lines'],
                                                    'skipped_local_maintenance':info['skipped_local_maintenance'],
                                                    'live_process_check':info['live_process_check'],'live_process_sources':info['live_process_sources']})
            if any(op['live_process_check']=='unavailable' for op in result['native_operations']):
                result['warnings']=['无法检测部分目标会话的运行进程，本次预演不能证明可以安全写入。']
        print(json.dumps(result,ensure_ascii=False));return result
    dest.mkdir(parents=True,exist_ok=reference is not None); restored=[]
    for rel,p,source,expected,f in write_plan:
        p.parent.mkdir(parents=True,exist_ok=True)
        write_checked(p,project_surroundings.payload_chunks(source),expected)
        if isinstance(source,Path) and f:shutil.copystat(source,p)
        if os.name!='nt' and 'permissions' in f:p.chmod(f['permissions'])
        restored.append({'path':rel,'sha256':expected[0]})
    for rel in surroundings_report['directories']:safe(dest,rel).mkdir(parents=True,exist_ok=True)
    state={'schema':'agent-project-restore/v2','package':str(package),'target':str(dest),'to':to,'files':restored,'sessions':[],'status':'importing','losses_summary':{} if native_mode else m.get('losses_summary',{}),'mode':to+'-native' if native_mode else 'conversion'}
    if to=='codex':state['runtime_policy_note']='Imported workspace-write/on-request defaults apply before App loading only. After loading, actual runtime policy follows the target App current user settings; source permissions are not activated.'
    suspicious=sum(any(0xE000<=ord(char)<=0xF8FF or 0xF0000<=ord(char)<=0xFFFFD or 0x100000<=ord(char)<=0x10FFFD for char in f['path']) for f in m['files'])
    if suspicious:state['filename_warnings']={'private_use_paths':suspicious,'action':'Preserved original names; possible earlier filename decoding damage. No automatic renaming.'}
    if deduplicated:state['deduplicated']=deduplicated
    state['surroundings']=surroundings_report
    if reference_report is not None:state['file_references']=reference_report
    r.dump(dest/'.rehome/restore.json',state)
    codex_results=[]
    if native_mode and to=='codex' and native_plans:
        try:codex_results=codex_relocate.restore_many(native_plans)
        except BaseException:
            state['status']='native-session-transaction-failed-project-files-retained';r.dump(dest/'.rehome/restore.json',state);raise
    for original in m['conversations']:
        if native_mode:
            snap,args=native_plans[len(state['sessions'])];args.allow_new_project=False
            imported=codex_results[len(state['sessions'])] if to=='codex' else claude_native.restore(snap,args)
            state['sessions'].append({'source_id':snap['source']['session_id'],'id':imported['id'],'cwd':imported.get('cwd',str(dest)),'title':snap['title'],'desktop_registry':imported['desktop_registry'],'losses_summary':{},'context':imported['context']})
            if fast_forward:state['sessions'][-1].update(operation='fast-forward',append_lines=imported['append_lines'],skipped_local_maintenance=imported['skipped_local_maintenance'],live_process_check=imported['live_process_check'],live_process_sources=imported['live_process_sources'],backup=imported.get('backup'),status=imported['status'])
            if to=='codex':state['sessions'][-1]['limitations']=imported['limitations']
            r.dump(dest/'.rehome/restore.json',state);continue
        b=copy.deepcopy(original); origin_id=b['source']['session_id']
        b['source']['original_session_id']=origin_id
        # Namespace imports by destination, avoiding collisions with existing live/test chats.
        b['source']['session_id']=str(uuid.uuid5(r.NS,'project/'+m['source_project']+'/'+origin_id+'/'+str(dest)))
        suffix=' · 项目迁移测试'
        b['title']=b.get('title') or ''
        while suffix and b['title'].endswith(suffix): b['title']=b['title'][:-len(suffix)]
        while title_suffix and b['title'].endswith(title_suffix): b['title']=b['title'][:-len(title_suffix)]
        first=b['turns'][0]['user']['text'] if b['turns'] else ''
        b['title']=restore_title(b['title'],origin_id,first)+title_suffix; b['project']['cwd']=str(dest)
        for t in b['turns']:
            att=t['user'].get('attachments',[])
            for a in att:
                a['local_path']=str(safe(dest,'.rehome/'+a['path']))
                if a.get('image') and Path(a['local_path']).stat().st_size>INLINE_IMAGE_LIMIT:
                    a['image']=False
                    state.setdefault('attachment_display_notes',[]).append({'path':a['path'],'reason':'large-image-file-reference'})
                if a.get('original'): t['user']['text']=remap_text(t['user']['text'],a['original'],a['local_path'])
            if att and to!='codex': t['user']['text']+='\n\n迁移附件（历史数据）：\n'+'\n'.join(f"[{a['name']}]({Path(a['local_path']).as_posix()})" for a in att)
            t['user']['text']=remap_text(t['user']['text'],m['source_project'],dest.as_posix())
        a=argparse.Namespace(cwd=str(dest),to=to,target_home=str(home) if home else None,dry_run=False,model=model,claude_version=claude_version,claude_model=claude_model,new_copy=False,desktop_registry=desktop_registry,no_desktop=no_desktop,claude_context_budget=claude_context_budget,codex_context_budget=codex_context_budget,convert=convert,project_restore=True)
        imported=r.import_bundle(b,a)
        sid=str(uuid.uuid5(r.NS,b['source']['agent']+'/'+b['source']['session_id']))
        state['sessions'].append({'source_id':origin_id,'id':sid,'title':b['title'],'turns':len(b['turns']),'attachments':sum(len(t['user'].get('attachments',[])) for t in b['turns']),'context':imported.get('context'),'desktop_registry':imported.get('desktop_registry'),'losses_summary':imported.get('losses_summary',{})}); r.dump(dest/'.rehome/restore.json',state)
    for f in restored:
        if r.digest(safe(dest,f['path']))!=f['sha256']: raise ValueError('Restored file mismatch: '+f['path'])
    if to=='codex':
        from codex_project_registry import register
        target_home=Path(home) if home else Path.home()/'.codex'
        if state['sessions']:
            database_path=target_home/'state_5.sqlite'
            with r.closing(sqlite3.connect(sqlite_read_uri(database_path),uri=True)) as db:
                pid=db.execute('select project_id from threads where id=?',(state['sessions'][0]['id'],)).fetchone()[0]
                name=db.execute('select name from projects where id=?',(pid,)).fetchone()[0]
        else:
            # Registration owns the native UI identity; an empty project needs no thread/DB insert.
            pid=str(uuid.uuid5(r.NS,'project/'+path_key(str(dest))))
            name=dest.name
        if no_desktop:
            state['desktop_project_registry']={'registered':False,'thread_binding_required':[t['id'] for t in state['sessions']],'next':'Add the restored folder in Codex APP, then associate the imported chats. Native sidebar verification is pending.'}
        else:
            state['desktop_project_registry']=register(target_home,str(dest),pid,name,[t['id'] for t in state['sessions']])
            state['desktop_project_registry'].setdefault('thread_binding_required',[t['id'] for t in state['sessions']])
    if not native_mode:
        # Session reports include source losses and any target context summarization.
        state['losses_summary']=dict(m.get('losses_summary',{}))
        source_counts={}
        for b in m['conversations']:
            for k,v in exchange.loss_summary(b.get('losses',[])).items():source_counts[k]=source_counts.get(k,0)+v
        for s in state['sessions']:
            for k,v in s['losses_summary'].items():state['losses_summary'][k]=state['losses_summary'].get(k,0)+v
        for k,v in source_counts.items():state['losses_summary'][k]-=v
    if state['sessions'] and not no_desktop:
        pending=(any(s.get('desktop_registry') for s in state['sessions']) if to=='claude'
                 else not state['desktop_project_registry'].get('registered'))
        if pending:
            add_next_steps(state,to,dest,[s['title'] for s in state['sessions']])
    state['status']='files-verified-native-resume-pending'; r.dump(dest/'.rehome/restore.json',state)
    print(json.dumps(state,ensure_ascii=False))
    return state
def main():
    configure()
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('pack'); p.add_argument('--from',dest='agent',choices=['claude','codex'],required=True);p.add_argument('--project',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--source-home',type=Path);p.add_argument('--sessions-json',type=Path,help='Explicit native project inventory with snapshot paths and titles')
    p.add_argument('--native',action='store_true');p.add_argument('--include-memory',action='store_true');p.add_argument('--include-checkpoints',action='store_true');p.add_argument('--source-desktop-registry')
    p.add_argument('--dry-run',action='store_true');p.add_argument('--allow-large',action='store_true',help='Deprecated compatibility flag')
    p.add_argument('--files',dest='files_mode',choices=['copy','reference'],default='copy')
    p.add_argument('--include-git',action='store_true')
    p.add_argument('--allow-secrets-in-config',action='store_true')
    p=sub.add_parser('restore');p.add_argument('package',type=Path);p.add_argument('--cwd',type=Path,required=True);p.add_argument('--to',choices=['claude','codex'],required=True);p.add_argument('--target-home',type=Path);p.add_argument('--no-desktop',action='store_true')
    p.add_argument('--native',action='store_true',help='Require the same-agent native route; otherwise inferred from package and target')
    p.add_argument('--model');p.add_argument('--claude-model');p.add_argument('--claude-version');p.add_argument('--desktop-registry')
    p.add_argument('--convert',action='store_true');p.add_argument('--dry-run',action='store_true');p.add_argument('--new-copy',action='store_true',help='Native Claude/Codex copy with a new owned session ID')
    p.add_argument('--fast-forward',action='store_true',help='Native Claude only: append prefix-compatible history into its original project')
    p.add_argument('--strict-files',action='store_true',help='Refuse differences in a reference project')
    p.add_argument('--claude-context-budget',type=int,default=r.DEFAULT_BUDGET)
    p.add_argument('--codex-context-budget',type=int,default=r.DEFAULT_BUDGET)
    a=ap.parse_args()
    if a.mode=='pack': pack(a.agent,a.project,a.out,a.source_home or Path.home()/('.claude' if a.agent=='claude' else '.codex'),json.loads(a.sessions_json.read_text(encoding='utf-8')) if a.sessions_json else None,a.native,a.include_memory,a.include_checkpoints,a.source_desktop_registry,dry_run=a.dry_run,allow_large=a.allow_large,allow_secrets_in_config=a.allow_secrets_in_config,files_mode=a.files_mode,include_git=a.include_git)
    else:
        if a.native and (a.convert or load_manifest(a.package).get('source_agent')!=a.to):raise ValueError('--native requires a same-agent package without --convert')
        restore(a.package,a.cwd,a.to,a.target_home,a.no_desktop,claude_context_budget=a.claude_context_budget,codex_context_budget=a.codex_context_budget,model=a.model,claude_model=a.claude_model,claude_version=a.claude_version,desktop_registry=a.desktop_registry,convert=a.convert,dry_run=a.dry_run,new_copy=a.new_copy,fast_forward=a.fast_forward,strict_files=a.strict_files)
if __name__=='__main__':
    import sys
    try:main()
    except (ValueError,KeyError,sqlite3.Error) as error:sys.exit(str(error))
