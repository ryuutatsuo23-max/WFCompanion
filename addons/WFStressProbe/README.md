# Forever stress-test capability probe

Small, independent addon for the installed Forever client line. It reads game APIs and records diagnostic snapshots automatically. It does not cast, target, send keypresses, reload the UI, alter other addons, or connect to the desktop companion.

## The short version

Once installed and enabled in the **Stress Test** client:

1. Start with **only Forever Stress Test API Probe enabled**. Disable other addons for this session; do not uninstall them or delete their settings.
2. Log in and play normally. Collection starts about two seconds after entering the world. No probe window or manual spell selection is required.
3. Type **`/reload`** when convenient. WoW saves the collected reports automatically. A normal logout/exit also saves them.

That is enough. There is no timed checklist to complete. If it fits naturally, use a spell, receive a buff, gain XP, and move an item in your bags. We can inspect whatever evidence is available afterward. Don't force combat or progress just for this probe.

Optional: `/wfprobe` opens the latest report. Run checks takes an immediate snapshot; a spell ID can override automatic cooldown selection for that one snapshot. `/wfprobe 12345` opens and checks that explicit ID. Copying the report is optional.

## Installation scope

Source folder: `C:\Dev\WoWForever\addons\WFStressProbe`.

Prepared package: `C:\Dev\WoWForever\build\WFStressProbe-0.1.0.zip`. The ZIP contains the `WFStressProbe` folder, not a second nested addon directory. No third-party addon files are bundled and there are no dependencies.

This task builds the source/package; it does **not** copy files into either game installation or change enabled-addon selections.

The launcher check on October 21 identified:

| Client | AddOns directory | Inspected build |
| --- | --- | --- |
| Stress Test | `C:\Program Files (x86)\World of Warcraft\_forever_\Interface\AddOns` | 1.60.1.70245 |
| Beta | `C:\Program Files (x86)\World of Warcraft\_classic_beta_\Interface\AddOns` | 1.60.1.70450 |

The supplied large CurseForge collection is in the **Beta** folder. Its enabled state and installed files do not by themselves tell us what is enabled in Stress Test. Always check the selected client's AddOns list. Test the probe alone first, then add preferred addons gradually (one bag replacement/main UI replacement at a time).

The package's destination, when installed, must contain `WFStressProbe\WFStressProbe.toc` directly below AddOns. Restart the client after a new addon-folder installation so it is discovered. No automatic install/restart script is included.

## What is recorded

- Client version/build/interface, locale, project/class IDs, session time and login/world context; no character/account names, realm names or GUIDs.
- Own HP/max HP; active power type/current/max; explicit mana current/max; XP/current maximum.
- Up to eight helpful aura records on the player, using only readable spell ID, stack, duration and expiration fields.
- Up to four distinct known spells discovered in action slots 1-12. Macros/items are not resolved. A missing/empty action bar or unavailable spell-known API is labelled, not guessed. We record cooldown fields, not a castability claim.
- Inventory API sample: bags 0-4 and at most four slots per bag, item IDs, counts and lock state. This is **not a full inventory scan**; bank, equipment and extra bag types remain unobserved.
- Event names and bounded counts. Payloads are ignored. Counts include all units and do not certify that a particular player's event fired.

Each call reports readable data, missing API, nil/unknown, restricted data, unavailable guard, unexpected type or error. Raw exceptions, links, names and secret values are never stored. Nil inventory records are not interpreted as zero ownership. The probe does not attempt to bypass restricted values.

## Automatic collection and saving

The addon takes an initial snapshot, then batches relevant HP/power/XP/aura/cooldown/bag/action-bar events into at most one pending ten-second capture. There is no per-frame callback or continuous polling. A final capture is attempted on logout/reload if world context is still valid; otherwise existing snapshots are retained. Brief transitions inside the batching interval may be missed: this is a capability sample, not a combat log.

`WFStressProbeDB` is the only SavedVariables global. It keeps the latest **three addon-load sessions**, each with its first baseline and most recent **59** further snapshots. Each report is capped at 32,000 characters. Earlier snapshots/sessions rotate out to keep disk and memory usage bounded. `/reload` creates a new session after saving the previous one.

WoW writes this variable to its normal file at `/reload`, logout or normal exit:

`<selected client>\WTF\Account\<account>\SavedVariables\WFStressProbe.lua`

It may also maintain its usual `.bak`. Data is held in memory until WoW flushes it; a crash or forced process termination can lose recent unsaved samples. No desktop watcher/importer or arbitrary file-writing API is used. Reading reports later should parse data without executing the SavedVariables Lua file.

If a future/unrecognized saved schema is encountered, the addon preserves it and falls back to memory-only diagnostics with a chat notice. Missing secret-value guards fail closed. Missing timers fall back to world-entry/manual/logout captures. The optional window preserves selected report text while it has focus.

## Compatibility evidence and validation

Interface `16001` is the initial TOC target, supported by the installed ForeverCompanion 1.0.0, BagSync 20.38, Syndicator 287 and MiniAuras 5.43.8 manifests. That is source evidence, not a successful load test. The report records actual `GetBuildInfo()` results for verification.

Primary API signatures and restriction flags were inspected in the local 70245 package; selected files were also compared with 70450. See [the client inspection](../../research/LOGIN_API_INSPECTION_2026-10-21.md) and [installed-addon references](../../research/PROBE_ADDON_REFERENCES_2026-10-21.md).

Offline tests execute the actual addon code in Lua 5.1 using the already available Python `lupa` runtime:

```powershell
python -B -m unittest discover -s tests -p 'test_stress_probe.py' -v
```

Tests cover secret/inaccessible values, missing guards/APIs, errors/nil, world gating, bounded sampling, event batching, persistence across simulated reloads, retention limits, malformed saved data, future-schema preservation and the optional UI wiring. Lua mocks cannot reproduce Blizzard's real secret-value VM, UI rendering, native API restrictions or disk flush timing. Those remain live-test work.

The desktop companion, existing character/settings files, installed addons and their databases are unchanged.

## Restriction diagnostics revision 1 (October 21)

Additive schema-1/report-0.1.0 diagnostics preserve the existing desktop reader.
The separate Access failure details section distinguishes issecretvalue, denied
canaccessvalue and denied canaccesstable results without recording the values.
C_Secrets checks cover build restrictions, general aura/cooldown secrecy, player
mana/maxima, first helpful aura index, and sampled spell cooldown secrecy.
Missing checks remain Missing API; thrown calls remain API error. No raw errors
are saved and a secrecy predicate does not prove why another API call failed.
Signatures come from extracted build 70245 documentation; availability and results
on live build 70532 require the next in-game reload/sample. Existing history,
sampling cadence, storage schema and desktop files are unchanged.

## Full inventory/equipment capture (October 21)

The additive `Full carried inventory and equipment - revision 1` section attempts
every slot in bags 0 through NUM_TOTAL_EQUIPPED_BAG_SLOTS, including an extra bag
when the client declares one. A declared keyring (-2) is also sampled. If the
constant is unavailable it falls back to 0-4 and explicitly reports partial coverage.
Equipment API slots 0 (ammo) and 1-19 are sampled for item ID and quantity.
Rows use B<bag>/<slot> or E<equipment slot>, id and qty. The section timestamp is
client-local time shared by its sequential reads, not an atomic transaction.
Nil slots and inaccessible counts stay Unknown; conflicting bag item IDs mark the
quantity Unknown (item changed). Equipment quantities are not inferred as one.
Bank/mail are not scanned. Safety bounds are 10 equipped bags, 200 slots per bag
and the existing 32,000-character report limit; incomplete coverage is explicit.
The original small Inventory section remains for the unchanged desktop summary.
Full records are in report details; no character inventory is automatically imported.
PLAYER_EQUIPMENT_CHANGED joins the existing debounced event collection.
Existing schema, retained history, namespace and save timing remain unchanged.

## Passive recipe ingredients (October 21)

Open a profession and leave it open a few seconds. The probe reads the current
profession's returned recipe list, learned status, schematic output ID/quantity,
and reagent slot quantities, required flags and alternative item IDs. It never
selects recipes, changes filters or crafts. Reload saves the additive text section
through the existing report mechanism; no companion or DataStore import occurs.
The most recently observed profession is retained in memory after window closure;
completed scans are also added to normal session history. Existing history limits
still apply. Missing, inaccessible and secret values remain explicitly labelled.
Four recipes per timer batch, at most 2,000 recipes, 16 slots and 8 alternatives per
slot are attempted. Collection bounds are labelled Partial.
Alternatives are choices rather than cumulative ingredient requirements. This is
an observed schematic, not a complete crafting calculator (variable quantities
and optional selections are not resolved). No profession API calls run per frame.
Verified client executable: 1.60.1.70532 / interface 16001. API shape comes from
extracted Blizzard definitions; live schematic readability still needs validation.
The desktop summary remains unchanged; see report details for the recipe section.

Large recipe lists now use revision 2: whole recipes are stored in bounded pages
under each session's recipeSets in WFStressProbeDB. The regular report includes
coverage and page count (and small single-page captures). Each set has profession,
capture header, coverage and ordered pages. The unchanged companion does not yet
display these separate pages; they can be inspected directly in the saved report.
Pages roll over between recipes after 6 KB, with a 24 KB validation ceiling and
40-page safety limit. Up to ten professions per session retain their latest scan;
the existing three-session retention applies. Normal diagnostic snapshot history
is not consumed by individual pages. Closing a window mid-scan records Partial.
Existing saved reports are preserved through the existing validation path.

## Trainer offers

Open a trainer and leave the window open for several seconds. TRAINER_SHOW and
TRAINER_UPDATE trigger batched read-only offer scans; closing stops an unfinished
scan with Partial coverage. No selection, training purchase or filter changes occur.
Capture includes NPC name, timestamp, observed filter flags, service names/status,
required level, skill/rank and ability requirements with their returned met flags,
cost and profession-training flag. C_Trainer.GetTrainerType distinguishes copper
from pet training points; unavailable currency metadata stays Unknown. Costs are
the current character's quoted prices, not universal prices. Indices are not IDs.
Nil optional requirements remain Unknown, rather than being inferred absent.
The extracted Forever Blizzard trainer UI supplies these API signatures; live
results still need validation. Existing secret/access guards protect every scalar.
trainerSets uses the same bounded page storage as recipes, separately: latest scan
per NPC name (names can collide), up to ten trainers per session and three sessions.
Four offers per timer batch, at most 2,000 offers, 40 pages and 16 ability requirements
per offer. Report details show coverage; full pages stay in the saved probe file.
The desktop tool and display addon are unchanged. Reload writes the probe normally;
installation never overwrites existing SavedVariables.

## Character bank capture

BANKFRAME_OPENED starts an automatic scan; bank/bag changes queue a fresh sample
while open. BANKFRAME_CLOSED or leaving the world cancels remaining reads, preserving
Partial results. Twelve slots per timer batch avoid per-frame polling. No bank UI
selection, purchases, sorting, deposits or withdrawals occur.
The probe reads BANK_CONTAINER and client-declared CharacterBankTab_1 through _9
container IDs, deduplicates them, and samples each returned slot (up to 200 per
container). Missing declarations and failed queries remain explicit; this does not
prove coverage of undeclared containers. Account and guild banks are not scanned.
Item ID, quantity and capture time are recorded; nil is Unknown, not an empty-bank
claim. Conflicting item IDs invalidate quantities. Bank observations are sequential
and may change during a scan. Reopening refreshes the observation; closed-bank data
remains a timestamped snapshot, not a live total.
Full records use session bankSets with the same bounded page validation as recipes;
regular report details show coverage. Existing histories, tool and display addon
are unchanged. Live bank API compatibility needs validation on build 70532.

## Empty trainer window diagnostics

Speak to the NPC and leave its conversation/trainer window open for ten seconds.
The probe observes GOSSIP_SHOW/CLOSED and trainer show/update/description/name/close
events, recording bounded counts and registration success. At interaction start
and after 0.5, 2, 5 and 9 seconds it reads trainer/gossip window visibility, service
count and filter flags. Closing or leaving cancels delayed reads. No conversation
text, choices or event payloads are collected; nothing is clicked or purchased.
Counts without a visible trainer frame are explicitly context-unconfirmed and may
be stale from a previous trainer. Visible trainer frames may trigger the existing
bounded offer scanner, including zero-offer results. This is not hidden-offer proof.
trainerDiagnosticSets stores the latest visit per NPC name, at most ten per session,
under existing session retention. Each visit has at most 24 observations; no polling
or additional persistent global is used. Existing reports survive validation.

## Party connection and vitals diagnostic

Automatic snapshots now sample party1 through party4, with no names or GUIDs.
GROUP_ROSTER_UPDATE, UNIT_CONNECTION and UNIT_FLAGS use the existing ten-second
event debounce; no per-frame polling is added. Membership and connection must be
readable and true before querying existence, death/ghost, HP or power. An explicitly
disconnected member is Offline: HP, mana and death are not queried or replaced by
zero. Unknown/restricted connection also suppresses those reads. Death is reported
only from UnitIsDeadOrGhost, never inferred from a numeric HP value. Mana is queried
only for a confirmed mana power type. Online readings may still be stale or out of
range; secret/access failures retain their diagnostic labels. Raid members are out
of scope. Results are additive text in normal reports, using existing history and
save timing; no companion import or display-addon change. Client API declarations
were checked against the extracted Forever UI; live results need the next reload.

## Vendor listings

MERCHANT_SHOW/UPDATE queue automatic snapshots while the vendor is open. Close
cancels unfinished scans with Partial coverage. No buy/sell/buyback/repair actions,
filter changes or page selections occur. Modern C_MerchantFrame.GetItemInfo is
preferred; legacy GetMerchantItemInfo is used only if the modern function is absent.
Capture includes listing item ID/name, quoted copper price, purchase bundle count,
stock (-1 is unlimited), purchasable/usable flags, affordability and extended costs.
Extended item/currency IDs are extracted from guarded links; raw links are not saved.
Prices are character-specific quotes per bundle. Detailed reputation, quest and
level gates are not inferred from the purchase flags; they remain Unknown. Vendor
filters may limit the returned list. Item stock and prices can change during reads.
Full data is in vendorSets: latest scan per NPC name, ten vendors per session, using
existing session retention. Four listings per batch, 2,000-listing/40-page safety
limits and 16 extended costs per listing keep capture bounded. Existing saved data
is not changed by installation; reload saves the new observations normally. The
companion and display test are unchanged. Live results require the next sample.

Vendor revision 2 adds `Enough money for one bundle` separately from raw `canAfford`.
It compares the recorded bundle price with guarded GetMoney readings immediately
before/after the listing info. Both must be readable nonnegative integer copper
amounts; changing money or unavailable/secret/invalid values yield Unknown. Equal
money and price counts as Yes, and zero copper price only means no cash is required.
Extra item/currency costs, stock and other eligibility are not implied satisfied.
The quoted price is never multiplied by stackCount. Recorded money is a sequential
observation, not an atomic transaction or a promise that a later purchase will work.

## Ironforge tour capture update

Trainer and vendor collectors now start after 0.15 seconds and process eight entries
per 0.05-second timer batch. Small lists normally finish within a second once data
is ready; allowing about three seconds is a practical margin, not a guaranteed
server response time. Updates still trigger rescans and early closure stays Partial.
The empty-window diagnostic still needs ten seconds for its delayed observations.
Trainer, vendor and trainer-diagnostic retention is now 100 distinct NPC names EACH
per session, overriding the earlier ten-NPC limits above. Reload validation preserves
all 100 sets. Recipe and bank limits are unchanged. Latest observations replace prior
ones for the same NPC name; the existing three-session retention still applies.
A single reload after a tour saves the collected pages. Frequent reloads are not
needed per NPC, and more than three sessions can age earlier observations out.

## Passive auction listing capture

Auctions.lua observes AUCTION_ITEM_LIST_UPDATE while the auction house is open,
using the legacy list API used by this client's Auctionator. No searches, page
requests, full scans, purchases, bids, posts or cancellations are sent. Revision 2 also observes modern commodity and item search result events through
C_AuctionHouse. Result events suffice without an earlier window-open event. Missing
APIs remain Unknown; live confirmation is required on build 1.60.1.70532 / interface 16001.

Each event records up to 500 returned rows in batches of 20, with client-local and
server-epoch timestamps, item ID/name, quantity, quality/level, bid/increment/buyout
amounts in copper and raw time-left band. Derived unit buyout is separate; zero
buyout means no buyout. Names of sellers/bidders and item links are omitted.
There is no stable listing ID or query/page identity in these snapshots: repeated
rows must not be summed as distinct auctions. Item variants are not fully identified.
Returned/total counts describe the result set, not the entire market. Updates,
closure, logout and bounds explicitly mark interrupted captures Partial.

The latest 50 event snapshots per session are stored in auctionSets, with the
existing three-session retention. Existing paged sets are preserved by validation.
No companion import occurs. Normal /reload writes SavedVariables; installation
does not edit saved data. Browse a couple of items after loading, then /reload to
save. Auctionator's Full Scan may exceed the per-event cap; it is not necessary.

Auction revision 2 stores bounded event counts, registration success and reader API
availability in auctionDiagnosticSets (separate from the 50 listing captures). It
records browse-summary events diagnostically; modern browse summaries are not
individual listings. Open an item result normally to receive its listing details.
Modern captures preserve auction IDs and item-key variants, native commodity unit
prices or item listing buyouts, plus HasFullResults. Secret payload keys are rejected
before field access; inaccessible values/errors are labelled without raw payloads.
No modern searches, requests for more results or transactions are performed.

## Character ownership (local only)

New sessions carry the logged-in player's guarded GUID, name and realm. This is
local saved data, with no upload or other player identity collection. The GUID
separates identical names across characters; display names are labels only. Old
sessions remain explicitly unassigned, never relabelled from the current player.
Unavailable/secret identity remains Unknown and is never merged with a known owner.
All inventory, bank, recipe and other capture pages belong to their owning session.

Retention is now three sessions per known character, with 30 sessions maximum
account-wide (oldest removed at the global limit). Unknown sessions count toward
that global limit. This supersedes the earlier three-session account-wide policy.
An external backup preserves the pre-upgrade report. The tool is unchanged; its
existing reader is not a multi-character browser and may only display a subset.
No captured inventory is imported into the tool automatically.

After installation, reload on the Paladin, open bags/equipment, wait a few seconds,
then log out normally to save a labelled baseline. Log into the alt with the probe
enabled, open bags/equipment, wait a few seconds and reload. Compare session owners
and their inventory pages; no items need to be moved or purchased.

Character name capture now reads Forever's first and second UnitName("player")
results separately through secret/access guards. New sessions retain firstName,
lastName when readable, lastNameStatus, and a combined display name. The GUID
remains the sole identity key; realm is still read separately from GetRealmName.
Historical labels are unchanged and missing/restricted surnames are not guessed.
The companion reader prefers the separate name parts when available and falls
back to older name labels. Captures remain local; no manual character records or
unfinished companion forms are updated. Reload on each character to capture its
name parts; restart the companion only after saving or finishing open edits.
