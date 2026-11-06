"""Run each test with a fresh HOME, no network/process launches, and guarded writes."""
import argparse, json, os, runpy, subprocess, sys, tempfile
from pathlib import Path


def child(test):
    scratch = Path(os.environ['REHOME_TEST_SANDBOX']).resolve()
    def inside(value):
        if not isinstance(value, (str, bytes, os.PathLike)): return True
        path = Path(os.fsdecode(value)).resolve()
        return path == scratch or scratch in path.parents
    def guard(event, args):
        if event in ('socket.connect', 'subprocess.Popen', 'os.system'):
            raise PermissionError('Tests cannot access the network or launch external processes')
        if event == 'open':
            path, mode, flags = args
            write = any(c in (mode or '') for c in 'wax+') or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
            if write and not inside(path): raise PermissionError('Test write outside temporary HOME')
            if isinstance(path, (str, bytes, os.PathLike)):
                parts = {p.lower() for p in Path(os.fsdecode(path)).parts}
                if parts & {'.codex', '.claude', 'claude-data'} and not inside(path):
                    raise PermissionError('Test attempted to read real agent data')
        if event == 'sqlite3.connect' and args[0] != ':memory:' and not inside(args[0]):
            # SQLite URI paths are handled explicitly without allowing real HOME access.
            from urllib.parse import unquote, urlparse
            value = unquote(urlparse(str(args[0])).path) if str(args[0]).startswith('file:') else args[0]
            if os.name == 'nt' and str(value).startswith('/') and len(str(value)) > 2 and str(value)[2] == ':': value = str(value)[1:]
            if not inside(value): raise PermissionError('Test database outside temporary HOME')
        if event in ('os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.utime') and not inside(args[0]):
            raise PermissionError('Test mutation outside temporary HOME')
        if event in ('os.rename', 'os.replace') and not all(inside(x) for x in args[:2]):
            raise PermissionError('Test move outside temporary HOME')
    sys.addaudithook(guard)
    runpy.run_path(str(test), run_name='__main__')


def main():
    from cli_output import print,configure
    configure()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--_child', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    scripts = Path(__file__).resolve().parent
    if args._child:
        test = args._child.resolve()
        if test.parent != scripts or not test.name.startswith('test_'): raise ValueError('Unknown test')
        child(test); return 0
    tests = sorted(scripts.glob('test_*.py'))
    if not tests: raise ValueError('No tests found')
    for test in tests:
        with tempfile.TemporaryDirectory(prefix='rehome-tests-') as directory:
            scratch = Path(directory)
            for name in ('tmp', 'local', 'roaming'): (scratch/name).mkdir()
            env = dict(os.environ, HOME=directory, USERPROFILE=directory, HOMEDRIVE=scratch.drive,
                HOMEPATH=str(scratch)[len(scratch.drive):], CODEX_HOME=str(scratch/'.codex'),
                LOCALAPPDATA=str(scratch/'local'), APPDATA=str(scratch/'roaming'),
                TEMP=str(scratch/'tmp'), TMP=str(scratch/'tmp'), TMPDIR=str(scratch/'tmp'),
                REHOME_TEST_SANDBOX=directory, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
            result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--_child', str(test)],
                cwd=directory, env=env, capture_output=True, encoding='utf-8', errors='replace')
            if result.returncode:
                print(test.name+': FAIL\n'+result.stdout+'\n'+result.stderr); return 1
            print(test.name+': PASS (fresh HOME, guarded I/O)')
    print(json.dumps({'tests':len(tests), 'failed':0, 'isolation':'fresh HOME per test; writes, agent-data reads, network and subprocesses guarded'}))
    return 0


if __name__ == '__main__': sys.exit(main())
