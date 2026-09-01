#!/usr/bin/env python3
import argparse
import re


_MANUAL_ABORT_RE = re.compile(r"(?mi)^\s*Aborted by\s+\S.*$")


def is_manual_abort_text(text):
    return bool(_MANUAL_ABORT_RE.search(text or ""))


def console_was_manually_aborted(path="jenkins_console.log"):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return is_manual_abort_text(handle.read())
    except OSError:
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Classify Jenkins build status from console output.")
    parser.add_argument("--manual-abort", metavar="CONSOLE_LOG")
    args = parser.parse_args(argv)
    if args.manual_abort:
        print("true" if console_was_manually_aborted(args.manual_abort) else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
