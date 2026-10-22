# Forever Core 0.7.0

Shared dependency for Forever addons. Interface 16001; current supported client
identity remains 1.60.1. This version is validated offline, not newly live-tested.

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

## API 1 lifecycle guarantees

These describe the existing lifecycle, not additional readiness or recovery APIs.
Core targets client 1.60.1 / interface 16001. Tests use synthetic APIs; the split
and these guarantees still require live-client validation.

| Trigger | Core behavior |
| --- | --- |
| Core's ADDON_LOADED | Initializes/validates the save envelope and sets db. Does not identify the player or call module hooks. Other addons' ADDON_LOADED events do not initialize Core. |
| Every PLAYER_ENTERING_WORLD | Sets inWorld=true, clears character/owner and attempts identification, then runs registered Start hooks, then Notify hooks. This also applies to repeated entry events and re-entry after leaving/logout. |
| PLAYER_LEAVING_WORLD or PLAYER_LOGOUT | Sets inWorld=false. Retains db/character/owner references and saved history. Does not call Start, Notify or an automatic Stop hook. |
| Register after world entry | Stores the module without invoking hooks or replaying events. Start first runs on the next world-entry event. |
| Explicit Notify | Calls registered Notify hooks even before Start, outside the world, or without usable identity/storage. Does not identify the player, initialize storage or call Start. |

Start and Notify receive no arguments (including no implicit self). Start must be
safe to repeat; Notify must work before Start. All Start attempts precede Core's
automatic Notify pass, but module order within each pass is unspecified. A failing
hook does not suppress another module or the later Notify pass. Do not depend on
registry changes made during dispatch taking effect in that same pass.

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

## Packaging

Install WFCore and WFStorage as sibling folders in Interface/AddOns. Back up an
old combined WFCore folder and all WTF settings before replacement. Replace the
old addon's package files, never its SavedVariables. Do not mix old combined TOCs
with the new Storage TOC. The split is source/package-only until explicitly installed.
See research/WFCORE_STORAGE_SPLIT_HANDOFF.md in the project for cross-chat ownership.
