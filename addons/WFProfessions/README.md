# Forever Professions 0.1.4

A cached profession journal with explicit manual capture for Tailoring and Cooking.
Requires **WFCore API 1**, supplied separately. Core and Professions version
numbers do not need to match. This candidate targets interface 16001; the last
verified client was **WoW Forever Beta 1.60.1.70532**.

The 0.1.4 journal and launcher were installed and tested by the owner during Beta.
Beta has ended. The planned release date is 4 November 2026 (user-provided);
**release-client compatibility is pending**, not implied by the interface number.
Current work is offline-only. This local candidate is not a published release or
authorization to install or change a companion bundle.

## Open the journal and settings

- `/wfprofessions`: toggle the journal.
- `/wfprofessions settings`: open settings independently.
- `/wfprofessions minimap show`: restore the minimap launcher.
- `/wfprofessions minimap hide`: hide the launcher.

Left-click the minimap icon to toggle the journal; right-click for settings.
Drag to reposition it around the minimap. Releasing a drag does not activate a
click. Position and visibility persist across reloads. Fresh settings use angle 135
(Storage defaults to 225). Existing saved positions, including 225, are preserved;
there is no automatic relocation. The new default has offline checks only; live
positioning remains pending. Per-frame launcher updates
run only while dragging. The approved logo also appears in the AddOn List; see
[artwork information](branding/README.md).

Settings uses the Forever Classic palette and offers Easy/Advanced details,
Classic/Slate/Warm/Midnight themes, background opacity (50-100%), text size
(12/14/16), window scale (70-130%, capped to fit), and launcher visibility.
Settings can open before the journal, is independently draggable, and closes
with its X or Escape. Closing the journal does not close independent settings.
The journal's title-bar lock controls dragging; its window position is
session-only. All preferences belong to Professions, not Storage.

## Browse cached observations

Choose a character and recorded profession, then select a recipe on the left.
Search filters recipe names; Clear restores the list. Mouse wheel and scrollbars
browse recipe and detail panes independently without changing recipe selection.
Tailoring and Cooking have separate capture ages and attempt notices.

The journal displays validated saved learned captures, with a saved single-recipe
probe fallback when applicable. With no supported observation, it shows Unknown.
Material names missing from a capture may resolve through a guarded client lookup;
resolved names stay in session memory and never rewrite the saved capture.

Easy mode shows names and known quantities. Advanced adds recipe/item IDs and
required-slot diagnostics. Hover tooltips follow the cursor. Tool requirements
are separate from materials and labelled recorded, with Met/Unmet/Unknown states.
Alternatives are choices, not cumulative ingredients. Unknown does not mean zero,
unlearned, no requirement or currently craftable. Every observation is historical,
even at age zero. Returned-list coverage is not proof of an unfiltered catalogue.

## Open profession and manual Refresh

For a supported current-character Tailoring or Cooking entry, **Open profession**
asks the game to open its own recipe page. It requires the supported build,
readable profession ownership and a known out-of-combat state. Opening never
captures or crafts. Once the matching page is ready, click **Refresh** separately
to record its returned learned recipes, materials and tool requirements.

Opening the journal, searching, switching professions and changing settings never
capture. The settings **Refresh age** button only updates displayed age labels.
There is no automatic crafting, inventory access, material spending, background
capture or companion count replacement.

Refresh requires your own matching visible profession recipe page and valid
observed window context. Closed, overview-only, mismatched or linked windows are
refused. Invalid/partial captures preserve the previous success; attempts are
stored separately. Interruptions preserve the previous capture and attempt.
Unknown learned flags, traversal limits and exceeded bounds also refuse replacement.
Other characters and professions are not refreshed. Normal client save flushing,
including normal logout, persists accepted results.

Refresh/Open profession require an existing supported journal entry. For initial
manual diagnostic capture, the commands include:

- `/wfprofprobe context`: record window/event/API context.
- `/wfprofprobe skills`: record a bounded profession-skill diagnostic.
- `/wfprofprobe recipes`: record a bounded recipe-list diagnostic.
- `/wfprofprobe learned tailoring` (or `learned`): capture learned Tailoring.
- `/wfprofprobe learned cooking`: capture learned Cooking.

Learned capture requires the matching own profession page. Traversal is bounded
to 2000 returned IDs and 100 learned detail records. Commands never craft.
Missing materials or requirements remain unknown/unavailable. Diagnostic captures
are separate from automatic collection, which remains disabled.

## Display modes and pending checks

- **Alongside:** the journal follows the native profession window, including the
  user's existing profession keybinding. Closing the native profession windows
  closes the journal; Escape also works while search has focus.
- **Custom â€” PENDING LIVE:** designed to show the cached journal alone. The
  inspected Beta native OnHide closes live profession context; hidden-window
  collection is not supported. Open profession temporarily exposes the native
  recipe page for a separate manual Refresh. If safe hiding is unavailable,
  native UI remains usable with a fallback notice.
- **Native UI â€” PENDING LIVE:** designed to leave the game's windows visible and
  suppress automatic journal opening while Professions remains loaded. Explicit
  journal/settings commands remain available. This does not implement a companion
  importer or continuous capture.

Mode changes never capture or craft, and do not reassign saved keybindings.
Custom/Native lifecycle, switching, profession-key/Escape behavior in those modes,
temporary native opening/manual Refresh in Custom, and native restoration remain
**PENDING LIVE**. Do not infer these results from prior Alongside tests. All
release-client checks are also **PENDING LIVE** while the client is unavailable.

## Confirmed Beta results

The owner confirmed six cached Tailoring and four Cooking recipes, selection,
search/Clear, resolved material names, per-craft quantities, separate recorded
requirements, Easy/Advanced cursor tooltips, and switching professions. Manual
Open profession and separate Refresh worked for both professions. Refused attempts
retained previous captures. Alongside opening/closing followed the existing and
remapped profession key; Escape worked, including with search focused.

For 0.1.4, the logo loaded on the minimap and in the AddOn List without Lua errors.
Independent settings, left-click toggle, drag without activation, angle reload
persistence, hide/slash recovery, and readable 16px text at 130% scale with reload
persistence were confirmed. These are Beta observations, not release guarantees.

A read-only comparison after normal logout confirmed the entire saved probe DB
unchanged after launcher/appearance testing: Tailoring, Cooking, materials,
requirements, timestamps, attempts and earlier probes. Only presentation
preferences changed. The latest learned attempts were successful; older refusal
checks do not imply the latest attempt is still refused after a successful Refresh.

## Saves, package and companion boundary

`WFProfessionsDB` holds journal/preferences and `WFProfessionsProbeDB` holds manual
observations. Both use `SavedVariables/WFProfessions.lua`. Keep that file and its
backup intact. Unsupported/malformed saved envelopes are preserved; no repair or
Core schema migration is performed. Cached projection and name resolution do not
rewrite observations. Normal save flushing is not a live companion export.

No WFProfessions companion importer is included. Installing this addon does not
automatically populate companion profession views. The separate DataStore reader
must not be confused with a WFProfessions integration. Core, Storage, a combined
launcher and companion bundle changes are outside this package.

The archive contains runtime Lua, TOC metadata, this README, license, branding
notes and approved PNG/TGA artwork. `PACKAGE_SHA256.json` records the 15 source
member hashes. Verify the archive hash against the separately supplied package
handoff; an embedded manifest alone is not a trusted external pin.

Development previews, detailed historical handoffs, build scripts and evidence
notes are repository-only and intentionally excluded from this install archive.
The source checkout provides the builder at `tools/professions_preview/package.py`
and synthetic tests at `tools/professions_preview`. No personal saves are loaded
by that test suite. The last runtime suite passed 133 offline checks; synthetic
checks do not establish outstanding live behavior. Integration requires a fresh
package handoff and explicit scope approval; publishing requires user approval.

Original code Copyright (C) 2026 Steve Vanhamel and WFCompanion contributors.
GPL-3.0-only; see [LICENSE](LICENSE). No warranty. Client textures/fonts are
referenced, not redistributed. No game recipe catalogue, artwork or fonts are
bundled; the original approved Forever Professions branding is included.


### Asset provenance and notices

The original Professions PNG and its derived TGA are **CC BY 4.0**, by explicit
owner choice for rights the owner controls. Code remains **GPL-3.0-only** under
the included LICENSE. [Branding provenance, attribution and licence](branding/README.md)
records the owner's personal-account/input confirmation, permission for their
Storage reference, generation terms and export modifications. Retain those
notices and the CC BY 4.0 link when redistributing artwork; mark further changes.

No client artwork, font or sound bytes are bundled. Client resource paths are
in-game references. This independent project is not endorsed by Blizzard or
OpenAI. Installed addons, saves and companion bundles are outside this candidate;
no installation or publishing is authorized by these notices.
