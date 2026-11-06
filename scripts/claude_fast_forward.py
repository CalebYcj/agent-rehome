"""Append-only Claude return. No merge, shared-line rewrite, or wholesale rollback."""
import datetime as dt, json, os, re, stat, subprocess, uuid
from pathlib import Path
from collections import Counter
import claude_native as n
from cli_output import print
from user_next_steps import FAST_FORWARD_AFTERCARE

UUID_TOKEN = r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}'
RESUME = r"""(?:^|\s)"?--(?:resume|session-id)"?(?:=|[ \t]+)["']?(""" + UUID_TOKEN + r""")["']?(?=\s|$)"""

SHORT_RESUME = r"""(?:^|\s)"?-r"?(?:=|[ \t]+)["']?(""" + UUID_TOKEN + r""")["']?(?=\s|$)"""
CLAUDE_MARKER = r'(?i)claude'


def command_sessions(command):
    yield from re.findall(RESUME,command)
    for match in re.finditer(SHORT_RESUME,command):
        if re.search(CLAUDE_MARKER,command[:match.start()]):
            yield match.group(1)


def process_rows():
    """Return only PIDs, matched session IDs and incomplete inspection markers."""
    def run(command):
        return subprocess.run(command, capture_output=True, check=True, timeout=8,
                              encoding='utf-8', errors='replace').stdout

    if os.name == 'nt':
        script = r"""
$ErrorActionPreference = 'Stop'
$pattern = '__RESUME__'
$short = '__SHORT__'
$claude = '__CLAUDE_MARKER__'
Get-CimInstance Win32_Process | ForEach-Object {
  $processId = $_.ProcessId
  "process " + $processId
  if ($_.CommandLine) {
    foreach ($match in [regex]::Matches($_.CommandLine, $pattern)) {
      "process " + $processId + " " + $match.Groups[1].Value
    }
    foreach ($match in [regex]::Matches($_.CommandLine, $short)) {
      if ([regex]::IsMatch($_.CommandLine.Substring(0, $match.Index), $claude)) {
        "process " + $processId + " " + $match.Groups[1].Value
      }
    }
  } elseif ($_.Name -in @('claude.exe','node.exe')) {
    "unavailable " + $processId
  }
}
""".replace('__RESUME__', RESUME.replace("'", "''")).replace('__SHORT__', SHORT_RESUME.replace("'", "''")).replace('__CLAUDE_MARKER__', CLAUDE_MARKER.replace("'", "''"))
        rows = [line.split() for line in run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script]).splitlines()
                if line.strip()]
        if not rows or any(len(row) not in (2,3) for row in rows):
            raise ValueError('Unexpected process metadata')
        return [(row[0],int(row[1]),row[2] if len(row)==3 else None) for row in rows]

    rows = []
    for line in run(['ps','-axww','-o','pid=','-o','args=']).splitlines():
        fields = line.split(maxsplit=1)
        if not fields:
            continue
        pid = int(fields[0])
        rows.append(('process',pid,None))
        if len(fields)==2:
            rows.extend(('process',pid,sid) for sid in command_sessions(fields[1]))
        else:
            rows.append(('unavailable',pid,None))
    if not rows:
        raise ValueError('Empty process listing')
    return rows


def session_file_matches(home, sid, alive):
    directory = home/'sessions'
    matched = set()
    unavailable = False
    try:
        directory_stat=directory.lstat()
    except FileNotFoundError:
        return matched, unavailable
    if not stat.S_ISDIR(directory_stat.st_mode) or getattr(directory_stat,'st_file_attributes',0)&1024:
        raise ValueError('Unsafe session process directory')
    for path in directory.iterdir():
        if not re.fullmatch('[0-9]+[.]json',path.name):
            continue
        try:
            info=path.lstat()
            if not stat.S_ISREG(info.st_mode) or getattr(info,'st_file_attributes',0)&1024:
                raise ValueError('Unsafe session process record')
            with path.open('rb') as stream:
                opened=os.fstat(stream.fileno())
                if (opened.st_dev,opened.st_ino)!=(info.st_dev,info.st_ino):
                    raise ValueError('Session process record changed before read')
                data=stream.read(65537)
            if len(data)>65536:
                raise ValueError('Session process record exceeds size limit')
            record=json.loads(data)
            if (not isinstance(record,dict) or type(record.get('pid')) is not int
                    or record['pid']<=0 or record['pid']!=int(path.stem)
                    or not isinstance(record.get('sessionId'),str)):
                raise ValueError('Invalid session process record')
            if str(uuid.UUID(record['sessionId']))==sid.lower() and record['pid'] in alive:
                matched.add(record['pid'])
        except (OSError, ValueError):
            unavailable = True
    return matched, unavailable


def live_process_check(home, sid, dry_run):
    try:
        rows = process_rows()
        active = {pid for _,pid,session in rows if session and session.lower()==sid.lower()}
        alive = {pid for _,pid,_ in rows}
        unavailable = any(kind=='unavailable' for kind,_,_ in rows)
    except (OSError, ValueError, subprocess.SubprocessError):
        active,alive,unavailable=set(),set(),True
    sources = ['command_line'] if active else []
    try:
        recorded, partial = session_file_matches(home,sid,alive)
        unavailable |= partial
        if recorded:
            active.update(recorded)
            sources.append('session_file')
    except (OSError, ValueError):
        unavailable = True
    if active:
        warning=f'有 {len(active)} 个进程正在运行这条会话。请先在应用里停止该会话或重启应用，再重新预演。重启后仍需重新检测。'
        print(json.dumps({'status':'blocked','live_process_check':'active','live_process_sources':sources,'warnings':[warning]},ensure_ascii=False))
        raise ValueError(warning)
    if unavailable and not dry_run:
        warning='无法检测目标会话的运行进程，快进写入已停止。请确认进程检测可用后重新预演。'
        print(json.dumps({'status':'blocked','live_process_check':'unavailable','live_process_sources':sources,'warnings':[warning]},ensure_ascii=False))
        raise ValueError(warning)
    return ('unavailable' if unavailable else 'clear'),sources


def records(data):
    offset=0;result=[]
    for line in data.split(b'\n'):
        length=len(line)+1
        clean=line.removeprefix(b'\xef\xbb\xbf') if offset==0 else line
        if clean.strip():result.append((offset,json.loads(clean)))
        offset+=length
    return result

MAINTENANCE = {'tools-used', 'last-prompt', 'cost-state'}


def maintenance(row):
    return 'uuid' not in row and (row.get('type') in MAINTENANCE or
                                  row.keys() == {'type', 'sessionId', 'customTitle'} and
                                  row['type'] == 'custom-title' and n.has_copy_title(row['customTitle']) or
                                  row.get('type') == 'mode' and row.keys() == {'type', 'mode', 'sessionId'})


def append_start(existing, incoming):
    """Match the common history while allowing either app's independent maintenance."""
    comparable = lambda row: {key:value for key,value in row.items() if key!='cwd'}
    local = remote = 0
    skipped = Counter()
    while local < len(existing):
        before = existing[local][1]
        after = incoming[remote][1] if remote < len(incoming) else None
        if after is not None and comparable(before)==comparable(after):
            local += 1
            remote += 1
        elif maintenance(before):
            skipped[before['type']] += 1
            local += 1
        elif after is not None and maintenance(after):
            remote += 1
        else:
            return None, skipped
    return remote, skipped


def plan(snap,a):
    import agent_rehome as r
    if a.to!='claude':raise ValueError('--fast-forward is only for native Claude history')
    if getattr(a,'new_copy',False):raise ValueError('--new-copy and --fast-forward are mutually exclusive')
    home=Path(a.target_home or Path.home()/'.claude').resolve();sid=snap['source']['session_id']
    uuid.UUID(sid)
    live,sources=live_process_check(home,sid,a.dry_run)
    hits=list((home/'projects').glob('*/'+sid+'.jsonl'))
    if len(hits)!=1:raise ValueError(f'Fast-forward needs exactly one existing session {sid}; found {len(hits)}. Use --new-copy for a separate session.')
    main=n.safe(home,hits[0].relative_to(home).as_posix());old=main.read_bytes();existing=records(old)
    cwd=next((row['cwd'] for _,row in existing if isinstance(row.get('cwd'),str) and row['cwd']),None)
    if not cwd:raise ValueError('Existing session has no cwd; fast-forward refused')
    writes=n.payload_writes(snap,home,cwd,sid,main.parent)
    incoming=next(data for path,data in writes if path==main);rows=records(incoming)
    start, skipped=append_start(existing,rows)
    if start is None:
        raise ValueError(f'Fast-forward divergence for {sid}; existing project: {main.parent}. Use --new-copy; history was not changed.')
    new_rows=rows[start:]
    old_ids={row['uuid'] for _,row in existing if row.get('uuid')}
    new_ids=[row['uuid'] for _,row in new_rows if row.get('uuid')]
    if old_ids.intersection(new_ids) or len(new_ids)!=len(set(new_ids)):
        raise ValueError('Fast-forward divergence: appended UUIDs overlap; use --new-copy')
    tail=incoming[new_rows[0][0]:] if new_rows else b''
    if tail and old and not old.endswith(b'\n'):tail=b'\n'+tail
    new_files=[]
    for path,data in writes:
        if path==main:continue
        if path.exists():
            if not path.is_file() or path.read_bytes()!=data:raise ValueError('Fast-forward sidecar divergence; use --new-copy: '+str(path))
        else:new_files.append((path,data))
    registration=None;registry=r.desktop_registry_dir(a)
    if registry:
        registered=[path for path in registry.glob('local_*.json') if json.loads(path.read_text(encoding='utf-8')).get('cliSessionId')==sid]
        if len(registered)>1:raise ValueError('Ambiguous existing desktop registration')
        if registered:registration=registered[0]
    planned=[(main,tail)] if tail else []
    planned+=new_files
    info={'live_process_check':live,'live_process_sources':sources,'main':main,'before':old,'identity':(main.stat().st_dev,main.stat().st_ino),'tail':tail,'append_lines':len(new_rows),'skipped_local_maintenance':dict(skipped),'new_files':new_files}
    return (home,cwd,planned,registration),info

def restore(snap,a):
    import agent_rehome as r
    (home,cwd,writes,registration),info=plan(snap,a)
    result={'mode':'claude-native','operation':'fast-forward','status':'preview' if a.dry_run else ('written' if writes else 'unchanged'),
            'id':snap['source']['session_id'],'cwd':cwd,'append_lines':info['append_lines'],'skipped_local_maintenance':info['skipped_local_maintenance'],
            'skipped_local_maintenance_count':sum(info['skipped_local_maintenance'].values()),'new_sidecars':len(info['new_files']),
            'desktop_registry':str(registration) if registration else None,'context':'existing history preserved; only prefix-compatible additions',
            'live_process_check':info['live_process_check'],'live_process_sources':info['live_process_sources'],'losses_summary':{},'warnings':[FAST_FORWARD_AFTERCARE,
            'No global file transaction: on partial failure preserve backup/journal and stop; never restore a shared history wholesale.']}
    if info['live_process_check']=='unavailable':result['warnings'].append('无法检测目标会话的运行进程，本次预演不能证明可以安全写入。')
    if a.dry_run or not writes:print(json.dumps(result,ensure_ascii=False));return result
    live_process_check(home,result['id'],False)
    backup=home/'rehome-backups'/('claude-native-fast-forward-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    r.dump(backup/'journal.json',{'status':'prepared','session_id':result['id'],'history':str(info['main']),'before_sha256':n.sha(info['before']),
        'append_lines':info['append_lines'],'skipped_local_maintenance':info['skipped_local_maintenance'],'new_files':[str(path) for path,_ in info['new_files']]})
    (backup/'history-before.jsonl').write_bytes(info['before'])
    if registration:(backup/'desktop-registration-before.json').write_bytes(registration.read_bytes())
    main=info['main']
    def unchanged():
        stat=main.stat()
        if (stat.st_dev,stat.st_ino)!=info['identity'] or main.read_bytes()!=info['before']:
            raise ValueError('Existing history changed concurrently; fast-forward stopped')
    try:
        unchanged()
        for path,data in info['new_files']:
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as stream:stream.write(data)
        unchanged()
        if info['tail']:
            live_process_check(home,result['id'],False)
            descriptor=os.open(main,os.O_WRONLY|os.O_APPEND|getattr(os,'O_BINARY',0))
            try:
                stat=os.fstat(descriptor)
                if (stat.st_dev,stat.st_ino)!=info['identity'] or stat.st_size!=len(info['before']):raise ValueError('History changed before append')
                if os.write(descriptor,info['tail'])!=len(info['tail']):raise OSError('Partial history append')
                os.fsync(descriptor)
            finally:os.close(descriptor)
        stat=main.stat()
        if (stat.st_dev,stat.st_ino)!=info['identity'] or main.read_bytes()!=info['before']+info['tail']:
            raise ValueError('History changed during append; inspect retained journal before proceeding')
    except BaseException:
        r.dump(backup/'journal.json',{'status':'partial-write-needs-review','session_id':result['id'],'history':str(main),
            'before_sha256':n.sha(info['before']),'recovery':'Preserve concurrent data; no automatic truncation or wholesale restore. Inspect sidecars and history against backup.'})
        raise
    r.dump(backup/'journal.json',{'status':'committed','session_id':result['id'],'history':str(main),'append_lines':info['append_lines'],'after_sha256':n.sha(main.read_bytes())})
    result['backup']=str(backup);print(json.dumps(result,ensure_ascii=False));return result
