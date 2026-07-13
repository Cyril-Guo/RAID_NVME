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
    command = ["bash", "./Fio_All.sh"] + fio_args
    command_text = " ".join(shlex.quote(arg) for arg in command)

    try:
        with open(launch_log, "a", encoding="utf-8") as log_handle:
            log_handle.write("{} [LAUNCH] cwd={}\n".format(ts(), os.path.abspath(io_stress_dir)))
            log_handle.write("{} [LAUNCH] command={}\n".format(ts(), command_text))
        with open(launch_log, "ab") as log_handle, open(os.devnull, "rb") as stdin_handle:
            process = subprocess.Popen(
                command,
                cwd=io_stress_dir,
                stdin=stdin_handle,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
    except Exception as exc:
        pytest.fail("Failed to launch background FIO {}: {}".format(item, exc))

    pid = str(process.pid)
    with open(pid_file, "w", encoding="utf-8") as handle:
        handle.write(pid + "\n")

    time.sleep(wait_seconds)
    return_code = process.poll()
    still_running = return_code is None

    log_text = ""
    if os.path.exists(launch_log):
        with open(launch_log, "r", encoding="utf-8", errors="replace") as handle:
            log_text = handle.read()
        allure.attach(log_text, name="{} launch log".format(item), attachment_type=allure.attachment_type.TEXT)

    if not still_running:
        pytest.fail(
            "Background FIO {} process exited before power-cycle was triggered, rc={}.\n{}"
            .format(item, return_code, log_text[-4000:])
        )

    print("{} [INFO] Background FIO {} process is running, pid={}.".format(ts(), item, pid))
