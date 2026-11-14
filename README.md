# Context Refcheck

Find stale local paths and command entry points in `CLAUDE.md`, `AGENTS.md`, and `HANDOFF.md`, without executing anything in them. Optionally compare declared evidence file hashes.

This is an offline, read-only CLI. A matched entry means the file or npm script key exists. It does **not** mean a command ran, a test passed, or an instruction is correct. Version 0.1.0 is a source release; it has not been published to a package registry.

## Install from this source tree

Python 3.11+ and a POSIX system supporting directory-relative no-follow opens are required. Local verification was performed on macOS with Python 3.14.7. The source-release CI also runs the test suite on Ubuntu and macOS with Python 3.11 and 3.14; see [the workflow](https://github.com/widechaos/context-refcheck/actions/workflows/check.yml). Windows has no supported safe-open implementation.

```sh
git clone https://github.com/widechaos/context-refcheck.git
cd context-refcheck
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/context-refcheck --version
```

Installation may download the setuptools build tool. Runtime uses only the Python standard library, needs no API keys, and makes no network requests. The source package installs the `context-refcheck` executable.

## Try three synthetic projects

Each healthy project has just one instruction file and no configuration. Each broken counterpart contains old references. The scripts in these examples deliberately throw if executed; Context Refcheck only checks their entry points.

```sh
.venv/bin/context-refcheck check --root examples/python/healthy
.venv/bin/context-refcheck check --root examples/python/broken
.venv/bin/context-refcheck check --root examples/javascript/healthy
.venv/bin/context-refcheck check --root examples/javascript/broken
.venv/bin/context-refcheck check --root examples/nested/healthy --doc nested/HANDOFF.md
.venv/bin/context-refcheck check --root examples/nested/broken --doc nested/HANDOFF.md
```

The healthy commands exit 0. Broken Python and JavaScript projects report `ENTRY_MISSING`; the nested example also reports `PATH_MISSING`. Broken commands exit 1. These examples are invented; they are not production adoption evidence.

For machine-readable output:

```sh
.venv/bin/context-refcheck check --root examples/javascript/broken --format json
```

Every report includes `execution=never`, a coverage description, matched/skipped counts and whether input processing completed. Missing default files are informational. If none of the selected documents can be read, the command exits 2. `--doc` replaces the default document set; repeat it to select more files. There is no recursive discovery or search of parent directories.

To repair an example, copy its broken directory to a temporary location you control, change the old reference to the corresponding healthy reference, and recheck it. The CLI does not edit files or accept new hashes for you.

## What gets checked

- Inline local links, including `[guide](docs/guide.md)` and `[guide](<docs/my guide.md>)`, and path-like inline code such as `./scripts/check.py`.
- Whole inline commands and single-line `sh`, `bash`, `shell` or `console` fenced blocks: exactly `python3 relative/file.py` or `npm run name`. A single `$ ` prompt is accepted in a shell fence. Python checks existence of a regular `.py` file; npm checks a nonempty string key in the instruction document's sibling `package.json`.
- Optional `.context-refcheck.json` declarations bind a check to exact document text, and can compare SHA-256 of explicitly declared evidence. See [the format](docs/format.md).

Paths are relative to the instruction file. A nested handoff may use `../scripts/check.py` if lexical normalization stays under the explicit root. Symlinks are rejected even if they point inside the root. Sensitive paths and special files are blocked. See [the safety boundary](docs/safety.md).

## Coverage limits

Multi-line fences and other language code examples are skipped as a whole, so fictitious files in examples do not become missing-path findings. This also means real commands inside a multi-line shell block are not checked. Unsupported single-line shell commands and recognized inline command candidates produce warnings; they are never interpreted as path fragments.

This parser handles a small Markdown subset. Full/reference-style links, nested parentheses, multi-backtick inline spans, HTML links and arbitrary shell syntax are unsupported. Recognized unsupported forms warn; bare prose paths, indented code, shortcut references and unrecognized command names may be outside detection. Relative inline code is path-like only when it contains `/` or `\`, or starts with `~`. Use a link for a bare filename. URL targets and fragments are skipped without network access. A file matching its hash only establishes byte equality with the declaration; there is no Git version, test result, factual or semantic validation.

Exit codes: **0** complete, no errors/warnings; **1** findings or recognized unsupported forms; **2** input/platform/limit/read failures made the check incomplete. Informational default absence and deliberate example/URL skips do not cause a warning. `complete` refers to processing selected input within this documented coverage, never comprehensive validation.

## Develop and uninstall

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip uninstall -y context-refcheck
```

Tests use synthetic temporary directories and shipped examples only. [Release files](docs/release-files.md) and [third-party notices](docs/third-party.md) define the intended public scope. MIT licensed; no dependency runtime is bundled.

Related tools: [markdownlint](https://github.com/DavidAnson/markdownlint) for Markdown style, [lychee](https://github.com/lycheeverse/lychee) for broad link checks, [agent-handoff](https://github.com/AgathonLi/agent-handoff) and [context-handoff-bundle](https://github.com/ucsandman/context-handoff-bundle) for handoff lifecycle and drift workflows. Their features were reviewed in author documentation, not benchmarked here. Context Refcheck focuses on existing instruction references and static command entries; hash drift checking is already present in other tools.

See the [source-based scope comparison](docs/comparison.md) for overlap with the existing Context Doctor projects and the provisional naming check.
