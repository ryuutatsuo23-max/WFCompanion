# Saved character header preview

## Core handoff adoption (supersedes the DataStore reader below)

The companion now reads only `WFCoreDB.characters[linked GUID].details`, using the contract in `WFCORE_CHARACTER_DETAILS_HANDOFF.md` (Core implementation `2fd8aa2`). The previous DataStore reader is removed; there is no fallback to DataStore, manual profile fields, file time or inventory time.

The existing literal-only Core envelope validator checks producer/client/identity data. The header additionally checks the linked GUID, realm, name, version and interface. Only details schema integer 1 is supported. All five status fields must be present and either ok or unknown. Each ok value is independently validated against the handoff's type/range/string constraints; malformed or unknown fields are displayed as Unknown without retaining a previous field value. Conflicting recognized class ID/token values display Unknown class. A readable localized class name, recognized token or recognized ID can provide the class label when another class field is unavailable.

The header says `Saved observation` for a representable Core observedAt. A missing, invalid or unrepresentable timestamp displays `Observation time Unknown`, while valid class/level can remain visible. The tooltip distinguishes observation-attempt time from inventory age, disk-save time and live identity. Cache invalidation still follows changes to the linked Core file and character link; no DataStore files are read.

Seven focused offline tests cover the new Core-only reader, absent/future schema, partial/unknown fields, invalid values, GUID/realm/client/name mismatches, executable Lua rejection, cache invalidation and planning-control separation. Real installed Core remains unchanged and does not yet produce these details. Live reload/logout/exit, earned level changes and cross-character checks remain pending an explicitly authorized Core installation. An already-running preview retains its old reader until reopened.

## Earlier DataStore preview (historical)

Source-only companion change, 2026-10-23. No publication or addon modification.

The main selector is labelled Character. Class, level and saved time come from the linked account's DataStore_Characters.lua, matched through DataStore.lua GUID and reciprocal name/realm mappings, then checked against the existing Core identity link. The literal-only parser never executes Lua. Manual profiles and planning roles are unchanged.

The inspected installed DataStore_Characters version is 2026.10.14, declaring interface 16001 (also 120105). Its BaseInfo stores level in bits 0-6 and class ID in bits 7-10. Missing/invalid metadata is Unknown; no current class/level is inferred from manual fields. The timestamp is DataStore's lastUpdate, not file modification time or the newer inventory timestamp. A tooltip explains that distinction. The existing Beta save for Ice Leaker reports Mage, level 2, saved 23 Oct 2026 at 00:14 local time; its newer inventory save is independent.

Reads are signature-cached per profile. The two-second header refresh retries temporary unreadable saves, revalidates changed mappings/Core files, and stops on window close. Saved data is never written. The older experimental character-follow status now appears with its Settings controls instead of occupying the main header.

Playstyle is under Settings / Planning settings. It retains existing per-character persistence and wishlist/checklist draft handling. It does not change saved character details or inventory counts.

Validation: four new metadata/UI tests, fourteen saved-inventory tests, three navigation tests and eight saved-character connection tests passed (29 total). The isolated Beta preview rendered correctly and displayed Ice Leaker's saved details. Interactive selection and planning-settings testing remain with the user.

Preview: `build/character-header-preview-20261023/Open preview.cmd`. It uses copied installed JSON settings in its own state folder and reads the real Beta saves. Updates and the experimental capture monitor are disabled in this preview. No real settings, installed addons or public release files were changed.
