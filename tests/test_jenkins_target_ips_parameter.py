from pathlib import Path


def test_target_ips_are_loaded_from_jenkins_build_parameters():
    source = Path("Jenkinsfile").read_text(encoding="utf-8")

    assert "name: 'TARGET_IPS'" in source
    assert "def ipContent = (params.TARGET_IPS ?: '').trim()" in source
    assert ".collect { it.trim() }" in source
    assert "candidate.tokenize('.')" in source
    assert "octet ==~ /^\\d{1,3}$/" in source
    assert "octet.toInteger() > 255" in source
    assert "Invalid TARGET_IPS entries" in source
    assert "readFile('target_ips.txt')" not in source
