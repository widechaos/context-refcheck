"""Bounded readers and static checks. Checked content is never executable."""
from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import stat
from dataclasses import dataclass

from . import __version__

MAX_FILE = 1024 * 1024
MAX_TOTAL = 8 * MAX_FILE
MAX_DOCS = 32
MAX_CHECKS = 256
MAX_REFS = 4096
DEFAULT_DOCS = ("AGENTS.md", "CLAUDE.md", "HANDOFF.md")
SHELLS = {"sh", "bash", "shell", "console"}
DENIED_DIRS = {".git", ".ssh", ".aws", ".gnupg", "node_modules", "env",
               "environment_keys", "credentials", "secrets", "credential"}
COMMAND_START = re.compile(r"^(?:python\d*(?:\.\d+)?|npm|node|pnpm|yarn|bash|sh|make|curl|wget|git|uv|pip\d*|pytest|cargo|go|npx|sudo|cd)\b")
PYTHON = re.compile(r"python3 ([A-Za-z0-9_./-]+\.py)\Z")
NPM = re.compile(r"npm run ([A-Za-z0-9:_-]+)\Z")
TOKEN = re.compile(r"`([^`\n]+)`|!?\[[^\]\n]*\]\((<[^>\n]+>|[^()\s\n]+)\)")


class InputError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def normalize(value: str, base: str = "") -> str:
    """Normalize relative paths without touching the filesystem."""
    if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise InputError("PATH_BLOCKED", "invalid relative path")
    if value.startswith(("/", "~")) or any(c in value for c in ("\\", ":", "$", "%")):
        raise InputError("PATH_BLOCKED", "absolute, encoded or expanded paths are not allowed")
    parts = base.split("/") if base else []
    for part in value.split("/"):
        low = part.casefold()
        if low in DENIED_DIRS or low.startswith((".env", "credentials")) or "secret" in low or low.endswith((".pem", ".key")):
            raise InputError("PATH_BLOCKED", "sensitive paths are not allowed")
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise InputError("PATH_BLOCKED", "relative path leaves the explicit root")
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts) or "."


class Reader:
    """No-follow traversal relative to one open root directory descriptor."""
    def __init__(self, root: str):
        if (not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY")
                or os.open not in os.supports_dir_fd):
            raise InputError("PLATFORM_UNSUPPORTED", "safe directory-relative opens are unavailable")
        self.total = 0
        self.fd = None
        try:
            self.fd = os.open(os.path.abspath(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except (OSError, ValueError):
            raise InputError("INPUT_INVALID", "cannot open the explicit root as a non-symlink directory") from None

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _open(self, path: str):
        path = normalize(path)
        parent = os.dup(self.fd)
        try:
            parts = path.split("/")
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = child
            return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                raise InputError("PATH_MISSING", "referenced path does not exist") from None
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise InputError("PATH_BLOCKED", "symlink or non-directory traversal is not allowed") from None
            raise InputError("INPUT_INVALID", "referenced path cannot be opened") from None
        finally:
            os.close(parent)

    def exists(self, path: str, *, file_only: bool = False):
        fd = self._open(path)
        try:
            mode = os.fstat(fd).st_mode
            if not stat.S_ISREG(mode) and (file_only or not stat.S_ISDIR(mode)):
                raise InputError("PATH_BLOCKED", "target must be a regular file" if file_only else "special files are not allowed")
        finally:
            os.close(fd)

    def read(self, path: str, *, purpose: str) -> bytes:
        path = normalize(path)
        allowed = {"document": {".md"}, "json": {".json"},
                   "evidence": {".md", ".txt", ".json", ".csv"}}[purpose]
        if PurePosixPath(path).suffix.lower() not in allowed:
            raise InputError("PATH_BLOCKED", "file type is not allowed for this check")
        fd = self._open(path)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise InputError("PATH_BLOCKED", "content reads require a regular file")
            if before.st_size > MAX_FILE or self.total + before.st_size > MAX_TOTAL:
                raise InputError("LIMIT_EXCEEDED", "input byte limit exceeded")
            chunks = []
            count = 0
            while True:
                chunk = os.read(fd, min(65536, MAX_FILE + 1 - count))
                if not chunk:
                    break
                count += len(chunk)
                self.total += len(chunk)
                if count > MAX_FILE or self.total > MAX_TOTAL:
                    raise InputError("LIMIT_EXCEEDED", "input byte limit exceeded")
                chunks.append(chunk)
            after = os.fstat(fd)
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or count != after.st_size:
                raise InputError("INPUT_CHANGED", "input changed during the read")
            return b"".join(chunks)
        finally:
            os.close(fd)


def text_data(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise InputError("INPUT_INVALID", "input must be valid UTF-8") from None


def json_data(data: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InputError("INPUT_INVALID", "duplicate JSON keys are not allowed")
            result[key] = value
        return result
    try:
        return json.loads(text_data(data), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(InputError("INPUT_INVALID", "non-finite JSON is not allowed")))
    except (ValueError, RecursionError):
        raise InputError("INPUT_INVALID", "invalid JSON input") from None


@dataclass
class Ref:
    line: int
    kind: str
    value: str


def command_candidate(value: str) -> bool:
    return bool(COMMAND_START.match(value) or any(c in value for c in ("|", ";", "&&", "$(", ">", "<")))


def references(source: str):
    """Parse the documented small Markdown subset; never parse code examples as paths."""
    lines = source.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        fence = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            marker, language = fence.groups()
            end = index + 1
            while end < len(lines) and not re.fullmatch(r"\s{0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}\s*", lines[end]):
                end += 1
            if end == len(lines):
                yield Ref(index + 1, "unsupported", "unclosed fenced block")
                return
            content = [(n + 1, lines[n].strip()) for n in range(index + 1, end) if lines[n].strip()]
            if language.strip().lower() in SHELLS and len(content) == 1:
                n, value = content[0]
                if value.startswith("$ "):
                    value = value[2:]
                yield Ref(n, "entry", value)
            else:
                yield Ref(index + 1, "skip_block", "code example outside command coverage")
            index = end + 1
            continue
        # Reference-style and HTML links are outside this parser's contract.
        if re.search(r"\[[^\]]+\]\s*\[|^\s*\[[^\]]+\]:|<(?:a|img)\b", line, re.I):
            yield Ref(index + 1, "unsupported", "reference-style or HTML link is not checked")
        consumed = []
        for match in TOKEN.finditer(line):
            consumed.append(match.span())
            inline, link = match.groups()
            if inline is not None:
                if command_candidate(inline):
                    yield Ref(index + 1, "entry", inline)
                elif "/" in inline or inline.startswith(("~", "./", "../")) or "\\" in inline:
                    yield Ref(index + 1, "path", inline)
            else:
                yield Ref(index + 1, "path", link[1:-1] if link.startswith("<") else link)
        leftover = line
        for start, end in reversed(consumed):
            leftover = leftover[:start] + " " * (end - start) + leftover[end:]
        if re.search(r"\[[^\]]*\]\(", leftover) or "``" in leftover:
            yield Ref(index + 1, "unsupported", "complex Markdown reference is not checked")
        index += 1


class Doctor:
    def __init__(self, reader: Reader):
        self.reader = reader
        self.report = {"schema_version": 1, "tool_version": __version__, "complete": True,
                       "execution": "never", "coverage": {
                           "paths": "inline local links and path-like inline code",
                           "entries": "whole inline commands and single-line shell fences: python3 file.py; npm run name",
                           "evidence": "not_configured", "recursive_discovery": False,
                           "semantics": "not_checked", "fragments": "not_checked",
                           "arbitrary_shell": "not_checked"},
                       "summary": {"documents": 0, "references": 0, "declarations": 0,
                                   "matched": 0, "skipped": 0, "skipped_blocks": 0,
                                   "errors": 0, "warnings": 0, "info": 0, "unsupported": 0},
                       "findings": [], "checks": []}
        self.source = {}

    def finding(self, code, severity, document="", line=None, check_id="", message="", action="Review this location manually."):
        self.report["findings"].append(dict(code=code, severity=severity, document=document,
                                           line=line, check_id=check_id, message=message, action=action))
        if code in {"INPUT_INVALID", "LIMIT_EXCEEDED", "INPUT_CHANGED", "PLATFORM_UNSUPPORTED"}:
            self.report["complete"] = False

    def result(self, doc, line, kind, ident, status):
        self.report["checks"].append(dict(document=doc, line=line, kind=kind, id=ident, status=status))
        if status == "matched":
            self.report["summary"]["matched"] += 1

    def run_check(self, doc, line, kind, value, ident, *, base=None, package=None, expected=None):
        base = str(PurePosixPath(doc).parent) if base is None else base
        if base == ".":
            base = ""
        try:
            if kind == "path":
                if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value) or value.startswith(("mailto:", "#")):
                    self.report["summary"]["skipped"] += 1
                    self.result(doc, line, kind, ident, "skipped")
                    return
                value = value.split("#", 1)[0]
                target = normalize(value, base)
                self.reader.exists(target)
            elif kind == "entry":
                py, npm = PYTHON.fullmatch(value), NPM.fullmatch(value)
                if py:
                    self.reader.exists(normalize(py[1], base), file_only=True)
                elif npm:
                    target = normalize(package) if package is not None else normalize("package.json", base)
                    data = json_data(self.reader.read(target, purpose="json"))
                    scripts = data.get("scripts") if isinstance(data, dict) else None
                    if not isinstance(scripts, dict) or not isinstance(scripts.get(npm[1]), str) or not scripts[npm[1]].strip():
                        raise InputError("ENTRY_MISSING", "npm script key is absent or is not a nonempty string")
                else:
                    self.finding("ENTRY_UNSUPPORTED", "warning", doc, line, ident,
                                 "command is outside the two supported static entry grammars",
                                 "Check this command manually; it was not executed.")
                    self.result(doc, line, kind, ident, "unsupported")
                    return
            elif kind == "evidence":
                digest = hashlib.sha256(self.reader.read(normalize(value), purpose="evidence")).hexdigest()
                if digest != expected:
                    raise InputError("EVIDENCE_CHANGED", "evidence bytes differ from the declared SHA-256")
            self.result(doc, line, kind, ident, "matched")
        except InputError as exc:
            code = "ENTRY_MISSING" if kind == "entry" and exc.code == "PATH_MISSING" else exc.code
            self.finding(code, "error", doc, line, ident, exc.message)
            self.result(doc, line, kind, ident, "unmatched")

    def documents(self, docs, explicit):
        if len(docs) > MAX_DOCS:
            raise InputError("LIMIT_EXCEEDED", "document count limit exceeded")
        for index, raw in enumerate(docs):
            # Do not include an unvalidated path in reports.
            try:
                doc = normalize(raw)
                source = text_data(self.reader.read(doc, purpose="document"))
            except InputError as exc:
                if exc.code == "PATH_MISSING" and not explicit:
                    self.finding("DOCUMENT_MISSING", "info", raw, message="default document not found")
                else:
                    self.finding(exc.code, "error", message=exc.message)
                    self.report["complete"] = False
                continue
            if doc in self.source:
                continue
            self.source[doc] = source
            self.report["summary"]["documents"] += 1
            for ref in references(source):
                self.report["summary"]["references"] += 1
                if self.report["summary"]["references"] > MAX_REFS:
                    raise InputError("LIMIT_EXCEEDED", "reference count limit exceeded")
                ident = f"auto:{index}:{self.report['summary']['references']}"
                if ref.kind == "skip_block":
                    self.report["summary"]["skipped_blocks"] += 1
                    self.report["summary"]["skipped"] += 1
                    self.result(doc, ref.line, "example", ident, "skipped")
                elif ref.kind == "unsupported":
                    self.finding("REFERENCE_UNSUPPORTED", "warning", doc, ref.line, ident, ref.value)
                    self.result(doc, ref.line, "reference", ident, "unsupported")
                else:
                    self.run_check(doc, ref.line, ref.kind, ref.value, ident)
        if not self.source:
            raise InputError("INPUT_INVALID", "no readable selected instruction documents found")

    def manifest(self):
        try:
            data = json_data(self.reader.read(".context-refcheck.json", purpose="json"))
        except InputError as exc:
            if exc.code == "PATH_MISSING":
                return
            raise
        if not isinstance(data, dict) or set(data) != {"schema_version", "checks"} or type(data["schema_version"]) is not int or data["schema_version"] != 1 or not isinstance(data["checks"], list):
            raise InputError("INPUT_INVALID", "invalid manifest schema")
        if len(data["checks"]) > MAX_CHECKS:
            raise InputError("LIMIT_EXCEEDED", "declaration count limit exceeded")
        ids = set()
        validated = []
        for item in data["checks"]:
            if not isinstance(item, dict):
                raise InputError("INPUT_INVALID", "each declaration must be an object")
            required = {"id", "kind", "document", "quote"}
            kind = item.get("kind")
            fields = {"path": {"target"}, "entry": {"command"}, "evidence": {"target", "sha256"}}
            if not isinstance(kind, str) or kind not in fields:
                raise InputError("INPUT_INVALID", "unknown declaration kind")
            allowed = required | fields[kind] | ({"package"} if kind == "entry" else set())
            if not required.union(fields[kind]) <= set(item) or not set(item) <= allowed or not all(isinstance(v, str) for v in item.values()):
                raise InputError("INPUT_INVALID", "invalid declaration fields")
            ident = item["id"]
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", ident) or ident in ids:
                raise InputError("INPUT_INVALID", "declaration ids must be unique simple identifiers")
            ids.add(ident)
            doc = normalize(item["document"])
            if doc not in self.source:
                raise InputError("INPUT_INVALID", "declaration document is not selected and readable")
            quote = item["quote"]
            value = item["command"] if kind == "entry" else item["target"]
            if not quote or "\n" in quote or "\r" in quote or not value or value not in quote:
                raise InputError("INPUT_INVALID", "quote must bind a nonempty target or command on one line")
            if kind == "evidence" and not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
                raise InputError("INPUT_INVALID", "SHA-256 must be 64 lowercase hex digits")
            validated.append((item, doc, quote, value))
        self.report["summary"]["declarations"] = len(validated)
        if any(i[0]["kind"] == "evidence" for i in validated):
            self.report["coverage"]["evidence"] = "declared whole-file SHA-256 comparisons only"
        for item, doc, quote, value in validated:
            source = self.source[doc]
            first = source.find(quote)
            count = 0 if first < 0 else (2 if source.find(quote, first + 1) >= 0 else 1)
            if count != 1:
                self.finding("SOURCE_MISSING" if count == 0 else "SOURCE_AMBIGUOUS", "error", doc,
                             check_id=item["id"], message="declaration quote must occur exactly once")
                self.result(doc, None, item["kind"], item["id"], "unbound")
                continue
            line = source[:source.index(quote)].count("\n") + 1
            self.run_check(doc, line, item["kind"], value, item["id"], base="",
                           package=item.get("package"), expected=item.get("sha256"))

    def finish(self):
        self.report["findings"].sort(key=lambda x: (x["document"], x["line"] or 0, x["code"], x["check_id"]))
        self.report["checks"].sort(key=lambda x: (x["document"], x["line"] or 0, x["id"]))
        for severity, key in (("error", "errors"), ("warning", "warnings"), ("info", "info")):
            self.report["summary"][key] = sum(x["severity"] == severity for x in self.report["findings"])
        self.report["summary"]["unsupported"] = sum(x["status"] == "unsupported" for x in self.report["checks"])
        code = 2 if not self.report["complete"] else (1 if self.report["summary"]["errors"] or self.report["summary"]["warnings"] else 0)
        return self.report, code


def check(root: str, docs=None):
    doctor = Doctor(None)
    reader = None
    try:
        reader = Reader(root)
        doctor.reader = reader
        doctor.documents(docs if docs is not None else DEFAULT_DOCS, docs is not None)
        doctor.manifest()
    except InputError as exc:
        doctor.finding(exc.code, "error", message=exc.message)
        doctor.report["complete"] = False
    except (OSError, ValueError, RecursionError):
        doctor.finding("INPUT_INVALID", "error", message="input could not be processed safely")
        doctor.report["complete"] = False
    finally:
        if reader:
            reader.close()
    return doctor.finish()
