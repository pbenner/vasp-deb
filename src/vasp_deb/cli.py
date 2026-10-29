"""Command line interface for local VASP-to-Debian packaging."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
import tempfile
from collections.abc import Sequence
from contextlib import ExitStack
from pathlib import Path

from . import builder, verification
from ._version import __version__
from .errors import PackagingError
from .resources import PROFILE_NAMES, profile_file


def _dependency_options(command: argparse.ArgumentParser) -> None:
    mappings = command.add_mutually_exclusive_group()
    mappings.add_argument(
        "--dependency-profile",
        choices=PROFILE_NAMES,
        help="use a bundled runtime mapping (must match the build and target stack)",
    )
    mappings.add_argument(
        "--shlibs-local",
        type=Path,
        help="use a custom shlibs mapping file for dependency discovery",
    )


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(
        prog="vasp-deb",
        description="Build private Debian packages from a local VASP archive or existing binaries.",
    )
    cli.add_argument("--version", action="version", version=f"vasp-deb {__version__}")
    commands = cli.add_subparsers(dest="command", required=True)
    diagnostic = commands.add_parser("doctor", help="check the Debian GNU build environment")
    _dependency_options(diagnostic)
    verify = commands.add_parser(
        "verify", help="run a small silicon SCF calculation using a local Si PAW-PBE POTCAR"
    )
    verify.add_argument("potcar", type=Path, help="uncompressed, standard Si PAW-PBE POTCAR")
    verify.add_argument("--executable", default="vasp_gam", help="VASP command (default: vasp_gam)")
    verify.add_argument("--timeout", type=int, default=120, help="wall time limit in seconds")
    verify.add_argument(
        "--work-dir", type=Path, default=Path(".work"), help="parent for private verification runs"
    )
    for name in ("build", "package"):
        command = commands.add_parser(
            name,
            help="build from a local source archive"
            if name == "build"
            else "package existing native VASP binaries",
        )
        if name == "build":
            command.add_argument("archive", type=Path)
            command.add_argument(
                "--makefile-include", type=Path, help="complete custom compiler configuration"
            )
            command.add_argument("--make-var", action="append", default=[], metavar="NAME=VALUE")
            command.add_argument("--jobs", "-j", type=int, default=min(os.cpu_count() or 1, 4))
        else:
            command.add_argument(
                "bin_dir", type=Path, help="binary directory or archive containing bin/vasp_*"
            )
            command.add_argument(
                "--bundle-runtime",
                action="append",
                default=[],
                metavar="DIRECTORY",
                help="include a sibling runtime directory (e.g. hpc_sdk), preserving relative paths",
            )
            command.add_argument(
                "--mpi-prefix",
                metavar="RELATIVE_PATH",
                help="Open MPI prefix within a bundled runtime; generate relocation-aware launchers",
            )
        command.add_argument("--upstream-version")
        command.add_argument("--revision", default="local1")
        command.add_argument(
            "--package-name",
            default="vasp",
            help="Debian package name prefix; the upstream version is appended (default: vasp)",
        )
        command.add_argument(
            "--access-group",
            help="authorized Unix group (default: versioned name with punctuation changed to '-'); "
            "created on installation",
        )
        command.add_argument("--maintainer", default="Local administrator <root@localhost>")
        command.add_argument(
            "--variants", nargs="+", choices=builder.VARIANTS, default=list(builder.VARIANTS)
        )
        command.add_argument(
            "--output-dir",
            type=Path,
            default=Path("dist"),
            help="package/log directory (default: ./dist)",
        )
        command.add_argument(
            "--work-dir", type=Path, help="parent for the private temporary workspace"
        )
        command.add_argument(
            "--keep-work",
            action="store_true",
            help="retain successful workspaces too; failures always retain them",
        )
        command.add_argument("--overwrite", action="store_true")
        command.add_argument(
            "--depends", action="append", default=[], help="additional Debian dependency expression"
        )
        command.add_argument(
            "--no-auto-depends",
            action="store_true",
            help="use explicit --depends instead of scanning libraries",
        )
        _dependency_options(command)
        command.add_argument("--library-dir", type=Path, action="append", default=[])
        command.add_argument(
            "--copyright-file", type=Path, help="complete upstream copyright/license notice"
        )
    return cli


def doctor(args: argparse.Namespace) -> int:
    checks = [
        (name, builder.shutil.which(name) is not None)
        for name in ("dpkg", "dpkg-deb", "dpkg-shlibdeps")
    ]
    checks.extend(builder.gnu_requirements())
    checks.append(("Python tarfile extraction filter", hasattr(builder.tarfile, "data_filter")))
    for name, present in checks:
        print(f"{'OK     ' if present else 'MISSING'} {name}")
    metadata_ok = True
    if all(builder.shutil.which(name) for name in ("g++", "dpkg-shlibdeps")):
        with tempfile.TemporaryDirectory(prefix="vasp-deb-doctor-") as folder:
            work = Path(folder)
            settings = argparse.Namespace(
                command="package",
                package_name="vasp-deb-probe",
                maintainer="Local administrator <root@localhost>",
                no_auto_depends=False,
                depends=[],
                library_dir=[],
                shlibs_local=args.shlibs_local,
            )
            with (work / "doctor.log").open("w") as log:
                try:
                    builder.dependency_preflight(settings, work, log)
                    print("OK      GNU runtime dependency metadata")
                except (PackagingError, OSError) as error:
                    metadata_ok = False
                    print(f"MISSING GNU runtime dependency metadata:\n{error}")
    if not all(present for _, present in checks):
        print(
            "\nDebian GNU build prerequisites:\n"
            "sudo apt install build-essential gfortran openmpi-bin libopenmpi-dev "
            "libopenblas-dev libscalapack-openmpi-dev libfftw3-dev rsync dpkg-dev python3"
        )
    else:
        print("\nCompiler and library build prerequisites are available.")
    if not metadata_ok:
        print("Automatic dependency discovery still needs installed symbols/shlibs metadata.")
        if not args.shlibs_local:
            print(
                "If the build/target stack is Debian 13 with GCC/GFortran 14 and OpenMPI 5, "
                "test its explicit mapping with:"
            )
            print(
                shlex.join(
                    [
                        sys.executable,
                        "-m",
                        "vasp_deb",
                        "doctor",
                        "--dependency-profile",
                        "debian13-gnu",
                    ]
                )
            )
            print(
                "For builds, add the same --dependency-profile option. "
                "This declares package mappings; it does not repair dpkg's database."
            )
    return 0 if metadata_ok and all(present for _, present in checks) else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run the installed command or module entry point."""
    args = parser().parse_args(argv)
    try:
        if args.command == "verify":
            return verification.verify(
                args.potcar,
                executable=args.executable,
                timeout=args.timeout,
                work_dir=args.work_dir,
            )
        with ExitStack() as resources:
            if args.dependency_profile:
                args.shlibs_local = resources.enter_context(profile_file(args.dependency_profile))
            if args.command == "doctor":
                return doctor(args)
            builder.package(args)
            return 0
    except (PackagingError, OSError) as error:
        print(f"vasp-deb: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("vasp-deb: interrupted", file=sys.stderr)
        return 130
