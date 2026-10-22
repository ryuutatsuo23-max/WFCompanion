# WFCompanion 0.1.11

Settings now keeps the installed version visible above the update status, so you
can confirm a successful upgrade even after the automatic check completes. This
also removes a stray character from the previous status text.

To test the 0.1.10 updater, save your work and reopen the existing companion with
automatic update checks enabled. After about five seconds, accept the update
notification. Download progress appears in Settings. Once the download is verified,
confirm Update and restart. The companion should close, show installation progress,
and reopen with Settings showing Installed version: 0.1.11. Manual Check for updates
also triggers the notification; it is shown once per version per session.

The update uses companion-only installation and preserves saved settings and
records. No addon source or game compatibility changes are included. Storage 0.7.0
automatic count replacement remains blocked pending live validation. The installer
remains unsigned pending SignPath review. Windows may still show a warning.
