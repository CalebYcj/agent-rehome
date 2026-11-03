"""Opaque native sidecars/checkpoints use only synthetic bytes and temporary roots."""
import argparse,base64,copy,json,os,sys,tempfile,uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import claude_native as n,project_rehome as p

def rejected(fn,fragment):
    try:fn()
    except ValueError as error:assert fragment.lower() in str(error).lower(),str(error)
    else:raise AssertionError('Unsafe native payload accepted')

@contextmanager
def test_link(link,target):
    """Use a real link where possible; Windows without link privilege mocks the same guard."""
    try:link.symlink_to(target)
    except OSError as error:
        if os.name!='nt' or getattr(error,'winerror',None) not in (5,1314):raise
        link.write_bytes(target.read_bytes());original=Path.is_symlink
        try:
            with patch.object(Path,'is_symlink',lambda path:path==link or original(path)):yield
        finally:link.unlink()
    else:
        try:yield
        finally:link.unlink()

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);home=root/'source-home';folder=home/'projects/fixture';folder.mkdir(parents=True)
    sid=str(uuid.uuid4());source=folder/(sid+'.jsonl');side=folder/sid/'tool-results';side.mkdir(parents=True)
    png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j9YQAAAAASUVORK5CYII=')
    text='历史工具输出 old cwd\r\n'.encode('utf-8');checkpoint=b'\xff\x00checkpoint\x80'
    (side/'image.png').write_bytes(png);(side/'output.txt').write_bytes(text)
    custom=b'{"title":"sidecar title", "cwd":"unchanged sidecar metadata"}\r\n'
    (folder/sid/'custom-title.json').write_bytes(custom)
    check=home/'file-history'/sid;check.mkdir(parents=True);(check/'checkpoint.jsonl').write_bytes(checkpoint)
    rows=[{'type':'user','sessionId':sid,'version':'0.0.0-test','cwd':'old cwd','timestamp':'2026-11-01T00:00:00Z','message':{'content':'Image: source: '+str(side/'image.png')}}]
    data=('\r\n'.join(json.dumps(row,ensure_ascii=False) for row in rows)+'\r\n').encode('utf-8');source.write_bytes(data)
    snap=n.snapshot(source,home,include_checkpoints=True)
    assert {item['relative'] for item in snap['files'] if item.get('binary')}=={sid+'/tool-results/image.png',sid+'/checkpoint.jsonl'}
    package=root/'native-package';manifest=n.pack(snap,package)
    assert all(type(item['binary']) is bool for item in manifest['files'])
    loaded=n.load(package)
    dest=root/'target-project';dest.mkdir();target_home=root/'target-home'
    args=argparse.Namespace(cwd=str(dest),target_home=str(target_home),to='claude',dry_run=True,no_desktop=True,desktop_registry=None)
    result=n.restore(loaded,args)
    assert not target_home.exists() and result['binary_files']==2 and result['binary_bytes']==len(png)+len(checkpoint)
    assert any('2' in warning and str(len(png)+len(checkpoint)) in warning for warning in result['warnings'])
    assert any('absolute' in warning.lower() and 'unchanged' in warning.lower() for warning in result['warnings'])
    args.dry_run=False;result=n.restore(loaded,args)
    restored=next(target_home.glob('projects/*/'+sid+'.jsonl'))
    assert (restored.with_suffix('')/'tool-results/image.png').read_bytes()==png
    assert (restored.with_suffix('')/'tool-results/output.txt').read_bytes()==text
    assert (restored.with_suffix('')/'custom-title.json').read_bytes()==custom
    assert (target_home/'file-history'/sid/'checkpoint.jsonl').read_bytes()==checkpoint
    assert restored.read_bytes()==n.rewrite_cwd(data,'old cwd',str(dest.resolve()))
    assert str(side/'image.png') in json.loads(restored.read_text(encoding='utf-8'))['message']['content'], 'Source absolute reference must remain historical'
    rejected(lambda:n.restore(loaded,args),'already exists')
    # Unchanged project API must also carry the opaque bytes through its native package.
    project=root/'project';project.mkdir();(project/'main.txt').write_text('synthetic project',encoding='utf-8')
    source.write_bytes(n.rewrite_cwd(data,'old cwd',str(project.resolve())))
    project_package=root/'project-package'
    p.pack('claude',project,project_package,home,[{'snapshot':str(source),'title':'binary project'}],native=True,include_checkpoints=True)
    project_target=root/'project-target';project_home=root/'project-home'
    state=p.restore(project_package,project_target,'claude',project_home,True)
    again=next(project_home.glob('projects/*/'+sid+'.jsonl'))
    assert state['mode']=='claude-native' and (again.with_suffix('')/'tool-results/image.png').read_bytes()==png
    assert (project_home/'file-history'/sid/'checkpoint.jsonl').read_bytes()==checkpoint
    # Binary flags are validated from bytes, never trusted to bypass text checks.
    args.target_home=str(root/'untouched');args.dry_run=True
    wrong=copy.deepcopy(loaded);next(item for item in wrong['files'] if item.get('binary'))['binary']=False
    rejected(lambda:n.plan(wrong,args),'binary');assert not Path(args.target_home).exists()
    private_header=('-----BEGIN '+'PRIVATE KEY-----').encode('utf-8')
    secret=side/'secret.txt';secret.write_bytes(private_header)
    rejected(lambda:n.snapshot(source,home),'credential');secret.unlink()
    forged=copy.deepcopy(loaded);item=next(item for item in forged['files'] if item['relative'].endswith('output.txt'))
    item.update(data=private_header,sha256=n.sha(private_header),binary=True)
    rejected(lambda:n.plan(forged,args),'credential')
    # Text under a binary-looking suffix is still scanned; forbidden names reject binary too.
    secret=side/'secret.png';secret.write_bytes(private_header)
    rejected(lambda:n.snapshot(source,home),'credential');secret.unlink()
    forbidden=side/'credentials.json';forbidden.write_bytes(png)
    rejected(lambda:n.snapshot(source,home),'Credential/configuration');forbidden.unlink()
    rejected(lambda:n.check_payload(png,'session.jsonl',True,allow_binary=True),'UTF-8')
    memory=folder/'memory';memory.mkdir();(memory/'binary.bin').write_bytes(png)
    rejected(lambda:n.snapshot(source,home,include_memory=True),'binary')
    with test_link(side/'alias.png',side/'image.png'):rejected(lambda:n.snapshot(source,home),'symlink')
    # Package links must be rejected even when their target remains inside the package.
    image_record=next(item for item in manifest['files'] if item.get('binary') and item['scope']=='project')
    image_path=package/image_record['path'];image_path.unlink();other=image_path.with_name('other.png');other.write_bytes(png)
    with test_link(image_path,other):rejected(lambda:n.load(package),'symlink')
    image_path.write_bytes(png)
    # The hash check still catches opaque tampering, independent of the binary marker.
    image_path.write_bytes(png+b'changed');rejected(lambda:n.load(package),'hash mismatch');image_path.write_bytes(png)
    record=next(item for item in manifest['files'] if item.get('binary'));record['binary']=False
    (package/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    rejected(lambda:n.load(package),'binary')
    # Old all-text native manifests without binary fields remain readable.
    legacy=copy.deepcopy(snap);legacy['files']=[item for item in legacy['files'] if not item.get('binary')]
    for item in legacy['files']:item.pop('binary',None)
    old=root/'legacy';n.pack(legacy,old)
    assert all(item.get('binary') is False for item in n.load(old)['files'])
print('PASS: binary sidecars/checkpoints byte roundtrip and project restore, flags/counts/warnings, text secrets, symlinks, tamper/collision refusal, legacy text compatibility')
