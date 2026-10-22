# WF Companion 0.1.18

Overview now has character cards, saved observation times and quick links to
Bags & Bank and Professions. Technical information is tucked under Details.

The new read-only professions journal reads your locally installed DataStore
cache from an explicitly selected Beta account folder. It shows verified saved
character names, skill cards and learned recipe IDs, with search, category filters
and sortable columns. Recipe names and ingredients are not available yet.

Open Overview and choose **Read professions save** to select the account's
SavedVariables folder. The professions cache lasts for the current session.
Temporary preview profiles and links are not migrated into the installed app.
Use **Review saved game data** for explicit character links. Existing inventory
eligibility checks remain in place; linking alone does not enable blocked updates.

Also includes clearer unchecked boxes, improved Page dropdown positioning, and a
remembered close-to-tray or quit choice that can be changed in Settings.

This release uses the full installer through the existing update/restart flow
because it adds application modules. Settings remain outside the installation.
No addon updates, game files, personal saves or third-party catalogue are bundled.
The optional first-party addon packages are unchanged from 0.1.17. The optical
bridge and capture backend are excluded. Saved observations are not live data.
The installer remains unsigned while publisher signing is pending.
