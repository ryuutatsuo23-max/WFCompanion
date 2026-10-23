# Forever Core 0.7.0

Shared dependency for Forever addons. Interface 16001; current supported client
identity remains 1.60.1. Offline validation and the limited user-reported save
verification below do not complete the broader live-validation checklist.

On October 22, 2026, the user reported normal logout persisted Beta WFCore.lua
at 23:01:12; parsing succeeded with two character records on build 70532, and the
companion reader accepted three Storage snapshots. Verification itself was
read-only. This report does not establish settings/history preservation, current
live character identity or completion of the pending lifecycle/API tests.

Saved-file integration remains active. The optical bridge is parked because its
strip is too distracting; no replacement live transport was established. Storage
eligibility is unchanged and automatic count replacement remains blocked. See
research/WFCORE_LIVE_VALIDATION_CHECKLIST.md in the repository for remaining checks.

## Saved-data welcome and command fix

Welcome.lua shows a compact 400x244 panel on the first PLAYER_ENTERING_WORLD of
the UI load, unless dismissed previously. It explains manual /reload and normal
logout/exit saves, and that a connected WF Companion shows saved information.
It never invokes reload, logout, exit, import or a live transport. Dismiss closes
the panel for this UI load. Check **Don't show again** before dismissing to store
`WFCoreDB.settings.coreWelcomeDismissed=true` in the
existing account-wide SavedVariables envelope. The preference survives normal
client save/load across characters in that account save, not across separate
client/account folders. Unsupported save envelopes are never repaired or changed;
their dismissal lasts for the current UI load only.

The checkbox starts unchecked for a new account. Use **/wfcore welcome** to reopen
with the saved preference selected; uncheck it and dismiss to restore the reminder
on the next login/reload. Simply reopening does not change the saved preference.
There is no inventory window or B binding in Core. Existing settings, character
history, producer/schema versions and Storage eligibility remain unchanged. This
optional settings key needs no companion parser change; snapshot addonVersion
still belongs to Storage. Core package version remains 0.7.0 / API 1; distinguish
the source-only command fix from the installed welcome by commit and file hashes.

Wording was checked against the current file-based companion reader
(`tools/qt_preview/saved_character_connection.py`), the October 22 logout report,
and the Forever recorder author's documented save points
([Forever State](https://github.com/tzcnt/forever-data)). That external project is
supporting API-behavior evidence, not live validation of this welcome. No external
code was copied. The user's logout report confirms persistence on build 70532;
the user subsequently confirmed the welcome renders and checked dismissal survives
logout/login on October 23. The installed /wfcore welcome incorrectly opened bags:
Storage's legacy SlashCmdList.WFCORE overwrote the original welcome handler.
The source-only fix registers /wfcore under the distinct WFCOREWELCOME key.
Storage's WFCORE compatibility handler, /wfstorage, /wfbags, /wf and B binding
remain untouched. Corrected reopening, unchecking to restore the reminder,
reload/normal-exit timing and broader integration still need live checks. The local extracted
Forever UI includes BackdropTemplate, UIPanelButtonTemplate and font-string APIs.

Focused tests in `tests/test_core_welcome.py` use synthetic saves only: first entry,
re-entry, dismissal/reopen, cross-character save/load, legacy settings/history,
unsupported saves, wording and absence of reload/input/timer side effects. No
installed addon or real save was changed while implementing or testing this UI.

## Ownership

Core owns guarded API reads, character identity, event dispatch, module lifecycle,
and WFCoreDB persistence. It contains no bags scanner, inventory UI, native-window
hooks or B binding. Forever Storage is a separate addon with `Dependencies: WFCore`.

API version 1 exposes Access, Read, Field, Integer, Stamp, On, Register, Notify, GetDiagnostics and
AttachNamespace. Register(name, module) requires a unique addon name. Start runs
on PLAYER_ENTERING_WORLD; Notify is an isolated refresh callback. Callbacks must
be bounded and avoid per-frame polling. On returns false for unavailable events.
AttachNamespace(addonNamespace) gives each addon its own writable state with
fallback reads of shared services and current db/character/owner/inWorld. Never
shadow those four shared fields. Do not place another addon's UI state on Core.
Read and Field return a guarded value plus status; unknown/restricted is not zero.

API 1 rejects invalid registrations before changing its registries. Register requires
a nonblank name without control characters and a plain module table; Start/Notify
must be absent or functions. Hooks may be assigned after registration. Invalid
registration raises an error; On returns false for malformed events/callbacks or
unavailable events. Module hook lookup and execution are isolated from other modules.
AttachNamespace requires a plain table distinct from Core with no existing shared
fields. It rejects ordinary writes to db/character/owner/inWorld and locks its
metatable, while other addon state remains writable. This guards accidental writes,
not deliberate rawset/debug bypasses. No saved-data or lifecycle semantics change.

## Guarded-read contract (current API 1 behavior)

These helpers are characterized directly in tests/test_core_reads.py with synthetic
Lua 5.1 APIs. Synthetic restricted values are not proof of live-client secret-value
behavior. Field now preflights table access before indexing; other read-helper
contracts are unchanged. This fix was installed and hash-verified on October 22,
2026; focused live validation of this fix remains pending.

| Helper | Current contract and caller responsibility |
| --- | --- |
| Access(value, record) | Requires issecretvalue and canaccessvalue; rejects secret/denied values and missing or throwing guards. A truthy record argument additionally requires canaccesstable approval. Returns a boolean, not a validity/type check. |
| Read(fn, ...) | Calls a function with the supplied arguments under pcall and processes only its first result. Returns a value/status pair as below. |
| Field(record, key) | Rejects non-table records with nil/error, then requires Access(record, true) before indexing. Denied records or missing/throwing guards return nil/restricted without lookup. Accessible records are indexed under Read's pcall and the result is guarded. Callers still supply a safe key. |
| Integer(value, low, high) | Inclusive integer-range predicate for an already accessible value and finite numeric bounds. Does not invoke access guards or protect comparisons with pcall. Invalid bounds may raise; infinite bounds can allow infinity. |
| Stamp() | Read(GetServerTime), with the same statuses. Does not independently require a nonnegative integer timestamp; callers needing that domain must validate it. |

Read statuses, in evaluation order:

- unavailable: fn is not a function.
- error: the function or field lookup throws; the error object is discarded.
- restricted: value/table access cannot be established, including missing guards.
- unknown: the readable result is nil. With missing guards, nil is restricted.
- ok: a readable boolean (including false), finite number (including zero and
  fractional/negative values), string, or accessible table.
- invalid: an accessible unsupported type, NaN or infinite number.

Strings have control characters and pipe markup replaced by spaces, then are
limited to 160 bytes; this is not Unicode-aware truncation. Tables are returned by
reference, not copied or recursively sanitized. Their fields need separate guarded
reads. Missing fields normally return nil/unknown; nil records and throwing
metamethod lookups return nil/error. Handled read failures do not create runtime
diagnostic entries, log raw errors or write to saves.

### Scope of the Field precheck

Denied tables no longer invoke __index or return an apparently readable field.
For accessible tables, missing fields remain unknown, throwing lookups remain error,
and restricted results remain restricted. Non-table inputs are explicitly unsupported.
Storage already obtains records through Read; Field now rechecks access at each
field. Loss of required item fields leaves collection unknown or refuses an action;
loss of optional fields omits that metadata. No Storage code or save schema changes.
Tests cover access loss after the initial successful record read. Integer's finite
numeric-bound precondition and Stamp's lack of timestamp-domain validation remain
unchanged. The precheck is not an atomicity guarantee or key-access validation.

## API 1 lifecycle guarantees

These describe the existing lifecycle, not additional readiness or recovery APIs.
Core targets client 1.60.1 / interface 16001. Tests use synthetic APIs; the split
and these guarantees still require live-client validation.

| Trigger | Core behavior |
| --- | --- |
| Core's ADDON_LOADED | Initializes/validates the save envelope and sets db. Does not identify the player or call module hooks. Other addons' ADDON_LOADED events do not initialize Core. |
| Every PLAYER_ENTERING_WORLD | Sets inWorld=true, clears character/owner and attempts identification, observes details when ownership is usable, then runs registered Start hooks, then Notify hooks. This also applies to repeated entry events and re-entry after leaving/logout. |
| PLAYER_LEAVING_WORLD or PLAYER_LOGOUT | Sets inWorld=false. Logout first attempts a GUID-checked details observation for the normal save boundary. Retains db/character/owner references and inventory history. Does not call Start, Notify or an automatic Stop hook. |
| Register after world entry | Stores the module without invoking hooks or replaying events. Start first runs on the next world-entry event. |
| Explicit Notify | Calls registered Notify hooks even before Start, outside the world, or without usable identity/storage. Does not identify the player, initialize storage or call Start. |

Start and Notify receive no arguments (including no implicit self). Start must be
safe to repeat; Notify must work before Start. All Start attempts precede Core's
automatic Notify pass, but module order within each pass is unspecified. A failing
hook does not suppress another module or the later Notify pass. Do not depend on
registry changes made during dispatch taking effect in that same pass.

### Dispatch limits and caller rules

Synthetic tests in tests/test_core_dispatch.py cover the dispatch guards. Fixtures
remain bounded even if a guard regresses. These fixes were installed and
hash-verified on October 22, 2026; focused live validation of these fixes remains
pending. API and saved-schema versions are unchanged.

- Notify is synchronous. Calls made while a notification pass is active return
  immediately; nested requests are discarded, not queued or replayed. Hook failures
  retain existing diagnostics and peer isolation. After the pass, a later independent
  Notify runs normally. Hooks must not rely on a nested request refreshing a peer
  that already ran earlier in the pass.
- Event dispatch captures the callback count at entry. On can append callbacks,
  but additions do not run in that delivery; they are eligible on the next delivery,
  including a separately nested delivery. Order, arguments and error isolation are
  unchanged. Duplicate registrations remain; total registrations across deliveries
  are not capped. Direct mutation of Core's event tables is unsupported.
- Register during Start/Notify changes a table being traversed with pairs. Same-pass
  participation has no supported guarantee. A successfully registered module is
  available to subsequent passes. Module dispatch order remains unspecified.
- A bounded nested event delivered directly by the synthetic event driver runs
  synchronously and resumes the outer callbacks afterward, preserving arguments.
  This does not establish how the live client schedules events.

Register modules and event handlers during addon initialization, outside dispatch;
do not repeatedly register them from Start on every world entry. Keep Notify hooks
as bounded refresh consumers that do not require nested Notify calls. Module
registration during traversal still has no same-pass guarantee. The guards do not
prevent arbitrary work inside hooks, repeated registration across deliveries or
direct recursive event delivery. Storage source is unchanged; integration tests
confirm its Notify hook refreshes both views once per independent pass, with no
save changes. No installed addon or save is changed by this source work.

inWorld is an event-state flag, not a readiness guarantee. Modules needing current
character storage must check inWorld, db, character and owner at use time, including
inside delayed callbacks, and compare a captured owner before using pending work.
Retained character/owner references while out of world are not permission to collect.
Modules own cancellation/cleanup and may subscribe to leaving/logout through On;
Core supplies no automatic teardown, retry timer, late-start or readiness event.

Identification is retried only on the next world-entry event. Missing, restricted or
invalid GUIDs, unsupported client version/interface, invalid character records, or
the 50-character limit for a new GUID leave character/owner nil. db can still be
usable in these cases; an existing character remains usable at the limit. Optional
name/realm/build/locale metadata can be unknown without blocking an otherwise valid
identity. Start and Notify still run after identification fails. notice is diagnostic
text that later hook failures may overwrite; it is not a stable readiness API.

Unsupported save envelopes leave db nil and the saved value untouched. World entry
does not revalidate or replace that envelope. There is no automatic in-session
repair; normal initialization occurs when Core loads. Supported existing envelopes
retain the current initialization behavior, including inventorySchema=2. None of
these lifecycle rules changes the persistence contract below.

## Runtime diagnostics

GetDiagnostics() returns a detached array of the most recent 32 failures, oldest
first. Each failure adds one record; the oldest is discarded at capacity. Module
records contain kind="module", module (registered name), and hook (Start/Notify).
Event records contain kind="event", event, and hook (OnEvent/RegisterEvent).
OnEvent records also contain callbackIndex, the one-based registration position
within that event. On does not accept an owner, so an event record identifies its
callback position, not an inferred addon/module owner. Labels are limited to 80
bytes and control characters/pipe markup are replaced with spaces; long labels
can therefore be ambiguous.

History is private runtime state, reset when Core is loaded anew. Re-entry and
logout events do not clear it in memory. No raw errors, stack traces, callback
arguments, timestamps or character data are retained. There is no automatic chat
output, UI, polling, persistence or companion export. Reading/modifying the returned
copy does not change Core's history. Existing notice text, failure isolation and
lifecycle behavior are unchanged. Malformed registration arguments still use the
existing rejection behavior; only failed hook execution/lookup, event callbacks
and RegisterEvent calls enter this history. API and saved schema versions remain
unchanged; Storage's snapshot addonVersion remains independent.

## Companion contract and compatibility

SavedVariables remains WFCoreDB, physically SavedVariables/WFCore.lua. Producer
remains WFCore, envelope schema remains 1, inventorySchema remains 2. Core retains
the legacy inventory envelope for compatibility; future domains must be versioned
and reviewed with the companion owner. Storage writes its own snapshot addonVersion
(0.7.0), independently of future Core releases. API version is not save-schema version.

Existing settings stay in WFCoreDB.settings without a destructive migration; these
legacy keys belong to Storage. New addons should use their own named settings table
under settings and leave Storage's keys alone. Existing characters, GUID keys,
locations and legacyV1 archives remain in place. Unsupported saves are not rewritten.

The companion consumes local saved files after WoW flushes them on reload/logout.
There is no socket, HTTP service, live two-way bridge or companion code in this addon.
Core alone preserves inventory history but cannot create new inventory observations.
Both addons must be enabled to collect bags/bank data.

## Saved character details (source-only)

Core optionally writes `WFCoreDB.characters[guid].details`, independent of
`identity`, `client` and inventory `locations`. This schema-1 observation contains
classID, classToken, className, level and observedAt, with a `status` table naming
each field as `ok` or `unknown`. Unknown fields are absent, never zero or a stale
value paired with a new timestamp. Missing details in older saves means Unknown.
Class names are localized and use Read's markup/control sanitization and 160-byte
limit. A class token or ID must not be inferred from the name.

Details refresh after identity on every PLAYER_ENTERING_WORLD (including login
and reload), before Start/Notify; on PLAYER_LEVEL_UP while in world using its
guarded new-level payload; and on PLAYER_LOGOUT before Core clears inWorld.
The latter covers the normal logout/reload save boundary, including when
PLAYER_LEAVING_WORLD fired first. No reload hooks, timers, polling, save-file writes
or automatic UI actions are introduced. Actual client save ordering remains a
live-test item. No new module API or login lifecycle event is introduced.

Every observation rechecks UnitGUID against the selected owner and record. Without
usable storage or matching identity it preserves the previous record/timestamp.
Otherwise readable fields replace the preceding schema-1 observation, with Unknown
for unavailable/restricted/invalid fields. observedAt is guarded GetServerTime in
Unix seconds: the observation attempt time, not file flush time, inventory freshness
or proof of live identity. An unavailable clock has unknown status and no timestamp.
Other characters, settings and inventory records remain untouched. Unsupported
existing details schemas/values are preserved; consumers must display Unknown for
them. Envelope schema 1, inventorySchema 2, producer WFCore, Core 0.7.0 / API 1 and
Storage's snapshot addonVersion are unchanged. No installed package is updated.

See `research/WFCORE_CHARACTER_DETAILS_HANDOFF.md` for exact types, bounds,
companion adoption rules, API evidence and pending live checks. The companion owner
must review this additive contract before changing its header reader. DataStore
fallback policy and parsing belong to that chat; no companion code changed here.

## Packaging

Install WFCore and WFStorage as sibling folders in Interface/AddOns. Back up an
old combined WFCore folder and all WTF settings before replacement. Replace the
old addon's package files, never its SavedVariables. Do not mix old combined TOCs
with the new Storage TOC. The split is source/package-only until explicitly installed.
See research/WFCORE_STORAGE_SPLIT_HANDOFF.md in the project for cross-chat ownership.
