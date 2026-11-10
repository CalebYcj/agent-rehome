"""Project-owned configuration inventory and non-executing cross-agent bridges."""
import json,os,re
from pathlib import Path,PurePosixPath
from privacy_scan import PATTERNS
from project_io import CHUNK, chunks, linked
import codecs

FORBIDDEN={'settings.local.json','auth.json','.credentials.json','credentials.json','token.json','tokens.json','access_token','refresh_token'}
CACHE={'sessions','archived_sessions','cache','.cache','logs','node_modules','__pycache__'}


def excluded(path):
    return (any(part.lower() in FORBIDDEN|CACHE or part.lower().startswith('.env') for part in path.parts)
        or path.suffix.lower() in {'.key','.pem','.p12','.pfx','.sqlite','.sqlite3','.db','.log','.pyc'})


def inventory(project,agent,ordinary):
    """Only explicit project scopes; never inspect a user-level data home."""
    paths=[];skipped=[]
    for path in ordinary:
        rel=path.relative_to(project)
        if rel.parts[0]=='.agents' and excluded(rel):skipped.append({'path':rel.as_posix(),'reason':'excluded-cache-or-credential'})
        else:paths.append(path)
    scopes={'.claude':{'settings.json','skills','commands','agents'},'.codex':{'config.toml','config.json','settings.json'}}
    for folder,allowed in scopes.items():
        base=project/folder
        if not base.exists():continue
        if linked(base):skipped.append({'path':folder,'reason':'symlink-or-reparse-point'});continue
        for child in sorted(base.iterdir()):
            relative=child.relative_to(project)
            # Preserve only the source agent's project configuration. Claude skills
            # are also the source material for a cross-agent bridge.
            if (folder!=('.claude' if agent=='claude' else '.codex') and not (folder=='.claude' and child.name=='skills')) or child.name not in allowed or excluded(relative) or linked(child):
                skipped.append({'path':relative.as_posix(),'reason':'excluded-or-unknown-agent-entry'});continue
            candidates=[child]
            if child.is_dir():
                candidates=[]
                for directory,dirs,names in os.walk(child):
                    dirs[:]=[name for name in dirs if not linked(Path(directory)/name) and not excluded((Path(directory)/name).relative_to(project))]
                    candidates.extend(Path(directory)/name for name in names)
            for path in candidates:
                rel=path.relative_to(project)
                if linked(path) or excluded(rel):
                    skipped.append({'path':rel.as_posix(),'reason':'excluded-or-symlink'});continue
                if path.is_file():paths.append(path)
    return sorted(set(paths)),skipped


def config_path(relative):
    relative=relative.lower().removeprefix('.rehome/surroundings/originals/')
    return relative=='.mcp.json' or relative=='.claude/settings.json' or relative.startswith('.codex/')


def bridge_input(relative):
    return config_path(relative) or PurePosixPath(relative).name in ('AGENTS.md','CLAUDE.md') or relative.startswith(('.claude/skills/','.agents/skills/','.claude/commands/','.claude/agents/'))


def config_text(data):
    """Structured configuration is metadata, with a bounded parser budget."""
    limit=8*CHUNK
    if isinstance(data,Path):
        with data.open('rb') as stream:data=stream.read(limit+1)
    if len(data)>limit:raise ValueError('Project configuration exceeds the 8 MiB parser budget')
    return data.decode('utf-8-sig')


def payload_chunks(data):
    if isinstance(data,Path):yield from chunks(data)
    elif isinstance(data,tuple):
        prefix,path=data
        yield prefix
        yield from chunks(path,skip_bom=True)
    else:
        for start in range(0,len(data),CHUNK):yield data[start:start+CHUNK]


def rule_references(data):
    if isinstance(data,bytes):
        yield from re.findall(r'(?<![\w@])@([^\s<>]+)',data.decode('utf-8-sig'))
        return
    # Keep a bounded tail for references split across blocks. Oversized tokens
    # are not useful file references and are omitted from the advisory report.
    decoder=codecs.getincrementaldecoder('utf-8-sig')()
    pending=''
    pattern=re.compile(r'(?<![\w@])@([^\s<>]{1,4096})(?=[\s<>]|$)')
    for block in chunks(data):
        text=pending+decoder.decode(block)
        cutoff=max(0,len(text)-4097)
        for match in pattern.finditer(text):
            if match.start()<cutoff:yield match.group(1)
        pending=text[cutoff:]
    yield from pattern.findall(pending+decoder.decode(b'',final=True))


def secret_preflight(project,paths,allow=False):
    hits=[]
    for path in paths:
        rel=path.relative_to(project).as_posix()
        if not config_path(rel):continue
        try:text=config_text(path)
        except UnicodeError:raise ValueError('Configuration must be UTF-8: '+rel)
        if PATTERNS['credential'].search(text):hits.append(rel)
    if hits and not allow:raise ValueError('Possible secret in project configuration: '+', '.join(hits)+'; clean it or explicitly pass --allow-secrets-in-config')
    return hits


def bridges(payload,source,target,inventory_skips=(),secrets=(),directories=()):
    """Pure preflight: return new relative-path bytes and a report, without overwrites."""
    files=dict(payload);report={'generated':[],'skipped':list(inventory_skips),'manual':[],
        'references':[],'mcp_servers':[],'config_secret_overrides':list(secrets),
        'user_level':'Project packages do not carry user-level rules, skills or plugins. Batch moves carry the global rules and user-level Skills separately (global_rules.py, user_skills.py); plugins are not collected.',
        'warnings':[]};cross=source in ('claude','codex') and source!=target
    report['directories']=list(directories)
    report['manual'].extend({'path':item['path'],'reason':'source-hook-scripts-not-enabled'} for item in inventory_skips if PurePosixPath(item['path']).name=='hooks')
    def add(path,data,reason):
        if path in files:report['skipped'].append({'path':path,'reason':'target-exists'});return
        files[path]=data;report['generated'].append({'path':path,'reason':reason})
    for path,data in list(payload.items()):
        if path.startswith('.rehome/surroundings/originals/'):continue
        rel=PurePosixPath(path)
        if cross and rel.name==('AGENTS.md' if source=='codex' else 'CLAUDE.md'):
            dest=str(rel.with_name('CLAUDE.md' if target=='claude' else 'AGENTS.md'))
            if dest in files:report['skipped'].append({'path':dest,'reason':'target-exists'})
            else:
                prefix='<!-- 由 agent-rehome 根据 CLAUDE.md 生成 -->\n\n'.encode('utf-8')
                content=b'@AGENTS.md\n' if target=='claude' else ((prefix,data) if isinstance(data,Path) else prefix+data.decode('utf-8-sig').encode('utf-8'))
                add(dest,content,'rule-bridge')
            if source=='claude':
                for reference in rule_references(data):
                    if len(report['references'])<1024:report['references'].append({'path':path,'reference':reference})
                    elif 'Rule reference report limited to 1024 entries.' not in report['warnings']:
                        report['warnings'].append('Rule reference report limited to 1024 entries.')
        if path.lower()=='.mcp.json':
            original='.rehome/surroundings/originals/.mcp.json'
            if original in files:raise ValueError('Configuration original archive collision')
            add(original,data,'preserve-inactive-mcp-config');files.pop(path)
            report['manual'].append({'path':path,'reason':'mcp-config-quarantined','original':original,'enable':'After explicit review/approval, copy the archived original to the project root .mcp.json. Restore never enables it.'})
            try:servers=json.loads(config_text(data)).get('mcpServers',{})
            except (ValueError,AttributeError):report['manual'].append({'path':path,'reason':'invalid-mcp-config'});continue
            if not isinstance(servers,dict):report['manual'].append({'path':path,'reason':'invalid-mcp-servers'});continue
            for name,settings in servers.items():
                if not isinstance(settings,dict):continue
                redact=lambda value:PATTERNS['credential'].sub('[REDACTED]',str(value))
                args=settings.get('args',[])
                report['mcp_servers'].append({'name':name,'command':redact(settings.get('command','')),'args':[redact(arg) for arg in args if isinstance(arg,str)] if isinstance(args,list) else []})
            report['manual'].append({'path':path,'reason':'review-server-commands-and-destination-approval; not launched by restore'})
        if path.lower()=='.claude/settings.json':
            try:settings=json.loads(config_text(data))
            except ValueError:settings=None
            if not isinstance(settings,dict):
                raise ValueError('Invalid project .claude/settings.json')
            inactive={key:settings[key] for key in ('hooks','permissions','allowedTools','enabledPlugins','enableAllProjectMcpServers','enabledMcpjsonServers','mcpServers','statusLine','apiKeyHelper','awsAuthRefresh','awsCredentialExport') if key in settings}
            if inactive:
                original='.rehome/surroundings/originals/'+path
                if original in files:raise ValueError('Configuration original archive collision')
                add(original,data,'preserve-inactive-settings-original')
                files[path]=(json.dumps({key:value for key,value in settings.items() if key not in inactive},ensure_ascii=False,indent=2)+'\n').encode('utf-8')
                report['manual'].append({'path':path,'reason':'hooks-and-source-permissions-disabled','fields':list(inactive),'original':original})
        if path.lower().startswith('.codex/') and config_path(path):
            # Do not enable source MCP/hooks/permissions through a copied runtime config.
            text=config_text(data)
            if re.search(r'(?im)(?:hooks|mcp_servers|mcpServers|approval_policy|sandbox_mode|sandbox_workspace_write|permissions|command|notify|shell_environment_policy)\b',text):
                original='.rehome/surroundings/originals/'+path
                if original in files:raise ValueError('Configuration original archive collision')
                add(original,data,'preserve-inactive-codex-config');files.pop(path)
                report['manual'].append({'path':path,'reason':'executable-or-permission-config-quarantined','original':original})
        if cross and (path.startswith('.claude/commands/') or path.startswith('.claude/agents/')):
            report['manual'].append({'path':path,'reason':'source-command-or-agent-definition-not-converted'})
    if cross:
        source_prefix='.claude/skills/' if source=='claude' else '.agents/skills/'
        target_prefix='.agents/skills/' if target=='codex' else '.claude/skills/'
        names=sorted({path[len(source_prefix):].split('/')[0] for path in [*payload,*directories] if path.startswith(source_prefix) and path[len(source_prefix):]})
        for name in names:
            dest=target_prefix+name
            if dest in directories or any(path==dest or path.startswith(dest+'/') for path in files):
                report['skipped'].append({'path':dest,'reason':'target-skill-exists'});continue
            for path,data in payload.items():
                if path.startswith(source_prefix+name+'/'):add(target_prefix+path[len(source_prefix):],data,'skill-bridge')
            report['directories'].extend(target_prefix+path[len(source_prefix):] for path in directories if path==source_prefix+name or path.startswith(source_prefix+name+'/'))
        if names:report['warnings'].append('Skill bytes are unchanged; tool names and runtime requirements may differ between agents.')
    return files,report
