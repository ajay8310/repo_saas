"""Run tests and write output to test-results.txt. Usage: python run_tests.py [pytest args]"""
import subprocess
import sys

args = sys.argv[1:] if len(sys.argv) > 1 else ["tests/unit/", "-v", "--tb=short"]
result = subprocess.run(
    [sys.executable, "-m", "pytest"] + args,
    capture_output=True,
    text=True,
    cwd=r"c:\repo_as_service\repo_saas",
)
with open(r"c:\repo_as_service\repo_saas\test-results.txt", "w") as f:
    f.write(result.stdout)
    if result.stderr:
        f.write("\n=== STDERR ===\n")
        f.write(result.stderr)
    f.write(f"\n=== EXIT CODE: {result.returncode} ===\n")
print(f"Exit code: {result.returncode}")
