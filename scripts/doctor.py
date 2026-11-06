"""Read-only environment report. Does not launch apps, read credentials or alter data."""
import argparse, json, platform, sqlite3, sys
from contextlib import closing
from pathlib import Path
from platform_paths import sqlite_read_uri
from target_settings import codex_model, claude_settings


def inspect(home=None, system=None, codex_home=None, claude_home=None, desktop_registry=None):
    home=Path(home or Path.home());system=system or sys.platform
    cx=Path(codex_home or home/'.codex');ch=Path(claude_home or home/'.claude')
    result={'platform':system,'architecture':platform.machine(),'python':platform.python_version(),
        'read_only':True,'native_resume_verified':False,'desktop_registration_verified':False}
    database=cx/'state_5.sqlite'
    result['codex']={'home_exists':cx.is_dir(),'database_exists':database.is_file()}
    if database.is_file():
        try:
            with closing(sqlite3.connect(sqlite_read_uri(database),uri=True)) as db:
                result['codex']['tables']={table:[r[1] for r in db.execute('pragma table_info('+table+')')]
                    for table in ('threads','projects','project_roots')}
        except sqlite3.Error: result['codex']['database_error']='Cannot read schema; check database version/access'
    for agent,root,resolve in [('codex',cx,lambda:codex_model(cx)),('claude',ch,lambda:claude_settings(ch))]:
        result.setdefault(agent,{})['home_exists']=root.is_dir()
        try: resolve();result[agent]['settings_detected']=True
        except ValueError as error: result[agent]['settings_detected']=False;result[agent]['action']=str(error)
    candidates=[]
    if desktop_registry: candidates.append(('explicit',Path(desktop_registry)))
    if system=='darwin':
        candidates.extend([('unverified-macos-candidate',home/'Library/Application Support/Claude/claude-code-sessions'),
            ('unverified-macos-candidate',home/'Library/Application Support/Claude/Claude-Data')])
    result['claude']['desktop_candidates']=[]
    for origin,root in candidates:
        records=[]
        # Bounded known-depth patterns; no scan of arbitrary Library contents.
        for pattern in ('local_*.json','*/*/local_*.json','*/claude-code-sessions/*/*/local_*.json'):
            records.extend(root.glob(pattern))
        parents={p.parent for p in records}
        result['claude']['desktop_candidates'].append({'kind':origin,
            'path':str(root).replace(str(home),'~',1),'exists':root.is_dir(),
            'registry_record_count':len(set(records)),'account_directory_count':len(parents)})
    result['next']='Verify model/version and schema, then test isolated imports. macOS desktop paths are candidates only; use an explicitly verified --desktop-registry. No apps have been restarted.'
    return result


def main():
    from cli_output import print,configure
    configure()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home',type=Path);parser.add_argument('--claude-home',type=Path)
    parser.add_argument('--desktop-registry',type=Path)
    args=parser.parse_args();print(json.dumps(inspect(codex_home=args.codex_home,claude_home=args.claude_home,
        desktop_registry=args.desktop_registry),ensure_ascii=False,indent=2))


if __name__=='__main__': main()
