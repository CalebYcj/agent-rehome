"""Global rules ("main persona"): the user-level instruction file that applies to every conversation.

pack     --from claude|codex --out DIR       copy the source's global rules into DIR (credential scan)
install  DIR --to claude|codex [--apply]     preview by default; --apply writes after a backup

Codex reads ~/.codex/AGENTS.override.md if present, else ~/.codex/AGENTS.md.
Claude reads ~/.claude/CLAUDE.md and follows @imports in it.

Install never replaces the target's own file:
- Claude: the rules are saved as ~/.claude/rehome/global-rules-from-<agent>.md and one
  `@rehome/...` import line is appended to ~/.claude/CLAUDE.md (delete the line to undo).
- Codex has no imports, so the text is appended inside begin/end markers (delete the block to undo).
The text is not rewritten; lines naming the old agent, its paths or tools are listed for the user.
"""
import argparse, datetime as dt, hashlib, json, os, re, shutil, sys
from pathlib import Path

from privacy_scan import PATTERNS
from cli_output import print, configure

SCHEMA = 'agent-rehome-global-rules/v1'
DIRNAME = 'global-rules'
RULES = 'rules.md'
MANIFEST = 'manifest.json'
CODEX_DOC_LIMIT = 32 * 1024  # Codex's default instruction byte budget; larger text may be cut.
MENTION = re.compile(r'(?i)\b(?:codex|openai|chatgpt|gpt-[\w.]+|claude(?: code)?|anthropic|opus|sonnet|haiku)\b'
                     r'|[~.]?[\\/]?\.(?:codex|claude|agents)\b|\b(?:AGENTS|CLAUDE)(?:\.override)?\.md\b'
                     r'|\b(?:apply_patch|update_plan|TodoWrite|AskUserQuestion|ExitPlanMode)\b')
NAMES = {'claude': 'Claude', 'codex': 'Codex'}


def default_home(agent):
    if agent == 'codex' and os.environ.get('CODEX_HOME'):
        return Path(os.environ['CODEX_HOME'])
    return Path.home() / ('.claude' if agent == 'claude' else '.codex')


def source_file(agent, home):
    """The global rules file the agent actually loads, or None."""
    home = Path(home)
    if agent == 'claude':
        candidates = [home / 'CLAUDE.md']
    else:
        candidates = [home / 'AGENTS.override.md', home / 'AGENTS.md']
    for path in candidates:
        if path.is_file() and path.read_bytes().strip():
            return path
    return None


def codex_target(home):
    """Codex ignores AGENTS.md when a non-empty override exists, so append where it reads."""
    override = Path(home) / 'AGENTS.override.md'
    return override if override.is_file() and override.read_bytes().strip() else Path(home) / 'AGENTS.md'


def mentions(text):
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        words = sorted({m.group().strip() for m in MENTION.finditer(line)})
        if words:
            found.append({'line': number, 'words': words, 'text': line.strip()[:160]})
    return found


def imports(agent, text):
    if agent != 'claude':
        return []
    # Claude @imports are not expanded: the referenced files stay on the source machine.
    return sorted(set(re.findall(r'(?<![\w@`])@([^\s`<>]+)', text)))


def pack(agent, out, home=None, allow_secrets=False):
    home = Path(home) if home else default_home(agent)
    path = source_file(agent, home)
    if not path:
        return {'status': 'none', 'source_agent': agent, 'reason': 'no global rules file'}
    data = path.read_bytes()
    try:
        text = data.decode('utf-8-sig')
    except UnicodeError:
        raise ValueError('Global rules must be UTF-8: ' + str(path))
    if PATTERNS['credential'].search(text) and not allow_secrets:
        raise ValueError('Possible secret in global rules ' + str(path) + '; clean it or pass --allow-secrets')
    folder = Path(out) / DIRNAME
    folder.mkdir(parents=True, exist_ok=False)
    (folder / RULES).write_bytes(data)
    manifest = {'schema': SCHEMA, 'source_agent': agent, 'source_file': path.name, 'bytes': len(data),
                'sha256': hashlib.sha256(data).hexdigest(), 'imports_not_included': imports(agent, text),
                'mentions': mentions(text)}
    (folder / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return dict(manifest, status='packed', package=str(folder))


def load(package):
    package = Path(package)
    folder = package if (package / MANIFEST).is_file() else package / DIRNAME
    manifest = json.loads((folder / MANIFEST).read_text(encoding='utf-8'))
    if manifest.get('schema') != SCHEMA:
        raise ValueError('Unsupported global rules package')
    data = (folder / RULES).read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest['sha256']:
        raise ValueError('Global rules package failed its checksum')
    return manifest, data


def _markers(source, sha):
    begin = f'<!-- agent-rehome:global-rules:begin from={source} sha256={sha} -->'
    return begin, '<!-- agent-rehome:global-rules:end -->'


def plan(package, to, home=None):
    manifest, data = load(package)
    home = Path(home) if home else default_home(to)
    source, sha = manifest['source_agent'], manifest['sha256']
    text = data.decode('utf-8-sig')
    result = {'source_agent': source, 'target_agent': to, 'bytes': len(data), 'mentions': manifest['mentions'],
              'imports_not_included': manifest['imports_not_included'], 'writes': [], 'warnings': []}
    if to == 'claude':
        copy = home / 'rehome' / f'global-rules-from-{source}.md'
        main = home / 'CLAUDE.md'
        line = f'@rehome/{copy.name}'
        if copy.exists() and copy.read_bytes() != data:
            raise ValueError(f'{copy} already exists with different text; remove it first (nothing was changed)')
        current = main.read_text(encoding='utf-8-sig') if main.is_file() else ''
        linked = any(x.strip() == line for x in current.splitlines())
        if copy.exists() and linked:
            return dict(result, status='already_installed')
        if not copy.exists():
            result['writes'].append({'file': str(copy), 'action': 'create', 'content': 'rules text (unchanged)'})
        if not linked:
            result['writes'].append({'file': str(main), 'action': 'append' if main.is_file() else 'create',
                                     'content': [f'<!-- agent-rehome: global rules from {NAMES[source]}; delete the next line to undo -->', line]})
        result['undo'] = f'Delete the line "{line}" from {main}; the copied file can then be deleted.'
    else:
        target = codex_target(home)
        begin, end = _markers(source, sha)
        current = target.read_text(encoding='utf-8-sig') if target.is_file() else ''
        if begin in current:
            return dict(result, status='already_installed')
        if '<!-- agent-rehome:global-rules:begin from=' + source + ' ' in current:
            raise ValueError(f'{target} already has a different global-rules block from {source}; remove that block first (nothing was changed)')
        result['writes'].append({'file': str(target), 'action': 'append' if target.is_file() else 'create',
                                 'content': [begin, '(rules text, unchanged)', end]})
        size = len(current.encode('utf-8')) + len(data) + len(begin) + len(end) + 4
        if size > CODEX_DOC_LIMIT:
            result['warnings'].append(f'{target.name} would be {size} bytes; Codex may cut instructions beyond {CODEX_DOC_LIMIT} bytes')
        result['undo'] = f'Delete everything from "{begin}" to "{end}" in {target}.'
    if result['mentions']:
        result['warnings'].append(f'{len(result["mentions"])} lines name an agent, its paths or tools; show them to the user, who decides whether to edit')
    if result['imports_not_included']:
        result['warnings'].append('Files referenced with @ were not copied: ' + ', '.join(result['imports_not_included']))
    result['status'] = 'planned'
    return result


def install(package, to, home=None, apply=False):
    """Preview unless apply=True. Apply only after the user has seen the preview and agreed."""
    result = plan(package, to, home)
    if not apply or result['status'] != 'planned':
        return result
    manifest, data = load(package)
    home = Path(home) if home else default_home(to)
    source = manifest['source_agent']
    backup = home / 'rehome-backups' / ('global-rules-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True)
    record = []
    for write in result['writes']:
        path = Path(write['file'])
        if path.exists():
            shutil.copy2(path, backup / path.name)
        record.append({'file': str(path), 'existed': path.exists()})
    (backup / 'backup.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    if to == 'claude':
        copy = home / 'rehome' / f'global-rules-from-{source}.md'
        if not copy.exists():
            copy.parent.mkdir(parents=True, exist_ok=True)
            with open(copy, 'xb') as handle:
                handle.write(data)
        lines = next((w['content'] for w in result['writes'] if w['file'].endswith('CLAUDE.md')), None)
        if lines:
            _append(home / 'CLAUDE.md', '\n'.join(lines) + '\n')
    else:
        begin, end = _markers(source, manifest['sha256'])
        body = data.decode('utf-8-sig').rstrip('\n')
        _append(codex_target(home), f'{begin}\n{body}\n{end}\n')
    return dict(result, status='installed', backup=str(backup))


def _append(path, block):
    path.parent.mkdir(parents=True, exist_ok=True)
    current = path.read_bytes() if path.exists() else b''
    prefix = b'' if not current or current.endswith(b'\n\n') else (b'\n' if current.endswith(b'\n') else b'\n\n')
    temp = path.with_name(path.name + '.rehome-tmp')
    with open(temp, 'xb') as handle:
        handle.write(current + prefix + block.encode('utf-8'))
    os.replace(temp, path)


def main():
    configure()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='mode', required=True)
    p = sub.add_parser('pack'); p.add_argument('--from', dest='agent', choices=['claude', 'codex'], required=True)
    p.add_argument('--out', type=Path, required=True); p.add_argument('--source-home', type=Path)
    p.add_argument('--allow-secrets', action='store_true')
    p = sub.add_parser('install'); p.add_argument('package', type=Path); p.add_argument('--to', choices=['claude', 'codex'], required=True)
    p.add_argument('--target-home', type=Path); p.add_argument('--apply', action='store_true', help='Write after the user approved the preview')
    a = ap.parse_args()
    if a.mode == 'pack':
        out = pack(a.agent, a.out, a.source_home, a.allow_secrets)
    else:
        out = install(a.package, a.to, a.target_home, a.apply)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        sys.exit(str(error))
