"""User-level Skills: the ones the user installed for every project, not the ones inside a project.

pack     --from claude|codex --out DIR [--only NAME]   copy the source's own Skills into DIR (credential scan)
install  DIR --to claude|codex [--only NAME] [--apply] preview by default; --apply copies after the user agreed

Claude keeps them in ~/.claude/skills/<name>/. Codex reads ~/.agents/skills/<name>/ and ~/.codex/skills/<name>/;
installs for Codex go to ~/.agents/skills/.

A Skill is a folder with a SKILL.md. Folders are copied byte for byte and never rewritten, so tool names and
runtime needs may not fit the new agent. Nothing is overwritten: a Skill whose name already exists at the
target is skipped. Plugins, built-in Skills (dot folders), linked folders and this Skill itself are left out.
Undo by deleting the folders listed in the install record.
"""
import argparse, datetime as dt, hashlib, json, os, re, shutil, sys
from pathlib import Path

from privacy_scan import PATTERNS
from cli_output import print, configure
import global_rules as gr

SCHEMA = 'agent-rehome-user-skills/v1'
DIRNAME = 'user-skills'
MANIFEST = 'manifest.json'
SELF = 'agent-rehome'
PRUNE = {'.git', '__pycache__', 'node_modules', '.venv', 'venv'}
SCRIPTS = {'.py', '.sh', '.ps1', '.js', '.mjs', '.ts', '.bat', '.cmd', '.exe'}
SCAN_LIMIT = 2 * 1024 * 1024


class Linked(ValueError):
    pass


def roots(agent, home=None):
    """Folders the agent loads user-level Skills from; the first one is where installs go."""
    home = Path(home) if home else gr.default_home(agent)
    if agent == 'claude':
        return [home / 'skills']
    default = gr.default_home('codex')
    agents = (Path.home() if home.resolve() == default.resolve() else home.parent) / '.agents'
    return [agents / 'skills', home / 'skills']


def _linked(path):
    return path.is_symlink() or bool(getattr(path, 'is_junction', lambda: False)())


def _files(folder):
    """(posix relative path, file) for every file to copy, in a stable order."""
    found = []
    for base, dirs, names in os.walk(folder):
        base = Path(base)
        dirs[:] = sorted(x for x in dirs if x not in PRUNE)
        for name in dirs + names:
            if _linked(base / name):
                raise Linked(str((base / name).relative_to(folder)))
        found += [((base / n).relative_to(folder).as_posix(), base / n) for n in sorted(names) if not n.endswith(('.pyc', '.pyo'))]
    return found


def _digest(files):
    total = hashlib.sha256()
    for relative, path in files:
        total.update(relative.encode('utf-8') + b'\0' + hashlib.sha256(path.read_bytes()).digest())
    return total.hexdigest()


def _describe(text):
    match = re.search(r'^description:\s*(.+)$', text.split('\n---', 1)[0], re.M)
    return match.group(1).strip().strip('"\'')[:160] if match else ''


def inventory(agent, home=None, allow_secrets=False, only=None):
    """What would travel, and what is left out and why. Reads only."""
    skills, skipped, seen = [], [], set()
    for root in roots(agent, home):
        if not root.is_dir():
            continue
        for folder in sorted(root.iterdir(), key=lambda x: x.name.lower()):
            name = folder.name
            if only and name not in only:
                continue
            if name.startswith('.') or name == SELF or not folder.is_dir() and not _linked(folder):
                continue
            if _linked(folder):
                skipped.append({'name': name, 'reason': 'linked-folder'}); continue
            if not (folder / 'SKILL.md').is_file():
                continue
            if name.lower() in seen:
                skipped.append({'name': name, 'reason': 'duplicate-name', 'path': str(folder)}); continue
            try:
                files = _files(folder)
            except Linked as error:
                skipped.append({'name': name, 'reason': 'contains-link', 'path': str(error)}); continue
            secret = None
            for relative, path in files:
                if allow_secrets or path.stat().st_size > SCAN_LIMIT:
                    continue
                try:
                    if PATTERNS['credential'].search(path.read_text(encoding='utf-8')):
                        secret = relative; break
                except UnicodeError:
                    pass
            if secret:
                skipped.append({'name': name, 'reason': 'possible-secret', 'path': secret}); continue
            seen.add(name.lower())
            text = (folder / 'SKILL.md').read_text(encoding='utf-8-sig', errors='replace')
            skills.append({'name': name, 'source': str(folder), 'files': len(files), 'bytes': sum(p.stat().st_size for _, p in files),
                           'sha256': _digest(files), 'description': _describe(text), 'mentions': len(gr.mentions(text)),
                           'has_scripts': any(p.suffix.lower() in SCRIPTS for _, p in files)})
    return skills, skipped


def pack(agent, out, home=None, allow_secrets=False, only=None):
    skills, skipped = inventory(agent, home, allow_secrets, only)
    if not skills:
        return {'status': 'none', 'source_agent': agent, 'skipped': skipped}
    folder = Path(out) / DIRNAME
    folder.mkdir(parents=True, exist_ok=False)
    for skill in skills:
        source = Path(skill.pop('source'))
        for relative, path in _files(source):
            target = folder / skill['name'] / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    manifest = {'schema': SCHEMA, 'source_agent': agent, 'skills': skills, 'skipped': skipped}
    (folder / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return dict(manifest, status='packed', package=str(folder))


def load(package):
    package = Path(package)
    folder = package if (package / MANIFEST).is_file() else package / DIRNAME
    manifest = json.loads((folder / MANIFEST).read_text(encoding='utf-8'))
    if manifest.get('schema') != SCHEMA:
        raise ValueError('Unsupported user skills package')
    for skill in manifest['skills']:
        name = skill['name']
        if Path(name).name != name or name.startswith('.') or not (folder / name / 'SKILL.md').is_file():
            raise ValueError('Bad skill name in package: ' + name)
        if _digest(_files(folder / name)) != skill['sha256']:
            raise ValueError('Skill failed its checksum: ' + name)
    return manifest, folder


def plan(package, to, home=None, only=None):
    manifest, folder = load(package)
    places = roots(to, home)
    source = manifest['source_agent']
    result = {'source_agent': source, 'target_agent': to, 'target': str(places[0]), 'install': [], 'skipped': [], 'warnings': []}
    for skill in manifest['skills']:
        name = skill['name']
        if only and name not in only:
            continue
        existing = next((p / name for p in places if (p / name).exists() or _linked(p / name)), None)
        if existing:
            try:
                same = not _linked(existing) and _digest(_files(existing)) == skill['sha256']
            except (Linked, OSError):
                same = False
            result['skipped'].append({'name': name, 'reason': 'already-installed' if same else 'target-skill-exists', 'path': str(existing)})
            continue
        result['install'].append({k: skill[k] for k in ('name', 'description', 'files', 'bytes', 'mentions', 'has_scripts')})
    if not result['install']:
        return dict(result, status='nothing_to_install')
    scripted = [x['name'] for x in result['install'] if x['has_scripts']]
    if scripted:
        result['warnings'].append('These Skills contain scripts the new agent may run; the user should know them: ' + ', '.join(scripted))
    if source != to:
        result['warnings'].append('Skill files are copied unchanged; tool names and runtime needs may differ between agents, so some may not work as they are.')
    result['warnings'].append('Open a new conversation (restart the app if needed) before expecting the new Skills to be listed.')
    result['undo'] = 'Delete these folders: ' + ', '.join(str(places[0] / x['name']) for x in result['install'])
    return dict(result, status='planned')


def install(package, to, home=None, apply=False, only=None):
    """Preview unless apply=True. Apply only after the user has seen the list and agreed."""
    result = plan(package, to, home, only)
    if not apply or result['status'] != 'planned':
        return result
    _, folder = load(package)
    target = Path(result['target'])
    target.mkdir(parents=True, exist_ok=True)
    done = []
    for skill in result['install']:
        final, temp = target / skill['name'], target / (skill['name'] + '.rehome-tmp')
        shutil.copytree(folder / skill['name'], temp)  # fails if a previous attempt left the temp folder behind
        os.rename(temp, final)
        done.append(str(final))
    base = Path(home) if home else gr.default_home(to)
    record = base / 'rehome-backups' / ('user-skills-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    record.mkdir(parents=True)
    (record / 'installed.json').write_text(json.dumps({'installed': done, 'undo': result['undo']}, ensure_ascii=False, indent=2), encoding='utf-8')
    return dict(result, status='installed', installed=done, record=str(record))


def main():
    configure()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='mode', required=True)
    p = sub.add_parser('pack'); p.add_argument('--from', dest='agent', choices=['claude', 'codex'], required=True)
    p.add_argument('--out', type=Path, required=True); p.add_argument('--source-home', type=Path)
    p.add_argument('--only', action='append', help='Only this Skill (repeatable)'); p.add_argument('--allow-secrets', action='store_true')
    p = sub.add_parser('install'); p.add_argument('package', type=Path); p.add_argument('--to', choices=['claude', 'codex'], required=True)
    p.add_argument('--target-home', type=Path); p.add_argument('--only', action='append', help='Only this Skill (repeatable)')
    p.add_argument('--apply', action='store_true', help='Copy after the user approved the preview')
    a = ap.parse_args()
    if a.mode == 'pack':
        out = pack(a.agent, a.out, a.source_home, a.allow_secrets, a.only)
    else:
        out = install(a.package, a.to, a.target_home, a.apply, a.only)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        sys.exit(str(error))
