"""Reference inventory, capacity refusal, and Git selection using synthetic files."""
import argparse
import contextlib
import io
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import project_rehome as p


def refuses(action, phrase):
    try:
        action()
    except ValueError as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError('Expected refusal')


with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
    root=Path(directory).resolve()
    source=root/'source'
    fixture={'a.bin':b'data','missing.txt':b'missing','CLAUDE.md':b'project rule',
             '.claude/skills/demo/SKILL.md':b'fixture skill','.claude/skills/demo/resource.bin':b'large resource',
             'node_modules/cache.bin':b'ignored','.git/config':b'[remote "origin"]\nurl = https://fixture/repo\n'}
    for relative,data in fixture.items():
        path=source/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
    home=root/'source-home'
    preview=p.pack('claude',source,root/'preview',home,[],dry_run=True)
    assert preview['largest_files'][0]['path']=='.claude/skills/demo/resource.bin'
    assert preview['bytes_by_extension']['.bin']==18
    assert {item['path']:item['bytes'] for item in preview['excluded_directories']}['node_modules']==7
    assert preview['git_bytes']==0
    package=root/'reference-package'
    with patch.object(Path,'read_bytes',side_effect=AssertionError('whole file read')):
        p.pack('claude',source,package,home,[],files_mode='reference')
        assert not (package/'project/a.bin').exists()
        assert (package/'project/.claude/skills/demo/resource.bin').is_file()
        dest=root/'existing'
        dest.mkdir()
        (dest/'a.bin').write_bytes(b'edit')
        (dest/'extra.txt').write_bytes(b'extra')
        (dest/'CLAUDE.md').write_bytes(fixture['CLAUDE.md'])
        report=p.restore(package,dest,'codex',root/'target-home',True,dry_run=True)
        assert report['file_references']['different']==['a.bin']
        assert 'missing.txt' in report['file_references']['missing']
        assert report['file_references']['extra']==['extra.txt']
        refuses(lambda:p.restore(package,dest,'codex',root/'target-home',True,strict_files=True),'strict restore stopped')
        assert not (dest/'.rehome').exists()
        with patch('project_io.shutil.disk_usage',return_value=argparse.Namespace(free=0)):
            refuses(lambda:p.restore(package,dest,'codex',root/'target-home',True),'short by')
        assert not (dest/'.rehome').exists()
        state=p.restore(package,dest,'codex',root/'target-home',True)
        assert state['file_references']==report['file_references']
    assert (dest/'a.bin').read_bytes()==b'edit' and not (dest/'missing.txt').exists()
    assert (dest/'.agents/skills/demo/resource.bin').read_bytes()==fixture['.claude/skills/demo/resource.bin']
    exact=root/'exact'
    for relative,data in fixture.items():
        path=exact/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
    assert not any(p.restore(package,exact,'codex',root/'target-home',True,strict_files=True,dry_run=True)['file_references'].values())
    git=root/'git-package'
    p.pack('claude',source,git,home,[],include_git=True)
    assert (git/'project/.git/config').read_bytes()==fixture['.git/config']
    assert p.pack('claude',source,root/'git-preview',home,[],include_git=True,dry_run=True)['git_bytes']==len(fixture['.git/config'])
    (source/'.git/config').write_text('[remote "origin"]\nurl = https://user:fixture@host/repo\n',encoding='utf-8')
    refuses(lambda:p.pack('claude',source,root/'unsafe-git',home,[],include_git=True),'credentials in Git remote URL')
    assert not (root/'unsafe-git').exists()
print('PASS: reference report/strict mode, streamed skills, disk refusal, Git opt-in and credential rejection')
