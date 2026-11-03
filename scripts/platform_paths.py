"""Host-aware storage paths and foreign history paths; no filesystem mutations."""
import ntpath, posixpath, re, sys
from pathlib import Path, PureWindowsPath, PurePosixPath


def windows_path(value):
    value=str(value)
    return bool(ntpath.splitdrive(value)[0]) or value.startswith('\\\\')


def storage_path(value, platform=None):
    value=str(value);platform=platform or sys.platform
    if platform=='win32':
        if value.startswith('\\\\?\\'): return value
        if value.startswith('\\\\'): return '\\\\?\\UNC\\'+value[2:]
        return '\\\\?\\'+value if ntpath.isabs(value) else value
    if windows_path(value): raise ValueError('Windows destination path on a POSIX host; select a local destination project')
    return value


def path_key(value):
    value=str(value)
    if value.startswith('\\\\?\\UNC\\'): value='\\\\'+value[8:]
    elif value.startswith('\\\\?\\'): value=value[4:]
    # POSIX paths retain case; macOS can use case-sensitive volumes.
    return ntpath.normcase(ntpath.normpath(value)) if windows_path(value) else posixpath.normpath(value)


def portable_name(value):
    return (PureWindowsPath(str(value)) if windows_path(value) else PurePosixPath(str(value))).name


def portable_suffix(value):
    return PurePosixPath(portable_name(value)).suffix


def remap_text(text, old, new):
    old=str(old);variants={old}
    if windows_path(old):
        clean=old.removeprefix('\\\\?\\')
        variants.update({clean,clean.replace('\\','/'),old.replace('\\','/')})
    for source in sorted(variants,key=len,reverse=True):
        if not source: continue
        boundary=r'''(?=$|[\\/\s<>"'()[\]`])'''
        if windows_path(old) and not windows_path(new):
            text=re.sub(re.escape(source)+boundary+r'([\\/][^\s<>"\n]*)?',
                lambda match:str(new)+(match.group(1) or '').replace('\\','/'),text)
        else: text=re.sub(re.escape(source)+boundary,lambda match:str(new),text)
    return text


def sqlite_read_uri(path):
    return Path(path).resolve().as_uri()+'?mode=ro'


def source_rollout(home, stored):
    """Resolve a copied data root without trusting an obsolete absolute path."""
    home=Path(home).resolve();normalized=str(stored).replace('\\','/')
    def variants(path):
        plain=Path(str(path)[:-4]) if str(path).endswith('.jsonl.zst') else path
        return (plain,Path(str(plain)+'.zst')) if str(plain).endswith('.jsonl') else (plain,)
    def choose(candidates):
        hits=list(dict.fromkeys(p for p in candidates if p.is_file() and p.resolve().is_relative_to(home)))
        if len(hits)>1:raise ValueError('Source rollout ambiguous: multiple .jsonl/.jsonl.zst candidates in the selected source data root')
        return hits[0] if hits else None
    direct=Path(stored)
    if not direct.is_absolute():direct=home/direct
    found=choose(variants(direct))
    if found:return found
    for folder in ('sessions','archived_sessions'):
        if '/'+folder+'/' not in normalized:continue
        tail=normalized.rsplit('/'+folder+'/',1)[1]
        relative=PurePosixPath(tail)
        if relative.is_absolute() or '..' in relative.parts: raise ValueError('Unsafe source rollout path')
        found=choose(variants(home/folder/Path(*relative.parts)))
        if found:return found
    names=[p.name for p in variants(Path(portable_name(stored)))]
    found=choose(p for folder in ('sessions','archived_sessions') for name in names for p in (home/folder).rglob(name))
    if found:return found
    raise ValueError('Source rollout unavailable in the selected source data root (.jsonl and .jsonl.zst checked)')
