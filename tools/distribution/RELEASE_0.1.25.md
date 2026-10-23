# WF Companion 0.1.25

Fixes the misleading replacement warning when Forever Core already matches the bundle and Forever Storage has not been installed. Missing files now show "Ready to install missing files" and can be installed without a replacement prompt. Existing files with different contents still require confirmation, including changed Core dependency files.

The pinned Forever Core and Forever Storage packages are unchanged. Forever Professions remains in development and is not bundled. This release uses the full installer and retains the obsolete bundled README cleanup from 0.1.24. Updating the companion does not automatically install game addons or change game saves. Saved inventory remains read-only; automatic count replacement eligibility is unchanged. Readable guild-bank and permission-transition checks remain pending.
