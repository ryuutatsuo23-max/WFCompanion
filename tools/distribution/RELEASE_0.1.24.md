# WF Companion 0.1.24

- Fixes Addons-page package verification after upgrading an older companion installation: the full installer removes one obsolete bundled Forever Storage README. The player's game addon folders and saved data are not cleanup targets.
- Gives **Forever Core** and **Forever Storage** separate entries, installation status and buttons. Core can be installed independently; installing Storage still includes its required Core dependency.
- Uses the addon names shown in WoW. Forever Professions remains in development and is not bundled.

Uses the full installer so the upgrade cleanup is applied. The pinned addon revisions are unchanged from 0.1.23. Updating the companion alone does not install game addons. Saved inventory remains read-only; automatic count replacement eligibility is unchanged. Readable guild-bank access and permission-transition checks remain pending. Compatibility evidence remains Beta build 70532/interface 16001; future builds are unverified.
