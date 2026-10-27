"""Exercise verification with generated output and an original fake program."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vasp_deb.verification import check_outputs

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/silicon_smoke.py"


class SiliconSmokeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="silicon-runner-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_rejects_unconverged_iteration_limited_and_nonfinite_results(self):
        for converged, iteration, energy in (
            (False, 12, "-12.0"),
            (True, 40, "-12.0"),
            (True, 12, "NaN"),
        ):
            with self.subTest(converged=converged, iteration=iteration, energy=energy):
                (self.root / "OUTCAR").write_text(
                    "aborting loop because EDIFF is reached" if converged else "unconverged"
                )
                (self.root / "OSZICAR").write_text(
                    f"DAV: {iteration} -12.0 -0.000001 -0.000001\n"
                    f" 1 F= {energy} E0= -12.1 d E = 0\n"
                )
                with self.assertRaises(ValueError):
                    check_outputs(self.root)

    def invoke(self, program, timeout=5, *, example=False, potential_text=None):
        potential = self.root / "POTCAR"
        potential.write_text(potential_text or "TITEL = PAW_PBE Si synthetic-test-fixture\n")
        executable = self.root / "fake-vasp"
        executable.write_text(f"#!{sys.executable}\n" + program)
        executable.chmod(0o700)
        return subprocess.run(
            [
                sys.executable,
                *([str(EXAMPLE)] if example else ["-m", "vasp_deb", "verify"]),
                str(potential),
                "--executable",
                str(executable),
                "--timeout",
                str(timeout),
            ],
            cwd=self.root,
            env=dict(os.environ, OMP_NUM_THREADS="8", OPENBLAS_NUM_THREADS="8"),
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_runner_limits_threads_and_preserves_private_inputs(self):
        result = self.invoke(
            "import os\n"
            "from pathlib import Path\n"
            "assert os.environ['OMP_NUM_THREADS'] == '1'\n"
            "assert os.environ['OPENBLAS_NUM_THREADS'] == '1'\n"
            "Path('OUTCAR').write_text('aborting loop because EDIFF is reached')\n"
            "Path('OSZICAR').write_text('DAV: 12 -12.0 -1E-6 -1E-6\\n'\n"
            "    '1 F= -12.000 E0= -12.001 d E = 0\\n')\n"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS: Si2 SCF converged", result.stdout)
        run = next((self.root / ".work").iterdir())
        self.assertEqual(run.stat().st_mode & 0o777, 0o700)
        for name in ("INCAR", "POSCAR", "KPOINTS", "POTCAR", "inputs.json", "vasp.log"):
            self.assertTrue((run / name).is_file(), name)

    def test_nonzero_exit_is_failure(self):
        result = self.invoke("raise SystemExit(7)\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("status 7", result.stderr)

    def test_example_forwards_to_installed_verification(self):
        result = self.invoke("raise SystemExit(7)\n", example=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("status 7", result.stderr)

    def test_wrong_potential_is_rejected_before_running(self):
        result = self.invoke(
            "raise SystemExit(7)\n", potential_text="TITEL = PAW_PBE C synthetic-test-fixture\n"
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("standard Si PAW-PBE", result.stderr)
        self.assertFalse((self.root / ".work").exists())

    def test_invalid_timeout_is_rejected_before_running(self):
        result = self.invoke("raise SystemExit(7)\n", timeout=0)
        self.assertEqual(result.returncode, 1)
        self.assertIn("--timeout must be positive", result.stderr)
        self.assertFalse((self.root / ".work").exists())

    def test_timeout_is_failure_and_retains_log(self):
        result = self.invoke("import time\ntime.sleep(60)\n", timeout=1)
        self.assertEqual(result.returncode, 1)
        self.assertIn("timed out", result.stderr)
        self.assertTrue(next((self.root / ".work").glob("*/vasp.log")).is_file())


if __name__ == "__main__":
    unittest.main()
