# WFCompanion 0.1.10

Updates now show a small notification with Download update and Cancel choices,
once per available version per session. Downloads show percentage and byte counts,
disable conflicting actions, and retain checksum verification. A verified download
offers Update and restart with a final confirmation.

Update and restart waits for the companion to exit normally, verifies the installer
again, runs Inno Setup in silent companion-only mode with a progress window, and
reopens the app after a successful exit code. It uses the current installation
folder, preserves saved data, does not install game addons, never force-closes the
app, and never reboots Windows. Unsaved settings and applied records block restart;
the confirmation reminds users to save unfinished editor fields. Helper failures
show an error and retain logs in the companion data folder's updates directory.

Confirmation dialogs now explicitly use the selected theme's background and text
colours, fixing pale text on a white native Windows surface.

One manual update from 0.1.9 is needed to receive this new updater. The automated
restart path is available in recognized installed Windows copies, not development
checkouts. The installer remains unsigned pending SignPath review. Storage 0.7.0
automatic count replacement remains blocked pending live validation.

Implementation reference: https://jrsoftware.org/ishelp/topic_setupcmdline.htm
