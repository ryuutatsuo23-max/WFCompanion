# Forever Professions artwork: provenance and licence

## Explicit owner grant (23 October 2026)

The project owner explicitly selected **Creative Commons Attribution 4.0
International (CC BY 4.0)** for the original Professions PNG and derived TGA,
for any rights the owner controls. This is an artwork-specific grant, not an
inference from visual approval or code licensing. Code remains **GPL-3.0-only**;
the full code licence and existing copyright/SPDX notices remain unchanged.

Artwork licence: https://creativecommons.org/licenses/by/4.0/
Full legal terms: https://creativecommons.org/licenses/by/4.0/legalcode.en

Scope is limited to these two files:

| File | Source and modifications | Licence |
| --- | --- | --- |
| forever-professions-logo.png | Original AI-generated artwork produced for the owner through the built-in OpenAI image-generation tool on 23 October 2026. Original full-resolution output retained unchanged. | CC BY 4.0, for rights the owner controls |
| forever-professions-icon.tga | Derived solely from the PNG: RGBA conversion, Lanczos resize to 64x64, uncompressed TGA export on 23 October 2026. | CC BY 4.0, for rights the owner controls |

Attribution record to retain with redistribution: **Forever Professions artwork,
WoWForever project owner; AI-generated using OpenAI image generation, 2026;
CC BY 4.0. Original PNG; TGA resized/converted from that PNG.** Include the licence
link above, preserve supplied notices and indicate further changes. The packaged
PNG is the original source artwork; the packaged TGA is the recorded export.

Artwork is provided as-is, without warranties; see section 5 of the licence.
The licence covers only rights the licensor can grant. It is not a guarantee of
copyrightability, uniqueness or third-party clearance, and grants no trademark
rights or endorsement. No extra noncommercial restriction is imposed. Retain
AI-generation provenance rather than describing these images as human-created.

## Generation and reference chain

Generation output identifier:
`exec-35301347-8287-4cb8-9813-b165d9403954.png`.
The tool did not identify a model/version; none is asserted. The anvil, hammer,
teal cloth and gold infinity emblem were generated as a new no-text professions
logo. The only image input was the owner's existing generated Storage emblem.

The owner confirmed both logos were generated for them through their personal
OpenAI account, with no third-party artwork inputs beyond their own generated
Storage logo, and explicitly authorized that reference use. This direct owner
permission supports the reference use independently of its existing public
licence; it does not change the public licence of the Storage artwork.

Storage's README at commit `e2591c7505b5eabe22c49cab36464d7906bf14a7` identifies
that reference as original AI-generated project art under GPL-3.0-only, with no
extracted game imagery, and records its generation prompt. That Storage licence
is preserved; the Storage file itself is not redistributed in this package.
No Blizzard artwork was supplied as a generation input.

File identities (SHA-256):

- Professions PNG: `ae290067bdb06cf0e36bcdd5ce361d3e61ab08eb49013c7e4bd8e659c74254b5`
- Professions TGA: `910b2ca72917e6679fd5c1c6b2bc80c7f188919ed52cee0c9f293a6f3b4c68f5`
- Storage reference: `042874dcde14924b52344cd9c3dfef04a08a657c12f630291c3bfa2bf75fac2e`

## Generation-service terms reviewed

Primary sources checked on 23 October 2026:

- [OpenAI Europe Terms of Use](https://openai.com/policies/eu-terms-of-use/),
  updated 16 January 2026, Content section. These are the published individual
  terms for EEA/Switzerland/UK residents. OpenAI assigns its output rights to the
  user to the extent permitted by law; the user must have input rights. Outputs
  may be similar to others, and the assignment excludes third-party/other-user
  output. Output must not be misrepresented as human-generated.
- [OpenAI Service Terms](https://openai.com/policies/service-terms/), updated
  16 October 2026, section 6. Public sharing on the service does not grant other
  users off-service rights. That sharing provision is not our reference-use basis:
  both images were generated for this owner, who authorized reference use.
- [Sharing and publication policy](https://openai.com/policies/sharing-publication-policy/):
  retain clear AI provenance, review outputs and avoid implying human generation.

The personal-account route is supported by the owner's confirmation. No private
contract, account acceptance log or organisation terms were inspected; no business
account or API indemnity is claimed. Published generation terms and owner licence
choice are distinct. The latter is the downstream CC BY 4.0 grant recorded above.
This resolves the previously missing licence decision and reference/account
confirmation for this local package record; it is not a general legal guarantee.

## Client references and other notices

The package includes only the original PNG and TGA as media. No fonts, sounds or
extracted Blizzard assets are bundled. UI.lua/Launcher.lua use installed client
resources through WoW APIs: Fonts/FRIZQT__.TTF, GameFontNormal, WHITE8X8,
UI-OptionsButton, horizontal/vertical UI-SliderBar buttons,
UI-DialogBox-Border and MiniMap-TrackingBorder. These are references, not copied
asset bytes. The title-bar lock is original frame geometry. The repository-only
preview uses locally installed OS fonts without bundling them.

Forever Professions is independent and is not endorsed by Blizzard Entertainment
or OpenAI. Naming generation tools and referenced resources does not imply
sponsorship or transfer their trademarks. Do not extract or bundle client assets
without documented permission covering that use. Preserve third-party licences
and notices; attribution alone or free/noncommercial use is not a licence.

## Validation and future changes

The owner confirmed the logo loaded on the Beta minimap and AddOn List without
Lua errors, plus launcher interaction and reload persistence. This applies to
Beta 1.60.1.70532. Release-client icon loading/readability, the new default position,
and Custom/Native lifecycle remain PENDING LIVE. Beta has ended.

For new assets, record creator/source, date/version, derivation, hashes, licence,
notices and restrictions. Flag uncertainty before packaging. Any file change
requires new package hashes and a handoff. Publication still needs owner approval;
this licence choice does not authorize this agent to publish or install anything.
