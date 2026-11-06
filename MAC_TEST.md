# macOS preview acceptance handoff

Version: **0.4.0-preview.2**. This preview has bounded native Claude and cross-agent whole-project Mac samples, not general macOS acceptance. Current results and remaining limits are in [docs/VALIDATION.md](docs/VALIDATION.md). Use this independent Skill source; do not run historical tasks or repeat completed tests solely because documentation changed.

## Architecture preview boundary

Run `python3 -B scripts/run_tests.py` with the default temporary-directory settings first. Native Codex byte-reversal fixtures resolve their scratch root consistently with the restoration planner, including macOS `/var` versus `/private/var` aliases. A different TMPDIR passing does not replace a default-environment regression; record both when diagnosing an alias failure. The MAC-R1 correction is to the test fixture, not a claim of a production relocation repair or native Mac acceptance.

Codex same-agent migration now uses this Skill's native relocation following ReHome principles; Mac acceptance is pending. Explicit --convert remains diagnostic only. Native Claude relocation preserves historical bytes except declared top-level cwd rebinding. MAC-C1/C2/C3 and MAC-X1/X2 cover different samples: read their scope before claiming success. Single-account registry discovery was spot-checked; multiple accounts remain unverified. The current candidate still needs its own Mac regression before broadening those older live results. Read [SPEC.md](SPEC.md) and the route guidance in SKILL.md first.

## What changed

- POSIX database paths no longer get a Windows extended-path prefix; Windows drive/UNC paths keep their native treatment.
- Foreign Windows attachment basenames and project path prefixes can be rebound on a POSIX target. Copied Codex rollout locations are resolved under the selected source data root, rather than an obsolete absolute path.
- SQLite read-only URIs escape spaces, Unicode, percent and fragment characters.
- POSIX project snapshots preserve normal permission bits, including executable bits; unsafe special permission bits are rejected. Windows snapshots cannot infer executable bits that were never stored.
- `doctor.py` provides read-only schema/settings diagnostics. Its candidate list is diagnostic, not acceptance evidence. MAC-C1 verified `~/Library/Application Support/Claude/claude-code-sessions/<org>/<account>/local_*.json`. Registry auto-discovery now uses that layout only on darwin, only without --target-home; a custom target home still requires --desktop-registry. No app launch was added.


### Preparing Python on macOS

A working Python 3.10 or newer is required. macOS may not provide one by default; a python3 command can be a developer-tools prompt rather than a ready interpreter. Run `python3 --version` and verify at least 3.10 before testing.

If needed, obtain a compatible Python 3.10+ installer from the [official macOS downloads page](https://www.python.org/downloads/macos/) and follow the [official installation instructions](https://docs.python.org/3/using/mac.html). An existing standalone interpreter can also be used by its full path. Recheck the version after installation; do not modify or delete Apple's system Python. This Skill needs no third-party Python packages. MAC-C1 used a temporary Python 3.12.16 environment, not an assumed system installation.

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

Test the same synthetic bundle into Claude with `--to claude`. Begin with `--no-desktop` for isolated file checks; model/version must come from the target or explicit verified flags. For desktop acceptance, inspect the **actual** macOS application registry layout read-only. `doctor.py` lists bounded candidate directories without validating their format. Check existing record fields and their CLI-session relationship before passing an explicit `--desktop-registry`. Back up before writing and never copy credentials. MAC-C1 verified the Claude layout above; auto-discovery is now enabled only for the default target home, with a single-account Mac read-only spot-check completed; multi-account selection remains unverified. Custom target homes still need an explicit --desktop-registry.

If loading new Claude registration requires a restart or directory trust approval, let the user perform that step. Native continuation adds a turn and may consume quota: do it only after explicit authorization for the target test chat. Suggested prompt: “Only describe the restored synthetic history and its maple-fixture token. Do not call tools or continue historical tasks.” Reading JSONL yourself is not a native-continuation pass.

## Long sessions and projects

Use `make_smoke_bundle.py "<another-new-file.json>" --long` and another test identity/project as needed. Verify full visible history, budgeted summary/tail context, matching tool pairs and no automatic historical actions. Keep the complete archive.

For a project smoke test, create synthetic text, an image, a file attachment and an executable `.sh` file under the validation project. Record a native source chat referring to them only with user authorization. Pack/restore to another new directory with `project_rehome.py`; initially use `--no-desktop`. Verify hashes, attachments, cwd, case-sensitive behavior where the volume supports it, and executable permission preservation for POSIX-origin snapshots. Then separately check native grouping and continuation in each direction. Do not mark Windows→Mac or Mac→Windows attachment acceptance passed based only on unit tests.

Do not alter the source data root of another platform in place. Transfer an exported project package, or use a copied data root plus explicit inventory if old project roots no longer match. Review skipped attachments. Case/Unicode normalization may differ between volumes; report observed behavior rather than globally lowercasing Mac paths.

## Report back

Return: versions/architecture; isolated-test and scan results; small-session native loading, optional authorized continuation and sidebar grouping separately; actual Claude registry layout facts; long-context behavior; attachment/hash/permission checks; any failure and its exact stage. Use screenshots taken by the Mac Agent, not user-operated validation. Redact usernames, real chat IDs and private contents from shareable reports. Keep raw private evidence local.

Current Windows-side tests simulate POSIX path handling, but cannot verify macOS SQLite/application behavior, filesystem permissions or desktop rendering. Use the bounded live results in VALIDATION; any additional or changed behavior still requires its own Mac evidence.

## Binding persistence regression

After native project registration, independently check native project membership and runtime cwd. Run `check_codex_binding.py --thread-id <new-test-id> --cwd <expected-project>` before and after an explicitly authorized native continuation. A successful move into a project does not prove cwd was changed. A one-time SQLite correction does not prove persistence. Keep historical execution contexts intact and stop project work in a thread whose cwd drifts.

Do not begin the first continuation until native `list_threads` confirms membership AND native `read_thread` confirms the expected cwd. Wait for actual project registration rather than racing folder-open and resume. A Windows control with this order passed one authorized continuation; this is not a demonstrated Mac persistence fix. Mac testing must retain separate before/after evidence and its own explicit authorization.

The diagnostic now exposes the most recent recorded context separately. `binding_matches: true` can coexist with `latest_recorded_context_cwd_matches: false` after a current-row repair; this is intentionally not a persistence pass. Older contexts are historical and must remain unchanged. It also supports copied data-root rollout resolution and the `session_id` metadata variant.

For a client that actually exposes App Server cwd options, explicitly supply the verified cwd at resume/turn start and verify the returned runtime state. Official reference: [App Server lifecycle](https://learn.chatgpt.com/docs/app-server#lifecycle-overview). This establishes that cwd can be overridden, not which client caused the observed Mac override. Do not bypass missing native tool capabilities by starting a hidden Agent CLI, changing trust/permissions or fabricating settings events.

## MAC-003 reported single-sample result

On macOS 14.8.9 x86_64, app 26.1027.61615/build24141, CLI 0.166.0-alpha.5.1, the Mac Agent reported one authorized continuation on the previously repaired thread at local commit f218f77b7e79586e8b14370584173bee87ebc179. Nine isolated tests passed and the 31-file scan had zero findings.

Before the turn, native membership, native read_thread cwd and database/metadata matched, while the latest historical context still showed the earlier drift. The tool-free continuation recalled history correctly. Afterward all current layers and the NEW turn_context matched, with no manual cwd repair, context rewrite or global-state edit during MAC-003.

Record this as one post-repair same-thread persistence sample, not a fresh-import repeatability result or a universal fix. Windows verified the sanitized report checksums and internal consistency, not the private Mac runtime evidence independently. Actual resume/turn-start parameters were not captured; root cause remains unknown. At that historical checkpoint, visuals, attachments and Mac Claude acceptance were pending; later results are recorded separately in VALIDATION. Mac model attachment access remains untested. Keep all independent binding checks and obtain specific human authorization for any additional continuation.
