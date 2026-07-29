#!/usr/bin/env python3
import glob
import os
import urllib.error
import urllib.request


def download_console(build_url, timeout=30):
    if not build_url:
        return ""
    request = urllib.request.Request(
        f"{build_url.rstrip('/')}/logText/progressiveText?start=0",
        headers={"User-Agent": "RAID_NVME-Jenkins-Reporter"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError):
        return ""


def local_log_snapshot():
    sections = []
    paths = sorted(glob.glob("environment_prepare_*.log")) + sorted(glob.glob("test_execution_*.log"))
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        sections.append(f"\n===== {path} =====\n{text}")
    return "".join(sections).lstrip()


def main():
    build_url = os.environ.get("BUILD_URL", "")
    console = download_console(build_url)
    if not console:
        console = (
            "Unable to download Jenkins consoleText; showing collected environment and test logs instead.\n"
            + local_log_snapshot()
        )

    with open("jenkins_console.log", "w", encoding="utf-8") as handle:
        handle.write(console)
        if console and not console.endswith("\n"):
            handle.write("\n")
    print(f"Collected Jenkins console snapshot: {len(console.encode('utf-8'))} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
