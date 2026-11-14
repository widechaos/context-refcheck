# Optional declaration format

The root's `.context-refcheck.json` is optional. Automatic path/entry checks work without it. Declarations add exact quote binding and whole-file evidence hashes. They cannot configure the reader, change the root, suppress findings or execute anything.

```json
{
  "schema_version": 1,
  "checks": [
    {
      "id": "report-version",
      "kind": "evidence",
      "document": "HANDOFF.md",
      "quote": "Evidence: `reports/check.txt`.",
      "target": "reports/check.txt",
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
    }
  ]
}
```

The hash above is a placeholder, not a passing report. Working synthetic declarations are under `examples/evidence/{healthy,broken}`.

The only top-level fields are integer `schema_version: 1` and array `checks`. Each declaration requires string `id`, `kind`, `document`, `quote`. IDs are unique, 1–64 characters from `[A-Za-z0-9_-]`. Documents must be selected and readable in this run. Quotes are nonempty single-line strings, occurring exactly once in that document. Missing/ambiguous quotes fail the declaration without checking its target.

| Kind | Additional fields | Static check |
| --- | --- | --- |
| `path` | `target` | Ordinary file/directory exists |
| `entry` | `command`; optional `package` | Strict Python file or npm script key exists |
| `evidence` | `target`, `sha256` | Ordinary allowed data file matches 64 lowercase hex SHA-256 |

All fields are strings except the top-level version/array. Unknown or duplicate JSON keys are errors. Non-finite JSON values are errors. Targets/commands must occur literally in the quote. Declaration paths, including Python entry paths and optional npm package, are **root-relative**; automatic references are instruction-directory-relative. Without `package`, a declared npm entry uses root `package.json`. Automatic npm entries use the instruction's sibling package. Neither searches upward or follows workspaces.

Entry grammar: `python3 ([A-Za-z0-9_./-]+\.py)` or `npm run ([A-Za-z0-9:_-]+)`, as a full string with one space between tokens. No additional arguments, interpreter flags, quotes, environment variables, shell expressions or tool aliases. `../` is only permitted where it normalizes inside the explicit root. A script key must hold a nonempty string. Script bodies, Python contents, dependencies, command success and environment availability are not checked.

Run the two hash examples:

```sh
.venv/bin/context-refcheck check --root examples/evidence/healthy
.venv/bin/context-refcheck check --root examples/evidence/broken
```

Healthy exits 0, changed evidence exits 1. Hash equality compares bytes only. Obtain new evidence independently and review any hash edits manually. There is no automatic update command.

## Report schema v1

JSON contains `schema_version`, `tool_version`, `complete`, `execution`, `coverage`, `summary`, `findings`, `checks`. Findings carry `code`, `severity`, `document`, `line` (or null), `check_id`, `message`, `action`. Checks contain `document`, `line`, `kind`, `id`, `status` (`matched`, `unmatched`, `unsupported`, `unbound`, `skipped`). Unsupported forms are warnings; deliberate URL/example skips are counted. An empty evidence configuration is explicitly `not_configured` in coverage.

Finding codes: `PATH_MISSING`, `PATH_BLOCKED`, `REFERENCE_UNSUPPORTED`, `SOURCE_MISSING`, `SOURCE_AMBIGUOUS`, `ENTRY_MISSING`, `ENTRY_UNSUPPORTED`, `EVIDENCE_CHANGED`, `DOCUMENT_MISSING`, `INPUT_INVALID`, `INPUT_CHANGED`, `LIMIT_EXCEEDED`, `PLATFORM_UNSUPPORTED`.

Results sort by document/line/code/ID; they have no runtime timestamp. IDs for automatic occurrences are positional within the selected document set and are not permanent issue identities. Source moves may change line numbers and IDs.
