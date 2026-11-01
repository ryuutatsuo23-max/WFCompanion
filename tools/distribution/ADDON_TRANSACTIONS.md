# Transactional Addons installation

The normal **Install bundled** buttons use the shared transaction service. The
confirmation names the client, destination, addons and backup location; Cancel is
the default. Storage and Professions also install the pinned Core package.
Changed addon files require explicit replacement confirmation.

## Runtime and source layout

The distribution runtime consists of `install_addons`,
`addon_installation_context`, `addon_installation_configuration`,
`addon_installation_service`, `addon_operation_status` and
`addon_installation_gui`. The Qt page loads `addon_recovery_dialog` on demand.
The builder audits these exact sources, rechecks their identities and hashes,
and maps the six distribution modules to the payload root. Required lazy imports
are collected explicitly. Tests, state and verification tools are excluded.

The repository-root `install_addons.py` imports the canonical source engine in
`tools/distribution`; both paths share the same lock registry. Frozen builds
collect the canonical engine directly. The launcher `--install-addons` and
installer actions keep their legacy route; this change does not claim
transactional integration of those separate entry points.

## Ownership and preservation

GUI operations require native Windows current-user identity and non-elevated
interactive context. Unknown identities, impersonation, elevation, conflicting
configuration and replaced locations fail closed. Environment paths and the
window's data directory cannot authorize another user.

The current user's LocalAppData Known Folder anchors the configuration registry
at `WoWForever/AddonInstallation`. Default state is `WoWForever/Companion`, with
code backups under `AddonBackups`. Existing custom selections require verified
identity and explicit adoption; no backups or preferences are migrated. Addon
recovery records are separate from the companion backup ZIP feature.

The engine binds the canonical client to filesystem identity and a cross-process
lock. It validates pinned package bytes, safe paths, link counts, supported local
filesystems, existing recovery evidence and original contents before preparing
backups and stages. Pending metadata precedes forward writes. Saves, unrelated
addons and original backups are retained. Code load lists follow module bytes.
Different clients remain independent; competing operations for one client block.

A blocked or uncertain operation never becomes successful merely because there
is no exception or pending marker. Verified installation/rollback, durable
reporting and evidence retirement have separate outcomes. Cleanup errors retain
evidence and a visible warning. Navigation and closing are blocked during Addons
operations.

## Recovery

Unresolved recovery prevents new installs. **Review addon recovery** inspects
bounded records without starting another install. Completion or rollback needs
explicit confirmation. The service rechecks the client, account, configuration,
transaction and bytes under the lock. Invalid, conflicting or unverifiable
evidence requires manual review; it is never guessed or deleted.

**Finish reporting** requires independently verified terminal file outcomes with
reporting/retirement outstanding. It does not reinstall addons. A rollback is
reported as rollback, never installation success. Ambiguous late errors retain
warnings until a fresh verified resolution.

## Verification and limits

Tests use disposable clients, packages and identity providers. They cover normal
installs, dependencies, interruption, rollback/recovery, durable reporting,
configuration adoption, Windows mutexes, hard links and UI confirmation.
Packaging tests check source mapping and import closure without PyInstaller or
Inno Setup. Existing public Qt feature regressions remain required.

These are cooperative process-interruption protections, not an OS sandbox or
atomicity against hostile concurrent filesystem writers. Physical power loss,
directory-entry durability, timestamp/ACL restoration, privileged symlinks,
alternate users and other filesystem providers need separate qualification.
Runtime identity/query failures reject rather than guess.

A rebuilt frozen application and installer still require independent Windows
validation using synthetic clients, then separately authorized fresh-install,
upgrade and uninstall/data-preservation checks. Prior frozen candidates and
source tests do not prove this frozen write path. No live-game compatibility or
public release approval is implied.
