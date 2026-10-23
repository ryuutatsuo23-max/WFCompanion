# Code signing policy

Current status: unsigned. The SignPath Foundation application was declined in October 2026 because the project did not yet have sufficient public visibility. Signing is deferred and may be reconsidered as the project grows. There is no SignPath sponsorship or guarantee of SmartScreen clearance.

Maintainer, reviewer and intended release approver:
[Steve Vanhamel (ryuutatsuo23-max)](https://github.com/ryuutatsuo23-max).

Public Windows builds run from this repository using the Windows build workflow.
The workflow has read-only repository permissions, verifies the pinned Inno
Setup download, checks hash-pinned public assets and builds an allowlisted
payload. It does not automatically sign, publish releases or update users.
Dependencies keep their upstream licences and publisher identities.

Any future signing integration will require explicit release approval and must
bind signed output to reviewed public source and workflow inputs. Final checksums
must be generated after signing. The maintainer will document the accepted
signing provider and policy here before publishing signed releases.

See [Privacy](PRIVACY.md) for automatic GitHub update checks and local data storage.
