# Agent Rehome

Version **0.6.0** · [中文](README.md) · [MIT](LICENSE)

If you've spent weeks working on a project inside one coding agent—building up context across dozens of turns—and want to switch to another tool or move to a new computer, you usually end up starting a blank chat and explaining the project all over again.

Agent Rehome avoids that reset. It reads the conversation history stored locally on your machine and writes it into the target app's local storage, bringing your project files and attachments along with it. Once moved, your old chats show up in the target app's sidebar under the right project, so you can open them and pick up where you left off.

Because everything comes from local files on disk, the old app doesn't need to be open, signed in, or have any quota left. Your original conversations stay untouched where they are, and the scripts back up affected target files before writing anything.

## Supported apps

Agent Rehome works on Windows and macOS, whether you're switching between different apps on the same computer or moving the same app to a new machine:

| App | Windows | macOS | Where to put the Skill folder |
| --- | --- | --- | --- |
| **Codex** (ChatGPT Desktop / CLI) | Yes | Yes | `~/.agents/skills/agent-rehome/` or `~/.codex/skills/agent-rehome/` |
| **Claude Code** | Yes | Yes | `~/.claude/skills/agent-rehome/` |
| **WorkBuddy** | Yes | Yes | `~/.workbuddy/skills/agent-rehome/` (or workspace receive) |
| **DeepSeek Harness** (`dsh`) | Yes | Depends on architecture/runtime (see [DSH notes](docs/DSH_RUNTIME.md)) | `~/.dsh/skills/agent-rehome/` |
| **Antigravity Desktop** | Yes | Yes | `~/.gemini/antigravity/skills/agent-rehome/` |

Each app stores local sessions very differently. For exact version coverage and route-by-route limitations, check the [validation record](docs/VALIDATION.md).

## How to use it

Agent Rehome is packaged as a Skill for your agent to read and run, so you normally don't need to type CLI flags yourself.

1. **Drop the Skill into the target agent**
   Download the latest archive from [Releases](https://github.com/CalebYcj/agent-rehome/releases/latest), unzip it, and place the `agent-rehome` folder inside the skills directory of **the agent you are moving to** (see the table above). You can also just paste this repository URL into the target agent and ask it to install the Skill for you.

2. **Make sure Python 3.10+ is available**
   Uncompressed histories only use the Python standard library (an optional `zstd` decoder is only needed if you have older compressed `.zst` logs). If you aren't sure what version is installed, let your agent check.
   <details>
   <summary>Note on Python for macOS</summary>

   On macOS, `python3` may prompt to install Apple's developer tools or point to an older 3.9 build. Run `python3 --version` to check. If it's older than 3.10, install a current release from [python.org](https://www.python.org/downloads/macos/) without modifying Apple's system Python.
   </details>

3. **Tell the new agent what to move**
   In the receiving agent, ask in plain language—for example:
   `Use Agent Rehome to move my Codex projects here` (or name a specific project, or swap in Claude, WorkBuddy, DSH, or Antigravity).
   The agent will scan your local history and show you a preview first; nothing is written until you confirm. If you're moving from another computer, copy the old agent's data folder (`.codex`, `.claude`, `.workbuddy`, `.dsh`, or `.gemini/antigravity`) and your project folders over first, then tell the agent where you put them.

4. **Reopen the app and continue**
   Most desktop clients read their session index on startup or require closing the app briefly to register offline changes. Follow the agent's final prompt to restart the app, verify the conversation appears under your project in the sidebar, and keep going.

## What else can move with your chats

- **Batch moves, global rules, and personal Skills**: When moving all projects out of an app at once, Agent Rehome can also pack your global instructions (`~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`) and personal Skills you installed yourself. Restore only previews them—nothing is installed until you opt in, and existing files with the same name are never overwritten.
- **Reference mode for large repos**: If a project directory is huge, copy the folder yourself and pack with `--files reference`. The package carries only the chats, attachments, and SHA-256 file manifest, then checks for missing or modified files on the destination.

## Good to know beforehand

- **Keep migration packages private**: A package contains your full chat transcripts and project source files. Treat it like a local backup—don't upload it to public repositories or shared links.
- **App updates can change storage formats**: Because Agent Rehome writes directly to local databases and session files, a future app update may change an internal schema before this tool catches up. Automatic pre-write backups are saved under `rehome-backups/` in the target data root, and per-project receipts live in `.rehome/`.
- **Cross-agent moves carry visible history only**: Moving within the same app preserves native records where possible; moving between different apps converts chats through a neutral format. Internal reasoning blocks, encrypted compaction records, login sessions, and folder trust approvals are not carried over—anything omitted is logged in `.rehome/losses/` rather than dropped silently. `.mcp.json` files are quarantined under `.rehome/surroundings/originals/` so moved projects won't auto-connect to external servers behind your back.

## Documentation and CLI reference

For protocol details, route-specific evidence, or running the scripts directly from a terminal:

- [Platform validation record](docs/VALIDATION.md)
- [Exchange specification](SPEC.md)
- [Codex project grouping and cwd notes](docs/CODEX_PROJECT_BINDING.md)
- [DeepSeek Harness runtime guide](docs/DSH_RUNTIME.md) · [Interrupted move recovery](docs/RECOVERY.md)

<details>
<summary>Expand manual CLI commands and test suite</summary>

Preview operations with `--dry-run` first, then re-run without `--dry-run` once the summary looks right. For a read-only environment check:

```bash
python3 -B scripts/doctor.py
```

**1. Move every project at once**

```bash
python scripts/batch_rehome.py list --from all
python scripts/batch_rehome.py move --from codex --to claude --root "<new-parent-dir>" --dry-run
python scripts/batch_rehome.py move --from codex --to claude --root "<new-parent-dir>"

# Optional: review and apply carried global rules and personal Skills
python scripts/global_rules.py install "<batch-package-dir>" --to claude --apply
python scripts/user_skills.py install "<batch-package-dir>" --to claude --apply
```

**2. Pack and restore a single project (Codex / Claude Code)**

```bash
# Portable cross-agent package (add --native for same-agent relocation)
python scripts/project_rehome.py pack --from codex --project "<source-project>" --out "<new-package-dir>"
python scripts/project_rehome.py restore "<package-dir>" --to claude --cwd "<new-project-dir>" --dry-run

# Large repositories: carry conversations + file checksum manifest only
python scripts/project_rehome.py pack --from codex --project "<source-project>" --out "<new-package-dir>" --files reference
python scripts/project_rehome.py restore "<package-dir>" --to codex --cwd "<copied-project-dir>" --strict-files --dry-run
```

**3. Move a single conversation**

```bash
python scripts/agent_rehome.py transfer --from "claude:<session-id-or-jsonl>" --to codex --cwd "<existing-target-project>" --dry-run
```

**4. WorkBuddy / DeepSeek Harness / Antigravity Desktop**

```bash
# WorkBuddy (export with project_rehome.py pack --from workbuddy)
python scripts/workbuddy_receive.py "<portable-package>" --cwd "<new-workspace>"
python scripts/workbuddy_native.py "<new-workspace>" --template-space "<existing-local-space-id>"

# DeepSeek Harness (export with project_rehome.py pack --from dsh; close DSH before offline registration)
python scripts/dsh_native.py "<portable-package>" --cwd "<new-project>" --dsh-home "<dsh-data-dir>"
python scripts/dsh_native.py --cwd "<new-project>" --dsh-home "<dsh-data-dir>" --register-offline "<backup-file>"

# Antigravity Desktop (export with project_rehome.py pack --from antigravity; quit app before --apply)
python scripts/antigravity_stage.py "<portable-package>" --cwd "<new-workspace>" --profile "<staging-profile>"
python scripts/antigravity_desktop.py --cwd "<new-workspace>" --project-id "<native-project-id>" --apply
```

**5. Self-tests and privacy scan**

Tests run against synthetic fixtures in isolated temporary `HOME` directories without network access or touching real agent data:

```bash
python -B scripts/run_tests.py
python -B scripts/privacy_scan.py .
```

</details>
