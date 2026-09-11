from pathlib import Path

from powercycle import salvage_junit_reports


def test_merge_from_directory_writes_node_report(tmp_path):
    item_dir = tmp_path / "items"
    item_dir.mkdir()
    (item_dir / "report_test_powercycle_01_reboot.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1">
  <testcase classname="test_items.test_powercycle_01_reboot" name="test_reboot_powercycle" />
</testsuite>
""",
        encoding="utf-8",
    )
    output = tmp_path / "report_192.168.22.134.xml"

    items = salvage_junit_reports.merge_from_directory(str(item_dir), str(output))

    assert items == ["test_powercycle_01_reboot"]
    assert output.exists()
    assert "test_reboot_powercycle" in output.read_text(encoding="utf-8")


def test_merge_from_directory_keeps_duplicate_run_keys(tmp_path):
    item_dir = tmp_path / "items"
    item_dir.mkdir()
    for run_key in ("test_powercycle_01_reboot__2", "test_powercycle_01_reboot__5"):
        (item_dir / f"report_{run_key}.xml").write_text(
            f"""<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1">
  <testcase classname="test_items.{run_key}" name="test_reboot_powercycle" />
</testsuite>
""",
            encoding="utf-8",
        )
    output = tmp_path / "report.xml"

    items = salvage_junit_reports.merge_from_directory(str(item_dir), str(output))

    assert items == ["test_powercycle_01_reboot__2", "test_powercycle_01_reboot__5"]
    merged = output.read_text(encoding="utf-8")
    assert merged.count("testcase") == 2
    assert "test_items.test_powercycle_01_reboot__2" in merged
    assert "test_items.test_powercycle_01_reboot__5" in merged


def test_monitor_pkill_pattern_does_not_embed_plain_path():
    assert salvage_junit_reports.MONITOR_PKILL_PATTERN == "[S]tress_Monitor/main.py"
    source = Path("powercycle/salvage_junit_reports.py").read_text(encoding="utf-8")
    assert "sys.path.insert" in source
