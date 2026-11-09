# Agent Rehome

Version **0.5.1** · [中文](README.md) · [MIT](LICENSE)

Move your Codex and Claude Code conversations and projects to another agent, and keep going.

Spent months on a project in Codex and want to continue in Claude? No need to explain it all again. Install this Skill in the new agent and say "move my Codex projects over". Chat history, images and project files move together, and the new agent picks up where you left off. The old agent does not need to be open, or even have quota left: what moves is the local history on your computer.

- Codex → Claude, Claude → Codex, and same-agent moves
- Windows and macOS, including moving to another computer
- A single conversation or a whole project
- Your original conversation stays where it is
- Free and open source (MIT)

## Quick start

1. **Install the Skill**: download the latest [Release](https://github.com/CalebYcj/agent-rehome/releases/latest), unzip it, and put the `agent-rehome` folder in:
   - Claude Code: `~/.claude/skills/agent-rehome/`
   - Codex: `~/.agents/skills/agent-rehome/`

   Installing it in the agent you are moving to is enough. You can also send this repository link to your agent and ask it to install the Skill by these instructions.
2. **Have Python 3.10+**: if it is missing, the agent tells you where to get it.
3. **Say one sentence**: in the new agent, say: `Use Agent Rehome to move all my Codex projects here` (or Claude, the other way round). It lists them for you to confirm, then moves them in one go.
4. **New computer**: copy the old `.codex` or `.claude` folder and your project folders over first, then tell the agent where they are.
5. **Keep going**: follow the agent's prompts for the last step or two, then open the moved conversation and continue.

If the old computer also has the Skill, the two-step way still works: say "pack" in the old agent and "receive this package" in the new one.

> Packages contain your private conversations and project files. Don't upload them anywhere public. Moving writes application data, so keep a backup.

Command-line usage and technical details follow.

---

### Large projects and reference inventories

Full copies are limited by destination capacity. Pack and restore estimate writes for files, attachments, histories and backups by filesystem and reserve 64 MiB per filesystem. Errors report the shortfall. Estimates use logical bytes and may include the full size of sparse files. The legacy `--allow-large` flag remains accepted.

For very large projects, move the project directory separately and use `pack --files reference`. The package carries sessions, supported surroundings and session attachments, plus relative paths, sizes and SHA-256 hashes for the project inventory. Restore with `--cwd` pointing at the existing project. It reports missing, extra and changed paths within the same inclusion rules. Existing project files are kept. Missing surroundings can be installed. `--strict-files` stops before writing on differences. Use a preview.2-compatible tool on both ends.

```text
python scripts/project_rehome.py pack --from codex --project "<source>" --out "<package>" --native --files reference
python scripts/project_rehome.py restore "<package>" --to codex --cwd "<already-copied-project>" --strict-files --dry-run
```

Git directories are excluded by default. `--include-git` copies them in full-copy mode or lists them in reference mode. Preview reports their byte total. Clean suspected credentials or external includes from Git configuration before packing. Git worktree pointer files are excluded.

Project files and attachment assets are copied and hashed in bounded blocks. Images over 16 MiB in converted projects keep their bytes and use a file reference. Session JSON, native histories and native sidecars retain their writer-specific memory requirements. Structured project configuration uses a separate 8 MiB parser budget.

The release archive uses ZIP64 and UTF-8 entry names. `CHECKSUMS.json` covers every release payload file other than itself.

Native Claude returns now offer explicit `--new-copy` (deterministic fresh owned IDs, matching structured sessionId values, sidecar/checkpoint directory names and desktop registration) or `--fast-forward` (verified existing record prefix, ignoring only top-level cwd; append new rows into the original session/cwd). Neither overwrites divergent history. Unchanged histories are no-ops; conflicting sidecars are refused. Preview reports append counts. Project files still go to a new --cwd while fast-forwarded history stays in its original project; inspect sessions[].cwd. Backups/journals precede writes; partial failures retain evidence for review, without a cross-process transaction or wholesale rollback. The existing desktop registration is not hot-reloaded. Body strings and old absolute paths remain unchanged, including in copied sessions.

CLI output is UTF-8 with encoding-safe fallback. Suspect private-use filename characters are reported without renaming. Imported Codex workspace-write/on-request defaults apply before App loading only; actual runtime policy follows the target user's current App mode, not source permissions.

Migrate visible Claude Code ↔ Codex conversation history into native target sessions. Project snapshots can include files, multiple conversations, recoverable attachments and destination path rebinding.

It writes application data directly. Application updates may break compatibility. Keep backups; never publish packages containing private conversations or source files.

Bounded Windows and macOS samples cover native relocation and both cross-agent whole-project directions; see [docs/VALIDATION.md](docs/VALIDATION.md). If something looks off, start with `python3 -B scripts/doctor.py`.

## Routes and evidence

The platform matrix and bounded historical results live in [docs/VALIDATION.md](docs/VALIDATION.md). Read [docs/CODEX_PROJECT_BINDING.md](docs/CODEX_PROJECT_BINDING.md) for native grouping, cwd drift and before/after continuation checks. A successful sample does not certify all platforms or versions.

Native Claude transfer is the default for same-agent `transfer`. For a portable private package use `export --native`; for whole projects use `project_rehome.py pack --native`. Restore retains source IDs and version; existing IDs or memory files are refused. JSONL bytes are preserved except top-level cwd strings; native compactions stay unchanged and no new summary is generated. Optional `--include-memory`, `--include-checkpoints` and `--source-desktop-registry` select extra data. Session-owned binary sidecars and optional binary checkpoints retain their bytes and SHA-256, with binary=true in native manifests and counts/bytes in result warnings; binary contents are not credential-scanned. UTF-8 text is still scanned, forbidden credential filenames and symlinks are refused, and session JSONL must remain valid UTF-8. Historical absolute sidecar references remain unchanged and may not resolve on the destination; carrying bytes does not certify native image display. Target desktop permissionMode is default; authentication and trust are never activated. Supply a verified target `--desktop-registry`, or use `--no-desktop`. Preview with `--dry-run`, then remove it to apply.

Cross-agent conversion exports agent-exchange/v2; the writer uses a v1 adapter. Existing v1 bundles remain readable. Same-agent converted imports require explicit `--convert`, and Claude native project restore requires a package created with `--native`. Loss summaries are returned in JSON and `.rehome/restore.json`; `.rehome/losses/` contains details and `.rehome/exchange/` retains canonical import data. Attachment bytes do not certify native widget fidelity.

### Native Codex relocation (bounded Windows and macOS samples)

Project preview reports file count, logical bytes, the ten largest files, distribution by top-level directory and extension, and excluded-directory sizes. Pack dry-run does not read session bodies. Native rollouts use sessions/YYYY/MM/DD/rollout-time-ID.jsonl with source metadata time, falling back to the first record time; missing times are refused rather than invented.

Native titles prefer the last matching session_index thread_name, then database title, the first visible user message (60 characters), and ID. --new-copy updates matching source-owned id/session_id in session_meta; message/tool contents and ancestor references remain unchanged. Existing imported copies are not patched in place; accept fixes with a fresh package/destination.

This Skill implements same-agent relocation following ReHome principles. The source agent only packages or inventories projects, chats and files; the receiving agent restores, writes, registers, groups and validates them itself. Initialize a compatible target Codex database first. Codex can restore while its App is running; offline writes use the same path. Earlier ReHome App results do not certify this implementation.

Online backups precede a bounded SQLite writer transaction (2-second lock budget), exclusive rollout creation and append-only index writes. Verify the original index before appending, then its unchanged prefix and complete appended rows. On failure, compensate only this transaction and an intact owned EOF index block; foreign suffixes or incomplete writes require manual review recorded in the backup manifest. Never overwrite the shared index/database to recover. Native folder-open registration returns thread_binding_required for receiver-side project tools; --no-desktop leaves registration pending. The user handles folder trust; the agent does not change security prompts or restart the App.

```text
python scripts/agent_rehome.py transfer --from "codex:<id-or-rollout>" --source-home "<source-codex-home>" --to codex --target-home "<target-codex-home>" --cwd "<existing-target-project>" --dry-run
python scripts/agent_rehome.py export --from "codex:<id-or-rollout>" --source-home "<source-codex-home>" --native --out "<new-native-package>"
python scripts/agent_rehome.py import "<native-package>" --to codex --target-home "<target-codex-home>" --cwd "<existing-target-project>" --dry-run
python scripts/project_rehome.py pack --from codex --project "<source-project>" --source-home "<source-codex-home>" --native --out "<new-project-package>"
python scripts/project_rehome.py restore "<new-project-package>" --to codex --target-home "<target-codex-home>" --cwd "<new-target-project>" --dry-run
```

Remove --dry-run after reviewing the preview. Existing IDs are refused; explicit --new-copy remaps ownership IDs for a separate copy. Reasoning, compacted and encrypted records retain their bytes. Paginated lineage is refused; external generated images/local references are not collected automatically. Inspect manifest/result limitations. Database/index/file compensation is scoped to this transaction; retained project files and interrupted operations require review of backup manifests. See [SPEC](SPEC.md) for boundaries and the project binding document for separate grouping/resume checks. A two-session macOS sample passed native loading. Project registration on macOS still requires the native App.

## Requirements and installation

Project surroundings: allowlisted project .claude/settings.json, skills, commands and agents, plus .codex/config.toml, config.json and settings.json are collected. Local settings, credentials, caches and unknown agent entries are skipped/reported; user-level rules, skills and plugins are not collected. Cross-agent rules bridge only absent targets: Claude gets @AGENTS.md; Codex gets a labeled CLAUDE.md copy with unresolved @ references reported. Skill directories retain their bytes and originals; existing destination names are skipped, including empty directories. Tool names are not converted.

Inspect surroundings in .rehome/restore.json. For every route, .mcp.json is archived byte-for-byte at .rehome/surroundings/originals/.mcp.json and removed from the active project root, preventing target auto-connections after folder trust. The report lists names/commands without environment values; explicit review/approval and manually copying the original back are required to enable it. Claude hooks/permissions and known automatic settings are removed; executable/permission-bearing Codex configs are quarantined. Cross-agent commands/agents need manual work. File checks do not prove runtime loading.

Config files receive the existing conservative credential-feature scan before packing. Matches refuse without creating a package unless --allow-secrets-in-config is explicit; overrides record paths, not matching values. This flag retains sensitive original bytes, does not sanitize them, and never permits excluded credential filenames. Keep such packages private; the scanner is not exhaustive.

Python 3.10+; uncompressed sessions use only the standard library. Compressed Codex sources require an optional zstd decoder (see below). Initialize the target application first; Codex needs a compatible existing `state_5.sqlite`. Initial acceptance used Windows with Claude Code 2.1.309, Codex CLI 0.166.0-alpha.5.1 and Codex desktop 26.1027.3384.0. See MAC_TEST.md for bounded follow-up Mac evidence; Mac Claude registration/loading has only the bounded samples in docs/VALIDATION.md; Linux remains unverified.

Copy this entire folder to `~/.claude/skills/agent-rehome/` for Claude Code, or `~/.agents/skills/agent-rehome/` for Codex. Back up an existing skill before replacing it. Alternatively, run scripts directly from this directory. Test source repository (no stable Release):

```text
git clone https://github.com/CalebYcj/agent-rehome.git
cd agent-rehome
```

macOS and Windows use the same Skill. See [validation notes](docs/VALIDATION.md) for what has been tested.


### Preparing Python on macOS

A working Python 3.10 or newer is required. macOS may not provide one by default; a python3 command can be a developer-tools prompt rather than a ready interpreter. Run `python3 --version` and verify at least 3.10 before testing.

If needed, obtain a compatible Python 3.10+ installer from the [official macOS downloads page](https://www.python.org/downloads/macos/) and follow the [official installation instructions](https://docs.python.org/3/using/mac.html). An existing standalone interpreter can also be used by its full path. Recheck the version after installation; do not modify or delete Apple's system Python. Uncompressed sessions need no third-party Python packages; compressed sources use the optional decoders described below. An early macOS sample used a temporary Python 3.12.16 environment, not an assumed system installation.

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

## Move every project at once

The easiest way is `move`: the receiving agent reads the source agent's local data directly, packs it, and restores it right away. The source agent is never opened and needs no login or quota.

```text
python scripts/batch_rehome.py move --from codex --to claude --root "<new-parent-directory>" --dry-run
python scripts/batch_rehome.py move --from codex --to claude --root "<new-parent-directory>" --source-home "<.codex copied from the old computer>"
```

The package is kept next to the root as `<root>-rehome-package`. It holds private copies; keep it as a backup and delete it yourself once the move is verified.

The two-step way also works: `batch_rehome.py` lists every project with conversations in the source Agent, packs them all, and restores them all under one new folder. Each project still goes through the single-project checks (credential scan, space check, fresh target, backups); a project that fails is reported and the rest continue.

```text
python scripts/batch_rehome.py list --from all
python scripts/batch_rehome.py pack --from codex --to claude --out "<new-batch-directory>"
python scripts/batch_rehome.py restore "<batch-directory>" --to claude --root "<new-parent-directory>" --dry-run
```

- Claude: restart the desktop app once, then trust the restore folder once by starting a session there; every project under it is covered (verified on Windows).
- Codex: each project folder asks for trust once. The dry run's `user_notice` says how many prompts to expect; adding projects and grouping chats is done by the Agent. A folder-open slower than 60 seconds is reported as `pending` and is re-checked, not resent.
- Conversations whose project folder was deleted are skipped and listed.

### Global rules ("main persona")

Batch packs also carry the global rules file: `~/.codex/AGENTS.md` (or a non-empty `AGENTS.override.md`) or `~/.claude/CLAUDE.md`. Pass `--no-global-rules` to leave it out. Restore only previews it:

```text
python scripts/global_rules.py install "<batch-directory>" --to claude          # preview
python scripts/global_rules.py install "<batch-directory>" --to claude --apply  # after the user agrees
```

- To Claude: the text is saved as `~/.claude/rehome/global-rules-from-codex.md` and one `@rehome/...` import line is appended to `~/.claude/CLAUDE.md`. Delete that line to undo.
- To Codex: the text is appended inside begin/end markers to the file Codex reads. Delete the block to undo.
- The text is never rewritten. The preview lists every line that names the old Agent, its paths or tools, and any `@` imports that were not carried. Writes are backed up; installing the same rules twice is skipped.

## Opening and desktop fallback

Claude desktop registration is auto-detected on Windows and at the tested macOS layout: `~/Library/Application Support/Claude/claude-code-sessions/<org>/<account>/local_*.json`. Verified environments and sample limits are recorded in [VALIDATION.md](docs/VALIDATION.md). Restart the desktop normally to load registration, then approve directory trust yourself if prompted. The tool does not restart applications or copy login credentials. `--target-home` needs an explicit `--desktop-registry "<verified-directory>"` for desktop registration. Missing registration produces warnings; `--no-desktop` intentionally writes history only. CLI authentication may differ from desktop authentication.

Codex file writing and native project grouping require separate verification. Follow [CODEX_PROJECT_BINDING.md](docs/CODEX_PROJECT_BINDING.md) for grouping, cwd and continuation checks; registration alone is not proof of application loading.

For cross-agent conversion of a Codex project, use `pack` without `--native` to create an interchange package, then use `restore --convert`. Native Codex project packages lack the interchange events needed for conversion.

## Limits and recovery

- Bounded same-agent Codex samples retained compaction records and resumed successfully. Decryption of the encrypted content was unverified. Users trigger compaction manually in the app. This tool does not trigger it.
- Cross-account migration is untested. The Codex Skill catalog did not refresh during the tested continuations, and cross-machine history retains source-machine paths.

- Results apply only to the recorded platforms, application versions and samples in [VALIDATION](docs/VALIDATION.md). This tool writes application data directly; application updates may invalidate formats. Extensions, branches and pixel-identical rendering are not guaranteed.
- Reading .jsonl.zst needs an optional decoder: Python 3.14+ compression.zstd, zstandard, or the zstd command. Missing decoders raise an error; compressed sessions are not silently skipped. Decompression uses memory.
- Database inventory reads only inside the selected Codex data root. Externally moved cold archives are refused, not counted as restored. Supplying an external single-session file path is a separate explicit source selection.
- Sources without recognizable visible messages are refused by single-session export and listed in skipped by cross-agent project packing. Inspect the reasons; these are not proof of empty chats or full-batch success.
- Cross-agent conversion carries visible history, skips source compaction summaries, and drops encrypted compaction items. Hidden reasoning, harness injections, and account or tool permissions are also omitted. See the loss report. Historical authorization and tasks are not new instructions. Native same-agent Claude byte-preservation rules are documented separately in SPEC.
- Native Claude relocation leaves old absolute paths inside message bodies unchanged, including screenshot references. Copied sidecar bytes do not prove those references work on another computer.
- Claude target files remain textual path references, not native attachment cards or fabricated Read caches. The target model must read the path; a historical text snapshot may be partial.
- Codex target files render as native file chips. One Windows click opened a terminal; parity with a native file click is unverified, so an editor/preview is not guaranteed. Desktop evidence for image thumbnails, attachment clicks, and project grouping is limited. A macOS same-agent sample confirmed that the model could see the embedded image after restore.
- Long cross-agent conversations may use budget summaries with weaker coverage of early themes/details. Full archives in .rehome/history do not mean all history is loaded into model context. Estimates are not an official tokenizer.
- Users must restart Claude desktop and approve directory trust themselves. Parent-folder trust inheritance and multiple-account registry selection remain unverified.
- Credentials and Git history are not migrated. Sources are not moved/deleted; unknown conflicts are refused. Failed batches are not automatically rolled back.

Backups and manifests live under the target data root in rehome-backups/ and rehome-imports/; project results are in .rehome/restore.json. For rollback, stop target writes, preserve new content, and restore only the affected files from the manifest. Do not replace a shared database/index blindly with an old copy containing other chats.

## Tests and privacy checks

```text
python -B scripts/run_tests.py
python -B scripts/privacy_scan.py .
```

Each test runs with a new temporary HOME, synthetic fixtures and guarded filesystem/database writes. Real Agent data, network access and external process launches are blocked. No Agent login is needed. The privacy scanner checks user-home absolute paths, emails, non-fixture session IDs and common credential patterns; review additional files before publishing.

### Legacy and compressed Codex sources

The reader accepts both item_completed UI events and legacy user_message/agent_message events. Legacy function/custom calls and search results are paired by call_id; matched modern items take precedence with occurrence-based deduplication. Provider harness messages are filtered; reasoning, unknown events and missing tool results are reported as losses.

Single-session ID lookup checks threads.rollout_path, then sessions/archived_sessions, including .jsonl.zst and filenames without a rollout- prefix. Project packs include archived sessions with the exact project cwd. Indexed paths remain within the selected data root; an external single-session path can be supplied explicitly.

For compressed sources only, the reader tries Python 3.14+ compression.zstd, an installed zstandard package (`python -m pip install zstandard`), then the system zstd command with only -d -c. Missing decoders cause an actionable error, not a silent skip. No dependency is installed automatically. Decompression is in memory, source files stay unchanged, and large histories require sufficient memory. Uncompressed sources and target writers do not acquire this dependency.
