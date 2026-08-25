import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MIRROR_SCRIPT = REPO_ROOT / "ci" / "ensure_ubuntu_china_mirrors.sh"


def _bash():
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is required to exercise ensure_ubuntu_china_mirrors.sh")
    return bash


def test_mirror_script_targets_aliyun_and_official_hosts():
    source = MIRROR_SCRIPT.read_text(encoding="utf-8")
    assert "mirrors.aliyun.com" in source
    assert "archive\\.ubuntu\\.com" in source or "archive.ubuntu.com" in source
    assert "security\\.ubuntu\\.com" in source or "security.ubuntu.com" in source
    assert "ports\\.ubuntu\\.com" in source or "ports.ubuntu.com" in source
    assert "ubuntu-ports" in source
    assert "APT_SOURCES_ROOT" in source


def test_install_and_prepare_call_china_mirrors():
    install = (REPO_ROOT / "ci" / "install_test_dependencies.sh").read_text(encoding="utf-8")
    prepare = (REPO_ROOT / "ci" / "prepare_env.sh").read_text(encoding="utf-8")
    draid = (REPO_ROOT / "ci" / "prepare_draid_driver.sh").read_text(encoding="utf-8")
    assert "ensure_ubuntu_china_mirrors" in install
    assert "ensure_ubuntu_china_mirrors.sh" in prepare
    assert "ensure_ubuntu_china_mirrors.sh" in draid


def test_rewrites_official_ubuntu_sources_list(tmp_path):
    bash = _bash()
    apt_root = tmp_path / "apt"
    sources_d = apt_root / "sources.list.d"
    sources_d.mkdir(parents=True)
    sources = apt_root / "sources.list"
    sources.write_text(
        "deb http://archive.ubuntu.com/ubuntu jammy main restricted\n"
        "deb http://security.ubuntu.com/ubuntu jammy-security main\n",
        encoding="utf-8",
        newline="\n",
    )
    deb822 = sources_d / "ubuntu.sources"
    deb822.write_text(
        "Types: deb\n"
        "URIs: http://archive.ubuntu.com/ubuntu\n"
        "Suites: jammy jammy-updates\n"
        "Components: main universe\n",
        encoding="utf-8",
        newline="\n",
    )

    env = os.environ.copy()
    env["APT_SOURCES_ROOT"] = str(apt_root).replace("\\", "/")
    if len(env["APT_SOURCES_ROOT"]) >= 2 and env["APT_SOURCES_ROOT"][1] == ":":
        p = env["APT_SOURCES_ROOT"]
        env["APT_SOURCES_ROOT"] = f"/{p[0].lower()}{p[2:]}"
    env["APT_ARCHITECTURE"] = "amd64"
    env["NODE_IP"] = "test"

    result = subprocess.run(
        [bash, str(MIRROR_SCRIPT).replace("\\", "/")],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    text = sources.read_text(encoding="utf-8")
    deb = deb822.read_text(encoding="utf-8")
    assert "mirrors.aliyun.com/ubuntu" in text
    assert "archive.ubuntu.com" not in text
    assert "security.ubuntu.com" not in text
    assert "mirrors.aliyun.com/ubuntu" in deb


def test_arm_uses_ubuntu_ports_path(tmp_path):
    bash = _bash()
    apt_root = tmp_path / "apt"
    (apt_root / "sources.list.d").mkdir(parents=True)
    sources = apt_root / "sources.list"
    sources.write_text(
        "deb http://ports.ubuntu.com/ubuntu-ports jammy main\n"
        "deb http://mirrors.aliyun.com/ubuntu jammy main\n",
        encoding="utf-8",
        newline="\n",
    )

    env = os.environ.copy()
    root = str(apt_root).replace("\\", "/")
    if len(root) >= 2 and root[1] == ":":
        root = f"/{root[0].lower()}{root[2:]}"
    env["APT_SOURCES_ROOT"] = root
    env["APT_ARCHITECTURE"] = "arm64"
    env["NODE_IP"] = "test"

    result = subprocess.run(
        [bash, str(MIRROR_SCRIPT).replace("\\", "/")],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    text = sources.read_text(encoding="utf-8")
    assert "mirrors.aliyun.com/ubuntu-ports" in text
    assert "ports.ubuntu.com" not in text
    assert "mirrors.aliyun.com/ubuntu " not in text
