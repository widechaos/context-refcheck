# Third-party and ownership notes

The runtime, tests, documentation and synthetic fixtures in the release allowlist were written independently for this tool and are offered under the repository's MIT license, copyright 2026 Renchao Wu. No employer code, private product source, credentials, real project data, external screenshots or copied competitor source are included. This is a provenance statement for the listed files, not a legal clearance of all possible intellectual-property rights.

Runtime: Python 3.11+ standard library only, supplied by the caller, not bundled. Python's licensing is described by the [Python Software Foundation](https://docs.python.org/3/license.html).

Build verification: setuptools 84.2.1 (MIT), installed as a build tool and not bundled in the wheel or source archive. pip 26.2.1 (MIT) was the local installer, not a runtime dependency and not bundled. Local tests use standard-library unittest; no pytest or test service dependency. Python 3.14.7 was used for local validation. The project requires setuptools >=77 to support the license metadata used by this source tree; version constraints are build requirements, not runtime requirements.

Author repositories consulted for feature comparisons, without copying their code or documentation: [markdownlint](https://github.com/DavidAnson/markdownlint), [lychee](https://github.com/lycheeverse/lychee), [agent-handoff](https://github.com/AgathonLi/agent-handoff), [context-handoff-bundle](https://github.com/ucsandman/context-handoff-bundle). Additional source review: [michal-franc/context-doctor](https://github.com/michal-franc/context-doctor), [DheerG/context-doctor](https://github.com/DheerG/context-doctor), [KushalP1/context-doctor](https://github.com/KushalP1/context-doctor). Their public sources were read for scope comparison after the initial implementation; none were executed, copied or bundled. References are informational, not endorsements or compatibility claims.

Names and package/executable identifiers are provisional until the publication owner completes name checks. No registry namespace, trademark or third-party affiliation is claimed.
