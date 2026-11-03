# Changelog

Historical entries describe their original checkpoints; current bounded evidence is in docs/VALIDATION.md.

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

- Document MAC-003: one reported authorized Mac post-repair same-thread continuation kept the correct binding; root cause, fresh-import repeatability, visuals, attachments and Mac Claude remain unverified.

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
