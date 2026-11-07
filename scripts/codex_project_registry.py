"""Register restored projects in the desktop sidebar state as well as SQLite."""
from platform_paths import sqlite_read_uri
import argparse,datetime as dt,json,os,shutil,uuid,sys,time,subprocess,sqlite3
from pathlib import Path

def desktop_executable():
    if os.name!='nt':
        raise RuntimeError('Desktop process detection is implemented only on Windows; use an offline target home')
    import ctypes
    from ctypes import wintypes
    psapi=ctypes.WinDLL('psapi',use_last_error=True); kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    pids=(wintypes.DWORD*8192)(); used=wintypes.DWORD()
    if not psapi.EnumProcesses(pids,ctypes.sizeof(pids),ctypes.byref(used)):raise RuntimeError('Cannot enumerate desktop processes')
    for pid in pids[:used.value//ctypes.sizeof(wintypes.DWORD)]:
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:continue
        try:
            size=wintypes.DWORD(32768);buf=ctypes.create_unicode_buffer(size.value)
            if kernel.QueryFullProcessImageNameW(handle,0,buf,ctypes.byref(size)):
                path=buf.value.lower().replace('\\','/')
                if '/windowsapps/openai.codex_' in path and path.endswith('/chatgpt.exe'):return buf.value
        finally:kernel.CloseHandle(handle)
    return None

def desktop_running():return desktop_executable() is not None

def live_home(home):return Path(home).resolve()==(Path.home()/'.codex').resolve()

def native_project(home,cwd,thread_ids,timeout=15):
    """Use the desktop's supported folder-open command line, not UI injection/state rewriting."""
    home=Path(home);state_path=home/'.codex-global-state.json'
    def find():
        state=json.loads(state_path.read_text(encoding='utf-8'))
        hits=[v for v in state.get('local-projects',{}).values() if any(os.path.normcase(x.removeprefix('\\\\?\\'))==os.path.normcase(str(cwd)) for x in v.get('rootPaths',[]))]
        if len(hits)>1:raise ValueError('Multiple native projects have this root; choose explicitly')
        if not hits:return None
        project=hits[0];assigned=state.get('thread-project-assignments',{})
        missing=[tid for tid in thread_ids if assigned.get(tid,{}).get('projectId')!=project['id']]
        return {'registered':not missing,'project_created':True,'project_id':project['id'],'name':project['name'],'transport':'native-folder-open','thread_binding_required':missing,'next':'Use native move_thread_to_project then verify all IDs with list_projects/list_threads'}
    existing=find()
    if existing:return existing
    exe=desktop_executable()
    if not exe:raise RuntimeError('No running Codex desktop executable found')
    backup=home/'rehome-backups'/('native-project-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f'));backup.mkdir(parents=True)
    shutil.copy2(state_path,backup/state_path.name)
    db=home/'state_5.sqlite'
    if db.exists():
        a=sqlite3.connect(sqlite_read_uri(db),uri=True);b=sqlite3.connect(backup/db.name)
        try:a.backup(b)
        finally:b.close();a.close()
    startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
    child=subprocess.Popen([exe,str(cwd)],startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        result=find()
        if result:return dict(result,backup=str(backup))
        time.sleep(0.2)
    raise TimeoutError('Native folder-open did not register a project; do not claim success or retry blindly')

def register(home,cwd,pid,name,thread_ids):
    home=Path(home);p=home/'.codex-global-state.json'
    if live_home(home):
        try:
            if desktop_running(): return native_project(home,cwd,thread_ids)
        except (RuntimeError,OSError) as error:
            return {'registered':False,'reason':str(error),'next':'Sessions/files were written; add the folder in Codex APP and associate chats manually, or use native list_projects/move_thread_to_project tools when available. Sidebar verification is pending.'}
    if not p.exists():return {'registered':False,'reason':'desktop state not initialized'}
    original=p.read_bytes();state=json.loads(original)
    projects=state.setdefault('local-projects',{})
    if pid in projects and projects[pid].get('rootPaths')!=[str(cwd)]: raise ValueError('Existing UI project has different roots')
    ms=int(dt.datetime.now().timestamp()*1000)
    rec=projects.get(pid) or {'id':pid,'name':name,'rootPaths':[str(cwd)],'createdAt':ms,'updatedAt':ms}
    projects[pid]=rec
    order=state.setdefault('project-order',[])
    if pid not in order:order.append(pid)
    roots=state.setdefault('electron-saved-workspace-roots',[])
    if str(cwd) not in roots:roots.append(str(cwd))
    assignments=state.setdefault('thread-project-assignments',{});hosts=state.setdefault('thread-project-membership-host-ids',{})
    for tid in thread_ids:
        existing=assignments.get(tid)
        if existing and existing.get('projectId')!=pid:raise ValueError('Thread already assigned to another UI project')
        assignments[tid]={'projectKind':'local','projectId':pid};hosts[tid]='local'
    projectless=state.get('projectless-thread-ids')
    if isinstance(projectless,list):state['projectless-thread-ids']=[t for t in projectless if t not in thread_ids]
    data=json.dumps(state,ensure_ascii=False,separators=(',',':')).encode()
    if json.loads(original)==state:return {'registered':True,'changed':False}
    backup=home/'rehome-backups'/('desktop-project-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f'));backup.mkdir(parents=True)
    (backup/p.name).write_bytes(original)
    tmp=p.with_name(p.name+'.rehome-'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_bytes(data)
        if live_home(home) and desktop_running():raise ValueError('Desktop reopened during registration; retry after exit')
        if p.read_bytes()!=original:raise ValueError('Desktop state changed concurrently; registration not written, retry when idle')
        os.replace(tmp,p)
    finally:
        if tmp.exists():tmp.unlink()
    return {'registered':True,'changed':True,'backup':str(backup),'project_id':pid,'restart_may_be_required':True}
def apply_pending(job,timeout=1800):
    job=Path(job);payload=json.loads(job.read_text(encoding='utf-8'));deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if desktop_running():time.sleep(0.25);continue
        time.sleep(0.5)
        if desktop_running():continue
        result=register(payload['home'],payload['cwd'],payload['pid'],payload['name'],payload['thread_ids'])
        if not result.get('registered'):continue
        state=json.loads((Path(payload['home'])/'.codex-global-state.json').read_text(encoding='utf-8'))
        assert state['local-projects'][payload['pid']]['rootPaths']==[payload['cwd']]
        assert all(state['thread-project-assignments'][tid]['projectId']==payload['pid'] for tid in payload['thread_ids'])
        payload.update(status='registered-offline-ui-verification-pending',result=result)
        job.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        return result
    payload['status']='timed-out-no-registration-applied';job.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    raise TimeoutError('Desktop did not exit within the one-shot 30-minute window; no configuration applied')

if __name__=='__main__':
    from cli_output import print,configure
    configure()
    if len(sys.argv)>1 and sys.argv[1]=='apply-pending':
        print(json.dumps(apply_pending(sys.argv[2]),ensure_ascii=False));raise SystemExit(0)
    ap=argparse.ArgumentParser();ap.add_argument('restore_manifest',type=Path);a=ap.parse_args()
    import sqlite3
    m=json.loads(a.restore_manifest.read_text(encoding='utf-8'));home=Path.home()/'.codex'
    with sqlite3.connect(sqlite_read_uri(home/"state_5.sqlite"),uri=True) as db:
        row=db.execute('select project_id from threads where id=?',(m['sessions'][0]['id'],)).fetchone()
        pid=row[0];name=db.execute('select name from projects where id=?',(pid,)).fetchone()[0]
    print(json.dumps(register(home,m['target'],pid,name,[t['id'] for t in m['sessions']]),ensure_ascii=False))
