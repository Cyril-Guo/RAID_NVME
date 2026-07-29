from ci import collect_console_output


def test_collect_console_uses_downloaded_jenkins_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BUILD_URL", "http://jenkins/job/SMOKE/12/")
    monkeypatch.setattr(
        collect_console_output,
        "download_console",
        lambda build_url: "[Pipeline] stage\nrunning test\n",
    )

    assert collect_console_output.main() == 0
    assert (tmp_path / "jenkins_console.log").read_text(encoding="utf-8") == (
        "[Pipeline] stage\nrunning test\n"
    )


def test_collect_console_falls_back_to_local_execution_logs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(collect_console_output, "download_console", lambda build_url: "")
    (tmp_path / "environment_prepare_10.0.0.1.log").write_text(
        "driver loaded\n",
        encoding="utf-8",
    )
    (tmp_path / "test_execution_10.0.0.1.log").write_text(
        "ERROR: test hung\n",
        encoding="utf-8",
    )

    assert collect_console_output.main() == 0

    console = (tmp_path / "jenkins_console.log").read_text(encoding="utf-8")
    assert "environment_prepare_10.0.0.1.log" in console
    assert "test_execution_10.0.0.1.log" in console
    assert "ERROR: test hung" in console
