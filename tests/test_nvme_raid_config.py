from pathlib import Path
import os

import pytest

import nvme_raid_test
from nvme_raid_test import (
    discover_test_items,
    item_name_from_filename,
    parse_items_file,
)


def test_item_name_from_filename_supports_ci_and_plain_patterns():
    assert item_name_from_filename("test_ci_03_lawdisk.py") == "lawdisk"
    assert item_name_from_filename("test_ci_01_reboot.py") == "reboot"
    assert item_name_from_filename("test_foo.py") == "foo"
    assert item_name_from_filename("basic_io_common.py") is None
    assert item_name_from_filename("test_basic_io_common.py") is None
    assert item_name_from_filename("powercycle_launch.py") is None
    assert item_name_from_filename("fio_run.py") is None
    assert item_name_from_filename("fio_allure.py") is None
    assert item_name_from_filename("random_io_plan.py") is None
    assert item_name_from_filename("__init__.py") is None


def test_discover_test_items_finds_repository_ci_cases():
    catalog = discover_test_items()

    assert catalog["reboot"] == "test_items/test_ci_01_reboot.py"
    assert catalog["dc"] == "test_items/test_ci_02_dc.py"
    assert catalog["lawdisk"] == "test_items/test_ci_03_lawdisk.py"
    assert catalog["filesystem"] == "test_items/test_ci_04_filesystem.py"
    assert catalog["mix"] == "test_items/test_ci_05_mix.py"
    assert catalog["basic_io"] == "test_items/test_ci_06_basic_io.py"
    assert catalog["basic_rebuild_io"] == "test_items/test_ci_07_basic_rebuild_io.py"
    assert catalog["random_io"] == "test_items/test_ci_08_random_io.py"
    assert catalog["env_prepare"] == "test_items/test_ci_00_env_prepare.py"


def test_discover_test_items_rejects_duplicate_names(tmp_path):
    items_dir = tmp_path / "test_items"
    items_dir.mkdir()
    (items_dir / "test_ci_01_foo.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    (items_dir / "test_foo.py").write_text("def test_b():\n    pass\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate test item name 'foo'"):
        discover_test_items(str(items_dir))


def test_repository_test_items_file_is_valid():
    config = Path(__file__).resolve().parents[1] / "test_items.txt"
    text = config.read_text(encoding="utf-8")
    catalog = discover_test_items()

    selected, params = parse_items_file(config)
    entries = nvme_raid_test.read_selection_entries(str(config))

    assert "BEGIN SELECTION" in text
    assert "END SELECTION" in text
    assert [name for name, _orders, _enabled in entries]
    assert set(name for name, _orders, _enabled in entries) == set(catalog)
    assert selected
    assert all(name in catalog for name in selected)
    assert "defaults" not in params
    assert "lawdisk" in params
    assert params["lawdisk"]["IGNORE_ERROR"] == "yes"
    assert params["lawdisk"]["FIO_CONFIG"] == "Input_Config_lawdisk.csv"
    assert params["mix"]["FIO_CONFIG"] == "Input_Config_mix.csv"
    assert params["mix"]["MIX_FAIL_ON_ANY"].strip().lower() in ("yes", "no")
    assert params["basic_io"]["FIO_CONFIG"] == "Input_Config_basic_io.csv"
    assert params["random_io"]["FIO_CONFIG"] == "Input_Config_random_io.csv"
    assert "FIO_CYCLES" not in params["lawdisk"]
    assert params["dc"]["FIO_CYCLES"] == "5"
    assert params["reboot"]["FIO_CYCLES"] == "100"
    assert params["basic_io"]["STRESS_MONITOR"] == "no"
    assert params["basic_rebuild_io"]["STRESS_MONITOR"] == "no"
    assert "env_prepare" in params


def test_main_prints_item_boundaries():
    source = Path("nvme_raid_test.py").read_text(encoding="utf-8")

    assert "[ITEM_START] {run_key}" in source
    assert "[ITEM_END] {run_key} exit_code={exit_code}" in source
    assert "sync_selection_list" in source
    assert "[defaults]" not in Path("test_items.txt").read_text(encoding="utf-8")


def test_sync_selection_lists_all_discovered_items(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# header
# === BEGIN SELECTION（自动同步；名称后数字为执行顺序，# 表示不跑）===
lawdisk 3
# mix 5
# === END SELECTION ===

[lawdisk]
IGNORE_ERROR = no

[mix]
IGNORE_ERROR = no
""",
        encoding="utf-8",
        newline="\n",
    )
    catalog = {
        "reboot": "test_items/test_ci_01_reboot.py",
        "dc": "test_items/test_ci_02_dc.py",
        "lawdisk": "test_items/test_ci_03_lawdisk.py",
        "filesystem": "test_items/test_ci_04_filesystem.py",
        "mix": "test_items/test_ci_05_mix.py",
    }

    assert nvme_raid_test.sync_selection_list(str(config), catalog) is True
    text = config.read_text(encoding="utf-8")
    selected, _params = parse_items_file(config)
    entries = nvme_raid_test.read_selection_entries(str(config))

    assert selected == ["lawdisk"]
    assert [(name, orders, enabled) for name, orders, enabled in entries] == [
        ("reboot", [1], False),
        ("dc", [2], False),
        ("lawdisk", [3], True),
        ("filesystem", [4], False),
        ("mix", [5], False),
    ]
    assert "lawdisk 3\n" in text
    for name in ("reboot", "dc", "filesystem", "mix"):
        assert f"# {name} " in text


def test_sync_selection_preserves_custom_numeric_order(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# === BEGIN SELECTION（自动同步；名称后数字为执行顺序，# 表示不跑）===
mix 1
# filesystem 2
lawdisk 3
# reboot 4
# dc 5
# === END SELECTION ===

[mix]
IGNORE_ERROR = no

[lawdisk]
IGNORE_ERROR = no
""",
        encoding="utf-8",
        newline="\n",
    )
    catalog = {
        "reboot": "test_items/test_ci_01_reboot.py",
        "dc": "test_items/test_ci_02_dc.py",
        "lawdisk": "test_items/test_ci_03_lawdisk.py",
        "filesystem": "test_items/test_ci_04_filesystem.py",
        "mix": "test_items/test_ci_05_mix.py",
    }

    assert nvme_raid_test.sync_selection_list(str(config), catalog) is False
    selected, _params = parse_items_file(config)
    entries = nvme_raid_test.read_selection_entries(str(config))

    assert selected == ["mix", "lawdisk"]
    assert [(name, orders) for name, orders, _enabled in entries] == [
        ("mix", [1]),
        ("filesystem", [2]),
        ("lawdisk", [3]),
        ("reboot", [4]),
        ("dc", [5]),
    ]


def test_parse_whitelist_controls_enabled_items_with_per_case_params(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# === BEGIN SELECTION（自动同步；名称后数字为执行顺序，# 表示不跑）===
# reboot 1
dc 2
mix 5
# === END SELECTION ===

[dc]
FIO_CYCLES = 3
IGNORE_ERROR = no

[mix]
FIO_DISKS = sdb,sdc
STRESS_MONITOR = yes
""",
        encoding="utf-8",
    )

    selected, params = parse_items_file(config)

    assert selected == ["dc", "mix"]
    assert params["dc"] == {"FIO_CYCLES": "3", "IGNORE_ERROR": "no"}
    assert params["mix"] == {"FIO_DISKS": "sdb,sdc", "STRESS_MONITOR": "yes"}
    assert "FIO_CYCLES" not in params["mix"]


def test_parse_sorts_enabled_items_by_numeric_order(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# === BEGIN SELECTION（自动同步；名称后数字为执行顺序，# 表示不跑）===
mix 5
lawdisk 3
reboot 1
# === END SELECTION ===

[mix]
IGNORE_ERROR = no

[lawdisk]
IGNORE_ERROR = no

[reboot]
FIO_CYCLES = 10
""",
        encoding="utf-8",
    )

    selected, _params = parse_items_file(config)

    assert selected == ["reboot", "lawdisk", "mix"]


def test_parse_selection_entry_supports_multiple_orders():
    assert nvme_raid_test.parse_selection_entry("mix 8 10") == ("mix", [8, 10], True)
    assert nvme_raid_test.parse_selection_entry("# mix 8 10") == ("mix", [8, 10], False)
    assert nvme_raid_test.parse_selection_entry("basic_io 1") == ("basic_io", [1], True)


def test_read_enabled_selection_repeats_item_for_multiple_orders(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# === BEGIN SELECTION（自动同步；名称后数字为执行顺序，# 表示不跑）===
mix 8 10
basic_io 1
basic_rebuild_io 9
# === END SELECTION ===

[mix]
IGNORE_ERROR = no

[basic_io]
IGNORE_ERROR = no

[basic_rebuild_io]
IGNORE_ERROR = no
""",
        encoding="utf-8",
    )
    catalog = {
        "mix": "test_items/test_ci_05_mix.py",
        "basic_io": "test_items/test_ci_06_basic_io.py",
        "basic_rebuild_io": "test_items/test_ci_07_basic_rebuild_io.py",
    }

    selected = nvme_raid_test.read_enabled_selection(str(config))
    plan = nvme_raid_test.build_run_plan(str(config), test_items=catalog)

    assert selected == ["basic_io", "mix", "basic_rebuild_io", "mix"]
    assert [entry["item"] for entry in plan] == selected
    assert [entry["run_key"] for entry in plan] == [
        "basic_io__1",
        "mix__8",
        "basic_rebuild_io__9",
        "mix__10",
    ]


def test_build_run_plan_tags_run_key_with_order(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# === BEGIN SELECTION（自动同步；名称后数字为执行顺序，# 表示不跑）===
lawdisk 3
# === END SELECTION ===

[lawdisk]
IGNORE_ERROR = no
""",
        encoding="utf-8",
    )
    catalog = {"lawdisk": "test_items/test_ci_03_lawdisk.py"}

    plan = nvme_raid_test.build_run_plan(str(config), test_items=catalog)

    assert plan == [{"item": "lawdisk", "order": 3, "run_key": "lawdisk__3"}]


def test_run_single_item_omits_allure_args_without_plugin(monkeypatch, tmp_path):
    captured = {}
    clear_calls = []

    def fake_pytest_main(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(nvme_raid_test.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(nvme_raid_test.pytest, "main", fake_pytest_main)
    monkeypatch.setattr(
        "test_items.basic_io_common.release_and_clear_csd",
        lambda disks, log: clear_calls.append(True),
    )

    assert nvme_raid_test.run_single_item(
        "lawdisk", {}, clean_allure=True, work_dir=str(tmp_path)
    ) == 0

    args = captured["args"]
    assert clear_calls == []
    assert "--clean-alluredir" not in args
    assert not any(arg.startswith("--alluredir=") for arg in args)
    assert "--junitxml=report_lawdisk.xml" in args


def test_run_single_item_clears_csd_only_for_basic_io_cases(monkeypatch, tmp_path):
    clear_calls = []

    monkeypatch.setattr(nvme_raid_test.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(nvme_raid_test.pytest, "main", lambda args: 0)
    monkeypatch.setattr(
        "test_items.basic_io_common.release_and_clear_csd",
        lambda disks, log: clear_calls.append(True),
    )
    catalog = {
        "basic_io": "test_items/test_ci_06_basic_io.py",
        "basic_rebuild_io": "test_items/test_ci_07_basic_rebuild_io.py",
        "random_io": "test_items/test_ci_08_random_io.py",
        "env_prepare": "test_items/test_ci_00_env_prepare.py",
    }

    for item in ("basic_io", "basic_rebuild_io"):
        clear_calls.clear()
        assert (
            nvme_raid_test.run_single_item(
                item, {}, clean_allure=False, work_dir=str(tmp_path), test_items=catalog
            )
            == 0
        )
        assert clear_calls == [True], item

    for item in ("random_io", "env_prepare"):
        clear_calls.clear()
        assert (
            nvme_raid_test.run_single_item(
                item, {}, clean_allure=False, work_dir=str(tmp_path), test_items=catalog
            )
            == 0
        )
        assert clear_calls == [], item


def test_run_single_item_uses_run_key_for_junit_and_env(monkeypatch, tmp_path):
    captured = {}

    def fake_pytest_main(args):
        captured["args"] = args
        captured["run_key"] = os.environ.get("RAID_NVME_RUN_KEY")
        captured["order"] = os.environ.get("RAID_NVME_RUN_ORDER")
        captured["item"] = os.environ.get("RAID_NVME_ITEM")
        return 0

    monkeypatch.setattr(nvme_raid_test.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(nvme_raid_test.pytest, "main", fake_pytest_main)
    monkeypatch.setattr(
        "test_items.basic_io_common.release_and_clear_csd",
        lambda disks, log: None,
    )

    assert nvme_raid_test.run_single_item(
        "lawdisk",
        {},
        clean_allure=True,
        work_dir=str(tmp_path),
        run_key="lawdisk__2",
        order=2,
    ) == 0

    assert "--junitxml=report_lawdisk__2.xml" in captured["args"]
    assert captured["run_key"] == "lawdisk__2"
    assert captured["order"] == "2"
    assert captured["item"] == "lawdisk"
    assert os.environ.get("RAID_NVME_RUN_KEY") is None


def test_merge_junit_reports_keeps_duplicate_run_keys(tmp_path):
    for run_key in ("lawdisk__2", "lawdisk__5"):
        (tmp_path / f"report_{run_key}.xml").write_text(
            f"""<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1">
  <testcase classname="test_items.{run_key}" name="test_lawdiskstress" />
</testsuite>
""",
            encoding="utf-8",
        )
    output = tmp_path / "report.xml"
    previous = os.getcwd()
    try:
        os.chdir(tmp_path)
        nvme_raid_test.merge_junit_reports(["lawdisk__2", "lawdisk__5"], "report.xml")
    finally:
        os.chdir(previous)

    merged = output.read_text(encoding="utf-8")
    assert merged.count("testcase") == 2


def test_discover_junit_run_keys_skips_node_reports(tmp_path):
    (tmp_path / "report_lawdisk__2.xml").write_text("<testsuite/>", encoding="utf-8")
    (tmp_path / "report_192.168.1.10.xml").write_text("<testsuite/>", encoding="utf-8")

    assert nvme_raid_test.discover_junit_run_keys(str(tmp_path)) == ["lawdisk__2"]


def test_prepare_case_workdir_isolates_io_stress(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "nvme_raid_test.py").write_text("print('ok')\n", encoding="utf-8")
    io_stress = repo / "IO_Stress"
    io_stress.mkdir()
    (io_stress / "Fio_All.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (io_stress / "log").mkdir()
    (io_stress / "log" / "old.log").write_text("old\n", encoding="utf-8")
    (repo / "test_items").mkdir()
    (repo / "cases").mkdir()

    case_dir = Path(nvme_raid_test.prepare_case_workdir(str(repo), "mix"))

    assert case_dir == repo / "cases" / "mix"
    assert (case_dir / "nvme_raid_test.py").exists()
    assert (case_dir / "IO_Stress" / "Fio_All.sh").is_file()
    assert not (case_dir / "IO_Stress" / "log" / "old.log").exists()
    assert (case_dir / "IO_Stress" / "log").is_dir()


def test_main_stops_after_first_failed_item(monkeypatch, tmp_path):
    executed = []
    merged_calls = []

    monkeypatch.setattr(nvme_raid_test, "sync_selection_list", lambda path, catalog: False)
    monkeypatch.setattr(
        nvme_raid_test,
        "build_run_plan",
        lambda path, test_items=None: [
            {"item": "lawdisk", "order": 3, "run_key": "lawdisk"},
            {"item": "mix", "order": 5, "run_key": "mix"},
        ],
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "parse_items_file",
        lambda path: (["lawdisk", "mix"], {"lawdisk": {}, "mix": {}}),
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "discover_test_items",
        lambda items_dir=None: {
            "lawdisk": "test_items/test_ci_03_lawdisk.py",
            "mix": "test_items/test_ci_05_mix.py",
        },
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "prepare_case_workdir",
        lambda repo_root, item: str(tmp_path / item),
    )
    monkeypatch.setattr(nvme_raid_test, "collect_case_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        nvme_raid_test,
        "run_single_item",
        lambda item, params, clean_allure, test_items=None, work_dir=None, **kwargs: executed.append(item) or (1 if item == "lawdisk" else 0),
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "merge_junit_reports",
        lambda items, out_path: merged_calls.append(list(items)),
    )

    with pytest.raises(SystemExit) as exc:
        nvme_raid_test.main([])

    assert exc.value.code == 1
    assert executed == ["lawdisk"]
    assert merged_calls == [["lawdisk"]]


def test_main_uses_whitelist_order_not_discovery_order(monkeypatch, tmp_path):
    executed = []

    monkeypatch.setattr(nvme_raid_test, "sync_selection_list", lambda path, catalog: False)
    monkeypatch.setattr(
        nvme_raid_test,
        "build_run_plan",
        lambda path, test_items=None: [
            {"item": "mix", "order": 1, "run_key": "mix"},
            {"item": "lawdisk", "order": 3, "run_key": "lawdisk"},
        ],
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "parse_items_file",
        lambda path: (["mix", "lawdisk"], {"mix": {}, "lawdisk": {}}),
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "discover_test_items",
        lambda items_dir=None: {
            "lawdisk": "test_items/test_ci_03_lawdisk.py",
            "mix": "test_items/test_ci_05_mix.py",
        },
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "prepare_case_workdir",
        lambda repo_root, item: str(tmp_path / item),
    )
    monkeypatch.setattr(nvme_raid_test, "collect_case_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        nvme_raid_test,
        "run_single_item",
        lambda item, params, clean_allure, test_items=None, work_dir=None, **kwargs: executed.append(item) or 0,
    )
    monkeypatch.setattr(nvme_raid_test, "merge_junit_reports", lambda items, out_path: None)

    with pytest.raises(SystemExit) as exc:
        nvme_raid_test.main([])

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
