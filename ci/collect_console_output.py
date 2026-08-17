#!/usr/bin/env python3
import glob
import os
import urllib.error
import urllib.request


def download_console(build_url, timeout=60):
    if not build_url:
        return ""
    chunks = []
    start = 0
    seen = set()
    while True:
        if start in seen:
            break
        seen.add(start)
        request = urllib.request.Request(
            f"{build_url.rstrip('/')}/logText/progressiveText?start={start}",
            headers={"User-Agent": "RAID_NVME-Jenkins-Reporter"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                more = (response.headers.get("X-More-Data") or "").lower() == "true"
                size_header = response.headers.get("X-Text-Size")
        except (OSError, urllib.error.URLError):
            break
        chunks.append(raw.decode("utf-8", errors="replace"))
        if size_header:
            try:
                next_start = int(size_header)
            except ValueError:
                break
        else:
            next_start = start + len(raw)
        if not more or next_start <= start:
            break
        start = next_start
    return "".join(chunks)


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


def job_running_count(text):
    return sum(1 for line in text.splitlines() if " is Running.." in line)


def merge_console(downloaded, local):
    if not downloaded:
        return (
            "Unable to download Jenkins consoleText; showing collected environment and test logs instead.\n"
            + local
        )
    if local and job_running_count(local) > job_running_count(downloaded):
        return (
            downloaded.rstrip()
            + "\n\n===== complete local execution logs =====\n"
            + local
        )
    return downloaded


def main():
    build_url = os.environ.get("BUILD_URL", "")
    console = merge_console(download_console(build_url), local_log_snapshot())

    with open("jenkins_console.log", "w", encoding="utf-8") as handle:
        handle.write(console)
        if console and not console.endswith("\n"):
            handle.write("\n")
    print(f"Collected Jenkins console snapshot: {len(console.encode('utf-8'))} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
