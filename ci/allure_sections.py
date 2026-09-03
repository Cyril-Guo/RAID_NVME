"""Present console, test outcome and diagnostic artifacts as peer sections."""
import glob
import json
import shutil
from pathlib import Path

try:
    from ci.execution_failure import execution_context
except ModuleNotFoundError:
    from execution_failure import execution_context


SECTION_NAMES = ("终端输出", "测试结果", "日志收集")


def take_attachments(node):
    attachments = node.pop("attachments", [])
    for step in node.get("steps", []):
        attachments.extend(take_attachments(step))
    return attachments


def unique_attachments(attachments):
    return list({a.get("source"): a for a in attachments if a.get("source")}.values())


def organize_results(allure_dir, console_path="jenkins_console.log"):
    root = Path(allure_dir)
    console = Path(console_path)
    if console.is_file():
        shutil.copyfile(console, root / "jenkins_console_full.log")
    count = 0
    for path in root.glob("*-result.json"):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        labels = {x.get("name"): x.get("value") for x in result.get("labels", [])}
        original_steps = result.pop("steps", [])
        attachments = take_attachments(result)
        test_steps = []
        for step in original_steps:
            attachments.extend(take_attachments(step))
            if step.get("name") == "测试结果":
                test_steps.extend(step.get("steps", []))
            elif step.get("name") not in SECTION_NAMES:
                test_steps.append(step)
        for log_path in glob.glob("test_execution_*.log"):
            node, kind = execution_context(log_path)
            if labels.get("host") != node or labels.get("target") != kind:
                continue
            debug_path = Path(log_path.replace("test_execution_", "debug_", 1))
            for log in (Path(log_path), debug_path):
                if log.is_file():
                    source = "collected_" + log.name
                    shutil.copyfile(log, root / source)
                    attachments.append({"name": log.name, "source": source, "type": "text/plain"})
        steps = [{"name": name, "status": "passed", "attachments": []} for name in SECTION_NAMES]
        if console.is_file():
            steps[0]["attachments"].append({"name": "Jenkins Console Output", "source": "jenkins_console_full.log", "type": "text/plain"})
        else:
            missing = root / "jenkins_console_unavailable.txt"
            missing.write_text("Jenkins Console capture unavailable. See test_execution log in diagnostics.\n", encoding="utf-8")
            steps[0]["attachments"].append({"name": "Console capture unavailable", "source": missing.name, "type": "text/plain"})
        status = result.get("status", "broken")
        detail = result.get("statusDetails", {})
        source = f"{result.get('uuid', path.stem)}-test-result.txt"
        outcome = f"Case: {result.get('name')}\nStatus: {status}\n"
        outcome += detail.get("message", "") + "\n" + detail.get("trace", "")
        (root / source).write_text(outcome, encoding="utf-8")
        steps[1].update(status=status, steps=test_steps)
        steps[1]["attachments"].append({"name": "测试结果", "source": source, "type": "text/plain"})
        if detail:
            steps[1]["statusDetails"] = detail
        # Old per-test stdout is useful debug, not the full Jenkins Console.
        steps[2]["attachments"] = unique_attachments([
            a for a in attachments if a.get("name") not in ("Jenkins Console Output", "测试结果", "Console capture unavailable")
        ])
        missing = [a for a in steps[2]["attachments"] if not (root / a["source"]).is_file()]
        if missing:
            missing_file = root / f"{result.get('uuid', path.stem)}-missing-artifacts.txt"
            missing_file.write_text(
                "Referenced artifacts were not recovered (collection interrupted, failed or timed out):\n" +
                "\n".join(f"{a.get('name')}: {a['source']}" for a in missing), encoding="utf-8",
            )
            steps[2]["attachments"] = [a for a in steps[2]["attachments"] if a not in missing]
            steps[2]["attachments"].append({"name": "Missing artifact details", "source": missing_file.name, "type": "text/plain"})
        if not steps[2]["attachments"]:
            unavailable = root / "diagnostics_unavailable.txt"
            unavailable.write_text("No diagnostic artifacts were recovered. Target may be unreachable or collection did not finish.\n", encoding="utf-8")
            steps[2]["attachments"].append({"name": "Diagnostics unavailable", "source": unavailable.name, "type": "text/plain"})
        result["steps"] = steps
        path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        count += 1
    return count


def native_case_exists(allure_dir, case, node, kind):
    suffix = f"{case.get('classname', '')}#{case.get('name', '')}"
    for path in Path(allure_dir).glob("*-result.json"):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        labels = {x.get("name"): x.get("value") for x in result.get("labels", [])}
        if labels.get("host") == node and labels.get("target") == kind:
            if str(result.get("fullName", "")).endswith(suffix):
                # A finalized JUnit teardown error must not remain green in Allure.
                detail = case.find("error")
                status = "broken"
                if detail is None:
                    detail = case.find("failure")
                    status = "failed"
                if detail is not None and result.get("status") not in ("failed", "broken"):
                    result["status"] = status
                    result["statusDetails"] = {"message": detail.get("message", status),
                                               "trace": detail.text or detail.get("message", status)}
                    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                return True
    return False
