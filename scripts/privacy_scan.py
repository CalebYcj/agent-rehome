"""Conservative release-content scan, not a general-purpose secrets detector."""
import argparse, json, re
from pathlib import Path

# Stable protocol namespace and deliberately synthetic fixture identifiers.
PUBLIC_IDS = {'6f1c2a9e-4b7d-4c1e-9a3f-c1a0dec0de01',
    '12345678-1234-4567-8123-123456789012', 'aaaaaaaa-1234-4567-8123-123456789012'}
PATTERNS = {
    'user-home-path': re.compile(r'(?:[A-Za-z]:[\\/]+Users[\\/]+(?!<)[^\s<>"\'\\/]+|/(?:Users|home)/(?!<)[^\s<>"\'/]+)'),
    'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),
    'session-id': re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.I),
    'credential': re.compile(r'(?:\bsk-[A-Za-z0-9_-]{20,}|\bgh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)'),
}


def scan(root):
    root=Path(root).resolve();hits=[];count=0
    for path in sorted(root.rglob('*')):
        if '.git' in path.relative_to(root).parts: continue
        if not path.is_file(): continue
        count+=1;relative=path.relative_to(root).as_posix()
        if path.suffix in ('.pyc','.pyo','.log') or '__pycache__' in path.parts:
            hits.append({'file':relative,'kind':'generated-or-log-file'});continue
        try: text=path.read_text(encoding='utf-8')
        except UnicodeError:
            hits.append({'file':relative,'kind':'unreviewed-binary'});continue
        for kind,pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                if kind=='session-id' and match.group().lower() in PUBLIC_IDS: continue
                hits.append({'file':relative,'kind':kind,'line':text.count('\n',0,match.start())+1})
    return {'files_scanned':count,'hits':len(hits),'findings':hits,
        'scope':'UTF-8 contents; paths/email/non-fixture UUID/common credentials; excludes .git; not exhaustive secret detection'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path);args=parser.parse_args()
    if not args.directory.is_dir(): parser.error('Directory does not exist')
    result=scan(args.directory);print(json.dumps(result,ensure_ascii=False,indent=2));return bool(result['hits'])


if __name__=='__main__': raise SystemExit(main())
