"""Run a small, explicitly requested VASP calculation using a local Si POTCAR."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .resources import silicon_inputs


def check_outputs(work: Path) -> tuple[float, float]:
    """Require SCF convergence and finite F/E0 energies for this static run."""
    outcar = (work / "OUTCAR").read_text(errors="replace")
    if "aborting loop because EDIFF is reached" not in outcar:
        raise ValueError("OUTCAR does not report electronic convergence")
    oszicar = (work / "OSZICAR").read_text(errors="replace")
    iterations = re.findall(r"^\s*DAV:\s*(\d+)", oszicar, re.MULTILINE)
    if not iterations or int(iterations[-1]) >= 40:
        raise ValueError("SCF did not finish before the 40-iteration limit")
    energies = re.findall(r"^\s*1\s+F=\s*(\S+)\s+E0=\s*(\S+)", oszicar, re.MULTILINE)
    if len(energies) != 1:
        raise ValueError("OSZICAR does not contain one static energy result")
    free_energy, energy_zero = (float(s.replace("D", "E")) for s in energies[0])
    if not all(math.isfinite(value) for value in (free_energy, energy_zero)):
        raise ValueError("OSZICAR contains a non-finite energy")
    return free_energy, energy_zero


def verify(
    potcar: Path,
    *,
    executable: str = "vasp_gam",
    timeout: int = 120,
    work_dir: Path = Path(".work"),
) -> int:
    """Run the silicon smoke test only when explicitly invoked by the user."""
    work = None
    try:
        if timeout <= 0:
            raise ValueError("--timeout must be positive")
        potential = potcar.read_bytes()
        titles = re.findall(rb"^\s*TITEL\s*=\s*(\S+)\s+(\S+)", potential, re.MULTILINE)
        if titles != [(b"PAW_PBE", b"Si")]:
            raise ValueError("provide exactly one standard Si PAW-PBE dataset")
        resolved = shutil.which(executable)
        if resolved is None:
            raise ValueError(f"executable not found: {executable}")
        executable = str(Path(resolved).resolve())
        work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="silicon-smoke-", dir=work_dir)).resolve()
        print(f"Run directory: {work}", flush=True)
        for name, text in silicon_inputs().items():
            (work / name).write_text(text)
        (work / "POTCAR").write_bytes(potential)
        provenance = {
            "executable": executable,
            "executable_sha256": hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
            "potcar_sha256": hashlib.sha256(potential).hexdigest(),
            "timeout_seconds": timeout,
        }
        (work / "inputs.json").write_text(json.dumps(provenance, indent=2) + "\n")
        environment = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
        started = time.monotonic()
        with (work / "vasp.log").open("w") as log:
            with subprocess.Popen(
                [executable],
                cwd=work,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            ) as process:
                try:
                    status = process.wait(timeout=timeout)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    raise
        if status != 0:
            raise ValueError(f"VASP exited with status {status}; see vasp.log")
        free_energy, energy_zero = check_outputs(work)
        print(
            f"PASS: Si2 SCF converged in {time.monotonic() - started:.1f} s; "
            f"F={free_energy:.8f} eV; E0={energy_zero:.8f} eV"
        )
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        if work:
            print(f"Inspect {work / 'vasp.log'}", file=sys.stderr)
        return 1
