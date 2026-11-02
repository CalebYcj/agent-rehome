"""Synthetic leak samples verify that a zero-hit release scan is meaningful."""
import json, sys, tempfile, uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from privacy_scan import scan
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    samples=['C:'+ '/Users/'+'fixture-person/private', 'person'+'@'+'example.invalid', str(uuid.uuid4()), 'sk-'+'x'*24]
    (root/'sample.txt').write_text('\n'.join(samples),encoding='utf-8')
    result=scan(root)
    assert result['hits']==4
    assert {x['kind'] for x in result['findings']}=={'user-home-path','email','session-id','credential'}
    (root/'sample.txt').write_text('Synthetic fixture only',encoding='utf-8')
    assert scan(root)['hits']==0
print('PASS: privacy scan detects synthetic paths, email, UUID and credentials')
