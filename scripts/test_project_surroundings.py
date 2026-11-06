"""Four project routes, immutable originals, collisions, secrets and inactive commands."""
import contextlib,io,json,sqlite3,sys,tempfile,uuid
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import project_rehome as p,project_surroundings as s

def refuses(fn,fragment):
    try:fn()
    except ValueError as error:assert fragment in str(error),str(error)
    else:raise AssertionError('Unsafe config accepted')

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory).resolve();project=root/'source';project.mkdir();source_home=root/'source-home';source_home.mkdir()
    entries={'CLAUDE.md':b'Claude fixture @notes.md\n','nested/AGENTS.md':b'Codex fixture\n',
        'both/CLAUDE.md':b'keep Claude','both/AGENTS.md':b'keep Codex',
        '.claude/settings.json':json.dumps({'model':'fixture','hooks':{'fixture':[{'command':'fixture-never-run'}]},'permissions':{'allow':['fixture']}}).encode(),
        '.claude/settings.local.json':b'local must not copy',
        '.claude/skills/new/SKILL.md':b'original skill',' .unused':b'ordinary',
        '.claude/skills/new/resource.bin':b'\x00\xfffixture',
        '.claude/skills/collision/SKILL.md':b'Claude collision',
        '.agents/skills/collision/SKILL.md':b'Codex collision',
        '.agents/skills/other/SKILL.md':b'other skill',
        '.claude/commands/fixture.md':b'command definition','.claude/agents/fixture.md':b'agent definition',
        '.claude/hooks/fixture':b'hook script','.claude/unknown/data':b'unknown',
        '.claude/auth.json':b'credential excluded','.claude/skills/new/token.json':b'excluded-token',
        '.claude/skills/new/cache/log':b'excluded-cache',
        '.codex/config.toml':b'model = "fixture"\n','.codex/sessions/cache.json':b'cache',
        '.mcp.json':json.dumps({'mcpServers':{'fixture':{'command':'fixture-command','args':['fixture-arg'],'env':{'PRIVATE_FIXTURE':'DO_NOT_REPORT'}}}}).encode()}
    for rel,data in entries.items():
        path=project/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    (project/'.claude/skills/empty').mkdir();(project/'.agents/skills/empty').mkdir(parents=True)
    for source,target in [('claude','claude'),('codex','codex'),('claude','codex'),('codex','claude')]:
        route=source+'-'+target;package=root/(route+'-package');home=root/(route+'-home');home.mkdir()
        with closing(sqlite3.connect(home/'state_5.sqlite')) as db:db.executescript((Path(__file__).parent/'fixtures/codex_schema.sql').read_text())
        with contextlib.redirect_stdout(io.StringIO()):
            p.pack(source,project,package,source_home,selected_sessions=[],native=source==target)
            preview=p.restore(package,root/(route+'-preview'),target,home,True,dry_run=True)
            state=p.restore(package,root/(route+'-target'),target,home,True)
        dest=root/(route+'-target');report=state['surroundings']
        assert not (root/(route+'-preview')).exists() and preview['surroundings']==report
        assert (dest/'both/AGENTS.md').read_bytes()==entries['both/AGENTS.md']
        assert (dest/'both/CLAUDE.md').read_bytes()==entries['both/CLAUDE.md']
        assert not (dest/'.mcp.json').exists()
        assert (dest/'.rehome/surroundings/originals/.mcp.json').read_bytes()==entries['.mcp.json']
        assert any(item['reason']=='mcp-config-quarantined' and item['enable'] for item in report['manual'])
        assert 'DO_NOT_REPORT' not in json.dumps(report) and report['mcp_servers'][0]['command']=='fixture-command'
        assert report['user_level'] and any(item['reason']=='target-exists' for item in report['skipped'])==(source!=target)
        assert not (dest/'.claude/auth.json').exists() and not (dest/'.claude/settings.local.json').exists()
        assert not (dest/'.codex/sessions').exists()
        if source=='claude':
            assert json.loads((dest/'.claude/settings.json').read_text())=={'model':'fixture'}
            assert (dest/'.rehome/surroundings/originals/.claude/settings.json').read_bytes()==entries['.claude/settings.json']
            assert (dest/'.claude/commands/fixture.md').exists() and not (dest/'.claude/hooks').exists()
        if source==target=='codex':assert (dest/'.codex/config.toml').read_bytes()==entries['.codex/config.toml']
        if source=='claude' and target=='codex':
            assert (dest/'AGENTS.md').read_text(encoding='utf-8').startswith('<!-- 由 agent-rehome 根据 CLAUDE.md 生成 -->')
            assert (dest/'.agents/skills/new/resource.bin').read_bytes()==entries['.claude/skills/new/resource.bin']
            assert (dest/'.agents/skills/collision/SKILL.md').read_bytes()==b'Codex collision'
            assert report['references']==[{'path':'CLAUDE.md','reference':'notes.md'}]
            assert any(item['reason']=='source-command-or-agent-definition-not-converted' for item in report['manual'])
        if source=='codex' and target=='claude':
            assert (dest/'nested/CLAUDE.md').read_bytes()==b'@AGENTS.md\n'
            assert (dest/'.claude/skills/other/SKILL.md').read_bytes()==b'other skill'
            assert (dest/'.claude/skills/collision/SKILL.md').read_bytes()==b'Claude collision'
        assert (dest/'.agents/skills/empty').is_dir() and (dest/'.claude/skills/empty').is_dir()
    # Both archive namespaces travel as inert originals on a second leg.
    intermediate=root/'claude-claude-target'
    archive='.rehome/surroundings/originals/'
    codex_original=intermediate/(archive+'.codex/config.toml')
    codex_original.parent.mkdir()
    codex_original.write_bytes(b'[mcp_servers.fixture]\ncommand="fixture"\n')
    (codex_original.parent/'auth.json').write_text('excluded fixture')
    returned=root/'returned-project'
    with contextlib.redirect_stdout(io.StringIO()):
        p.pack('claude',intermediate,root/'return-package',source_home,selected_sessions=[])
        p.restore(root/'return-package',returned,'claude',root/'return-home',True)
    assert (returned/(archive+'.claude/settings.json')).read_bytes()==entries['.claude/settings.json']
    assert json.loads((returned/'.claude/settings.json').read_text())=={'model':'fixture'}
    assert (returned/(archive+'.codex/config.toml')).read_bytes()==codex_original.read_bytes()
    assert not (returned/'.codex/config.toml').exists()
    assert not (returned/(archive+'.codex/auth.json')).exists()
    # Empty projects must still attempt native registration; no target DB is needed.
    empty_package=root/'empty-registration-package'
    with contextlib.redirect_stdout(io.StringIO()):
        p.pack('claude',project,empty_package,source_home,selected_sessions=[])
    empty_home=root/'empty-registration-home';empty_home.mkdir()
    for label,registration in [('ready',{'registered':True,'project_id':'fixture-project'}),
                               ('pending',{'registered':False,'reason':'fixture registration unavailable'})]:
        destination=root/('empty-registration-'+label)
        with patch('codex_project_registry.live_home',return_value=True),patch('codex_project_registry.desktop_running',return_value=True),patch('codex_project_registry.native_project',return_value=registration) as native,contextlib.redirect_stdout(io.StringIO()):
            state=p.restore(empty_package,destination,'codex',empty_home)
        native.assert_called_once_with(empty_home,str(destination),[])
        assert state['desktop_project_registry']['registered']==registration['registered']
        assert state['desktop_project_registry']['thread_binding_required']==[]
        assert json.loads((destination/'.rehome/restore.json').read_text())['desktop_project_registry']==state['desktop_project_registry']
    with patch('codex_project_registry.register',side_effect=AssertionError('preview/disabled registration called')),contextlib.redirect_stdout(io.StringIO()):
        p.restore(empty_package,root/'empty-registration-preview','codex',empty_home,dry_run=True)
        disabled=p.restore(empty_package,root/'empty-registration-disabled','codex',empty_home,no_desktop=True)
    assert disabled['desktop_project_registry']['registered'] is False
    assert disabled['desktop_project_registry']['thread_binding_required']==[]
    assert not (root/'empty-registration-preview').exists() and not (empty_home/'state_5.sqlite').exists()
    # The existing credential feature is conservative; overrides list paths, never matching values.
    key='sk-'+'a'*24
    for rel in ('.mcp.json','.claude/settings.json','.codex/config.toml'):
        path=project/rel;before=path.read_bytes();path.write_text(key)
        agent='codex' if rel.startswith('.codex') else 'claude'
        with contextlib.redirect_stdout(io.StringIO()):
            refuses(lambda:p.pack(agent,project,root/('secret-'+path.name),source_home,selected_sessions=[]),'--allow-secrets-in-config')
            assert not (root/('secret-'+path.name)).exists()
            p.pack(agent,project,root/('override-'+path.name),source_home,selected_sessions=[],allow_secrets_in_config=True)
        assert rel in p.load_manifest(root/('override-'+path.name))['surroundings']['config_secret_overrides']
        path.write_bytes(before)
    payload={'.codex/config.toml':b'[mcp_servers.fixture]\ncommand="fixture"\n'}
    result,report=s.bridges(payload,'codex','codex')
    assert '.codex/config.toml' not in result and result['.rehome/surroundings/originals/.codex/config.toml']==payload['.codex/config.toml']
    result,report=s.bridges({'.mcp.json':b'not JSON'},'claude','claude')
    assert '.mcp.json' not in result and result['.rehome/surroundings/originals/.mcp.json']==b'not JSON'
    refuses(lambda:s.bridges({'.mcp.json':b'{}','.rehome/surroundings/originals/.mcp.json':b'keep'},'claude','codex'),'archive collision')
print('PASS: four routes; rules/skills and empty directories; no overwrites; inactive hooks/permissions; MCP env omission; config-secret refusal/override; no user assets')
