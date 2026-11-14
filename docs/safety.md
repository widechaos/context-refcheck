# Safety boundary

All checked documents, JSON declarations, package scripts and evidence are untrusted data. The caller explicitly chooses one root. No instruction in a file can change that root, configure a process, enable a network request, upload content or write a report file.

## File access

The reader opens the explicit root with `O_DIRECTORY | O_NOFOLLOW`, holds its descriptor, and traverses each normalized relative component with directory-relative `os.open` and `O_NOFOLLOW`. Intermediate components must be directories. Every final target is opened nonblocking and checked with `fstat`; only ordinary files and (for existence checks) directories are accepted. This rejects final/intermediate symlinks, sockets, FIFOs and devices without content reads. The explicit root's OS-level ancestors are chosen by the caller and may contain platform aliases; the CLI does not establish a sandbox around them.

Paths normalize lexically. Parent steps are allowed until they would leave the root, then rejected before target access. Absolute paths, backslashes/UNC paths, colon/drive syntax, percent-encoded paths, expansions, control characters and null bytes are rejected. Fragment identifiers are not checked. Root-relative declarations cannot select an unread instruction file or escape the root.

Content reads have purpose-specific suffix allowlists: `.md` for instruction documents; `.json` for the optional manifest and declared npm package; `.md`, `.txt`, `.json`, `.csv` for evidence. Python entry files and linked files are checked for existence/type without reading their content. Evidence files are hashed as bytes; their contents are never followed as links or instructions.

Every path component is checked case-insensitively against `.git`, `.ssh`, `.aws`, `.gnupg`, `node_modules`, `env`, `Environment_keys`, credential/secret directories; `.env*`, `credentials*`, names containing `secret`, and `.pem`/`.key` suffixes are blocked. This intentionally may reject ordinary files with those names. A secret disguised as an ordinary `.md` or `.json` file cannot be identified by its name. Use only authorized non-sensitive data; this is not a credential scanner or a general filesystem sandbox. Hard links and mounted filesystems inside a chosen root are not isolated.

Fixed limits: 1 MiB per file, 8 MiB cumulative bytes read (including repeated reads), 32 selected documents, 256 explicit declarations, 4096 parsed references. Limit failures return incomplete status. UTF-8, JSON schema/types, duplicate keys, and finite JSON values are validated. File size/mtime/ctime are checked before and after reads; observed mutation returns `INPUT_CHANGED`. This does not provide an atomic snapshot of a concurrently changing repository. Use a stable checkout for reproducible results.

## Execution and output

Runtime imports no shell/process/network client and invokes no subprocess. npm values and Python files may contain malicious commands; only key/file existence is checked. Arbitrary shell is unsupported, including arguments, pipes, substitutions and redirects. There is no plugin, automatic repair, hash refresh or command execution option.

Reports omit document lines, commands, evidence contents, hashes and absolute root paths. Findings reference the selected root-relative document and line, with fixed reason text. A blocked target is not echoed. CLI text and JSON escape terminal control characters; text uses ASCII escapes for non-ASCII names. Reports still disclose document names and locations, so review them before sharing. stdout/stderr are the only destinations; the caller can save output explicitly.

Coverage is deliberately narrow. A `matched` result is structural, `complete=true` means processing selected inputs finished under the reported coverage, and `execution=never` applies to this CLI. Neither result proves the instructions are safe to execute, a test passed, evidence was honestly produced, or its meaning is current.

Safe descriptor capabilities are required. Unsupported systems exit 2 with `PLATFORM_UNSUPPORTED`; there is no resolve-then-open or Windows fallback. Local validation is macOS/Python 3.14.7 only.
