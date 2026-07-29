#!/usr/bin/env python3
import glob
import json
import os
import shutil
import urllib.error
import urllib.request
import uuid


def download_console():
    build_url = os.environ.get("BUILD_URL", "").rstrip("/")
    if not build_url:
        return ""
    request = urllib.request.Request(
        f"{build_url}/logText/progressiveText?start=0",
        headers={"User-Agent": "RAID_NVME-Jenkins-Reporter"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError):
        return ""


def collected_test_logs():
    sections = []
    for path in sorted(glob.glob("test_execution_*.log")):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                content = handle.read()
        except OSError:
            continue
        sections.append(f"\n===== {path} =====\n{content}")
    return "".join(sections).lstrip()


def attach_console(allure_dir="allure-results"):
    console = download_console()
    local_logs = collected_test_logs()
    if local_logs and local_logs not in console:
        console = f"{console.rstrip()}\n\n{local_logs}" if console else local_logs
    if not console:
        console = "No Jenkins console or remote test execution log was collected.\n"

    console_path = "jenkins_console.log"
    with open(console_path, "w", encoding="utf-8") as handle:
        handle.write(console)
        if not console.endswith("\n"):
            handle.write("\n")

    result_paths = sorted(glob.glob(os.path.join(allure_dir, "*-result.json")))
    if not result_paths:
        print("No Allure test result exists; console log is archived only.")
        return 0

    source = f"{uuid.uuid4()}-jenkins-console.log"
    shutil.copyfile(console_path, os.path.join(allure_dir, source))
    attached = 0
    for path in result_paths:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                result = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        attachments = result.setdefault("attachments", [])
        if not any(item.get("name") == "Jenkins Console Output" for item in attachments):
            attachments.append(
                {
                    "name": "Jenkins Console Output",
                    "source": source,
                    "type": "text/plain",
                }
            )
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False)
        attached += 1
    print(f"Attached Jenkins console output to {attached} Allure result(s).")
    return attached


if __name__ == "__main__":
    attach_console()
