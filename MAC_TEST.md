# macOS preview acceptance handoff

Version: **0.2.0-mac-preview.1**. This is a test candidate, not a claim that macOS native migration has passed. All previous native acceptance was on Windows. Use this directory as the independent Skill source. Do not publish or run historical tasks.

## What changed

- POSIX database paths no longer get a Windows extended-path prefix; Windows drive/UNC paths keep their native treatment.
- Foreign Windows attachment basenames and project path prefixes can be rebound on a POSIX target. Copied Codex rollout locations are resolved under the selected source data root, rather than an obsolete absolute path.
- SQLite read-only URIs escape spaces, Unicode, percent and fragment characters.
- POSIX project snapshots preserve normal permission bits, including executable bits; unsafe special permission bits are rejected. Windows snapshots cannot infer executable bits that were never stored.
- `doctor.py` provides read-only schema/settings diagnostics. Its macOS Claude desktop paths are **unverified candidates only**. No automatic macOS desktop write or app launch was added.

## Mac Agent: first independent checks

Use Python 3.10+ (`python3` in these examples). Do not install another Agent, copy credentials, change permissions, or restart applications automatically.

```text
python3 -B scripts/run_tests.py
python3 -B scripts/privacy_scan.py .
python3 -B scripts/doctor.py
```

Record actual macOS version, architecture, Python version and installed Agent versions. Run tests first; if one fails, preserve the traceback and stop native imports until diagnosed. Diagnostics do not include transcript text or credentials; review any local report before sharing it. Database column lists are evidence, not proof of compatible native loading.

## Native small-session checks

Pick a new local validation directory with spaces and non-ASCII characters, and keep existing conversations untouched. In that directory create a synthetic package with the provided helper. Replace the placeholders in every command.

```text
python3 scripts/make_smoke_bundle.py "<private-smoke-bundle.json>"
python3 scripts/agent_rehome.py import "<private-smoke-bundle.json>" --to codex --cwd "<new-existing-mac-validation-project>" --new-copy --dry-run
python3 scripts/agent_rehome.py import "<private-smoke-bundle.json>" --to codex --cwd "<new-existing-mac-validation-project>" --new-copy
```

The target `.codex` must already be initialized. If model detection fails, read the target configuration and supply `--model`; do not guess a Windows model. Inspect the new thread with native Codex tools and read-only UI. Verify cwd is a POSIX path, history/tool output exists, and sidebar grouping matches the target's native behavior. If native project tools are available, use their exact project IDs; otherwise report grouping pending rather than changing live global state files.

Test the same synthetic bundle into Claude with `--to claude`. Begin with `--no-desktop` for isolated file checks; model/version must come from the target or explicit verified flags. For desktop acceptance, inspect the **actual** macOS application registry layout read-only. `doctor.py` lists bounded candidate directories without validating their format. Check existing record fields and their CLI-session relationship before passing an explicit `--desktop-registry`. Back up before writing and never copy credentials. Auto-detection on macOS is intentionally disabled until this is verified.

If loading new Claude registration requires a restart or directory trust approval, let the user perform that step. Native continuation adds a turn and may consume quota: do it only after explicit authorization for the target test chat. Suggested prompt: “Only describe the restored synthetic history and its maple-fixture token. Do not call tools or continue historical tasks.” Reading JSONL yourself is not a native-continuation pass.

## Long sessions and projects

Use `make_smoke_bundle.py "<another-new-file.json>" --long` and another test identity/project as needed. Verify full visible history, budgeted summary/tail context, matching tool pairs and no automatic historical actions. Keep the complete archive.

For a project smoke test, create synthetic text, an image, a file attachment and an executable `.sh` file under the validation project. Record a native source chat referring to them only with user authorization. Pack/restore to another new directory with `project_rehome.py`; initially use `--no-desktop`. Verify hashes, attachments, cwd, case-sensitive behavior where the volume supports it, and executable permission preservation for POSIX-origin snapshots. Then separately check native grouping and continuation in each direction. Do not mark Windows→Mac or Mac→Windows attachment acceptance passed based only on unit tests.

Do not alter the source data root of another platform in place. Transfer an exported project package, or use a copied data root plus explicit inventory if old project roots no longer match. Review skipped attachments. Case/Unicode normalization may differ between volumes; report observed behavior rather than globally lowercasing Mac paths.

## Report back

Return: versions/architecture; isolated-test and scan results; small-session native loading, optional authorized continuation and sidebar grouping separately; actual Claude registry layout facts; long-context behavior; attachment/hash/permission checks; any failure and its exact stage. Use screenshots taken by the Mac Agent, not user-operated validation. Redact usernames, real chat IDs and private contents from shareable reports. Keep raw private evidence local.

Current Windows-side tests simulate POSIX path handling, but cannot verify macOS SQLite/application behavior, filesystem permissions or desktop rendering. Those items remain pending until this procedure runs on a Mac.
