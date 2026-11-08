"""Batch moves: list every project an agent has history for, pack them all, restore them all.

list    --from claude|codex|all       show every project with conversations (read-only)
pack    --from X --to Y --out DIR     one package per project inside DIR, plus batch.json and the
                                      global rules file (installed only after the user approves; see global_rules.py)
restore DIR --to Y --root DIR         restore each package into ROOT/<project name>

Each project still goes through project_rehome.pack/restore, so every single-project
check (secret scan, space check, fresh target, backups) applies unchanged. One failing
project is recorded and the rest continue.
"""
import argparse, contextlib, io, json, re, sqlite3, sys
from pathlib import Path

from platform_paths import path_key, portable_name, sqlite_read_uri
import agent_rehome as r
import project_rehome as pr
import global_rules as gr
from cli_output import print, configure

BATCH = 'batch.json'
SCHEMA = 'agent-rehome-batch/v1'


def default_home(agent):
    return Path.home() / ('.claude' if agent == 'claude' else '.codex')


def _claude_projects(home):
    found = {}
    base = Path(home) / 'projects'
    if not base.is_dir():
        return found
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        for session in sorted(folder.glob('*.jsonl')):
            cwd = pr.claude_session_cwd(session)
            if not cwd:
                continue
            # pack finds sessions by the encoded cwd folder; only count sessions it will see.
            if re.sub(r'[^a-zA-Z0-9_-]', '-', cwd) != folder.name:
                continue
            item = found.setdefault(path_key(cwd), {'project': cwd, 'sessions': 0, 'last_active': ''})
            item['sessions'] += 1
            item['last_active'] = max(item['last_active'], _mtime(session))
    return found


def _mtime(path):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _codex_projects(home):
    found = {}
    db_path = Path(home) / 'state_5.sqlite'
    if not db_path.is_file():
        return found
    with r.closing(sqlite3.connect(sqlite_read_uri(db_path), uri=True)) as db:
        columns = {row[1] for row in db.execute('pragma table_info(threads)')}
        stamp = 'updated_at' if 'updated_at' in columns else "''"
        archived = 'archived' if 'archived' in columns else '0'
        for cwd, updated, is_archived in db.execute(f'select cwd,{stamp},{archived} from threads'):
            if not cwd:
                continue
            item = found.setdefault(path_key(cwd), {'project': cwd, 'sessions': 0, 'archived': 0, 'last_active': ''})
            item['sessions'] += 1
            if is_archived:
                item['archived'] += 1
            text = _stamp(updated)
            item['last_active'] = max(item['last_active'], text)
    return found


def _stamp(value):
    if isinstance(value, (int, float)) and value > 0:
        from datetime import datetime, timezone
        seconds = value / 1000 if value > 10**11 else value
        return datetime.fromtimestamp(seconds, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return str(value or '')


def inventory(agent, home=None):
    """Every project directory the agent has conversations for, newest first."""
    home = Path(home) if home else default_home(agent)
    found = _claude_projects(home) if agent == 'claude' else _codex_projects(home)
    items = []
    for item in found.values():
        item = dict(item, agent=agent, exists=Path(item['project']).is_dir())
        items.append(item)
    items.sort(key=lambda x: x['last_active'], reverse=True)
    return items


def _names(projects):
    """Readable, unique folder names: the project basename, then -2, -3 ..."""
    used, names = set(), []
    for project in projects:
        base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', portable_name(project)).strip(' .') or 'project'
        name, n = base, 2
        while name.lower() in used:
            name, n = f'{base}-{n}', n + 1
        used.add(name.lower())
        names.append(name)
    return names


def _quiet(call):
    """Run one single-project step, keep its JSON lines for the batch record."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = call()
    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    last = None
    for line in reversed(lines):
        try:
            last = json.loads(line)
            break
        except ValueError:
            continue
    return result, last


def batch_pack(agent, out, to=None, home=None, projects=None, dry_run=False, files_mode='copy', include_git=False, allow_secrets_in_config=False, global_rules=True):
    home = Path(home) if home else default_home(agent)
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('Batch output must be a new directory')
    listed = inventory(agent, home)
    if projects:
        wanted = {path_key(Path(p).resolve()) for p in projects} | {path_key(p) for p in projects}
        chosen = [x for x in listed if path_key(x['project']) in wanted]
        unknown = sorted(set(map(str, projects)) - {x['project'] for x in chosen} - {str(Path(x['project'])) for x in chosen})
        if len(chosen) < len(projects):
            raise ValueError('No conversations found for: ' + ', '.join(unknown))
    else:
        chosen = listed
    native = to == agent
    items, names = [], _names([x['project'] for x in chosen])
    if not dry_run:
        out.mkdir(parents=True)
    for entry, name in zip(chosen, names):
        item = {'project': entry['project'], 'name': name, 'sessions': entry['sessions']}
        if not entry['exists']:
            item.update(status='skipped', reason='project directory no longer exists')
            items.append(item)
            continue
        target = out / name
        try:
            preview, last = _quiet(lambda: pr.pack(agent, Path(entry['project']), target, home, native=native,
                                                    dry_run=dry_run, files_mode=files_mode, include_git=include_git,
                                                    allow_secrets_in_config=allow_secrets_in_config))
        except (ValueError, KeyError, OSError, sqlite3.Error) as error:
            item.update(status='failed', reason=str(error))
            items.append(item)
            continue
        if dry_run:
            item.update(status='planned', preview=preview)
        else:
            item.update(status='packed', package=name, conversations=(last or {}).get('conversations'),
                        files=(last or {}).get('files'), skipped=(last or {}).get('skipped', []))
        items.append(item)
    record = {'schema': SCHEMA, 'source_agent': agent, 'target_agent': to, 'native': native,
              'created_at': r.now(), 'projects': items}
    counts = {s: sum(1 for x in items if x['status'] == s) for s in ('packed', 'planned', 'skipped', 'failed')}
    record['summary'] = counts
    if global_rules:
        # The user-level "main persona" file travels too; it is only installed after the user approves a preview.
        source = gr.source_file(agent, home)
        if not source:
            record['global_rules'] = {'status': 'none'}
        elif dry_run:
            record['global_rules'] = {'status': 'planned', 'source_file': str(source), 'bytes': source.stat().st_size}
        else:
            try:
                packed = gr.pack(agent, out, home, allow_secrets_in_config)
                record['global_rules'] = {k: packed[k] for k in ('status', 'source_file', 'bytes')} | {'mentions': len(packed['mentions'])}
            except (ValueError, OSError) as error:
                record['global_rules'] = {'status': 'failed', 'reason': str(error)}
    if not dry_run:
        r.dump(out / BATCH, record)
        record['user_next_steps'] = {
            'title': '⚠ 批量打包完成，还差接收',
            'package_path': str(out),
            'same_computer': '打开目标 Agent，把下面这句话发给它。',
            'other_computer': '把整个文件夹复制到另一台电脑（U 盘、移动硬盘或局域网共享），再把这句话发给那边的 Agent，路径换成那台电脑上的位置。那边也要先装好本 Skill 和 Python 3.10+。',
            'privacy': '包里有私人对话和项目文件，不要传到公开位置。',
            'first_message': f'用 Agent Rehome 接收这批搬家包：{out}',
        }
    print(json.dumps(record, ensure_ascii=False))
    return record


def batch_restore(batch, to, root, home=None, dry_run=False, no_desktop=False, convert=False, **options):
    """options pass through to project_rehome.restore (model, claude_model, claude_version, desktop_registry)."""
    batch = Path(batch).resolve(); root = Path(root).resolve()
    record = json.loads((batch / BATCH).read_text(encoding='utf-8'))
    if record.get('schema') != SCHEMA:
        raise ValueError('Unsupported batch package')
    if root.is_relative_to(batch):
        raise ValueError('Restore root must be outside the batch folder')
    results = []
    if not dry_run:
        root.mkdir(parents=True, exist_ok=True)
    for item in record['projects']:
        if item.get('status') != 'packed':
            continue
        dest = root / item['name']
        result = {'project': item['project'], 'target': str(dest)}
        if dest.exists():
            result.update(status='failed', reason='target already exists; choose a new root')
            results.append(result)
            continue
        try:
            state, _ = _quiet(lambda: pr.restore(batch / item['package'], dest, to, Path(home) if home else None,
                                                 no_desktop=no_desktop, convert=convert, dry_run=dry_run, **options))
        except (ValueError, KeyError, OSError, sqlite3.Error) as error:
            result.update(status='failed', reason=str(error))
            results.append(result)
            continue
        state = state or {}
        result.update(status='planned' if dry_run else 'restored',
                      conversations=(lambda v: v if isinstance(v, int) else len(v or []))(state.get('sessions')),
                      sessions=[x.get('title') for x in state.get('sessions')] if isinstance(state.get('sessions'), list) else None)
        registry = state.get('desktop_project_registry')
        if to == 'codex' and isinstance(registry, dict):
            result['codex_project'] = ('registered' if registry.get('registered') or registry.get('project_id') and not registry.get('pending')
                                       else 'pending' if registry.get('pending') else 'not_registered')
            result['thread_binding_required'] = registry.get('thread_binding_required', [])
        results.append(result)
    summary = {s: sum(1 for x in results if x['status'] == s) for s in ('restored', 'planned', 'failed')}
    out = {'schema': SCHEMA + '+restore', 'target_agent': to, 'root': str(root), 'projects': results, 'summary': summary}
    if dry_run and to == 'codex' and not no_desktop and summary['planned']:
        # Codex asks for trust once per project folder; parent trust is not inherited (BATCH-3-ISO, 156.3).
        out['user_notice'] = (f'正式恢复时，Codex 会为每个项目弹出一次「信任此文件夹」，共 {summary["planned"]} 次，一个接一个出现。'
                              '请核对路径后逐个确认；添加项目和归组都由 Agent 完成。')
    if not dry_run and results:
        restored = [x['target'] for x in results if x['status'] == 'restored']
        if to == 'claude':
            out['user_next_steps'] = {'title': '⚠ 还差一步：请重启 Claude 桌面版',
                                      'instructions': ['所有项目都恢复完了，只需重启一次 Claude 桌面版。',
                                                       f'信任只需一次：在桌面版里用根目录 {root} 新开一个会话，出现「信任此文件夹」时核对路径并亲自确认。下面所有项目都沿用这次信任，不用逐个确认。',
                                                       '重启后每个项目在侧边栏里各有一组「· 迁移副本」会话。'],
                                      'projects': restored, 'options': ['已重启，继续', '稍后再说']}
        else:
            pending = [x['target'] for x in results if x.get('codex_project') in ('pending', 'not_registered')]
            out['agent_next'] = ('Re-check pending projects with native list_projects (do not resend folder-open), '
                                 'then move every thread_binding_required ID to its project with move_thread_to_project and verify cwd.')
            out['user_next_steps'] = {'title': '⚠ 还差一步：确认信任提示，等 Agent 完成归组',
                                      'instructions': ([f'还有 {len(pending)} 个项目在等「信任此文件夹」确认，请逐个核对路径后确认。'] if pending else [])
                                                      + ['每个项目在 Codex 里需要单独确认一次信任，这是 Codex 的规则。其余由 Agent 逐个归组并复查。'],
                                      'projects': restored, 'pending_trust': pending,
                                      'options': ['已全部确认，继续', '稍后再说']}
    if (batch / gr.DIRNAME).is_dir():
        try:
            out['global_rules'] = gr.plan(batch, to, home)
        except (ValueError, OSError) as error:
            out['global_rules'] = {'status': 'blocked', 'reason': str(error)}
        if out['global_rules'].get('status') == 'planned':
            out['global_rules_next'] = ('Not installed yet. Show the user this preview, including every mentions line and warning, '
                                        f'then run: global_rules.py install "{batch}" --to {to} --apply only after they agree.')
    if not dry_run and results:
        r.dump(root / 'rehome-batch-restore.json', out)
    print(json.dumps(out, ensure_ascii=False))
    return out


def main():
    configure()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='mode', required=True)
    p = sub.add_parser('list'); p.add_argument('--from', dest='agent', choices=['claude', 'codex', 'all'], required=True)
    p.add_argument('--source-home', type=Path, help='Data root for a single --from agent')
    p = sub.add_parser('pack'); p.add_argument('--from', dest='agent', choices=['claude', 'codex'], required=True)
    p.add_argument('--to', choices=['claude', 'codex'], required=True, help='Receiving agent; same agent packs natively')
    p.add_argument('--out', type=Path, required=True); p.add_argument('--source-home', type=Path)
    p.add_argument('--project', type=Path, action='append', help='Only these projects (repeatable); default all')
    p.add_argument('--dry-run', action='store_true'); p.add_argument('--files', dest='files_mode', choices=['copy', 'reference'], default='copy')
    p.add_argument('--include-git', action='store_true'); p.add_argument('--allow-secrets-in-config', action='store_true')
    p.add_argument('--no-global-rules', action='store_true', help='Leave the global rules (main persona) file out')
    p = sub.add_parser('restore'); p.add_argument('batch', type=Path); p.add_argument('--to', choices=['claude', 'codex'], required=True)
    p.add_argument('--root', type=Path, required=True, help='New parent folder; each project lands in ROOT/<name>')
    p.add_argument('--target-home', type=Path); p.add_argument('--dry-run', action='store_true'); p.add_argument('--no-desktop', action='store_true')
    p.add_argument('--convert', action='store_true')
    p.add_argument('--model'); p.add_argument('--claude-model'); p.add_argument('--claude-version'); p.add_argument('--desktop-registry')
    a = ap.parse_args()
    if a.mode == 'list':
        agents = ['claude', 'codex'] if a.agent == 'all' else [a.agent]
        if a.source_home and len(agents) > 1:
            raise ValueError('--source-home needs a single --from agent')
        rows = [x for agent in agents for x in inventory(agent, a.source_home)]
        print(json.dumps({'projects': rows, 'count': len(rows),
                          'conversations': sum(x['sessions'] for x in rows)}, ensure_ascii=False))
    elif a.mode == 'pack':
        batch_pack(a.agent, a.out, a.to, a.source_home, a.project, a.dry_run, a.files_mode, a.include_git, a.allow_secrets_in_config,
                   not a.no_global_rules)
    else:
        options = {k: v for k, v in (('model', a.model), ('claude_model', a.claude_model), ('claude_version', a.claude_version), ('desktop_registry', a.desktop_registry)) if v}
        batch_restore(a.batch, a.to, a.root, a.target_home, a.dry_run, a.no_desktop, a.convert, **options)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, sqlite3.Error) as error:
        sys.exit(str(error))
