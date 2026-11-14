# Intended public files

The source release was independently checked before publication. It is available as a public Git repository; there is no package-registry release.

The precise source allowlist is `docs/release-files.json`. Every entry is a path relative to the repository root. Files outside that list must not be added to a public repository or source release without review. The list includes itself and this policy; it is a path list, not a circular hash manifest. Distribution hashes and archive inventories live in the separate internal verification evidence.

Included: MIT license, package/build configuration, runtime modules, tests, public documentation, and invented healthy/broken examples. All these sources are MIT as described in `third-party.md`. Standard generated distribution metadata is also included by setuptools; no third-party runtime is bundled.

Excluded: local `CLAUDE.md` with internal task paths, `.git`, ignored `evidence/`, any venv, caches, egg-info/build/dist directories, private task Design/PRD/REVIEW documents, real logs, machine paths and credentials. The source archive and wheel must be inspected before publication; an ignore file alone is insufficient. A wheel contains runtime files and standard metadata, not the examples or tests. The source archive carries the public tests/examples/docs for reproduction.
