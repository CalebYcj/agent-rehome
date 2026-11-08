"""Global rules (main persona): pack with a credential scan, preview, install without replacing the target's own file."""
import contextlib, io, json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import global_rules as g, batch_rehome as b

RULES = '# 我的习惯\n\n- 用简体中文回答。\n- 你是 Codex，改代码前先跑测试，用 apply_patch。\n- 回答先给结论。\n'

with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp)
    codex, claude = d / 'codex', d / 'claude'
    codex.mkdir(); claude.mkdir()
    assert g.pack('codex', d / 'none', codex)['status'] == 'none'
    (codex / 'AGENTS.md').write_text(RULES, encoding='utf-8')
    (codex / 'AGENTS.override.md').write_text('   \n', encoding='utf-8')
    assert g.source_file('codex', codex).name == 'AGENTS.md', 'Blank override is ignored'

    packed = g.pack('codex', d / 'pkg', codex)
    assert packed['status'] == 'packed' and packed['source_file'] == 'AGENTS.md'
    assert [m['line'] for m in packed['mentions']] == [4], packed['mentions']
    assert {'Codex', 'apply_patch'} <= set(packed['mentions'][0]['words'])

    # Codex -> Claude: copy plus one import line; the user's own CLAUDE.md text is kept.
    (claude / 'CLAUDE.md').write_text('# 已有规则\n保持简短。', encoding='utf-8')
    before = (claude / 'CLAUDE.md').read_bytes()
    preview = g.install(d / 'pkg', 'claude', claude)
    assert preview['status'] == 'planned' and (claude / 'CLAUDE.md').read_bytes() == before, 'Preview writes nothing'
    assert not (claude / 'rehome').exists() and preview['warnings'] and preview['undo']
    done = g.install(d / 'pkg', 'claude', claude, apply=True)
    assert done['status'] == 'installed'
    text = (claude / 'CLAUDE.md').read_text(encoding='utf-8')
    assert text.startswith('# 已有规则\n保持简短。\n\n') and text.rstrip().endswith('@rehome/global-rules-from-codex.md')
    assert (claude / 'rehome' / 'global-rules-from-codex.md').read_text(encoding='utf-8') == RULES
    assert (Path(done['backup']) / 'CLAUDE.md').read_bytes() == before
    assert g.install(d / 'pkg', 'claude', claude, apply=True)['status'] == 'already_installed', 'Idempotent'
    (claude / 'rehome' / 'global-rules-from-codex.md').write_text('改过的', encoding='utf-8')
    try: g.install(d / 'pkg', 'claude', claude)
    except ValueError as e: assert 'different text' in str(e)
    else: raise AssertionError('Changed copy overwritten')

    # Claude -> Codex: appended inside markers; @imports reported, not expanded.
    src = d / 'claude-src'; src.mkdir()
    (src / 'CLAUDE.md').write_text('用中文。\n@~/.claude/extra.md\n参见 `@not-import`。\n', encoding='utf-8')
    packed = g.pack('claude', d / 'pkg2', src)
    assert packed['imports_not_included'] == ['~/.claude/extra.md'], packed['imports_not_included']
    target = d / 'codex2'; target.mkdir()
    (target / 'AGENTS.md').write_text('原有规则', encoding='utf-8')
    done = g.install(d / 'pkg2', 'codex', target, apply=True)
    text = (target / 'AGENTS.md').read_text(encoding='utf-8')
    assert text.startswith('原有规则\n\n<!-- agent-rehome:global-rules:begin from=claude ') and text.endswith('<!-- agent-rehome:global-rules:end -->\n')
    assert '@~/.claude/extra.md' in text and any('not copied' in w for w in done['warnings'])
    assert g.install(d / 'pkg2', 'codex', target)['status'] == 'already_installed'
    # A non-empty override is what Codex reads, so the block goes there.
    t3 = d / 'codex3'; t3.mkdir(); (t3 / 'AGENTS.override.md').write_text('覆盖', encoding='utf-8')
    g.install(d / 'pkg2', 'codex', t3, apply=True)
    assert 'agent-rehome:global-rules:begin' in (t3 / 'AGENTS.override.md').read_text(encoding='utf-8') and not (t3 / 'AGENTS.md').exists()

    # Credentials stop the pack; a tampered package is refused.
    bad = d / 'bad'; bad.mkdir(); (bad / 'CLAUDE.md').write_text('key sk-' + 'a' * 30, encoding='utf-8')
    try: g.pack('claude', d / 'pkg3', bad)
    except ValueError as e: assert 'secret' in str(e)
    else: raise AssertionError('Credential packed')
    (d / 'pkg' / 'global-rules' / 'rules.md').write_text('tampered', encoding='utf-8')
    try: g.plan(d / 'pkg', 'claude', d / 'c4')
    except ValueError as e: assert 'checksum' in str(e)
    else: raise AssertionError('Tampered package accepted')

    # Batch: packed alongside the projects; restore only previews it.
    with contextlib.redirect_stdout(io.StringIO()):
        record = b.batch_pack('codex', d / 'batch', 'claude', codex)
        assert record['global_rules']['status'] == 'packed' and record['global_rules']['mentions'] == 1
        out = b.batch_restore(d / 'batch', 'claude', d / 'root', d / 'c5', dry_run=True)
        skipped = b.batch_pack('codex', d / 'batch2', 'claude', codex, global_rules=False)
    assert out['global_rules']['status'] == 'planned' and '--apply' in out['global_rules_next'] and not (d / 'c5').exists()
    assert 'global_rules' not in skipped and not (d / 'batch2' / 'global-rules').exists()
print('PASS: global rules pack/scan, preview-only default, Claude import line, Codex marked block and override, idempotency, refusals, batch preview')
