"""Command-line interface; stdout is the only report destination."""
import argparse
import json

from . import __version__
from .core import check


def escaped(value):
    return json.dumps(value, ensure_ascii=True)[1:-1]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline static reference checks; commands are never executed.")
    parser.add_argument("--version", action="version", version=f"context-refcheck {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("check", help="check explicitly selected instruction documents")
    scan.add_argument("--root", required=True, help="explicit project directory; no recursive discovery")
    scan.add_argument("--doc", action="append", help="root-relative Markdown file; replaces default document selection")
    scan.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    report, code = check(args.root, args.doc)
    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        for finding in report["findings"]:
            location = escaped(finding["document"]) or "input"
            if finding["line"] is not None:
                location += f":{finding['line']}"
            print(f"{location} {finding['code']} {finding['severity']}: {escaped(finding['message'])}")
        s = report["summary"]
        print(f"Summary: {s['errors']} errors, {s['warnings']} warnings, {s['info']} info; "
              f"{s['documents']} docs, {s['references']} references, {s['declarations']} declarations, "
              f"{s['matched']} matched, {s['unsupported']} unsupported, {s['skipped']} skipped ({s['skipped_blocks']} example blocks)")
        print(f"complete={str(report['complete']).lower()}; execution=never; semantics=not_checked")
        for key, value in report["coverage"].items():
            print(f"coverage.{key}={escaped(str(value))}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
