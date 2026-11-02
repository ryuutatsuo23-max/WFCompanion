# Hosted frozen transaction qualification

The standard `windows-2025` GitHub-hosted VM is disposable. This workflow never
uses a self-hosted runner. The account-creating controller additionally requires
GitHub-hosted metadata, the expected repository and Windows Server, and rejects
the personal machine names. These guards prevent accidental local use; GitHub's
runner provisioning is the trust basis, not an environment-variable sandbox.

The workflow builds the exact PR head (recorded by SHA), keeps the public bundle
unchanged and authenticates all bundle bytes before/after testing. It makes a
**separate, test-only frozen instrumentation build** from the generated spec.
Qualification runs in its own fresh Windows job, in parallel with the unchanged
full regression/installer job. It builds an onedir bundle without invoking ISCC
or a compiler installer. This separate build has its own recorded binary hashes;
it is not claimed byte-identical to the independently built installer artifact.
Only a test entry script, harness search path and test hidden imports are added.
The test script runs after PyInstaller's built-in hooks (including Qt setup)
and before the existing launcher, using the supported multiple-script Analysis.
The original launcher and every bundled production/payload data file are
unchanged. The instrumentation hook exits before the normal launcher; it creates
the real bundled Companion, Addons page and recovery dialog. This is frozen
module/UI integration evidence, not an untouched release-binary transaction test.
The unchanged public executable also runs its existing startup smoke route under
the same temporary standard user. No installer runs.
Instrumentation uses the same optional-Qt pruning as the public builder and
rejects any additional or changed runtime file other than the instrumented EXE
and ZIP container metadata in base_library.zip (member bytes must match exactly).
No unittest/mock support package is added to the bundle.

The temporary account and profile exist only in the hosted VM. Its randomized
password is held in memory and passed through Windows credential APIs, never
arguments, logs or artifacts. The controller queries the actual process token:
expected SID, no Administrators SID (even deny-only), elevation false, elevation
type Default and nonzero session. The frozen harness repeats token and native
Known Folder checks. It uses the real production configuration authority.

Each child waits for a parent permit. The controller assigns and verifies its
kill-on-close Job Object and verifies the token before releasing it. Each phase
has a 60-second process budget plus at most 3 seconds to prove the job empty
(65-second total acceptance limit); the batch has a 480-second budget and a
12-minute outer Actions step deadline. Jobs are terminated on failure. No timeout
is accepted as successful interruption. The two intentional abrupt exits require
code 73 and an exact frozen/PID/invocation/commit-bound boundary record. No retry
is automatic. An outermost OS stall remains a platform limitation.

The test account receives no runner credentials. Only synthetic clients, a fresh
native profile, a writable case/result area and read access to the two generated
bundles are used. Outbound block rules are created for both executable paths;
firewall profile states are recorded, not inferred from successful rule creation.
Fixture Wow.exe files contain plain text and are never executed. Known game and
Companion state locations are checked before provisioning. A fresh GitHub VM,
not a broad scan of disks or personal files, establishes absence of real data.

Scenarios: module/native identity; client selection; confirmation bindings;
cancel; Core/Storage/Professions install and exact payload checks; original backup;
actual abrupt frozen-process exit after a destination replacement; fresh-process
rollback; interrupted status reporting without reinstallation/restoration;
changed recovery evidence; hardlinked/unsafe destination; in-process contention
while another thread holds the native client mutex. This case exercises the
cooperative in-process gate, not cross-process mutex contention.
QMessageBox responses are scripted, not human clicks.
Reporting failures and the crash boundary are injected; production checks are
not mocked. Tests retain the native account provider and filesystem/lock rules.

Artifacts contain bounded result JSON, source/build bindings, hashes and build
logs, never credentials, arbitrary child stdout or user profiles. Failed phase
records remain available. The VM lifecycle removes the account after the job;
no cleanup command targets host or previous evidence. Hosted Server/offscreen
results do not qualify Windows 10, visual interaction, installer lifecycle,
physical power failure or all interruption boundaries. Review the new harness
and its precise result claims before clearing any merge/release gate.
