# WFStorage asset provenance and notices

## Redistribution policy

Package only original assets or assets with explicit redistribution permission.
Free access, noncommercial use and attribution alone are not permission. Preserve
third-party licence texts and required notices. Uncertain provenance, licence scope
or notices block packaging until resolved. Do not extract or bundle Blizzard assets
without permission covering that redistribution. This project is independent and
is not endorsed by Blizzard Entertainment.

## Redistributed assets

- `branding/forever-storage-logo.png`
  - SHA-256: `042874dcde14924b52344cd9c3dfef04a08a657c12f630291c3bfa2bf75fac2e`.
  - Origin: original project emblem generated using the built-in image-generation
    tool, as recorded in the source README under Classic theme and release branding.
    That record states no extracted game imagery was used. Prompt reproduced below.
  - Project licence designation: GPL-3.0-only; retain the included LICENSE and this
    provenance notice. This records the project's designation, not a claim of
    exclusive copyright in AI-generated output or third-party trademark rights.
- `branding/forever-storage-icon.tga`
  - SHA-256: `66449b2c11a30d30e207b4d860488cf31e1244f9c45319245c07ea55702629c9`.
  - Origin: local Pillow resize/format conversion of the above PNG into an
    uncompressed 128x128 RGBA TGA for the minimap and AddOn List.
  - Same licence designation and notices as its source; no additional source art.

Generation prompt recorded in the source README:

> Use case: logo-brand. Create an original square app/addon logo for Forever Storage, a fantasy inventory and bank addon. A bold beautifully crafted leather adventurer's satchel in front of a compact iron-bound wooden bank chest, unified into one strong emblem, small golden infinity-shaped clasp. Warm antique gold, rich chestnut leather, muted teal accents, deep charcoal background. Hand-painted fantasy game icon polish, clean substantial silhouettes, restrained details, readable at small thumbnail size. Centered composition with generous safe margin. No text, no letters, no watermark, no existing game logos, no copied Blizzard icon or trademarked artwork. Standalone finished icon, not a mockup or sheet of alternatives.

## Client references only — not redistributed

Lua references client-provided WHITE8X8, UI-DialogBox-Border, UI-OptionsButton,
UI-SliderBar-Button-Horizontal, MiniMap-TrackingBorder, INV_Misc_QuestionMark,
GameFontNormal and Fonts/FRIZQT__.TTF. Item textures also use IDs supplied by the
client. These are in-game texture/font API references, not files in this package.
They convey no permission to extract, copy or redistribute those assets. Their
availability in the release client remains subject to compatibility testing.

No font or sound files or third-party artwork are included in the current allowlist.
No Blizzard asset files are included. Do not apply the project's GPL designation
to client-owned resources. New third-party assets require their own provenance,
redistribution permission and complete required notices before inclusion.
