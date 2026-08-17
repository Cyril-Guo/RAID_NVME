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


def test_collect_console_merges_local_logs_when_download_is_truncated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        collect_console_output,
        "download_console",
        lambda build_url: "Job 1/2800 is Running..\nJob 61/2800 is Running..\n",
    )
    (tmp_path / "test_execution_10.0.0.1.log").write_text(
        "Job 1/2800 is Running..\nJob 61/2800 is Running..\nJob 2800/2800 is Running..\n",
        encoding="utf-8",
    )

    assert collect_console_output.main() == 0
    console = (tmp_path / "jenkins_console.log").read_text(encoding="utf-8")
    assert "complete local execution logs" in console
    assert "Job 2800/2800 is Running.." in console


def test_download_console_follows_progressive_text_chunks(monkeypatch):
    class FakeHeaders(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class FakeResponse:
        def __init__(self, body, more, size):
            self._body = body.encode("utf-8")
            self.headers = FakeHeaders(
                {
                    "X-More-Data": "true" if more else "false",
                    "X-Text-Size": str(size),
                }
            )

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    calls = []

    def fake_urlopen(request, timeout=60):
        calls.append(request.full_url)
        if "start=0" in request.full_url:
            return FakeResponse("Job 1/2800 is Running..\n", True, 10)
        return FakeResponse("Job 2800/2800 is Running..\n", False, 20)

    monkeypatch.setattr(collect_console_output.urllib.request, "urlopen", fake_urlopen)
    text = collect_console_output.download_console("http://jenkins/job/CI/1/")
    assert "Job 1/2800 is Running.." in text
    assert "Job 2800/2800 is Running.." in text
    assert len(calls) == 2
