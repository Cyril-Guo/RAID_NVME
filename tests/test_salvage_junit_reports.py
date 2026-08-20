from pathlib import Path

from ci import salvage_junit_reports


def test_merge_from_directory_writes_node_report(tmp_path):
    item_dir = tmp_path / "items"
    item_dir.mkdir()
    (item_dir / "report_lawdisk.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1">
  <testcase classname="test_items.test_smoke_03_lawdisk" name="test_lawdiskstress" />
</testsuite>
""",
        encoding="utf-8",
    )
    output = tmp_path / "report_192.168.22.134.xml"

    items = salvage_junit_reports.merge_from_directory(str(item_dir), str(output))

    assert items == ["lawdisk"]
    assert output.exists()
    assert "test_lawdiskstress" in output.read_text(encoding="utf-8")


def test_monitor_pkill_pattern_does_not_embed_plain_path():
    assert salvage_junit_reports.MONITOR_PKILL_PATTERN == "[S]tress_Monitor/main.py"
    source = Path("ci/salvage_junit_reports.py").read_text(encoding="utf-8")
    assert "pkill -TERM -f Stress_Monitor/main.py" not in source
    assert "pkill -KILL -f Stress_Monitor/main.py" not in source
    assert "sys.path.insert" in source
