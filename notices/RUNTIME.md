# Runtime components

WFCompanion uses unmodified Qt and Qt for Python (PySide6/shiboken6) 6.11.1
under their open-source LGPL terms. Licence texts accompany this notice.
Corresponding Qt base, SVG, image-format and Qt for Python source archives are
available beside the installer in the WFCompanion GitHub release:
https://github.com/ryuutatsuo23-max/WFCompanion/releases/tag/v0.1.6

Qt libraries are separate DLLs in _internal/PySide6. You may replace them with
compatible modified libraries. No signature check prevents replacement.
Reverse engineering for debugging your modifications to these libraries is
permitted. No WFCompanion restriction overrides your third-party licence rights.
The release also supplies the application sources and build scripts.

On Windows, reminder audio uses the Windows runtime. The public package excludes
Qt Multimedia, FFmpeg, PDF, QML/Quick and Virtual Keyboard binaries/plugins.
Python and the included third-party library notices retain their own terms.
Microsoft runtime components are supplied with the Python/Qt runtime packages.
Source archives include upstream build instructions and third-party notices.

WFCompanion is an independent, free community project, not affiliated with or
endorsed by Blizzard Entertainment. World of Warcraft and Warcraft are trademarks
or registered trademarks of Blizzard Entertainment, Inc.
