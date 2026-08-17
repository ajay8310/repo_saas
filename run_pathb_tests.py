"""Run all three suites in separate processes and summarise."""
import subprocess
import sys

OUT = r"c:\repo_as_service\repo_saas\pathb-results.txt"
CWD = r"c:\repo_as_service\repo_saas"

SUITES = [("unit", "tests/unit/"), ("property", "tests/property/"),
          ("integration", "tests/integration/")]

lines, overall = [], 0
for name, path in SUITES:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", path, "-q", "--tb=line",
         "-p", "no:cacheprovider"],
        capture_output=True, text=True, cwd=CWD,
    )
    body = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
    lines.append(f"===== {name.upper()} (exit {r.returncode}) =====")
    lines.extend(body[-8:])
    lines.append("")
    if r.returncode != 0:
        overall = r.returncode

lines.append(f"===== OVERALL EXIT: {overall} =====")
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
