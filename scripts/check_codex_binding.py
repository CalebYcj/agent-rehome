"""Read-only binding check; sidebar membership and native continuation need separate evidence."""
import argparse, json, sqlite3
from contextlib import closing
from pathlib import Path
from platform_paths import path_key, sqlite_read_uri, source_rollout


def inspect(home, thread_id, expected_cwd):
    home=Path(home)
    with closing(sqlite3.connect(sqlite_read_uri(home/'state_5.sqlite'),uri=True)) as db:
        row=db.execute('select cwd,rollout_path,project_id from threads where id=?',(thread_id,)).fetchone()
    if row is None: raise ValueError('Selected thread not found')
    cwd,rollout,pid=row
    path=Path(rollout)
    if not path.is_file(): path=source_rollout(home,rollout)
    meta={};latest_context=None
    with path.open(encoding='utf-8-sig') as stream:
        for line in stream:
            if not line.strip(): continue
            record=json.loads(line)
            if record.get('type')=='session_meta': meta=record.get('payload') or {}
            elif record.get('type')=='turn_context': latest_context=record.get('payload') or {}
    same=lambda value: bool(value) and path_key(value)==path_key(expected_cwd)
    ids=[meta[k] for k in ('id','session_id') if meta.get(k)]
    identity_matches=bool(ids) and all(value==thread_id for value in ids)
    return {'read_only':True,'database_cwd_matches':same(cwd),
            'session_meta_id_matches':identity_matches,
            'session_meta_cwd_matches':same(meta.get('cwd')),
            'binding_matches':same(cwd) and identity_matches and same(meta.get('cwd')),
            'latest_recorded_context_present':latest_context is not None,
            'latest_recorded_context_cwd_matches':None if latest_context is None else same(latest_context.get('cwd')),
            'native_project_membership_verified':False,'continuation_persistence_verified':False,
            'next':'Verify native list_projects/list_threads/read_thread independently before any authorized continuation. Repeat after it. The latest recorded turn context is historical evidence, not live runtime state; never rewrite it to pass checks. A database project_id is not native sidebar evidence.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--codex-home',type=Path,default=Path.home()/'.codex')
    p.add_argument('--thread-id',required=True);p.add_argument('--cwd',required=True)
    a=p.parse_args()
    try:
        result=inspect(a.codex_home,a.thread_id,a.cwd);print(json.dumps(result));raise SystemExit(0 if result['binding_matches'] else 1)
    except (ValueError,OSError,sqlite3.Error) as e:p.exit(2,str(e)+'\n')
