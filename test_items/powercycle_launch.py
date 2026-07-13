import os
import shlex
import subprocess
import time
from datetime import datetime

import allure
import pytest


def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def trigger_background_fio(io_stress_dir, item, fio_args, wait_seconds=2):
    os.makedirs(os.path.join(io_stress_dir, "log", "ResultLog"), exist_ok=True)
    launch_log = os.path.join(io_stress_dir, "log", "ResultLog", "{}_launch.log".format(item))
    pid_file = os.path.join(io_stress_dir, "log", "ResultLog", "{}_launch.pid".format(item))
    quoted_args = " ".join(shlex.quote(arg) for arg in fio_args)
    launch_cmd = (
        "nohup setsid bash ./Fio_All.sh {} > {} 2>&1 < /dev/null & echo $! > {}"
        .format(quoted_args, shlex.quote(launch_log), shlex.quote(pid_file))
    )

    subprocess.run(["bash", "-lc", launch_cmd], cwd=io_stress_dir, check=True)
    time.sleep(wait_seconds)

    try:
        with open(pid_file, "r", encoding="utf-8") as handle:
            pid = handle.read().strip()
    except OSError:
        pid = ""

    if not pid:
        pytest.fail("Failed to get background FIO {} pid.".format(item))

    still_running = subprocess.run(
        ["bash", "-lc", "kill -0 {} 2>/dev/null".format(shlex.quote(pid))],
        cwd=io_stress_dir,
        check=False,
    ).returncode == 0

    log_text = ""
    if os.path.exists(launch_log):
        with open(launch_log, "r", encoding="utf-8", errors="replace") as handle:
            log_text = handle.read()
        allure.attach(log_text, name="{} launch log".format(item), attachment_type=allure.attachment_type.TEXT)

    if not still_running:
        pytest.fail(
            "Background FIO {} process exited before power-cycle was triggered.\n{}"
            .format(item, log_text[-4000:])
        )

    print("{} [INFO] Background FIO {} process is running, pid={}.".format(ts(), item, pid))
