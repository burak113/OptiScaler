"""Run only the explicitly portable handoff suites; never invoke GPU drivers."""
from pathlib import Path
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
SUITES = [
    ("anchor", ROOT / "portable/anchor", ["-m", "unittest", "discover", "-s", "tests", "-v"]),
    ("colour", ROOT / "portable/colour", ["-m", "unittest", "discover", "-p", "test_*.py", "-v"]),
    ("clips", ROOT / "fixtures/clips", ["test_clips.py"]),
    ("glass", ROOT / "fixtures/glass", ["test_glass.py"]),
]


def main():
    env = dict(os.environ, OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2",
               PYTHONDONTWRITEBYTECODE="1")
    start = time.monotonic()
    for name, cwd, command in SUITES:
        if not cwd.is_dir():
            raise SystemExit(f"Required suite missing: {cwd}")
        print(f"\n=== Portable CPU suite: {name} ===", flush=True)
        result = subprocess.run([sys.executable, *command], cwd=cwd, env=env, check=False)
        if result.returncode:
            raise SystemExit(result.returncode)
    print(f"All {len(SUITES)} portable CPU suites passed in {time.monotonic()-start:.3f}s.")


if __name__ == "__main__":
    main()
