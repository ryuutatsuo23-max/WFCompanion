# Saved character header

The companion reads Forever Core schema-1 character details by the saved character GUID. Class, level and observation time refresh when the saved file changes. DataStore is not required. Missing or unsupported details remain Unknown; inventory timestamps and manual planning fields are never substituted.

The header labels the time as Saved observation. This is the Core observation attempt, not inventory freshness, disk-save time or live identity. Reads are bounded, literal-only and cached by file signature; saved files are never written.

Playstyle is in Settings / Planning settings and retains per-character planning choices. Inventory summaries show Bags and Bank timestamps separately, distinguish unrecorded locations from empty snapshots, and show filtered item counts. Technical diagnostics remain under Details.

User-confirmed Beta checks covered reload refresh with DataStore disabled, two-character isolation, raw field/status validation, normal-exit persistence and welcome/Storage command behavior. Naturally earned level-change validation remains pending. Beta has ended; future-client compatibility requires new live validation. These checks do not establish full inventory/history preservation.
