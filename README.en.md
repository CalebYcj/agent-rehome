# Agent Rehome

Version **0.4.0-preview.1** · [中文](README.md) · [MIT](LICENSE)

Migrate visible Claude Code ↔ Codex conversation history into native target sessions. Project snapshots can include files, multiple conversations, recoverable attachments and destination path rebinding.

This is an unofficial third-party tool, not an Anthropic or OpenAI product. It writes application data directly. Application updates may break compatibility. Keep backups; never publish packages containing private conversations or source files.

Preview: bounded Windows and macOS samples cover native Claude relocation and both cross-agent whole-project directions; they do not certify all versions or projects. See [MAC_TEST.md](MAC_TEST.md) and start with `python3 -B scripts/doctor.py`.

## Routes and evidence

The platform matrix and bounded historical results live in [docs/VALIDATION.md](docs/VALIDATION.md). Read [docs/CODEX_PROJECT_BINDING.md](docs/CODEX_PROJECT_BINDING.md) for native grouping, cwd drift and before/after continuation checks. A successful sample does not certify all platforms or versions.

Native Claude transfer is the default for same-agent `transfer`. For a portable private package use `export --native`; for whole projects use `project_rehome.py pack --native`. Restore retains source IDs and version; existing IDs or memory files are refused. JSONL bytes are preserved except top-level cwd strings; native compactions stay unchanged and no new summary is generated. Optional `--include-memory`, `--include-checkpoints` and `--source-desktop-registry` select extra data. Session-owned binary sidecars and optional binary checkpoints retain their bytes and SHA-256, with binary=true in native manifests and counts/bytes in result warnings; binary contents are not credential-scanned. UTF-8 text is still scanned, forbidden credential filenames and symlinks are refused, and session JSONL must remain valid UTF-8. Historical absolute sidecar references remain unchanged and may not resolve on the destination; carrying bytes does not certify native image display. Target desktop permissionMode is default; authentication and trust are never activated. Supply a verified target `--desktop-registry`, or use `--no-desktop`. Preview with `--dry-run`, then remove it to apply.

Cross-agent conversion exports agent-exchange/v2; the writer uses a v1 adapter. Existing v1 bundles remain readable. Same-agent converted imports require explicit `--convert`, and Claude native project restore requires a package created with `--native`. Loss summaries are returned in JSON and `.rehome/restore.json`; `.rehome/losses/` contains details and `.rehome/exchange/` retains canonical import data. Attachment bytes do not certify native widget fidelity.

## Requirements and installation

Python 3.10+; uncompressed sessions use only the standard library. Compressed Codex sources require an optional zstd decoder (see below). Initialize the target application first; Codex needs a compatible existing `state_5.sqlite`. Initial acceptance used Windows with Claude Code 2.1.309, Codex CLI 0.166.0-alpha.5.1 and Codex desktop 26.1027.3384.0. See MAC_TEST.md for bounded follow-up Mac evidence; Mac Claude registration/loading has only the bounded samples in docs/VALIDATION.md; Linux remains unverified.

Copy this entire folder to `~/.claude/skills/agent-rehome/` for Claude Code, or `~/.agents/skills/agent-rehome/` for Codex. Back up an existing skill before replacing it. Alternatively, run scripts directly from this directory. Test source repository (no stable Release):

```text
git clone https://github.com/CalebYcj/agent-rehome.git
cd agent-rehome
```

This is a macOS test preview, not a claim of native macOS acceptance. Follow MAC_TEST.md.


### Preparing Python on macOS

A working Python 3.10 or newer is required. macOS may not provide one by default; a python3 command can be a developer-tools prompt rather than a ready interpreter. Run `python3 --version` and verify at least 3.10 before testing.

If needed, obtain a compatible Python 3.10+ installer from the [official macOS downloads page](https://www.python.org/downloads/macos/) and follow the [official installation instructions](https://docs.python.org/3/using/mac.html). An existing standalone interpreter can also be used by its full path. Recheck the version after installation; do not modify or delete Apple's system Python. Uncompressed sessions need no third-party Python packages; compressed sources use the optional decoders described below. MAC-C1 used a temporary Python 3.12.16 environment, not an assumed system installation.

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

Claude desktop registration is auto-detected on Windows and at the MAC-C1-verified macOS layout: `~/Library/Application Support/Claude/claude-code-sessions/<org>/<account>/local_*.json`. Verified environments and sample limits are recorded in [VALIDATION.md](docs/VALIDATION.md). Restart the desktop normally to load registration, then approve directory trust yourself if prompted. The tool does not restart applications or copy login credentials. `--target-home` needs an explicit `--desktop-registry "<verified-directory>"` for desktop registration. Missing registration produces warnings; `--no-desktop` intentionally writes history only. CLI authentication may differ from desktop authentication.

Codex file writing and native project grouping require separate verification. Follow [CODEX_PROJECT_BINDING.md](docs/CODEX_PROJECT_BINDING.md) for grouping, cwd and continuation checks; registration alone is not proof of application loading.

## Limits and recovery

- Results apply only to the recorded platforms, application versions and samples in [VALIDATION](docs/VALIDATION.md). This third-party tool writes application data directly; application updates may invalidate formats. Extensions, branches and pixel-identical rendering are not guaranteed.
- Reading .jsonl.zst needs an optional decoder: Python 3.14+ compression.zstd, zstandard, or the zstd command. Missing decoders raise an error; compressed sessions are not silently skipped. Decompression uses memory.
- Database inventory reads only inside the selected Codex data root. Externally moved cold archives are refused, not counted as restored. Supplying an external single-session file path is a separate explicit source selection.
- Sources without recognizable visible messages are refused by single-session export and listed in skipped by cross-agent project packing. Inspect the reasons; these are not proof of empty chats or full-batch success.
- Cross-agent conversion omits hidden reasoning, encrypted compactions, harness injections and account/tool permissions, with explicit loss reports. Historical authorization and tasks are not new instructions. Native same-agent Claude byte-preservation rules are documented separately in SPEC.
- Native Claude relocation leaves old absolute paths inside message bodies unchanged, including screenshot references. Copied sidecar bytes do not prove those references work on another computer.
- Claude target files remain textual path references, not native attachment cards or fabricated Read caches. The target model must read the path; a historical text snapshot may be partial.
- Codex target files render as native file chips. One Windows click opened a terminal; parity with a native file click is unverified, so an editor/preview is not guaranteed. Windows image-thumbnail/preview samples passed; Mac model attachment access remains untested.
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
