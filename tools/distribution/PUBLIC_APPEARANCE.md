# Public appearance assets

Classic Fantasy, Parchment and Midnight use original Qt-drawn double borders,
diamond corner ornaments, gradients and subtle diagonal background patterns.
No Blizzard texture is used for these themes, even in a development checkout
where legacy game assets exist. The theme background checkbox and Header mode
control the original background pattern. Existing settings are preserved.

From 0.1.8, fresh preferences default to Classic Fantasy. The companion menu
shows Classic Fantasy, Parchment, Midnight, Dark and Normal, without category or
interface-style controls. A previously saved legacy palette remains available
and selected so upgrading does not silently replace a user's choice. Its stored
interface-style field remains readable for compatibility. The application window
is titled WFCompanion.

Cinzel and Lora are unmodified font binaries from google/fonts, bundled under
SIL OFL 1.1. Their copyright and complete licence files accompany the font files
in tools/offline_preview/theme_art/public_fonts. Exact source URLs and SHA-256
hashes are recorded in public_theme_assets.json and checked during packaging.
Fonts register privately with Qt, not with Windows. Cinzel headings apply to the
three original themes; they use Lora body text when theme fonts are enabled.
Users can disable theme fonts and select their preferred body font in Settings.

These files are included in ordinary installer updates. Existing saved character
data and preferences are not replaced. No release has been published by this change.
