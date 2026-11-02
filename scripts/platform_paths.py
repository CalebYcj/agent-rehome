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
    if '/sessions/' in normalized:
        tail=normalized.rsplit('/sessions/',1)[1]
        relative=PurePosixPath(tail)
        if relative.is_absolute() or '..' in relative.parts: raise ValueError('Unsafe source rollout path')
        candidate=home/'sessions'/Path(*relative.parts)
        if candidate.is_file() and candidate.resolve().is_relative_to(home): return candidate
    hits=list((home/'sessions').rglob(portable_name(stored)))
    if len(hits)==1: return hits[0]
    raise ValueError('Source rollout unavailable or ambiguous in the selected source data root')
