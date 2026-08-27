from pathlib import Path


def test_prepare_env_script_covers_smoke_physical_steps():
    source = Path("ci/prepare_env.sh").read_text(encoding="utf-8")

    assert "reclaim_physical_host.sh" in source
    assert "clear_8p_csd_flash.sh" in source
    assert "flash-clear.sh" in source
    assert "clear dirty CSD flash via draid accel devices" in source
    assert "artifacts/dpraid" in source
    assert "rmmod" in source
    assert "insmod" in source
    assert "restore_physical_raid_state.sh" in source
    assert "/usr/bin/dpraid --help >/dev/null" in source
    assert "/usr/bin/dpraid --help >/dev/null 2>&1 || true" not in source
    assert "build-essential" in source
    assert "install_draid_build_deps" in source
    assert "ripgrep" in source
    assert "make -j 8 ACCEL_CDEV=y" in source
    # reclaim -> dpraid -> draid load -> CSD clear -> restore VD/PD
    assert source.index("reclaim_physical_host.sh") < source.index("insmod ./draid.ko")
    assert source.index("insmod ./draid.ko") < source.index("clear_8p_csd_flash.sh")
    assert source.index("clear_8p_csd_flash.sh") < source.index("restore_physical_raid_state.sh")
    assert source.index("install_draid_build_deps") < source.index("make -j 8 ACCEL_CDEV=y")


def test_reclaim_physical_host_stops_qemu_unloads_draid_and_unbinds_vfio():
    source = Path("ci/reclaim_physical_host.sh").read_text(encoding="utf-8")

    assert "qemu_guest_reachable" in source
    assert "list_host_qemu_pids" in source
    assert "poweroff" in source
    assert "qemu-system-x86_64.*vm-serial.log" in source
    assert 'grep -F "${QEMU_VM_WORKDIR}"' in source
    assert "unload draid" in source or "unload_draid_module" in source
    assert "rmmod" in source
    assert "list_vfio_nvme_devices" in source
    assert "vfio-pci" in source
    assert "unbind" in source
    assert "QEMU_VM_WORKDIR" in source
    assert "vfio-bind.sh" in source
    assert "/sys/bus/pci/rescan" in source


def test_install_dpraid_stages_artifact_for_env_prepare():
    source = Path("ci/install_dpraid_remote.sh").read_text(encoding="utf-8")

    assert "REMOTE_DIR" in source
    assert "artifacts/dpraid" in source
    assert ">/dev/null 2>&1 || true" not in source
    assert "/usr/bin/dpraid --help >/dev/null" in source


def test_legacy_prepare_physical_io_case_script_removed():
    assert not Path("ci/prepare_physical_io_case.sh").exists()
    assert Path("ci/prepare_env.sh").is_file()
    assert Path("ci/reclaim_physical_host.sh").is_file()
