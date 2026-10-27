"""Check distributable contents and installed entry points without VASP input."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from vasp_deb import PackagingError, __version__, builder, cli
from vasp_deb.resources import profile_file, profile_text

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PackageInterfaceTests(unittest.TestCase):
    def test_installed_metadata_and_cli_share_the_version(self):
        self.assertEqual(importlib.metadata.version("vasp-deb"), __version__)
        output = subprocess.check_output([sys.executable, "-m", "vasp_deb", "--version"], text=True)
        self.assertEqual(output.strip(), f"vasp-deb {__version__}")

    def test_unknown_profiles_are_rejected(self):
        with self.assertRaises(PackagingError):
            profile_text("../private")

    def test_profile_and_custom_mapping_are_mutually_exclusive(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "vasp_deb",
                "doctor",
                "--dependency-profile",
                "debian13-gnu",
                "--shlibs-local",
                "custom.shlibs",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)

    def test_recovery_preserves_a_profile_name_and_uses_module_entry_point(self):
        args = cli.parser().parse_args(
            [
                "package",
                "bin",
                "--upstream-version",
                "6.5.0",
                "--dependency-profile",
                "debian13-gnu",
            ]
        )
        with profile_file("debian13-gnu") as resource:
            args.shlibs_local = resource
            command = builder.recovery_command(args, Path("/retained/bin"), "6.5.0")
        self.assertEqual(command[:4], [sys.executable, "-m", "vasp_deb", "package"])
        self.assertIn("--dependency-profile", command)
        self.assertIn("debian13-gnu", command)
        self.assertNotIn("--shlibs-local", command)


@unittest.skipUnless(
    all(importlib.util.find_spec(name) for name in ("build", "hatchling", "pip")),
    "install the dev extra and pip to test distribution artifacts",
)
class DistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="vasp-deb-distribution-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        project = cls.root / "checkout"
        project.mkdir()
        # Copy only this helper's public source, then add synthetic private
        # artifacts to prove that the distribution allowlists exclude them.
        for name in (
            "src",
            "tests",
            "examples",
            "docs",
            "mkdocs.yml",
            "pyproject.toml",
            "README.md",
            "LICENSE",
            ".gitignore",
            ".pre-commit-config.yaml",
        ):
            source = PROJECT_ROOT / name
            target = project / name
            if source.is_dir():
                shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copyfile(source, target)
        for name in (
            "dist/private.deb",
            "reference/private.tgz",
            ".venv/private.txt",
            ".work/private.txt",
            "build.log",
            "private.txt",
            "src/vasp_deb/data/verification/silicon/POTCAR",
        ):
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("Synthetic exclusion sentinel; contains no VASP material.\n")
        output = cls.root / "artifacts"
        result = subprocess.run(
            [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(output)],
            cwd=project,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.wheel = next(output.glob("*.whl"))
        cls.sdist = next(output.glob("*.tar.gz"))
        environment = cls.root / "fresh-environment"
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(environment)], check=True
        )
        cls.installed_python = environment / "bin/python"
        cls.installed_command = environment / "bin/vasp-deb"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "--python",
                str(cls.installed_python),
                "install",
                "--no-index",
                "--no-deps",
                "--disable-pip-version-check",
                str(cls.wheel),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.unrelated_directory = cls.root / "unrelated-directory"
        cls.unrelated_directory.mkdir()

    def assert_no_private_artifacts(self, names):
        for name in names:
            parts = Path(name).parts
            self.assertFalse(
                {"dist", "reference", ".venv", ".work", "__pycache__"} & set(parts), name
            )
            self.assertFalse(name.endswith((".deb", ".tgz", ".log", ".pyc", "private.txt")), name)
            self.assertFalse(Path(name).name.startswith("POTCAR"), name)

    def test_wheel_contains_code_profile_license_and_entry_point(self):
        with zipfile.ZipFile(self.wheel) as archive:
            names = archive.namelist()
            self.assert_no_private_artifacts(names)
            self.assertIn("vasp_deb/cli.py", names)
            self.assertIn("vasp_deb/verification.py", names)
            for name in ("INCAR", "POSCAR", "KPOINTS"):
                self.assertIn(f"vasp_deb/data/verification/silicon/{name}", names)
            self.assertIn("vasp_deb/data/profiles/debian13-gnu.shlibs", names)
            entries = next(name for name in names if name.endswith("/entry_points.txt"))
            self.assertIn("vasp-deb = vasp_deb.cli:main", archive.read(entries).decode())
            self.assertTrue(any(name.endswith("/licenses/LICENSE") for name in names))

    def test_sdist_is_clean_and_contains_build_inputs(self):
        with tarfile.open(self.sdist) as archive:
            names = archive.getnames()
        self.assert_no_private_artifacts(names)
        self.assertTrue(any(name.endswith("/pyproject.toml") for name in names))
        self.assertTrue(any(name.endswith("/src/vasp_deb/_version.py") for name in names))
        self.assertTrue(any(name.endswith("/tests/test_vasp_deb.py") for name in names))
        self.assertTrue(any(name.endswith("/docs/index.md") for name in names))
        self.assertTrue(any(name.endswith("/mkdocs.yml") for name in names))
        self.assertTrue(any(name.endswith("/.pre-commit-config.yaml") for name in names))
        self.assertTrue(any(name.endswith("/examples/silicon_smoke.py") for name in names))

    def test_installed_wheel_works_outside_the_checkout(self):
        for command in (
            [str(self.installed_command), "--version"],
            [str(self.installed_python), "-I", "-m", "vasp_deb", "--version"],
        ):
            output = subprocess.check_output(command, cwd=self.unrelated_directory, text=True)
            self.assertEqual(output.strip(), f"vasp-deb {__version__}")
        script = (
            "import json; from vasp_deb.resources import profile_text; "
            "from vasp_deb.cli import parser; "
            "print(json.dumps({'profile': profile_text('debian13-gnu'), "
            "'output_dir': str(parser().parse_args(['package', 'bin', "
            "'--upstream-version', '6.5.0']).output_dir)}))"
        )
        output = subprocess.check_output(
            [str(self.installed_python), "-I", "-c", script],
            cwd=self.unrelated_directory,
            text=True,
        )
        values = json.loads(output)
        self.assertIn("libstdc++ 6 libstdc++6", values["profile"])
        self.assertEqual(values["output_dir"], "dist")

    def test_installed_verification_runs_outside_the_checkout(self):
        potential = self.root / "POTCAR"
        potential.write_text("TITEL = PAW_PBE Si synthetic-test-fixture\n")
        executable = self.root / "fake-vasp"
        executable.write_text(
            f"#!{self.installed_python}\n"
            "from pathlib import Path\n"
            "assert 'Si' in Path('POSCAR').read_text()\n"
            "assert 'ENCUT = 300' in Path('INCAR').read_text()\n"
            "assert '1 1 1' in Path('KPOINTS').read_text()\n"
            "Path('OUTCAR').write_text('aborting loop because EDIFF is reached')\n"
            "Path('OSZICAR').write_text('DAV: 12 -12.0 -1E-6 -1E-6\\n'\n"
            "    '1 F= -12.000 E0= -12.001 d E = 0\\n')\n"
        )
        executable.chmod(0o700)
        for command in (
            [str(self.installed_command)],
            [str(self.installed_python), "-I", "-m", "vasp_deb"],
        ):
            result = subprocess.run(
                [*command, "verify", str(potential), "--executable", str(executable)],
                cwd=self.unrelated_directory,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS: Si2 SCF converged", result.stdout)
        runs = list((self.unrelated_directory / ".work").iterdir())
        self.assertEqual(len(runs), 2)
        self.assertTrue(all((run / "inputs.json").is_file() for run in runs))
