"""Desktop discovery uses mocked platforms and temporary homes only."""
import argparse,json,os,sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import agent_rehome as r

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);home=root/'home';home.mkdir()
    args=argparse.Namespace(target_home=None,no_desktop=False,desktop_registry=None,dry_run=True)
    mac=home/'Library/Application Support/Claude/claude-code-sessions'
    old=mac/'org-old/account';recent=mac/'org-new/account'
    for folder,stamp in ((old,1000),(recent,2000)):
        folder.mkdir(parents=True)
        entry=folder/'local_fixture.json';entry.write_text(json.dumps({'model':'fixture-model','effort':'medium'}),encoding='utf-8')
        os.utime(entry,(stamp,stamp))
    windows=root/'local/Claude-Data/profile/claude-code-sessions/org/account'
    windows.mkdir(parents=True);(windows/'local_fixture.json').write_text('{}',encoding='utf-8')
    with patch.object(Path,'home',return_value=home),patch.dict(os.environ,{'LOCALAPPDATA':str(root/'local')}):
        with patch.object(sys,'platform','darwin'):
            assert r.desktop_registry_dir(args)==recent
            # Directory timestamps cannot override the newest registry file timestamp.
            os.utime(old,(3000,3000));assert r.desktop_registry_dir(args)==recent
            entry=old/'local_latest.json';entry.write_text('{"model":"new-model"}',encoding='utf-8');os.utime(entry,(4000,4000))
            assert r.desktop_registry_dir(args)==old
            assert r.desktop_model(args)=='new-model'
            sid='12345678-1234-4567-8123-123456789012';bundle={'title':'fixture','turns':[None]}
            planned=Path(r.register_desktop(bundle,args,sid,str(root/'project')))
            assert planned.parent==old and not planned.exists()
            args.dry_run=False;r.register_desktop(bundle,args,sid,str(root/'project'))
            record=json.loads(planned.read_text(encoding='utf-8'))
            assert record['model']=='new-model' and record['permissionMode']=='default' and record['completedTurns']==1
            args.target_home=str(root/'custom-home');assert r.desktop_registry_dir(args) is None
            args.desktop_registry=str(recent);assert r.desktop_registry_dir(args)==recent
            args.no_desktop=True;assert r.desktop_registry_dir(args) is None
            args.no_desktop=False;args.desktop_registry=None;args.target_home=None
        with patch.object(sys,'platform','win32'):assert r.desktop_registry_dir(args)==windows
        with patch.object(sys,'platform','linux'):assert r.desktop_registry_dir(args) is None
    empty=root/'empty-home';empty.mkdir()
    with patch.object(Path,'home',return_value=empty),patch.object(sys,'platform','darwin'):
        assert r.desktop_registry_dir(args) is None and not (empty/'Library').exists()
print('PASS: Mac/Windows latest-file discovery, empty/unsupported platforms, explicit/custom-home/no-desktop guards, isolated registration')
