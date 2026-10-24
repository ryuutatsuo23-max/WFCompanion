# WF Companion 0.1.32

Crafting is easier to track from shopping list to completed queue entry:

- **Find saved material** looks up a material across your characters' saved Bags & Bank. Manual planning counts stay separate.
- Shopping labels explain what is needed, manually recorded and still needed; unknown or stale counts stay Unknown.
- **Record one crafted** previews progress and the manual counts that need rechecking. Cancel keeps everything unchanged.
- Recorded progress and unsaved changes are clearer. **Undo last recorded craft** restores the previous progress in the current session. Use **Save plan** to keep applied changes; unfinished editor fields remain separate.

The addon bundle now includes a shared **WF minimap launcher**. Core uses the companion compass; opening it shows the installed addons' own icons. Storage and Professions keep their standalone fallback with older Core, and existing saved positions are preserved.

Updating the companion does not update your installed addons automatically. Use **Addons** to update the bundled Core, Storage and Professions together if you want the shared launcher. Existing files are backed up. WoW may remain open during copying; finish copying before a manual `/reload`. New addons or assets may require a full game restart.

Saved inventory remains read-only. Craft recording does not deduct materials, guess produced items or replace manual counts from snapshots. Undo is session-only and becomes unavailable after other plan or manual-inventory changes.

Verified offline: crafting tests, packaged startup/reopening, upgrade from 0.1.31, and temporary addon install/rollback checks. **Beta is unavailable; shared-launcher placement, dragging, combat, module regressions and release-client compatibility remain pending live.** Existing pending Core, Storage and Professions checks remain pending.

The installer is unsigned. SHA-256 checksums and dependency source archives accompany this release.
