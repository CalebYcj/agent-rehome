"""Claude-to-Claude relocation: preserve native bytes except top-level cwd values."""
import argparse, datetime as dt, hashlib, json, ntpath, posixpath, re, unicodedata, uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from platform_paths import windows_path
from privacy_scan import PATTERNS
from cli_output import print

SCHEMA='claude-native/v1'
FORBIDDEN_FILES={'.claude.json','auth.json','credentials.json','.env'}
FORBIDDEN_KEYS={'hasTrustDialogAccepted','access_token','refresh_token','api_key','oauthAccount','allowedTools','permissions'}


def sha(data): return hashlib.sha256(data).hexdigest()


def history_file(scope,relative):
    return scope=='project' and not relative.startswith('memory/') and PurePosixPath(relative).suffix=='.jsonl'


def binary_allowed(scope,relative,sid):
    return (scope=='project' and relative.startswith(sid+'/')) or (scope=='file-history' and relative.startswith(sid+'/'))


def fallback_title(text):
    """Keep a readable user-text prefix without exposing a partial filesystem path."""
    def clean(value):
        value=value.rstrip()
        while value and (value[-1].isspace() or unicodedata.category(value[-1]).startswith('P')):value=value[:-1]
        return value
    # Drop whole URL tokens before looking for filesystem paths, including one-letter schemes.
    text=re.sub(r'(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]*://\S+','',text).strip()
    path=re.search(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/]|(?<!\S)/(?=\S)',text)
    if path:
        prefix=clean(text[:path.start()])
        if prefix:text=prefix
        else:
            tail=text[path.start():].rstrip('\\/')
            tail=re.sub(r'^[A-Za-z]:','',tail)
            text=re.split(r'[\\/]',tail)[-1]
    if len(text)>60:
        prefix=text[:60]
        spaces=list(re.finditer(r'\s+',prefix))
        text=prefix[:spaces[-1].start()] if spaces else prefix
    return clean(text) or '未命名会话'


def safe(root,relative):
    q=PurePosixPath(relative)
    if not q.parts or q.is_absolute() or '..' in q.parts or '\\' in relative or ':' in relative:
        raise ValueError('Unsafe native package path')
    path=Path(root).joinpath(*q.parts)
    cursor=Path(root)
    if cursor.is_symlink():raise ValueError('Native root symlink refused')
    for part in q.parts:
        cursor=cursor/part
        if cursor.is_symlink():raise ValueError('Native payload symlink refused')
    if not path.resolve().is_relative_to(Path(root).resolve()): raise ValueError('Native path escapes its root')
    return path


def check_payload(data,name,jsonl=False,allow_binary=False):
    """Return binary status; opaque bytes are allowed only in selected owned sidecars."""
    if Path(name).name.lower() in FORBIDDEN_FILES: raise ValueError('Credential/configuration files cannot be migrated')
    try: text=data.decode('utf-8-sig')
    except UnicodeError:
        if jsonl:raise ValueError('Native JSONL must use valid UTF-8')
        if not allow_binary:raise ValueError('Native binary payload outside session-owned sidecars/checkpoints refused')
        return True
    if PATTERNS['credential'].search(text): raise ValueError('Possible credential in native payload; relocation stopped without editing content')
    if jsonl:
        for line in text.split('\n'):
            if not line.strip(): continue
            row=json.loads(line)
            if not isinstance(row,dict): raise ValueError('Native JSONL records must be objects')
            if FORBIDDEN_KEYS.intersection(row): raise ValueError('Active trust/credential/permission metadata cannot be migrated')
    return False


def validate_binary(item,data,sid):
    binary=check_payload(data,item['relative'],item['jsonl'],binary_allowed(item['scope'],item['relative'],sid))
    marker=item.get('binary',False)  # Existing all-text manifests predate this field.
    if type(marker) is not bool or marker!=binary:raise ValueError('Native binary marker does not match payload')
    return binary


def relocate_cwd(value,old_root,new_root):
    """Pure path mapping; None means outside the source root, with no filesystem lookup."""
    if not value or not old_root:return None
    windows=windows_path(old_root)
    if windows_path(value)!=windows:return None
    def parts(path):
        if windows:
            if path.startswith('\\\\?\\UNC\\'):path='\\\\'+path[8:]
            elif path.startswith('\\\\?\\'):path=path[4:]
            return PureWindowsPath(ntpath.normpath(path)).parts
        return PurePosixPath(posixpath.normpath(path)).parts
    base=parts(old_root);current=parts(value)
    if not base and current:return None
    key=lambda sequence:tuple(part.lower() for part in sequence) if windows else sequence
    if len(current)<len(base) or key(current[:len(base)])!=key(base):return None
    tail=current[len(base):]
    separator='\\' if windows_path(new_root) else '/'
    target=(ntpath if windows_path(new_root) else posixpath).normpath(new_root)
    return target.rstrip(separator)+separator+separator.join(tail) if tail else target


def source_roots(source):
    root=source.get('cwd');aliases=source.get('cwd_aliases',[])
    if not isinstance(root,str):raise ValueError('Native manifest source.cwd must be a string; source root is not inferred')
    if not isinstance(aliases,list) or any(not isinstance(alias,str) or not alias for alias in aliases):raise ValueError('Native source.cwd_aliases must be a list of nonempty strings')
    return root,aliases


def rewrite_cwd(data,old_root,new_root,stats=None,aliases=()):
    """Replace only lexical spans of top-level cwd strings, retaining CRLF/BOM/spacing."""
    if not isinstance(old_root,str) or not isinstance(new_root,str) or not new_root:raise ValueError('Native relocation requires explicit source and target roots')
    if not isinstance(aliases,(list,tuple)) or any(not isinstance(alias,str) or not alias for alias in aliases):raise ValueError('Invalid native cwd aliases')
    roots=sorted(set([old_root,*aliases]),key=len,reverse=True)  # Prefer the more specific declared root if aliases overlap.
    if stats is not None:
        stats.setdefault('outside_rows',0);stats.setdefault('outside_values',set())
    bom=b'\xef\xbb\xbf' if data.startswith(b'\xef\xbb\xbf') else b''
    text=data[len(bom):].decode('utf-8');decoder=json.JSONDecoder();output=[]
    for line in text.split('\n'):
        if not line.strip(): output.append(line);continue
        obj=json.loads(line)
        if not isinstance(obj,dict): raise ValueError('Native JSONL record is not an object')
        pos=line.index('{')+1;spans=[];keys=set()
        while True:
            while pos<len(line) and (line[pos].isspace() or line[pos]==','): pos+=1
            if line[pos]=='}': break
            key,end=decoder.raw_decode(line,pos)
            if key in keys: raise ValueError('Duplicate top-level metadata key')
            keys.add(key);pos=end
            while line[pos].isspace(): pos+=1
            if line[pos]!=':': raise ValueError('Invalid JSON member')
            pos+=1
            while line[pos].isspace(): pos+=1
            value,end=decoder.raw_decode(line,pos)
            if key=='cwd':
                if not isinstance(value,str): raise ValueError('Native cwd metadata must be a string')
                mapped=next((mapped for root in roots if (mapped:=relocate_cwd(value,root,new_root)) is not None),None)
                if mapped is not None:
                    if mapped!=value:spans.append((pos,end,mapped))
                elif value and stats is not None:
                    stats['outside_rows']+=1;stats['outside_values'].add(value)
            pos=end
        for start,end,mapped in reversed(spans): line=line[:start]+json.dumps(mapped,ensure_ascii=False)+line[end:]
        output.append(line)
    return bom+'\n'.join(output).encode('utf-8')


def snapshot(source,home,include_memory=False,include_checkpoints=False,source_registry=None):
    source=Path(source);home=Path(home);sid=source.stem;uuid.UUID(sid)
    if source.is_symlink(): raise ValueError('Native session symlink refused')
    entries=[]
    def add(path,scope,relative):
        if path.is_symlink(): raise ValueError('Native payload symlink refused')
        data=path.read_bytes();is_jsonl=history_file(scope,relative)
        binary=check_payload(data,path.name,is_jsonl,binary_allowed(scope,relative,sid))
        entries.append({'scope':scope,'relative':relative,'data':data,'sha256':sha(data),'jsonl':is_jsonl,'binary':binary})
    def tree(directory,scope,prefix):
        if directory.is_symlink(): raise ValueError('Native source directory symlink refused')
        if not directory.exists(): return
        for path in sorted(directory.rglob('*')):
            if path.is_symlink(): raise ValueError('Native source symlink refused')
            if path.is_file(): add(path,scope,(PurePosixPath(prefix)/path.relative_to(directory).as_posix()).as_posix())
    add(source,'project',sid+'.jsonl')
    tree(source.with_suffix(''),'project',sid)
    if include_memory: tree(source.parent/'memory','project','memory')
    if include_checkpoints: tree(home/'file-history'/sid,'file-history',sid)
    rows=[json.loads(x) for x in entries[0]['data'].decode('utf-8-sig').split('\n') if x.strip()]
    if any(r.get('sessionId') not in (None,sid) for r in rows): raise ValueError('Native session ID disagrees with filename')
    title=next((r.get('customTitle') for r in reversed(rows) if r.get('type')=='custom-title'),None)
    if not title:
        # Sidebar fallback mirrors the conversion export: first visible user text, never the raw session ID.
        first=next((c if isinstance(c,str) else '\n'.join(x.get('text','') for x in c if isinstance(x,dict) and x.get('type')=='text')
            for r in rows if r.get('type')=='user' and not r.get('isMeta') and not r.get('isSidechain') and not r.get('isCompactSummary')
            for c in [r.get('message',{}).get('content')] if (isinstance(c,str) and c.strip() and not c.lstrip().startswith('<'))
            or (isinstance(c,list) and any(isinstance(x,dict) and x.get('type')=='text' and x.get('text','').strip() for x in c))),'')
        title=fallback_title(first)
    version=next((r.get('version') for r in reversed(rows) if r.get('version')),None)
    model=next((r.get('message',{}).get('model') for r in reversed(rows) if r.get('message',{}).get('model')),None)
    template={}
    if not source_registry and home.resolve()==(Path.home()/'.claude').resolve():
        import agent_rehome as r
        source_registry=r.desktop_registry_dir(argparse.Namespace(target_home=None,no_desktop=False,desktop_registry=None))
    if source_registry:
        hits=[]
        for path in Path(source_registry).glob('local_*.json'):
            record=json.loads(path.read_text(encoding='utf-8'))
            if record.get('cliSessionId')==sid: hits.append(record)
        if len(hits)>1: raise ValueError('Ambiguous source desktop registration')
        if hits: template={k:hits[0][k] for k in ('title','model','effort','permissionMode') if k in hits[0]}
    return {'schema':SCHEMA,'source':{'agent':'claude','session_id':sid,'cwd':next((r['cwd'] for r in rows if r.get('cwd')),''),'version':version},
        'title':template.get('title') or title or sid,'model':template.get('model') or model,'registry_template':template,
        'turns':sum(r.get('type')=='user' and not r.get('isMeta') and not r.get('isCompactSummary') and
            (isinstance(r.get('message',{}).get('content'),str) or any(x.get('type')=='text' for x in r.get('message',{}).get('content',[]) if isinstance(x,dict))) for r in rows),
        'files':entries}


def pack(snap,directory):
    directory=Path(directory)
    if directory.exists(): raise ValueError('Native package directory must be new')
    records=[]
    for item in snap['files']:
        records.append({k:v for k,v in item.items() if k!='data'}|{'path':f"raw/{item['scope']}/{item['relative']}"})
    directory.mkdir(parents=True)
    for item,record in zip(snap['files'],records):
        path=safe(directory,record['path']);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(item['data'])
    manifest={k:v for k,v in snap.items() if k!='files'}|{'files':records}
    (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest


def load(directory):
    directory=Path(directory);manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema')!=SCHEMA: raise ValueError('Unsupported native Claude package')
    source_roots(manifest['source'])
    uuid.UUID(manifest['source']['session_id']);entries=[]
    for record in manifest['files']:
        if record['scope'] not in ('project','file-history'): raise ValueError('Unknown native file scope')
        if record['jsonl']!=history_file(record['scope'],record['relative']): raise ValueError('Native JSONL type mismatch')
        data=safe(directory,record['path']).read_bytes()
        if sha(data)!=record['sha256']: raise ValueError('Native package hash mismatch')
        safe(directory,record['relative']);binary=validate_binary(record,data,manifest['source']['session_id'])
        entries.append(dict(record,data=data,binary=binary))
    return dict(manifest,files=entries)


def copied_id(snap,cwd):
    old=snap['source']['session_id']
    digest=next((item['sha256'] for item in snap['files'] if item['scope']=='project' and item['relative']==old+'.jsonl'),None)
    if digest is None:raise ValueError('Native main session file missing')
    return str(uuid.uuid5(uuid.UUID('6f1c2a9e-4b7d-4c1e-9a3f-c1a0dec0de01'),'claude-native-copy/'+old+'/'+cwd+'/'+digest))


def rewrite_session_id(data,old,new):
    """Only structured sessionId string values; message strings and other IDs stay byte-identical."""
    decoder=json.JSONDecoder();bom=b'\xef\xbb\xbf' if data.startswith(b'\xef\xbb\xbf') else b'';output=[]
    for line in data[len(bom):].decode('utf-8').split('\n'):
        spans=[]
        def walk(pos):
            while line[pos].isspace():pos+=1
            if line[pos] not in '{[':return decoder.raw_decode(line,pos)[1]
            obj=line[pos]=='{';endchar='}' if obj else ']';pos+=1;keys=set()
            while True:
                while line[pos].isspace() or line[pos]==',':pos+=1
                if line[pos]==endchar:return pos+1
                key=None
                if obj:
                    key,pos=decoder.raw_decode(line,pos)
                    if key in keys:raise ValueError('Duplicate structured metadata key')
                    keys.add(key)
                    while line[pos].isspace():pos+=1
                    if line[pos]!=':':raise ValueError('Invalid JSON member')
                    pos+=1
                    while line[pos].isspace():pos+=1
                value,end=decoder.raw_decode(line,pos)
                if key=='sessionId' and value==old:spans.append((pos,end))
                walk(pos);pos=end
        if line.strip():walk(0)
        for start,end in reversed(sorted(spans)):line=line[:start]+json.dumps(new)+line[end:]
        output.append(line)
    return bom+'\n'.join(output).encode('utf-8')


def payload_writes(snap,home,cwd,sid,project,cwd_stats=None):
    old_sid=snap['source']['session_id'];old_root,aliases=source_roots(snap['source']);writes=[]
    for item in snap['files']:
        relative=item['relative']
        if item['scope'] not in ('project','file-history') or item['jsonl']!=history_file(item['scope'],relative):raise ValueError('Invalid native file type/scope')
        allowed=(relative==old_sid+'.jsonl' or relative.startswith(old_sid+'/') or relative.startswith('memory/')) if item['scope']=='project' else relative.startswith(old_sid+'/')
        if not allowed:raise ValueError('Native file is not owned by the selected session/project memory')
        base=project if item['scope']=='project' else home/'file-history'
        if not base.resolve().is_relative_to(home):raise ValueError('Native target link escapes data home')
        mapped=sid+relative[len(old_sid):] if relative==old_sid+'.jsonl' or relative.startswith(old_sid+'/') else relative
        target=safe(base,mapped)
        if any(parent.exists() and not parent.is_dir() for parent in target.parents):raise ValueError('Native destination parent is a file')
        if sha(item['data'])!=item['sha256']:raise ValueError('Native payload changed after snapshot')
        validate_binary(item,item['data'],old_sid)
        if item['scope']=='project' and relative==old_sid+'.jsonl':
            rows=[json.loads(line) for line in item['data'].decode('utf-8-sig').split('\n') if line.strip()]
            if any(row.get('sessionId') not in (None,old_sid) for row in rows):raise ValueError('Native root session identity mismatch')
        data=rewrite_cwd(item['data'],old_root,cwd,stats=cwd_stats,aliases=aliases) if item['jsonl'] else item['data']
        if sid!=old_sid and item['jsonl']:data=rewrite_session_id(data,old_sid,sid)
        writes.append((target,data))
    if sum(item['scope']=='project' and item['relative']==old_sid+'.jsonl' for item in snap['files'])!=1:raise ValueError('Native main session file missing or duplicated')
    if len({str(path.resolve()) for path,_ in writes})!=len(writes):raise ValueError('Duplicate native destination paths')
    return writes


COPY_TITLE_SUFFIX = r'(?: · (?:迁移副本|项目迁移测试|新副本(?: \[.*?\])?))+$'


def has_copy_title(title):
    return isinstance(title,str) and bool(re.search(r' · 新副本 \[.*?\]$',title))


def copy_title(title,cwd):
    base=re.sub(COPY_TITLE_SUFFIX,'',(title or '').strip())
    return f'{base} · 新副本 [{Path(cwd).name}]' if base else ''


def plan(snap,a,cwd_stats=None):
    import agent_rehome as r
    if getattr(a,'fast_forward',False):
        import claude_fast_forward
        return claude_fast_forward.plan(snap,a)[0]
    if a.to!='claude': raise ValueError('Native Claude packages are for Claude targets only')
    sid=snap['source']['session_id'];uuid.UUID(sid)
    old_root,aliases=source_roots(snap['source'])
    home=Path(a.target_home or Path.home()/'.claude').resolve();cwd=str(Path(a.cwd).resolve())
    if getattr(a,'new_copy',False):sid=copied_id(snap,cwd)
    if not Path(cwd).is_dir() and not getattr(a,'allow_new_project',False): raise ValueError('Target project directory must exist')
    hits=list((home/'projects').glob('*/'+sid+'.jsonl')) or list((home/'projects').glob('*/'+sid))
    if hits:
        raise ValueError(f'Target session ID already exists: {sid}; project directory: {hits[0].parent}. Refusing native overwrite. Use --new-copy for a separate session or --fast-forward only for an unchanged-prefix return.')
    encoded=re.sub(r'[^a-zA-Z0-9_-]','-',cwd);project=home/'projects'/encoded
    if not project.resolve().is_relative_to(home): raise ValueError('Target project link escapes data home')
    writes=payload_writes(snap,home,cwd,sid,project,cwd_stats)
    title=snap['title']
    if getattr(a,'new_copy',False):
        title=copy_title(title,cwd)
        if title:
            main=project/(sid+'.jsonl')
            record=json.dumps({'type':'custom-title','sessionId':sid,'customTitle':title},ensure_ascii=False).encode('utf-8')
            writes=[(path,data+(b'' if data.endswith(b'\n') else b'\n')+record+b'\n') if path==main else (path,data)
                    for path,data in writes]
    if any(target.exists() for target,_ in writes):raise ValueError('Native destination or memory file already exists; refusing overwrite')
    registry=r.desktop_registry_dir(a);registration=None
    if registry:
        for path in registry.glob('local_*.json'):
            if json.loads(path.read_text(encoding='utf-8')).get('cliSessionId')==sid: raise ValueError('Target desktop session ID already exists')
        b={'title':title,'turns':[None]*snap['turns']};probe=argparse.Namespace(**vars(a));probe.dry_run=True
        registration=Path(r.register_desktop(b,probe,sid,cwd))
        if registration.exists(): raise ValueError('Target native desktop registration exists')
        local=registration.stem;ms=int(dt.datetime.now().timestamp()*1000)
        rec={'sessionId':local,'cliSessionId':sid,'cwd':cwd,'originCwd':cwd,'gitAnchorsFolderRealpath':cwd,
            'title':title,'titleSource':'user','permissionMode':'default','createdAt':ms,'lastActivityAt':ms,'lastTurnEdgeAt':ms,
            'completedTurns':snap['turns'],'isArchived':False}
        template=snap.get('registry_template') or {}
        for k in ('model','effort'):
            value=template.get(k) or (snap.get('model') if k=='model' else None)
            if value:rec[k]=value
        if not rec.get('model'):
            value=r.desktop_model(a)
            if value:rec['model']=value
        writes.append((registration,json.dumps(rec,ensure_ascii=False,indent=2).encode('utf-8')))
    paths=[str(path.resolve()) for path,_ in writes]
    if len(paths)!=len(set(paths)): raise ValueError('Duplicate native destination paths')
    return home,cwd,writes,registration


def restore(snap,a):
    import agent_rehome as r
    if getattr(a,'fast_forward',False):
        import claude_fast_forward
        return claude_fast_forward.restore(snap,a)
    cwd_stats={}
    home,cwd,writes,registration=plan(snap,a,cwd_stats=cwd_stats);sid=copied_id(snap,cwd) if getattr(a,'new_copy',False) else snap['source']['session_id']
    binaries=[item for item in snap['files'] if item.get('binary',False)]
    binary_bytes=sum(len(item['data']) for item in binaries)
    result={'mode':'claude-native','status':'preview' if a.dry_run else 'written','id':sid,'cwd':cwd,'files':len(writes),
        'source_version':snap['source'].get('version'),'desktop_registry':str(registration) if registration else None,
        'context':'unchanged-native-history; no new summary or compaction','losses_summary':{},'binary_files':len(binaries),'binary_bytes':binary_bytes,
        'outside_cwd_rows':cwd_stats.get('outside_rows',0),'outside_cwd_values':len(cwd_stats.get('outside_values',set())),
        'warnings':['Private native history; credential preflight is conservative, not exhaustive.',
            'Source permission/trust is not activated; target desktop permissionMode is default.']}
    result['warnings'].append('Historical absolute paths, including old tool-results image references, are unchanged; copied sidecars may not open through those source paths.')
    if binaries:result['warnings'].append(f'Binary sidecars/checkpoints: {len(binaries)} files, {binary_bytes} bytes; binary contents do not receive credential regex scanning.')
    if result['outside_cwd_rows']:result['warnings'].append(f"Preserved out-of-project cwd: {result['outside_cwd_rows']} rows, {result['outside_cwd_values']} distinct values; source paths are not listed.")
    if not registration and not getattr(a,'no_desktop',False):result['warnings'].append('Desktop registration unavailable; native sidebar loading remains unverified.')
    if a.dry_run: print(json.dumps(result,ensure_ascii=False));return result
    backup=home/'rehome-backups'/('claude-native-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    before={str(path):{'existed':False,'backup':None} for path,_ in writes}
    r.dump(backup/'backup.json',before)
    for path,data in writes:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(data)
    r.dump(backup/'native-result.json',{**result,'output_hashes':{str(path):sha(data) for path,data in writes}})
    result['backup']=str(backup)
    if registration and not getattr(a,'project_restore',False):
        from user_next_steps import add_next_steps
        add_next_steps(result,'claude',cwd,[copy_title(snap['title'],cwd) if getattr(a,'new_copy',False) else snap['title']])
    print(json.dumps(result,ensure_ascii=False));return result
