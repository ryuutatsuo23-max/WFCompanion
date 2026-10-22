# Smaller updates

Implemented locally; not yet released or confirmed on the second PC.

## Measured comparison

The public 0.1.10 and 0.1.11 application bundles each contain 1,284 files.
The target is 109,644,258 bytes; 143 changed files total 4,481,806 bytes.
The production-template patch is 4,879,633 bytes versus the 38,066,152-byte full
0.1.11 installer: about 87% less download. Some changes are line endings and build
output; future sizes depend on actual bundle differences. Evidence is in
`build/incremental-comparison-0110-0111-v2/comparison.json`.

## Release construction

Always build and retain the full public installer first. A patch supplements it.
Keep the exact public application bundle from each supported base release.
The builder reads version constants from both bundles and rejects mismatches.

Use `build_installer.py --public --iscc <compiler> --base-bundle <old-app-folder>
--base-version <old-version>` to build a full installer and, when eligible, a
patch under its output folder's `incremental` subfolder. An incompatible base
leaves a successful full build and reports why no smaller package was produced.

Alternatively run `build_incremental.py --base <old-app-folder> --target
<new-app-folder> --from-version X.Y.Z --to-version X.Y.Z --output <new-folder>
--iscc <compiler>`. Arguments referring to paths must use absolute, verified paths
in release automation. Never use an installed user copy as a release source.

Upload only these three incremental assets alongside the canonical full installer
and checksum, with the actual base version in each name:

- `WFCompanion-patch-from-X.Y.Z.exe`
- `WFCompanion-patch-from-X.Y.Z.exe.sha256`
- `WFCompanion-patch-from-X.Y.Z.json`

Do not upload staging payload, compiler source, comparison logs or private state.
Multiple exact base versions may have separate patch assets. Users skipping an
unsupported base receive the full installer. Existing updaters ignore patch assets.
0.1.12 is a full-install transition because it adds the new updater module.

## Selection and recovery

Only fixed HTTPS GitHub release URLs are accepted. Bounded metadata must match
the release, base version, asset name, size and checksum. All expected installed
files are hash-checked; traversal, alternate streams, reserved device names and
linked paths are rejected. Missing metadata, invalid metadata, a changed/missing
base file, recovery marker, or failed patch download selects the full installer.
There is also an explicit Download full installer instead button.

The first format supports replacements only. Added/deleted files or changed
runtime libraries require a full installer. Patches use the existing Inno template,
including uninstall/data-retention behaviour. They recheck every base hash before
installation, reject linked trees, and disable game-addon installation. No extra
files in the installation are removed. Uninstall file ownership remains covered
by the prior full install and Inno's appended installation record.

After the app exits cleanly, the detached helper copies its installation to a
unique recovery folder under companion data/updates. A persistent
`full-update-required` marker is written before patch installation. The patch is
checksum-verified, installed, and checked with a disposable packaged smoke test.
Only a successful check clears the marker and restarts the app normally.

On a reported install/startup failure, previous application files (including the
uninstaller files) are restored and the next attempt uses the full installer.
The full installer repairs registration metadata as well. Backups are deliberately
retained; each needs approximately one installed application's disk space. If
backup fails (including disk exhaustion), patch installation does not start.

A power loss/forced process termination is not an atomic transaction. The recovery
copy and marker remain. If the app can start it selects the full installer; if it
cannot start, rerun the full installer manually. A forced power-loss interruption
still needs isolated end-to-end testing before public patch deployment. Do not
claim automatic rollback across power loss.

No new publisher authentication is claimed: this retains the existing GitHub HTTPS
and checksum trust model. SignPath approval/signing remains separate and pending.

## Verification performed

17 focused tests passed across incremental selection, updater UI, transport,
setup guide and distribution. Cases include modified/missing bases, invalid paths,
malformed/unavailable metadata, checksum disagreement, patch-download failure,
recovery-marker fallback, and changed runtime/file-set rejection.

A disposable Inno fixture (registration, shortcuts and main-window restart
disabled) reproduced all 1,284 target files exactly. The actual PowerShell helper
backed up, installed and passed the real packaged smoke check. An injected failure
after installation restored every base file and retained the full-fallback marker.
The compiled installer rejected a modified base without changing any files.
An isolated full install -> smaller update -> uninstall test removed both changed
application files and unchanged runtime libraries, preserved an unrelated file,
and removed its own fixture registration. It never used the real app registration.
These checks did not modify the installed companion, game addons or personal saves.

Technical references: https://jrsoftware.org/ishelp/topic_scriptevents.htm and
https://jrsoftware.org/ishelp/topic_isxfunc_getsha256offile.htm.
