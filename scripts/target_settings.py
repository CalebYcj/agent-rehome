"""Read target settings without launching agents or borrowing source defaults."""
from platform_paths import sqlite_read_uri
import json, re, sqlite3
from contextlib import closing
from pathlib import Path


def session_settings(home, agent):
    found = {}
    pattern = 'projects/*/*.jsonl' if agent == 'claude' else 'sessions/**/*.jsonl'
    for path in sorted(Path(home).glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with path.open(encoding='utf-8') as stream:
                for line in stream:
                    try: row = json.loads(line)
                    except ValueError: continue
                    if agent == 'claude':
                        if row.get('version'): found.setdefault('version', row['version'])
                        model = (row.get('message') or {}).get('model')
                    else:
                        model = (row.get('payload') or {}).get('model')
                    if model and model != 'imported-history': found.setdefault('model', model)
            if 'model' in found and (agent != 'claude' or 'version' in found): break
        except OSError: continue
    return found


def codex_model(home, explicit=None):
    if explicit: return explicit
    home = Path(home)
    config = home / 'config.toml'
    if config.is_file():
        # Only the top-level value, never an unrelated profile or provider section.
        top = config.read_text(encoding='utf-8').split('\n[', 1)[0]
        match = re.search(r'''(?m)^model\s*=\s*["']([^"']+)["']''', top)
        if match: return match[1]
    database = home / 'state_5.sqlite'
    if database.is_file():
        try:
            with closing(sqlite3.connect(sqlite_read_uri(database), uri=True)) as db:
                row = db.execute("select model from threads where model is not null and model != '' order by updated_at_ms desc limit 1").fetchone()
                if row: return row[0]
        except sqlite3.Error: pass
    model = session_settings(home, 'codex').get('model')
    if model: return model
    raise ValueError('Cannot detect the target Codex model. Set --model explicitly or initialize the target configuration.')


def claude_settings(home, model=None, version=None, registry_model=None):
    home = Path(home)
    if not model:
        settings = home / 'settings.json'
        if settings.is_file():
            try: model = json.loads(settings.read_text(encoding='utf-8')).get('model')
            except ValueError: pass
    existing = session_settings(home, 'claude') if not version or not (model or registry_model) else {}
    model = model or registry_model or existing.get('model')
    version = version or existing.get('version')
    if not model: raise ValueError('Cannot detect the target Claude model. Set --claude-model explicitly.')
    if not version: raise ValueError('Cannot detect the target Claude Code version. Set --claude-version explicitly.')
    return model, version
