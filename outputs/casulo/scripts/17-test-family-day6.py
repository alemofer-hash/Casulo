"""Run only permitted product/Family tests, preserving complete results."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env.pop("CASULO_ENABLE_LEGACY_RESEARCH", None)
    env["PYTHONPATH"] = os.pathsep.join([str(root/"src"), str(root/"private/casulo-owner/src")])
    tests = {}
    for label, scope in (("day6", "tests/family/test_day6_cleo_voice.py"),
                         ("family", "tests/family"), ("product", "tests/product")):
        command = [sys.executable, "-m", "pytest", scope, "-q", "--tb=short",
                   "--basetemp", str(root/"task/tmp"/("day6-"+evidence.name+"-"+label)),
                   "--junitxml", str(evidence/(label+".xml"))]
        print("TESTING", label, flush=True)
        with (evidence/("test-results-"+label+".txt")).open("x", encoding="utf-8") as output:
            result = subprocess.run(command, cwd=root, env=env, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=600)
        tests[label] = {"exit_code": result.returncode, "command": command}
        print(label, "EXIT", result.returncode, flush=True)
    (evidence/"test-summary.json").write_text(json.dumps(tests, indent=2)+"\n", encoding="utf-8", newline="\n")
    return int(any(test["exit_code"] for test in tests.values()))


if __name__ == "__main__":
    raise SystemExit(main())
