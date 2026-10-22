# WFCompanion 0.1.13

Small follow-up release to validate the exact-base update path from 0.1.12.
The installed version changes to 0.1.13; no game-addon or saved-data changes.

From installed 0.1.12, check for updates. The smaller download is about 4.6 MB
(compared with the 38.1 MB full installer). Matching installations should select the
smaller package. A modified, missing or incompatible base uses the full installer.
The full installer remains available explicitly in Settings and on the release.

Expected test: notification, download progress, confirmation, automatic restart,
Installed version: 0.1.13, and preserved settings. Smaller updates perform a
backup and startup check, so installation may take longer than downloading.

Installer signing is still pending. Forced power-loss recovery has not been
validated; keep the full installer available for repair. Recovery backups remain
under the companion data folder's updates directory.
