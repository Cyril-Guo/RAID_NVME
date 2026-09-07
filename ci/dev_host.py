#!/usr/bin/env python3
"""Bootstrap / sync helper for Linux edit host 192.168.22.226.

Prefer SSH key login. Password only via env DEV_HOST_PASS (never commit secrets).

Examples (Windows PowerShell):
  $env:DEV_HOST_PASS='...'
  python ci/dev_host.py bootstrap
  python ci/dev_host.py pull SMOKE
  python ci/dev_host.py status
"""
from __future__ import annotations

import os
import pathlib
import sys

import paramiko

HOST = os.environ.get("DEV_HOST", "192.168.22.226")
USER = os.environ.get("DEV_HOST_USER", "root")
PASS = os.environ.get("DEV_HOST_PASS", "")
REMOTE_ROOT = os.environ.get("DEV_HOST_ROOT", "/root/Cyril/Cursor")
REPO_NAME = os.environ.get("DEV_HOST_REPO", "RAID_NVME")
REPO_SSH = os.environ.get("DEV_HOST_GIT", "git@github.com:Cyril-Guo/RAID_NVME.git")
LOCAL_PUBKEY = pathlib.Path.home() / ".ssh" / "id_ed25519.pub"
LOCAL_KEY = pathlib.Path.home() / ".ssh" / "id_ed25519"
DEPLOY_KEY = "/root/.ssh/id_ed25519_raid_nvme"


def connect() -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = dict(hostname=HOST, username=USER, timeout=20)
    if LOCAL_KEY.exists():
        try:
            c.connect(
                **kwargs,
                key_filename=str(LOCAL_KEY),
                allow_agent=True,
                look_for_keys=True,
            )
            return c
        except Exception:
            c.close()
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if not PASS:
        raise SystemExit(
            "SSH key auth failed; set DEV_HOST_PASS or fix authorized_keys"
        )
    c.connect(
        **kwargs,
        password=PASS,
        allow_agent=False,
        look_for_keys=False,
    )
    return c


def run(c: paramiko.SSHClient, cmd: str, timeout: int = 300) -> tuple[int, str, str]:
    _stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def git_ssh_prefix() -> str:
    return (
        f"GIT_SSH_COMMAND='ssh -i {DEPLOY_KEY} "
        f"-o StrictHostKeyChecking=accept-new'"
    )


def cmd_bootstrap(c: paramiko.SSHClient) -> int:
    steps = [
        f"mkdir -p {REMOTE_ROOT}",
        "export DEBIAN_FRONTEND=noninteractive; "
        "command -v git >/dev/null || "
        "(apt-get update -qq && apt-get install -y -qq git openssh-client)",
        "mkdir -p /root/.ssh && chmod 700 /root/.ssh && "
        "touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys",
    ]
    for cmd in steps:
        code, out, err = run(c, cmd, timeout=600)
        print(f"$ {cmd}\nexit={code}\n{out}{err}")
        if code != 0:
            return code

    if LOCAL_PUBKEY.exists():
        pub = LOCAL_PUBKEY.read_text(encoding="utf-8").strip()
        _code, out, err = run(
            c,
            "python3 - <<'PY'\n"
            f"pub = {pub!r}\n"
            "path = '/root/.ssh/authorized_keys'\n"
            "with open(path, 'a+', encoding='utf-8') as cur:\n"
            "    cur.seek(0)\n"
            "    text = cur.read()\n"
            "    if pub not in text:\n"
            "        cur.write(pub + '\\n')\n"
            "        print('authorized_keys: added')\n"
            "    else:\n"
            "        print('authorized_keys: already present')\n"
            "PY",
        )
        print(out or err)

    run(
        c,
        f"test -f {DEPLOY_KEY} || "
        f"ssh-keygen -t ed25519 -N '' -f {DEPLOY_KEY} -C 'raid_nvme@{HOST}'",
    )
    _code, out, _err = run(c, f"cat {DEPLOY_KEY}.pub")
    print("=== ADD THIS as GitHub Deploy key (Settings → Deploy keys, allow write) ===")
    print(out.strip())

    repo = f"{REMOTE_ROOT}/{REPO_NAME}"
    code, out, err = run(
        c,
        f"if [ ! -d {repo}/.git ]; then "
        f"{git_ssh_prefix()} git clone {REPO_SSH} {repo}; "
        f"else echo ALREADY_CLONED; fi; "
        f"cd {repo} && git remote -v && git status -sb || true",
        timeout=600,
    )
    print(f"clone/status exit={code}\n{out}{err}")
    return 0


def cmd_pull(c: paramiko.SSHClient, branch: str) -> int:
    repo = f"{REMOTE_ROOT}/{REPO_NAME}"
    code, out, err = run(
        c,
        f"cd {repo} && {git_ssh_prefix()} git fetch origin && "
        f"git checkout {branch} && git pull --ff-only origin {branch} && "
        f"git rev-parse --short HEAD && git status -sb",
    )
    print(out or err)
    return code


def cmd_status(c: paramiko.SSHClient) -> int:
    repo = f"{REMOTE_ROOT}/{REPO_NAME}"
    code, out, err = run(
        c,
        f"cd {repo} && git rev-parse --short HEAD && git status -sb && git remote -v",
    )
    print(out or err)
    return code


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    c = connect()
    try:
        if action == "bootstrap":
            return cmd_bootstrap(c)
        if action == "pull":
            branch = sys.argv[2] if len(sys.argv) > 2 else "SMOKE"
            return cmd_pull(c, branch)
        if action == "status":
            return cmd_status(c)
        print(
            f"usage: {sys.argv[0]} bootstrap|pull [branch]|status",
            file=sys.stderr,
        )
        return 2
    finally:
        c.close()


if __name__ == "__main__":
    raise SystemExit(main())
