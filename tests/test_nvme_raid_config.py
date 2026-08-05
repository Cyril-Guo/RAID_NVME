from pathlib import Path

import pytest

import nvme_raid_test
from nvme_raid_test import (
    discover_test_items,
    item_name_from_filename,
    parse_items_file,
)


def test_item_name_from_filename_supports_smoke_and_plain_patterns():
    assert item_name_from_filename("test_smoke_03_lawdisk.py") == "lawdisk"
    assert item_name_from_filename("test_smoke_01_reboot.py") == "reboot"
    assert item_name_from_filename("test_foo.py") == "foo"
    assert item_name_from_filename("basic_io_common.py") is None
    assert item_name_from_filename("test_basic_io_common.py") is None
    assert item_name_from_filename("powercycle_launch.py") is None
    assert item_name_from_filename("__init__.py") is None


def test_discover_test_items_finds_repository_smoke_cases():
    catalog = discover_test_items()

    assert catalog["reboot"] == "test_items/test_smoke_01_reboot.py"
    assert catalog["dc"] == "test_items/test_smoke_02_dc.py"
    assert catalog["lawdisk"] == "test_items/test_smoke_03_lawdisk.py"
    assert catalog["filesystem"] == "test_items/test_smoke_04_filesystem.py"
    assert catalog["mix"] == "test_items/test_smoke_05_mix.py"
    assert "basic_io" not in catalog
    assert "basic_rebuild_io" not in catalog


def test_discover_test_items_rejects_duplicate_names(tmp_path):
    items_dir = tmp_path / "test_items"
    items_dir.mkdir()
    (items_dir / "test_smoke_01_foo.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    (items_dir / "test_foo.py").write_text("def test_b():\n    pass\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate test item name 'foo'"):
        discover_test_items(str(items_dir))


def test_repository_test_items_file_is_valid():
    config = Path(__file__).resolve().parents[1] / "test_items.txt"

    selected, params = parse_items_file(config)

    assert selected == []
    assert "lawdisk" in params
    assert params["lawdisk"]["STRESS_MONITOR"] == "yes"
    assert params["lawdisk"]["IGNORE_ERROR"] == "no"
    assert params["dc"]["FIO_CYCLES"] == "5"
    assert "basic_io" not in params


def test_main_prints_item_boundaries():
    source = Path("nvme_raid_test.py").read_text(encoding="utf-8")

    assert "[ITEM_START] {item}" in source
    assert "[ITEM_END] {item} exit_code={exit_code}" in source


def test_parse_whitelist_controls_enabled_items_and_merges_defaults(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# comment
dc
mix

[defaults]
IGNORE_ERROR = no
FIO_CYCLES = 10
STRESS_MONITOR = no

[dc]
FIO_CYCLES = 3

[mix]
FIO_DISKS = sdb,sdc
STRESS_MONITOR = yes
""",
        encoding="utf-8",
    )

    selected, params = parse_items_file(config)

    assert selected == ["dc", "mix"]
    assert params["dc"]["FIO_CYCLES"] == "3"
    assert params["dc"]["IGNORE_ERROR"] == "no"
    assert params["mix"]["FIO_DISKS"] == "sdb,sdc"
    assert params["mix"]["STRESS_MONITOR"] == "yes"
    assert params["mix"]["FIO_CYCLES"] == "10"


def test_parse_preserves_whitelist_order(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
mix
lawdisk
reboot

[defaults]
IGNORE_ERROR = no
""",
        encoding="utf-8",
    )

    selected, _params = parse_items_file(config)

    assert selected == ["mix", "lawdisk", "reboot"]


def test_run_single_item_omits_allure_args_without_plugin(monkeypatch):
    captured = {}

    def fake_pytest_main(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(nvme_raid_test.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(nvme_raid_test.pytest, "main", fake_pytest_main)

    assert nvme_raid_test.run_single_item("lawdisk", {}, clean_allure=True) == 0

    args = captured["args"]
    assert "--clean-alluredir" not in args
    assert not any(arg.startswith("--alluredir=") for arg in args)
    assert "--junitxml=report_lawdisk.xml" in args


def test_main_stops_after_first_failed_item(monkeypatch):
    executed = []
    merged_calls = []

    monkeypatch.setattr(
        nvme_raid_test,
        "parse_items_file",
        lambda path: (["lawdisk", "mix"], {"lawdisk": {}, "mix": {}}),
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "discover_test_items",
        lambda items_dir=None: {
            "lawdisk": "test_items/test_smoke_03_lawdisk.py",
            "mix": "test_items/test_smoke_05_mix.py",
        },
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "run_single_item",
        lambda item, params, clean_allure, test_items=None: executed.append(item) or 1,
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "merge_junit_reports",
        lambda items, out_path: merged_calls.append(list(items)),
    )

    with pytest.raises(SystemExit) as exc:
        nvme_raid_test.main()

    assert exc.value.code == 1
    assert executed == ["lawdisk"]
    assert merged_calls == [["lawdisk"]]


def test_main_uses_whitelist_order_not_discovery_order(monkeypatch):
    executed = []

    monkeypatch.setattr(
        nvme_raid_test,
        "parse_items_file",
        lambda path: (["mix", "lawdisk"], {"mix": {}, "lawdisk": {}}),
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "discover_test_items",
        lambda items_dir=None: {
            "lawdisk": "test_items/test_smoke_03_lawdisk.py",
            "mix": "test_items/test_smoke_05_mix.py",
        },
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "run_single_item",
        lambda item, params, clean_allure, test_items=None: executed.append(item) or 0,
    )
    monkeypatch.setattr(nvme_raid_test, "merge_junit_reports", lambda items, out_path: None)

    with pytest.raises(SystemExit) as exc:
        nvme_raid_test.main()

    assert exc.value.code == 0
    assert executed == ["mix", "lawdisk"]


def test_stop_monitor_escalates_to_kill(monkeypatch):
    calls = []
    checks = {"count": 0}
    monitor_main = nvme_raid_test.monitor_paths("/tmp/project")[0]

    def fake_run(cmd, stdout=None, stderr=None, check=False):
        calls.append(cmd)

        class Result:
            returncode = 0

        if cmd[:2] == ["pgrep", "-f"]:
            checks["count"] += 1
            # Stay alive through TERM wait, then disappear after KILL.
            Result.returncode = 1 if checks["count"] > 32 else 0
        return Result()

    monkeypatch.setattr(nvme_raid_test.subprocess, "run", fake_run)
    monkeypatch.setattr(nvme_raid_test.time, "sleep", lambda seconds: None)

    nvme_raid_test.stop_monitor_for_item("/tmp/project", wait_seconds=30)

    assert ["pkill", "-TERM", "-f", monitor_main] in calls
    assert ["pkill", "-KILL", "-f", monitor_main] in calls
