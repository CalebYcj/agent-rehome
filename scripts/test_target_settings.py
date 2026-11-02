"""Target detection and failure paths use only synthetic, isolated data."""
import argparse, json, sqlite3, sys, tempfile, uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_rehome as r
import project_rehome as projects
import codex_project_registry as registry
from target_settings import codex_model, claude_settings

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);home=root/'target';home.mkdir()
    for operation, flag in ((lambda:codex_model(home),'--model'), (lambda:claude_settings(home),'--claude-model')):
        try: operation()
        except ValueError as error: assert flag in str(error)
        else: raise AssertionError('Missing target settings silently defaulted')
    (home/'config.toml').write_text('model = "configured-model"\n[profiles.other]\nmodel = "unrelated-model"',encoding='utf-8')
    assert codex_model(home)=='configured-model' and codex_model(home,'explicit-model')=='explicit-model'
    (home/'config.toml').unlink()
    database=home/'state_5.sqlite'
    with sqlite3.connect(database) as db:
        db.executescript((Path(__file__).parent/'fixtures/codex_schema.sql').read_text())
        db.execute('insert into threads(id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,sandbox_policy,approval_mode,cli_version,first_user_message,memory_mode,model,updated_at_ms) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('fixture','fixture',0,0,'fixture','fixture','fixture','fixture','{}','fixture','test','fixture','enabled','history-model',1))
    db.close()
    assert codex_model(home)=='history-model'
    rows=home/'projects/fixture';rows.mkdir(parents=True)
    (rows/'fixture.jsonl').write_text(json.dumps({'version':'0.0.0-fixture','message':{'model':'history-claude'}})+'\n')
    assert claude_settings(home)==('history-claude','0.0.0-fixture')
    (home/'settings.json').write_text('{"model":"configured-claude"}')
    assert claude_settings(home)==('configured-claude','0.0.0-fixture')
    assert claude_settings(home,'explicit-claude','explicit-version')==('explicit-claude','explicit-version')
    project=root/'project';project.mkdir()
    bundle={'schema':'agent-transcript/v1','source':{'agent':'codex','session_id':str(uuid.uuid4())},
        'title':'Synthetic conversation','project':{'cwd':'fixture'},'turns':[{'user':{'ts':'2000-01-01T00:00:00Z','text':'Synthetic request'},'items':[]}]}
    args=argparse.Namespace(cwd=str(project),target_home=str(home),to='claude',dry_run=True,no_desktop=False,desktop_registry=None,claude_model=None,claude_version=None)
    with patch.object(r,'desktop_registry_dir',return_value=None):
        # The missing desktop registration is reported in both preview and result.
        r.import_bundle(bundle,args)
        args.dry_run=False;result=r.import_bundle(bundle,args)
        assert result['warnings'] and 'Windows' in result['warnings'][0] and result['desktop_registry'] is None
    with patch.object(registry,'live_home',return_value=True), patch.object(registry,'desktop_running',side_effect=RuntimeError('Platform not supported')):
        fallback=registry.register(home,'fixture','fixture','fixture',[])
        assert not fallback['registered'] and 'manually' in fallback['next']
    package=root/'package';package.mkdir()
    (package/'manifest.json').write_text(json.dumps({'schema':'agent-project/v1','files':[],'attachments':[],'conversations':[bundle]}))
    destination=root/'must-not-exist'
    try: projects.restore(package,destination,'claude',root/'empty-target',True)
    except ValueError as error: assert '--claude-model' in str(error)
    else: raise AssertionError('Missing target settings accepted')
    assert not destination.exists()
print('PASS: target configuration/history/explicit settings, no guessed model or version, registration warnings, desktop fallback, project preflight')
