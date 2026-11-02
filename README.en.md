# Agent Rehome

Version **0.2.0-mac-preview.1** · [中文](README.md) · [MIT](LICENSE)

Migrate visible Claude Code ↔ Codex conversation history into native target sessions. Project snapshots can include files, multiple conversations, recoverable attachments and destination path rebinding.

This is an unofficial third-party tool, not an Anthropic or OpenAI product. It writes application data directly. Application updates may break compatibility. Keep backups; never publish packages containing private conversations or source files.

macOS test candidate: portable paths, SQLite URIs, foreign attachment names and POSIX permissions are prepared; native macOS acceptance is pending. See [MAC_TEST.md](MAC_TEST.md) and start with `python3 -B scripts/doctor.py`.

## Requirements and installation

Python 3.10+, standard library only. Initialize the target application first; Codex needs a compatible existing `state_5.sqlite`. Tested only on Windows with Claude Code 2.1.309, Codex CLI 0.166.0-alpha.5.1 and Windows Codex desktop 26.1027.3384.0. macOS/Linux desktop registration is unverified.

Copy this entire folder to `~/.claude/skills/agent-rehome/` for Claude Code, or `~/.agents/skills/agent-rehome/` for Codex. Back up an existing skill before replacing it. Alternatively, run scripts directly from this directory. Test source repository (no stable Release):

```text
git clone https://github.com/CalebYcj/agent-rehome.git
cd agent-rehome
```

This is a macOS test preview, not a claim of native macOS acceptance. Follow MAC_TEST.md.

## A conversation

Replace every placeholder; the destination project folder must exist.

```text
python scripts/agent_rehome.py transfer --from "claude:<session-id-or-jsonl>" --to codex --cwd "<target-project>" --dry-run
python scripts/agent_rehome.py transfer --from "claude:<session-id-or-jsonl>" --to codex --cwd "<target-project>"
python scripts/agent_rehome.py transfer --from "codex:<session-id-or-rollout>" --to claude --cwd "<target-project>"
```

Model/version settings are read from the target configuration/history. If unavailable, supply `--model "<target-model>"`, or `--claude-model "<target-model>" --claude-version "<installed-version>"`. Values are never guessed. `--source-home` and `--target-home` select Agent data roots, not project folders. Use `--new-copy` for a new snapshot after source history changes; existing imports are protected.

## Projects and another computer

```text
python scripts/project_rehome.py pack --from codex --project "<source-project>" --out "<new-package-directory>"
python scripts/project_rehome.py restore "<package-directory>" --to claude --cwd "<new-project>"
```

Use a new package directory outside the source project and a new destination directory. Move the package to the other computer before restoring. `pack --source-home "<copied-agent-home>"` supports copied source data. For an explicit session inventory, pass `--sessions-json "<inventory.json>"` containing `[{"snapshot":"<native-jsonl-path>","title":"<title>"}]`. Codex project inventories reject previously imported Codex copies as native sources.

Single-session portable export/import:

```text
python scripts/agent_rehome.py export --from "claude:<session-id>" --source-home "<copied-claude-home>" --out "<transcript.json>"
python scripts/agent_rehome.py import "<transcript.json>" --to codex --cwd "<target-project>" --dry-run
```

Inspect the preview, then remove `--dry-run`. Same-machine handoffs can use local paths directly.

## Opening and desktop fallback

Claude desktop registration is auto-detected only on Windows. Restart the desktop normally to load registration, then approve directory trust yourself if prompted. The tool does not restart applications or copy login credentials. `--target-home` needs an explicit `--desktop-registry "<verified-directory>"` for desktop registration. Missing registration produces warnings; `--no-desktop` intentionally writes history only. CLI authentication may differ from desktop authentication.

Codex scripts independently write history/index/database/archive files. Windows project restoration can try the running desktop folder-open entry. Complete sidebar grouping needs an Agent inside Codex APP with native `list_projects`, `move_thread_to_project`, and `list_threads` tools. Without these tools, restore with `--no-desktop`, then add the folder and associate chats manually in Codex APP. File restoration is not proof of sidebar grouping or native continuation.

## Limits and recovery

- Long sessions use a conservative default budget of64000, a narrative summary and complete trailing turns. Full history remains in the session and `.rehome/history/`; exact details may require reading the archive. Estimates are not official tokenizer counts.
- Native command card appearance depends on target version/interface mode. Visible history is preserved, not pixel-identical product layouts.
- Missing attachments cannot be recreated unless embedded historically. Text snapshots may be excerpts. Recoverable attachments are placed in `.rehome/attachments/` with paths rebound.
- Credentials, account state, permissions, hidden reasoning, encrypted model state, Git history and installed dependencies are not transferred. Historical tasks/permissions are not current authorization. Common secret-file exclusions are not exhaustive secret detection.
- Cross-platform desktop registration, directory trust inheritance, all branches/extensions and future format compatibility are not guaranteed.

Imports back up touched existing files; SQLite uses online backup. Keep the returned backup path, `rehome-imports/` manifests and project `.rehome/restore.json`. There is no automatic rollback command. Stop target writes and preserve newer content before restoring specific backed-up files. Do not overwrite a shared database/index with an older copy that would remove unrelated new chats. Partial batches retain diagnostics rather than claiming an atomic rollback.

## Tests and privacy checks

```text
python -B scripts/run_tests.py
python -B scripts/privacy_scan.py .
```

Each test runs with a new temporary HOME, synthetic fixtures and guarded filesystem/database writes. Real Agent data, network access and external process launches are blocked. No Agent login is needed. The privacy scanner checks user-home absolute paths, emails, non-fixture session IDs and common credential patterns; review additional files before publishing.
