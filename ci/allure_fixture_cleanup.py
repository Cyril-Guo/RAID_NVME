"""Hide fixture UI sections after preserving their logs and real failures."""
import hashlib
from pathlib import Path

try:
    from ci.report_identity import all_attachments, read_json, save_json
except ModuleNotFoundError:
    from report_identity import all_attachments, read_json, save_json


def flatten_fixtures(allure_dir):
    root = Path(allure_dir)
    results = {r.get("uuid"): (p, r) for p in root.glob("*-result.json") if (r := read_json(p))}
    flattened = 0
    for path in root.glob("*-container.json"):
        container = read_json(path)
        if not container:
            continue
        targets = [results[key] for key in container.get("children", []) if key in results]
        if not targets:
            continue
        for key, phase in (("befores", "setup"), ("afters", "teardown")):
            for fixture in container.get(key) or []:
                for _, result in targets:
                    result.setdefault("attachments", []).extend(all_attachments(fixture))
                    if fixture.get("status") not in ("failed", "broken"):
                        continue
                    detail = fixture.get("statusDetails") or {}
                    error = f"{phase}: {fixture.get('name', 'fixture')}: {detail.get('message', fixture['status'])}"
                    trace = error + "\n" + detail.get("trace", "")
                    digest = hashlib.sha256((str(result.get("uuid")) + trace).encode()).hexdigest()[:20]
                    source = f"fixture-error-{digest}.txt"
                    (root / source).write_text(trace, encoding="utf-8")
                    result["attachments"].append({"name": "准备/收尾异常", "source": source, "type": "text/plain"})
                    original = result.get("statusDetails") or {}
                    if result.get("status") not in ("failed", "broken"):
                        result["status"] = fixture["status"]
                    result["statusDetails"] = {
                        "message": original.get("message") or error,
                        "trace": "\n".join(x for x in (original.get("trace"), trace) if x),
                    }
            if container.get(key):
                container[key] = []
                flattened += 1
        save_json(path, container)
    for path, result in results.values():
        save_json(path, result)
    return flattened
