# Forever Display Test

Separate read-only visual experiment for Forever 1.60.1 build 70532 / interface 16001.
No SavedVariables, disk report, desktop integration, input or spell casting.
The fixed panel appears on the left after entering the world outside combat.
HP/mana use native StatusBar and FontString consumers without inspecting secret values.
Seal (20154) and Stoneform (20594) use native duration objects; Seal may only show
its global cooldown, not its buff duration. Player buff icons/durations are owned
by Blizzard's CustomAuraContainerTemplate. No aura enumeration or visibility reads.

Uses packaged Blizzard API/template signatures and installed addon patterns as research;
original implementation, no third-party code copied. Availability in current combat
must be confirmed visually. Accepted API calls do not prove the correct rendering.
Missing/failed display paths say unavailable; raw errors and game values are not logged.
Disable Forever Display Test in AddOns to remove it; it has no stored settings.
A newly installed addon directory may require a full client restart before discovery.
Keep the separate Forever Stress Test API Probe enabled if collecting reports.
