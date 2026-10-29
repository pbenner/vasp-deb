from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vasp_deb import builder as tool
from vasp_deb import cli
from vasp_deb.payload import copy_runtime, extract_binaries
from vasp_deb.resources import profile_text


class ArchiveTests(unittest.TestCase):
    def test_version_detection_and_explicit_fallback(self):
        for archive, directory, expected in [
            ("vasp.6.5.0.tgz", "source", "6.5.0"),
            ("download.tar.xz", "vasp.6.6.1", "6.6.1"),
            ("vasp-7.1.2~rc1.tar.gz", "source", "7.1.2~rc1"),
            ("vasp-6.6.0-gpu-a_h_100.tar.gz", "source", "6.6.0"),
        ]:
            self.assertEqual(tool.infer_version(Path(archive), Path(directory)), expected)
        with self.assertRaisesRegex(tool.PackagingError, "upstream-version"):
            tool.infer_version(Path("download.tar.gz"), Path("source"))

    def test_rejects_traversal_absolute_names_links_and_devices(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for index, (name, kind, link) in enumerate(
                [
                    ("../escape", tarfile.REGTYPE, ""),
                    (str(root / "absolute"), tarfile.REGTYPE, ""),
                    ("link", tarfile.SYMTYPE, "../../escape"),
                    ("link", tarfile.LNKTYPE, "../../escape"),
                    ("device", tarfile.CHRTYPE, ""),
                ]
            ):
                archive = root / f"bad-{index}.tar"
                with tarfile.open(archive, "w") as handle:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    member.linkname = link
                    handle.addfile(member)
                with self.assertRaises((tool.PackagingError, tarfile.TarError)):
                    tool.extract_source(archive, root / f"unpack-{index}")
                # Selected binary archives receive the same path protection.
                if index < 2:
                    with self.assertRaises((tool.PackagingError, tarfile.TarError)):
                        extract_binaries(archive, root / f"binary-unpack-{index}", [])
            self.assertFalse((root / "escape").exists())
            self.assertFalse((root / "absolute").exists())

    def test_unambiguous_source_root_is_required(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "ambiguous.tar"
            with tarfile.open(archive, "w") as handle:
                for prefix in ("one", "two"):
                    directory = tarfile.TarInfo(prefix + "/src")
                    directory.type = tarfile.DIRTYPE
                    handle.addfile(directory)
                    handle.addfile(tarfile.TarInfo(prefix + "/Makefile"))
            with self.assertRaisesRegex(tool.PackagingError, "one VASP source root"):
                tool.extract_source(archive, root / "unpacked")

    def test_profile_uses_supplied_release_template_and_explicit_overrides(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            (source / "arch").mkdir()
            (source / "arch/makefile.include.gnu").write_text(
                "# Synthetic configuration, not a VASP template\n"
                "FFLAGS = -O2 -march=native\nLLIBS = $(SCALAPACK) $(BLASPACK) -lfftw3\n"
            )
            args = cli.parser().parse_args(["build", "unused.tgz", "--make-var", "FFLAGS=-O1"])
            with patch.object(tool, "gnu_requirements", return_value=[]):
                config = tool.configure(source, args).read_text()
            self.assertIn("Synthetic configuration", config)
            self.assertNotIn("-march=native", config)
            self.assertIn("SCALAPACK = -lscalapack-openmpi", config)
            self.assertTrue(config.rstrip().endswith("FFLAGS = -O1"))

    def test_metadata_rejects_control_field_injection(self):
        args = cli.parser().parse_args(
            [
                "package",
                "unused",
                "--upstream-version",
                "6.5.0",
                "--maintainer",
                "Someone <x@example.org>\nDepends: injected",
            ]
        )
        with self.assertRaisesRegex(tool.PackagingError, "single line"):
            tool.package(args)

    def test_doctor_distinguishes_metadata_failure_from_missing_build_tools(self):
        args = cli.parser().parse_args(["doctor"])
        output = io.StringIO()
        with (
            patch.object(tool, "gnu_requirements", return_value=[("g++", True)]),
            patch.object(tool.shutil, "which", return_value="/usr/bin/present"),
            patch.object(
                tool,
                "dependency_preflight",
                side_effect=tool.PackagingError("missing libstdc++ metadata"),
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(cli.doctor(args), 1)
        text = output.getvalue()
        self.assertIn("build prerequisites are available", text)
        self.assertIn("doctor --dependency-profile", text)
        self.assertIn("debian13-gnu", text)
        self.assertNotIn("sudo apt install", text)

    def test_bundle_options_reject_unsafe_paths_and_implicit_dependencies(self):
        for options, message in [
            (["--bundle-runtime", "../private"], "sibling directory"),
            (
                ["--bundle-runtime", "hpc_sdk", "--mpi-prefix", "hpc_sdk/../../outside"],
                "relative path",
            ),
            (["--bundle-runtime", "hpc_sdk"], "explicit --depends"),
        ]:
            args = cli.parser().parse_args(
                ["package", "unused", "--upstream-version", "6.6.0", *options]
            )
            with self.assertRaisesRegex(tool.PackagingError, message):
                tool.package(args)


@unittest.skipUnless(
    all(shutil.which(name) for name in ("cc", "make", "dpkg", "dpkg-deb")),
    "native C compiler, make and Debian tools are required",
)
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="vasp-deb-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "custom makefile.include"
        self.config.write_text("CC = cc\nCFLAGS = -O0\n")

    def make_archive(self, version="6.5.0", broken=False, gnu_template=False):
        source = self.root / "fixtures" / f"vasp.{version}"
        (source / "src").mkdir(parents=True)
        (source / "src/main.c").write_text(
            '#include <stdio.h>\nint main(void) { puts("synthetic fixture"); return 0; }\n'
        )
        (source / "src/POTCAR").write_text("Synthetic excluded payload, not a potential dataset.\n")
        if gnu_template:
            (source / "arch").mkdir()
            (source / "arch/makefile.include.gnu").write_text("CC = cc\nCFLAGS = -O0\n")
        (source / "Makefile").write_text(
            "include makefile.include\n.PHONY: std gam ncl\nstd gam ncl:\n"
            + (
                "\tfalse\n"
                if broken
                else "\tmkdir -p bin\n\t$(CC) $(CFLAGS) src/main.c -o bin/vasp_$@\n"
            )
        )
        archive = self.root / f"vasp.{version}.tgz"
        with tarfile.open(archive, "w:gz") as handle:
            handle.add(source, arcname=source.name)
        return archive

    def invoke(self, arguments, success=True):
        if "--work-dir" not in arguments:
            arguments = [*arguments, "--work-dir", self.root / "work"]
        result = subprocess.run(
            [sys.executable, "-m", "vasp_deb", *map(str, arguments)], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0 if success else 1, result.stdout + result.stderr)
        return result

    def build_arguments(self, archive):
        return [
            "build",
            archive,
            "--makefile-include",
            self.config,
            "--output-dir",
            self.root / "private output",
            "--work-dir",
            self.root / "work",
            "--no-auto-depends",
            "--depends",
            "libc6 (>= 2.34)",
            "--jobs",
            "2",
        ]

    def inspect(self, archive, upstream):
        packages = sorted((self.root / "private output").glob(f"*_{upstream}-local1_*.deb"))
        self.assertEqual(len(packages), 1)
        package = packages[0]
        self.assertEqual(package.stat().st_mode & 0o777, 0o600)
        for key, expected in [
            ("Package", f"vasp-{upstream}"),
            ("Version", upstream + "-local1"),
            ("Depends", "adduser, libc6 (>= 2.34)"),
        ]:
            actual = subprocess.check_output(
                ["dpkg-deb", "--field", package, key], text=True
            ).strip()
            self.assertEqual(actual, expected)
        tar_bytes = subprocess.check_output(["dpkg-deb", "--fsys-tarfile", package])
        with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as payload:
            members = payload.getmembers()
            self.assertTrue(all(member.uid == 0 and member.gid == 0 for member in members))
            names = [member.name for member in members]
            self.assertTrue(any(name.endswith(f"usr/bin/vasp_std-{upstream}") for name in names))
            self.assertFalse(
                any(name.endswith(("main.c", "POTCAR", "makefile.include")) for name in names)
            )
            info_name = next(name for name in names if name.endswith("build-info.json"))
            info = json.load(payload.extractfile(info_name))
        self.assertEqual(info["source_sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
        self.assertEqual(info["access_group"], "vasp-" + upstream.replace(".", "-"))
        private_member = next(m for m in members if m.name == f"./usr/lib/vasp-{upstream}")
        self.assertEqual(private_member.mode, 0o700)
        extracted = self.root / f"installed-{upstream}"
        subprocess.run(["dpkg-deb", "--extract", package, extracted], check=True)
        actual = subprocess.check_output([extracted / f"usr/bin/vasp_std-{upstream}"], text=True)
        self.assertEqual(actual, "synthetic fixture\n")
        for variant in tool.VARIANTS:
            binary = extracted / f"usr/lib/vasp-{upstream}/bin/vasp_{variant}"
            self.assertEqual(info["binaries_sha256"][binary.name], tool.digest(binary))
        self.assertFalse(any((self.root / "work").iterdir()))
        self.assertTrue(
            all(
                log.stat().st_mode & 0o777 == 0o600
                for log in (self.root / "private output").glob("*.log")
            )
        )
        return package, extracted

    def test_builds_real_deb_for_multiple_versions_and_preserves_inputs(self):
        for upstream in ("6.5.0", "6.6.1"):
            archive = self.make_archive(upstream)
            initial = tool.digest(archive)
            self.invoke(self.build_arguments(archive))
            self.inspect(archive, upstream)
            self.assertEqual(tool.digest(archive), initial)

    @unittest.skipUnless(shutil.which("fakeroot"), "fakeroot is required")
    def test_dpkg_coinstallation_upgrade_and_removal_are_independent(self):
        packages = []
        for upstream in ("6.5.0", "6.6.0"):
            self.invoke(self.build_arguments(self.make_archive(upstream)))
            packages.append(next((self.root / "private output").glob(f"*_{upstream}-*.deb")))
        installed = self.root / "dpkg-root"
        (installed / "var/lib/dpkg").mkdir(parents=True)
        (installed / "var/lib/dpkg/status").touch()

        def dpkg(*arguments):
            subprocess.run(
                ["fakeroot", "dpkg", f"--root={installed}", *map(str, arguments)],
                check=True,
                capture_output=True,
                text=True,
            )

        dpkg("--unpack", *packages)
        old = installed / "usr/bin/vasp_std-6.5.0"
        new = installed / "usr/bin/vasp_std-6.6.0"
        self.assertEqual(subprocess.check_output([old]), b"synthetic fixture\n")
        self.assertEqual(subprocess.check_output([new]), b"synthetic fixture\n")
        self.invoke([*self.build_arguments(self.root / "vasp.6.6.0.tgz"), "--revision", "local2"])
        upgraded = next((self.root / "private output").glob("*_6.6.0-local2_*.deb"))
        dpkg("--unpack", upgraded)
        self.assertTrue(old.is_file())
        dpkg("--remove", "vasp-6.5.0")
        self.assertFalse(old.exists())
        self.assertEqual(subprocess.check_output([new]), b"synthetic fixture\n")

    def test_group_configuration_is_fail_closed_and_repeatable(self):
        self.invoke([*self.build_arguments(self.make_archive()), "--access-group", "vasp-licensed"])
        package = next((self.root / "private output").glob("*.deb"))
        control = self.root / "control"
        subprocess.run(["dpkg-deb", "--control", package, control], check=True)
        script = control / "postinst"
        subprocess.run(["sh", "-n", script], check=True)
        payload = self.root / "payload"
        subprocess.run(["dpkg-deb", "--extract", package, payload], check=True)
        private = payload / "usr/lib/vasp-6.5.0"
        self.assertEqual(private.stat().st_mode & 0o777, 0o700)
        stubs = self.root / "stubs"
        stubs.mkdir()
        events = self.root / "events"
        group = self.root / "group-created"
        scripts = {
            "getent": f"test -f {shlex.quote(str(group))}",
            "addgroup": f'echo "addgroup $*" >> "$EVENTS"; touch {shlex.quote(str(group))}',
            "chown": 'echo "chown $*" >> "$EVENTS"; test "${FAIL_CHOWN:-0}" = 0',
            "chmod": 'echo "chmod $*" >> "$EVENTS"; /bin/chmod "$1" "$PRIVATE"',
        }
        for name, body in scripts.items():
            path = stubs / name
            path.write_text("#!/bin/sh\n" + body + "\n")
            path.chmod(0o755)
        env = {
            **os.environ,
            "PATH": f"{stubs}:/usr/bin:/bin",
            "EVENTS": str(events),
            "PRIVATE": str(private),
        }
        failure = subprocess.run(["sh", script, "configure"], env={**env, "FAIL_CHOWN": "1"})
        self.assertNotEqual(failure.returncode, 0)
        self.assertEqual(private.stat().st_mode & 0o777, 0o700)
        for _ in range(2):
            subprocess.run(["sh", script, "configure"], env=env, check=True)
        self.assertEqual(private.stat().st_mode & 0o777, 0o750)
        log = events.read_text()
        self.assertEqual(log.count("addgroup --system vasp-licensed"), 1)
        self.assertIn("chown root:vasp-licensed /usr/lib/vasp-6.5.0", log)
        # Scripts configure access only; no user membership or removal scripts.
        self.assertFalse((control / "postrm").exists())

    def test_prebuilt_archive_preserves_runtime_and_relocates_mpi_launchers(self):
        source = self.root / "gpu/vasp.6.6.0"
        binaries = source / "bin"
        binaries.mkdir(parents=True)
        runtime = source / "hpc_sdk"
        (runtime / "lib").mkdir(parents=True)
        (runtime / "bin").mkdir()
        code = self.root / "library.c"
        code.write_text("int runtime_value(void) { return 42; }\n")
        subprocess.run(
            [
                "cc",
                "-shared",
                "-fPIC",
                code,
                "-Wl,-soname,libfixture.so.1",
                "-o",
                runtime / "lib/libfixture.so.1",
            ],
            check=True,
        )
        (runtime / "lib/libfixture.so").symlink_to("libfixture.so.1")
        main = self.root / "main.c"
        main.write_text(
            '#include <stdio.h>\n#include <stdlib.h>\nint runtime_value(void);\nint main(void) { printf("%d %s\\n", runtime_value(), getenv("OPAL_PREFIX")); return 0; }\n'
        )
        subprocess.run(
            [
                "cc",
                main,
                "-L" + str(runtime / "lib"),
                "-lfixture",
                "-Wl,-rpath,$ORIGIN/../hpc_sdk/lib",
                "-o",
                binaries / "vasp_std",
            ],
            check=True,
        )
        mpirun = runtime / "bin/mpirun"
        mpirun.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$OPAL_PREFIX" "$PMIX_PREFIX" "$PRTE_PREFIX" "$@"\n'
        )
        mpirun.chmod(0o755)
        (source / "src").mkdir()
        (source / "src/private.F").write_text("Synthetic source exclusion sentinel")
        (source / "POTCAR").write_text("Synthetic potential exclusion sentinel")
        archive = self.root / "vasp-6.6.0-gpu-a_h_100.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            handle.add(source, arcname=source.name)
        self.invoke(
            [
                "package",
                archive,
                "--variants",
                "std",
                "--bundle-runtime",
                "hpc_sdk",
                "--mpi-prefix",
                "hpc_sdk",
                "--no-auto-depends",
                "--depends",
                "libc6",
                "--output-dir",
                self.root / "gpu-deb",
            ]
        )
        package = next((self.root / "gpu-deb").glob("*.deb"))
        relocated = self.root / "relocated with spaces"
        subprocess.run(["dpkg-deb", "--extract", package, relocated], check=True)
        private = relocated / "usr/lib/vasp-6.6.0"
        self.assertEqual(tool.digest(private / "bin/vasp_std"), tool.digest(binaries / "vasp_std"))
        self.assertTrue((private / "hpc_sdk/lib/libfixture.so").is_symlink())
        expected_prefix = str(private / "hpc_sdk")
        output = subprocess.check_output([relocated / "usr/bin/vasp_std-6.6.0"], text=True)
        self.assertEqual(output, f"42 {expected_prefix}\n")
        output = subprocess.check_output(
            [relocated / "usr/bin/vasp_mpirun-6.6.0", "two words"], text=True
        )
        self.assertEqual(output.splitlines(), [expected_prefix] * 3 + ["two words"])
        self.assertFalse(list(relocated.rglob("private.F")))
        self.assertFalse(list(relocated.rglob("POTCAR")))
        info = json.loads((relocated / "usr/share/doc/vasp-6.6.0/build-info.json").read_text())
        self.assertEqual(info["binary_archive_sha256"], tool.digest(archive))
        self.assertEqual(info["bundled_runtimes"], ["hpc_sdk"])

    def test_runtime_links_cannot_escape_or_point_to_missing_files(self):
        runtime = self.root / "runtime"
        runtime.mkdir()
        outside = self.root / "outside"
        outside.write_text("private")
        link = runtime / "link"
        link.symlink_to("../outside")
        with self.assertRaisesRegex(tool.PackagingError, "stay within"):
            copy_runtime(runtime, self.root / "copied")
        link.unlink()
        link.symlink_to("missing")
        with self.assertRaisesRegex(tool.PackagingError, "broken runtime link"):
            copy_runtime(runtime, self.root / "copied")

    def test_existing_output_is_not_overwritten_without_request(self):
        archive = self.make_archive()
        arguments = self.build_arguments(archive)
        self.invoke(arguments)
        package = next((self.root / "private output").glob("*.deb"))
        original = package.read_bytes()
        result = self.invoke(arguments, success=False)
        self.assertIn("output exists", result.stderr)
        self.assertEqual(package.read_bytes(), original)
        self.invoke([*arguments, "--overwrite"])

    def test_build_discards_preexisting_objects_and_executables(self):
        archive = self.make_archive()
        source = self.root / "fixtures/vasp.6.5.0"
        (source / "build").mkdir()
        (source / "build/stale.o").write_text("wrong compiler")
        (source / "bin").mkdir()
        (source / "bin/vasp_std").write_text("wrong architecture")
        makefile = source / "Makefile"
        makefile.write_text(
            makefile.read_text().replace(
                "\tmkdir -p bin", "\ttest ! -e build/stale.o\n\tmkdir -p bin"
            )
        )
        with tarfile.open(archive, "w:gz") as handle:
            handle.add(source, arcname=source.name)
        self.invoke(self.build_arguments(archive))
        self.inspect(archive, "6.5.0")

    def test_custom_prefix_keeps_same_release_builds_separate(self):
        archive = self.make_archive()
        for prefix in ("vasp", "vasp-gpu"):
            self.invoke([*self.build_arguments(archive), "--package-name", prefix])
        packages = list((self.root / "private output").glob("*.deb"))
        self.assertEqual(len(packages), 2)
        all_files = []
        for package in packages:
            data = subprocess.check_output(["dpkg-deb", "--fsys-tarfile", package])
            with tarfile.open(fileobj=io.BytesIO(data)) as payload:
                all_files.append({m.name for m in payload if not m.isdir()})
        self.assertFalse(all_files[0] & all_files[1])

    def test_failed_build_preserves_private_workspace_and_log_without_a_package(self):
        result = self.invoke(self.build_arguments(self.make_archive(broken=True)), success=False)
        self.assertIn("build failed", result.stderr)
        self.assertFalse(list((self.root / "private output").glob("*.deb")))
        logs = list((self.root / "private output").glob("*.log"))
        self.assertEqual(len(logs), 1)
        self.assertIn("false", logs[0].read_text())
        workspaces = list((self.root / "work").iterdir())
        self.assertEqual(len(workspaces), 1)
        self.assertEqual(workspaces[0].stat().st_mode & 0o777, 0o700)
        self.assertTrue((workspaces[0] / "source/vasp.6.5.0/Makefile").is_file())
        self.assertIn("Retained private workspace:", result.stdout)

    def test_dependency_preflight_fails_before_upstream_make(self):
        if not shutil.which("g++"):
            self.skipTest("g++ is required")
        archive = self.make_archive(gnu_template=True)
        args = cli.parser().parse_args(
            [
                "build",
                str(archive),
                "--output-dir",
                str(self.root / "preflight"),
                "--work-dir",
                str(self.root / "work"),
            ]
        )
        original_capture = tool.capture

        def missing_metadata(command, log, cwd=None):
            if command[0] == "dpkg-shlibdeps":
                raise tool.PackagingError("no dependency information found for libstdc++.so.6")
            return original_capture(command, log, cwd)

        with (
            patch.object(tool, "gnu_requirements", return_value=[]),
            patch.object(tool, "capture", side_effect=missing_metadata),
            patch.object(tool, "run_build") as upstream_make,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaisesRegex(
                tool.PackagingError, "preflight failed before VASP compilation"
            ):
                tool.package(args)
            upstream_make.assert_not_called()
        self.assertFalse(list((self.root / "preflight").glob("*.deb")))

    def test_existing_binaries_can_be_packaged_with_only_selected_variant(self):
        binaries = self.root / "existing binaries"
        binaries.mkdir()
        source = self.root / "fixture.c"
        source.write_text("int main(void) { return 0; }\n")
        subprocess.run(["cc", source, "-o", binaries / "vasp_std"], check=True)
        self.invoke(
            [
                "package",
                binaries,
                "--upstream-version",
                "7.0.0",
                "--package-name",
                "vasp-custom",
                "--variants",
                "std",
                "--output-dir",
                self.root / "prebuilt",
                "--no-auto-depends",
                "--depends",
                "libc6",
            ]
        )
        package = next((self.root / "prebuilt").glob("*.deb"))
        package_name = subprocess.check_output(
            ["dpkg-deb", "--field", package, "Package"], text=True
        ).strip()
        self.assertEqual(package_name, "vasp-custom-7.0.0")
        tar_bytes = subprocess.check_output(["dpkg-deb", "--fsys-tarfile", package])
        with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as payload:
            names = payload.getnames()
            self.assertTrue(any(name.endswith("/vasp_std") for name in names))
            self.assertFalse(any(name.endswith(("/vasp_gam", "/vasp_ncl")) for name in names))
            self.assertTrue(
                any(
                    name.endswith("/usr/share/doc/vasp-custom-7.0.0/build-info.json")
                    for name in names
                )
            )

    def test_automatic_dependencies_use_actual_dpkg_shlibdeps(self):
        if not shutil.which("dpkg-shlibdeps"):
            self.skipTest("dpkg-shlibdeps is required")
        archive = self.make_archive()
        # The test environment has shared libraries but may lack dpkg's package
        # database. Exercise the real scanner with a local mapping, as supported
        # for vendor libraries; never suppress missing dependency metadata.
        mappings = self.root / "shlibs.local"
        mappings.write_text("libc 6 libc6 (>= 2.34)\n")
        self.invoke(
            [
                "build",
                archive,
                "--makefile-include",
                self.config,
                "--output-dir",
                self.root / "automatic",
                "--variants",
                "std",
                "--shlibs-local",
                mappings,
            ]
        )
        package = next((self.root / "automatic").glob("*.deb"))
        dependencies = subprocess.check_output(
            ["dpkg-deb", "--field", package, "Depends"], text=True
        )
        self.assertIn("libc6 (>= 2.34)", dependencies)

    def test_scripts_and_foreign_elf_binaries_are_rejected(self):
        executable = self.root / "binary"
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        with self.assertRaisesRegex(tool.PackagingError, "ELF executable"):
            tool.validate_elf(executable, "amd64")
        header = bytearray(20)
        header[:6] = b"\x7fELF\x02\x01"
        header[16:20] = b"\x02\x00\xb7\x00"  # AArch64, not amd64
        executable.write_bytes(header)
        with self.assertRaisesRegex(tool.PackagingError, "architecture"):
            tool.validate_elf(executable, "amd64")

    def test_unmapped_runtime_library_fails_without_creating_a_package(self):
        if not shutil.which("dpkg-shlibdeps"):
            self.skipTest("dpkg-shlibdeps is required")
        binaries = self.root / "binaries"
        binaries.mkdir()
        library_source = self.root / "local-library.c"
        library_source.write_text("int local_fixture(void) { return 7; }\n")
        library = binaries / "libvaspdebfixture.so.1"
        subprocess.run(
            [
                "cc",
                "-shared",
                "-fPIC",
                "-Wl,-soname,libvaspdebfixture.so.1",
                library_source,
                "-o",
                library,
            ],
            check=True,
        )
        main_source = self.root / "caller.c"
        main_source.write_text(
            "int local_fixture(void); int main(void) { return local_fixture(); }\n"
        )
        subprocess.run(["cc", main_source, library, "-o", binaries / "vasp_std"], check=True)
        mappings = self.root / "shlibs.local"
        mappings.write_text("libc 6 libc6 (>= 2.34)\n")
        output = self.root / "unmapped"
        result = self.invoke(
            [
                "package",
                binaries,
                "--upstream-version",
                "6.5.0",
                "--variants",
                "std",
                "--output-dir",
                output,
                "--library-dir",
                binaries,
                "--shlibs-local",
                mappings,
            ],
            success=False,
        )
        self.assertIn(
            "dependency detection needs debian library package metadata", result.stderr.lower()
        )
        self.assertFalse(list(output.glob("*.deb")))
        workspaces = list((self.root / "work").iterdir())
        self.assertEqual(len(workspaces), 1)
        preserved = workspaces[0] / "package/usr/lib/vasp-6.5.0/bin"
        self.assertEqual(tool.digest(preserved / "vasp_std"), tool.digest(binaries / "vasp_std"))
        self.assertIn("Retry packaging without recompiling", result.stdout)
        self.assertIn(str(preserved), result.stdout)
        # Repair just the declared mapping and finish packaging the preserved
        # executable. No source extraction, compiler or make invocation is needed.
        mappings.write_text("libc 6 libc6 (>= 2.34)\nlibvaspdebfixture 1 libvaspdebfixture1\n")
        self.invoke(
            [
                "package",
                preserved,
                "--upstream-version",
                "6.5.0",
                "--variants",
                "std",
                "--output-dir",
                output,
                "--library-dir",
                binaries,
                "--shlibs-local",
                mappings,
            ]
        )
        package = next(output.glob("*.deb"))
        dependencies = subprocess.check_output(
            ["dpkg-deb", "--field", package, "Depends"], text=True
        )
        self.assertIn("libvaspdebfixture1", dependencies)

    def test_debian13_mapping_covers_real_cpp_runtime_and_records_provenance(self):
        if not all(shutil.which(name) for name in ("g++", "dpkg-shlibdeps")):
            self.skipTest("g++ and dpkg-shlibdeps are required")
        source = self.root / "runtime.cpp"
        source.write_text("int main() { return 0; }\n")
        binaries = self.root / "cpp-bin"
        binaries.mkdir()
        subprocess.run(
            ["g++", source, "-Wl,--no-as-needed", "-o", binaries / "vasp_std"], check=True
        )
        mapping = self.root / "debian13-gnu.shlibs"
        mapping.write_text(profile_text("debian13-gnu"))
        output = self.root / "mapped"
        self.invoke(
            [
                "package",
                binaries,
                "--upstream-version",
                "6.5.0",
                "--variants",
                "std",
                "--output-dir",
                output,
                "--shlibs-local",
                mapping,
            ]
        )
        package = next(output.glob("*.deb"))
        dependencies = subprocess.check_output(
            ["dpkg-deb", "--field", package, "Depends"], text=True
        )
        self.assertIn("libstdc++6 (>= 14)", dependencies)
        contents = subprocess.check_output(["dpkg-deb", "--fsys-tarfile", package])
        with tarfile.open(fileobj=io.BytesIO(contents)) as payload:
            path = next(name for name in payload.getnames() if name.endswith("build-info.json"))
            info = json.load(payload.extractfile(path))
        self.assertEqual(info["dependency_mode"], "explicit-shlibs")
        self.assertEqual(info["shlibs_local_sha256"], tool.digest(mapping))

    def test_bundled_profile_packages_from_another_working_directory(self):
        if not all(shutil.which(name) for name in ("g++", "dpkg-shlibdeps")):
            self.skipTest("g++ and dpkg-shlibdeps are required")
        source = self.root / "runtime.cpp"
        source.write_text("int main() { return 0; }\n")
        binaries = self.root / "cpp-bin"
        binaries.mkdir()
        subprocess.run(
            ["g++", source, "-Wl,--no-as-needed", "-o", binaries / "vasp_std"], check=True
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "vasp_deb",
                "package",
                str(binaries),
                "--upstream-version",
                "6.5.0",
                "--variants",
                "std",
                "--dependency-profile",
                "debian13-gnu",
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        package = next((self.root / "dist").glob("*.deb"))
        contents = subprocess.check_output(["dpkg-deb", "--fsys-tarfile", package])
        with tarfile.open(fileobj=io.BytesIO(contents)) as payload:
            path = next(name for name in payload.getnames() if name.endswith("build-info.json"))
            info = json.load(payload.extractfile(path))
        self.assertEqual(info["dependency_mode"], "bundled-profile")
        self.assertEqual(info["dependency_profile"], "debian13-gnu")

    def test_relative_workspace_on_python_before_312(self):
        if not shutil.which("dpkg-shlibdeps"):
            self.skipTest("dpkg-shlibdeps is required")
        archive = self.make_archive()
        mapping = self.root / "shlibs.local"
        mapping.write_text("libc 6 libc6 (>= 2.34)\n")
        args = cli.parser().parse_args(
            [*map(str, self.build_arguments(archive)), "--work-dir", "relative-work"]
        )
        args.no_auto_depends = False
        args.depends = []
        args.shlibs_local = mapping
        mkdtemp = tempfile.mkdtemp

        def relative_mkdtemp(*positional, **keywords):
            # Python 3.11 can return a relative path when dir is relative.
            return os.path.relpath(mkdtemp(*positional, **keywords))

        with (
            contextlib.chdir(self.root),
            patch.object(tool.tempfile, "mkdtemp", relative_mkdtemp),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            package = tool.package(args)
        self.assertTrue(package.is_file())
        self.assertFalse(any((self.root / "relative-work").iterdir()))

    def test_debian13_mapping_covers_gnu_mpi_fortran_math_stack(self):
        if not shutil.which("dpkg-shlibdeps") or not all(
            present for _, present in tool.gnu_requirements()
        ):
            self.skipTest("the complete GNU/OpenMPI math toolchain is required")
        source = self.root / "runtime.f90"
        source.write_text("program probe\nimplicit none\nend program probe\n")
        binaries = self.root / "gnu-bin"
        binaries.mkdir()
        libraries = ["-lstdc++", "-lscalapack-openmpi", "-lopenblas", "-lfftw3"]
        mvec = subprocess.check_output(
            ["gfortran", "-print-file-name=libmvec.so"], text=True
        ).strip()
        if mvec != "libmvec.so" and Path(mvec).is_file():
            libraries.append("-lmvec")
        subprocess.run(
            ["mpif90", source, "-Wl,--no-as-needed", *libraries, "-o", binaries / "vasp_std"],
            check=True,
        )
        mapping = self.root / "debian13-gnu.shlibs"
        mapping.write_text(profile_text("debian13-gnu"))
        output = self.root / "gnu-mapped"
        self.invoke(
            [
                "package",
                binaries,
                "--upstream-version",
                "6.5.0",
                "--variants",
                "std",
                "--output-dir",
                output,
                "--shlibs-local",
                mapping,
            ]
        )
        package = next(output.glob("*.deb"))
        dependencies = subprocess.check_output(
            ["dpkg-deb", "--field", package, "Depends"], text=True
        )
        for name in [
            "libstdc++6",
            "libgfortran5",
            "libopenmpi40",
            "libopenblas0",
            "libscalapack-openmpi2.2",
            "libfftw3-double3",
        ]:
            self.assertIn(name, dependencies)


if __name__ == "__main__":
    unittest.main()
