# WFCompanion 0.1.12

Adds support for optional smaller, exact-base updates and a Download full installer
instead button. Eligible later releases can download only changed files while
retaining the existing notification, progress, confirmation and restart flow.

Unknown or incompatible bases and failed patch downloads use the full installer.
Smaller updates keep a recovery copy and check application startup before reopening.
Saved companion data and game addons remain separate. This version itself requires
a full installer to introduce the new updater files.

Public smaller-update deployment and second-PC validation remain pending. Windows
publisher signing remains pending. No addon compatibility changes are included.
