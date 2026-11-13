# Changelog

Historical entries describe their original checkpoints; current bounded evidence is in docs/VALIDATION.md.

## Unreleased

- Codex migrations now carry the full project and chat list in the batch receipt. The receiving agent uses it to finish project registration and verify sidebar placement after any folder trust prompts, including when Claude is unavailable.

## 0.5.2

- Move your own Skills: batch packs now include the Skills installed for every project (`~/.claude/skills`, `~/.agents/skills`, `~/.codex/skills`). Restore only lists them; `user_skills.py install --apply` copies them after the user agrees, `--only NAME` picks. Folders are copied unchanged and an existing Skill of the same name is never overwritten. Plugins, built-in dot folders, linked folders and Agent Rehome itself are left out; a Skill with a possible secret is skipped and listed. `--no-user-skills` leaves them out.

## 0.5.1

- Receiver-only route is now the main path: `batch_rehome.py move` reads the source agent's local data directly, packs it next to the new folder and restores it in one step. The source agent is never opened and needs no login or quota.
- Codex keeps older conversations compressed on disk (`.jsonl.zst`). `list`, `pack --dry-run` and `move --dry-run` now count them and say when a decoder is needed; a real run without one stops before writing anything.

## 0.5.0

- Move everything at once: `batch_rehome.py` lists every project with conversations in Claude or Codex, packs them all, and restores them all under one new folder. A project that fails is reported and the rest continue.
- Move the global rules ("main persona"): batch packs include `~/.codex/AGENTS.md` or `~/.claude/CLAUDE.md`. Restore only previews it; `global_rules.py install --apply` writes after the user agrees, with a backup and a one-step undo, and never rewrites the text.
- Claude: trust the restore folder once and every project under it is covered. Codex: each project folder still asks once; the dry run says how many prompts to expect.
- A slow Codex folder-open is reported as pending instead of failed, and is not resent.
- Keep only a project's own sessions when two Claude project names share one folder.

## 0.4.0

- First stable release.
- Check for Python 3.10+ before starting and tell the user how to get it.
- After a project pack or single-session export, report where the package is, how to carry it to another computer, and a sentence to send to the receiving Agent.
- Report image attachments as carried instead of dropped; images whose source file is gone stay in `skipped`.
- Replace outdated "macOS acceptance pending" wording.

## 0.4.0-preview.9

- Documentation only: record the preview.8 Claude new-copy smoke on Windows and macOS, state that process detection can also miss sessions, and clean up validation wording.

## 0.4.0-preview.8

- Update the bilingual README and validation notes with bounded Windows and macOS migration evidence.
- Explain how to repack a native Codex project before cross-agent conversion when its interchange stream is empty.

## 0.4.0-preview.7

- Recognize short Claude resume flags after a case-insensitive Claude marker, including extensionless Node launchers and unquoted paths with spaces.

## 0.4.0-preview.6

- Detect Claude's short `-r` resume flag on Claude commands without broadening the long-flag rules.
- Append a copy-specific native Claude title outside the message chain, while preserving existing records.
- Clarify Codex's recorded Skill paths and the order for opening and grouping restored chats.
- Report ledger JSONL/Zstandard conversions separately, verify preserved prefixes when possible, and document how to exclude both agents' work sessions.

## 0.4.0-preview.5

- Detect Claude fast-forward targets by exact session flags across processes and live PID session records, without reading session keys.

## 0.4.0-preview.4

- Guard Claude fast-forward with a read-only live-session process check, and collect in-place return evidence without a project restore receipt.

## 0.4.0-preview.3

- Allow known independent Claude maintenance records in prefix-verified fast-forward returns while preserving local bytes.
- Keep native titles on empty overrides, supply readable fallbacks and distinguish project copies.
- Preserve quarantined agent configuration across round trips and clarify user-owned trust with receiver-owned project binding.

## 0.4.0-preview.2

- Filter Claude desktop reminders, preserve delegated messages with source attribution, and show explicit user-owned steps for desktop loading and continuation.

- Preserve Codex app-tool delegated turn inputs in cross-agent conversions with a source-thread label and a separate event count.

- Remove the 2 GiB project ceiling. Report file sizes and excluded directories, check destination capacity, and stream project files and attachment assets in bounded chunks.
- Add reference-mode projects with inventories, optional strict verification and optional Git history with remote-credential preflight. Build a ZIP64 release with UTF-8 names and a complete payload checksum list.
- Verify project surroundings on Windows and bounded Mac samples, including rule/Skill bridges. Mac Claude runtime evidence prompted MCP quarantine. Resolve default temporary-directory alias failures in regression fixtures.

Known limits: automatic Codex project registration on Mac still needs native App handling. Visual parity, external attachments, and concurrent interruption coverage remain limited. Runtime permissions follow the destination App. Four isolated endpoint lab tests are pending.

- Add native Claude --new-copy and prefix-verified --fast-forward returns, readable conflict paths, previews, backups and retained partial-write journals. Preserve original sessions and refuse divergent histories/sidecars.
- Use UTF-8/encoding-safe CLI output; report suspect private-use filenames without renaming. Quarantine project .mcp.json originals for all routes instead of activating destination auto-connections; document manual opt-in and target App runtime-policy selection.

- Resolve native Codex and project-surroundings test fixture roots before reversal/registration checks so default macOS temporary-directory aliases and Windows junction temporary paths do not produce false history-byte or registration failures. Keep production relocation behavior unchanged and verify canonical metadata for noncanonical requests.

- Attempt Codex project registration even when a restored project has no conversations; report registration status without creating placeholder threads or requiring a database for empty projects. Preview and --no-desktop retain their no-registration behavior.

- Let the receiving Codex agent restore native projects while its App runs: bounded SQLite locking, exclusive rollouts, append-only index integrity checks and scoped compensation; receiver-side native registration/grouping remains separately verified.

- Fix native copied session_meta.session_id ownership and resolve visible titles from the latest matching session index entry, sharing the index reader with cross-agent export; preserve message bytes and ancestor IDs.

- Match native Codex date/time rollout paths, use a visible-user fallback title and preview project size before packing.
- Preserve allowlisted project agent assets and bridge absent rule/Skill targets across agents. Report skipped/manual assets and MCP commands, scan sensitive configuration before packing, and retain inactive originals for executable/permission settings. User-level installations remain separate.

- Implement native Codex-to-Codex single-session and project relocation inside this Skill, following ReHome's metadata-only principle. Keep opaque reasoning/compaction bytes, decode optional zstd sources, refuse paginated dependencies, and require explicit copies for ID conflicts.
- Validate native Codex receipt on Windows and Mac, including one real two-session Windows → Mac → Windows round trip with the Mac-added turn visible in Windows. Validate one Mac-origin Codex session on Windows. Claude prefix-only return was verified at file level; native desktop loading remains separately verified.

## 0.4.0-preview.1

- Preserve Claude native project sidecars, binary checkpoints and nested working directories; support declared symbolic-link root aliases and macOS desktop registry discovery. A real two-conversation Windows-to-Mac project was accepted within the documented sample limits.
- Read legacy Codex visible events and optional zstd-compressed rollouts, including archived sessions and stale database .jsonl paths whose files now end in .jsonl.zst.
- Simplify the Skill entrypoint and replace temporary backend overrides with an explicit Codex writer, covered by frozen behavior regressions.
- Restore identical files mapped to the same destination once and report deduplication; reject conflicting content before creating the destination.
- Render Codex target file references using native file-mention headers while preserving image bytes. Native click-behavior parity remains unverified.
- Separate real Claude file-reference losses from system-injected attachment notices; keep unknown types explicit.
- Record bounded native whole-project results for both cross-agent directions on Mac, and Windows image/file-access checks. Claude target files remain path references; historical absolute sidecar references and long-history summary limits remain.

## 0.3.0-architecture-preview.1

- Default same-agent routing: Codex delegates to ReHome; Claude preserves native bytes, ID, sidecars and source version, rewriting only top-level cwd.
- Optional native memory/checkpoints and safe desktop registration; collisions and credential preflight stop before writes. No automatic restart.
- agent-exchange/v2 canonical events, explicit loss accounting, referenced project streams and v1 read compatibility. Same-agent converted imports require --convert.
- New isolated native multi-session project and exchange regression tests. Live Claude native relocation/desktop acceptance remains pending; prior Mac evidence stays bounded.


## 0.2.0-mac-preview.2 (local integration candidate)

- Record one reported authorized macOS post-repair continuation that kept the correct binding; root cause, fresh-import repeatability, visuals, attachments and Mac Claude remain unverified.

- Integrate Mac temporary-directory alias test corrections and binding diagnostics.
- Close SQLite fixture connections explicitly for Windows cleanup.
- Separate current-row binding from historical context evidence and native membership.
- Cover copied data roots, alternate/conflicting session identifiers and drift after row repair.
- Require independent native project/cwd checks around authorized continuation; no claim of a persistent Mac fix.

## 0.2.0-mac-preview.1

- Host-aware Windows/POSIX database paths and escaped read-only SQLite URIs.
- Foreign attachment names, project prefix rebinding and copied rollout resolution.
- POSIX project permission preservation with special-bit rejection.
- Read-only macOS candidate diagnostics, synthetic smoke bundles and Mac acceptance handoff.
- Native macOS application acceptance remains pending.

## 0.1.0

- Bidirectional native Claude Code/Codex visible-history migration.
- Project snapshots, attachment recovery and path rebinding.
- Bounded context for long-session continuation with full history archives.
- Backups, integrity checks, conflict protection and explicit desktop fallback.
- Target model/version detection; isolated synthetic tests and privacy scanning.
