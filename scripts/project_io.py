"""Bounded file I/O and capacity checks for project transfer."""
import hashlib
import base64
import json
import os
import shutil
from pathlib import Path

CHUNK = 1024 * 1024
RESERVE = 64 * CHUNK


def linked(path):
    return path.is_symlink() or bool(getattr(path.lstat(),'st_file_attributes',0) & 1024)


def chunks(path, skip_bom=False):
    with Path(path).open('rb') as stream:
        if skip_bom and stream.read(3) != b'\xef\xbb\xbf':
            stream.seek(0)
        while block := stream.read(CHUNK):
            yield block


def measure(blocks):
    digest = hashlib.sha256()
    size = 0
    for block in blocks:
        digest.update(block)
        size += len(block)
    return digest.hexdigest(), size


def digest(path):
    return measure(chunks(path))[0]


def inline_image(path):
    # The target history schema requires one base64 string. Each read has a
    # multiple-of-three size so the chunks concatenate without internal padding.
    with Path(path).open('rb') as stream:
        return ''.join(base64.b64encode(block).decode('ascii')
                       for block in iter(lambda:stream.read(3*(CHUNK//3)),b''))


def write_checked(path, blocks, expected):
    """Create exclusively and remove only our incomplete output on failure."""
    with path.open('xb') as stream:
        opened = os.fstat(stream.fileno())
        try:
            def written():
                for block in blocks:
                    stream.write(block)
                    yield block
            actual = measure(written())
            if actual != expected:
                raise ValueError('File changed during copy: ' + str(path))
        except BaseException:
            stream.close()
            if path.exists():
                current = path.lstat()
                if (current.st_dev,current.st_ino)==(opened.st_dev,opened.st_ino):
                    path.unlink()
            raise


def json_bytes(value):
    return sum(len(piece.encode('utf-8')) for piece in json.JSONEncoder(ensure_ascii=False,indent=2).iterencode(value))


def check_space(allocations):
    """Sum concurrent writes on the same filesystem, including one reserve per volume."""
    volumes = {}
    for path, size in allocations:
        if not size:
            continue
        anchor = Path(path).resolve()
        while not anchor.exists():
            anchor = anchor.parent
        if not anchor.is_dir():
            anchor = anchor.parent
        key = anchor.stat().st_dev
        record = volumes.setdefault(key, {'path': str(anchor), 'bytes': 0})
        record['bytes'] += size
    for record in volumes.values():
        free = shutil.disk_usage(record['path']).free
        required = record['bytes'] + RESERVE
        if free < required:
            raise ValueError(f"Insufficient disk space at {record['path']}: short by {required-free} bytes "
                             f"(need {required}, free {free}, including {RESERVE} bytes reserve)")
    return list(volumes.values())
