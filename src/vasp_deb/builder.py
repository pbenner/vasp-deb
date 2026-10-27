"""Compilation and Debian package generation for local VASP distributions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import TextIO

from ._version import __version__ as TOOL_VERSION
from .errors import PackagingError

VARIANTS = ("std", "gam", "ncl")
ELF_ARCHITECTURES = {
    "amd64": (62, 2, 1),
    "i386": (3, 1, 1),
    "arm64": (183, 2, 1),
    "armhf": (40, 1, 1),
    "armel": (40, 1, 1),
    "ppc64el": (21, 2, 1),
    "ppc64": (21, 2, 2),
    "riscv64": (243, 2, 1),
    "s390x": (22, 2, 2),
}


def digest(path: Path, algorithm: str = "sha256") -> str:
    result = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def single_line(value: str, name: str) -> str:
    if not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PackagingError(f"{name} must be a nonempty single line")
    return value


def require_commands(commands: list[str]) -> None:
    missing = [name for name in commands if shutil.which(name) is None]
    if missing:
        raise PackagingError(
            "missing commands: " + ", ".join(missing) + "; see README.md or run doctor"
        )


def capture(command: list[str], log: TextIO, cwd: Path | None = None) -> str:
    log.write("\n$ " + shlex.join(command) + "\n")
    log.flush()
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    log.write(result.stdout)
    log.write(result.stderr)
    log.flush()
    if result.returncode:
        details = "\n".join(result.stderr.strip().splitlines()[-8:])
        raise PackagingError(
            f"{command[0]} failed with exit status {result.returncode}"
            + (f":\n{details}" if details else "")
        )
    return result.stdout.strip()


def run_build(command: list[str], source: Path, log: TextIO) -> None:
    log.write("\n$ " + shlex.join(command) + "\n")
    log.flush()
    result = subprocess.run(command, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise PackagingError(f"VASP build failed with exit status {result.returncode}")


def extract_source(archive: Path, destination: Path) -> Path:
    if not hasattr(tarfile, "data_filter"):
        raise PackagingError(
            "Python with tarfile.data_filter is required (Python 3.12+ or a patched 3.11)"
        )
    destination.mkdir(mode=0o700)

    def source_filter(member: tarfile.TarInfo, target: str) -> tarfile.TarInfo | None:
        name = PurePosixPath(member.name)
        if name.is_absolute() or ".." in name.parts:
            raise PackagingError(f"unsafe archive member: {member.name!r}")
        return tarfile.data_filter(member, target)

    with tarfile.open(archive, "r:*") as handle:
        handle.extractall(destination, filter=source_filter)
    candidates = [destination, *(p for p in destination.iterdir() if p.is_dir())]
    roots = [
        p
        for p in candidates
        if (p / "src").is_dir() and any((p / name).is_file() for name in ("makefile", "Makefile"))
    ]
    if len(roots) != 1:
        raise PackagingError(
            "expected one VASP source root containing src/ and makefile or Makefile"
        )
    return roots[0]


def infer_version(archive: Path, source: Path) -> str:
    filename = archive.name
    for suffix in (".tar.gz", ".tar.xz", ".tar.bz2", ".tgz", ".tbz2", ".txz", ".tar"):
        if filename.endswith(suffix):
            filename = filename[: -len(suffix)]
            break
    for name in (source.name, filename):
        match = re.fullmatch(r"vasp[._-](\d+(?:\.\d+)+(?:[+~][A-Za-z0-9.+~]+)?)", name, re.I)
        if match:
            return match.group(1)
    raise PackagingError(
        "cannot detect VASP version from source directory or archive name; use --upstream-version"
    )


def gnu_requirements() -> list[tuple[str, bool]]:
    checks = [
        (name, shutil.which(name) is not None)
        for name in ("make", "rsync", "gcc", "g++", "gfortran", "mpif90")
    ]
    checks.append(
        ("FFTW Fortran header /usr/include/fftw3.f", Path("/usr/include/fftw3.f").is_file())
    )
    for library in ("libfftw3.so", "libopenblas.so", "libscalapack-openmpi.so"):
        path = ""
        if shutil.which("gfortran"):
            result = subprocess.run(
                ["gfortran", "-print-file-name=" + library],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                path = result.stdout.strip()
        checks.append((library, bool(path and path != library and Path(path).is_file())))
    return checks


def configure(source: Path, args: argparse.Namespace) -> Path:
    target = source / "makefile.include"
    if target.is_symlink():
        target.unlink()
    if args.makefile_include:
        text = args.makefile_include.read_text()
    else:
        missing = [name for name, present in gnu_requirements() if not present]
        if missing:
            raise PackagingError(
                "Debian GNU profile is missing: " + ", ".join(missing) + "; run doctor"
            )
        template = source / "arch" / "makefile.include.gnu"
        if not template.is_file():
            raise PackagingError(
                "archive has no arch/makefile.include.gnu; provide --makefile-include"
            )
        text = template.read_text()
        # Configure the archive's own template using documented Debian bindings.
        # No upstream template or implementation is embedded in this helper.
        text = text.replace("-march=native", "").replace("-mtune=native", "")
        text += "\n# Local Debian GNU/OpenMPI library bindings\n"
        text += "VASP_TARGET_CPU =\nOPENBLAS_ROOT = /usr\nBLASPACK = -lopenblas\n"
        text += "SCALAPACK_ROOT = /usr\nSCALAPACK = -lscalapack-openmpi\nFFTW_ROOT = /usr\n"
        text += "INCS += -I/usr/include\n"
    text += "\n# Explicit local build overrides\n"
    for setting in args.make_var:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", setting):
            raise PackagingError("--make-var requires NAME=VALUE")
        single_line(setting, "make variable")
        name, value = setting.split("=", 1)
        text += f"{name} = {value}\n"
    target.write_text(text)
    return target


def validate_elf(path: Path, architecture: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise PackagingError(f"expected a regular executable file: {path}")
    if not path.stat().st_mode & stat.S_IXUSR:
        raise PackagingError(f"binary is not executable: {path}")
    with path.open("rb") as handle:
        header = handle.read(20)
    if len(header) < 20 or header[:4] != b"\x7fELF" or header[5] not in (1, 2):
        raise PackagingError(f"binary is not an ELF executable: {path}")
    kind, machine = struct.unpack(("<" if header[5] == 1 else ">") + "HH", header[16:20])
    expected = ELF_ARCHITECTURES.get(architecture)
    if kind not in (2, 3) or expected != (machine, header[4], header[5]):
        raise PackagingError(
            f"ELF architecture does not match native Debian architecture {architecture}: {path}"
        )


def runtime_dependencies(
    binaries: list[Path], args: argparse.Namespace, work: Path, log: TextIO
) -> str:
    dependencies = []
    if not args.no_auto_depends:
        debian = work / "debian"
        debian.mkdir(exist_ok=True)
        (debian / "control").write_text(
            f"Source: {args.package_name}\nSection: non-free/science\nPriority: optional\n"
            f"Maintainer: {args.maintainer}\n\nPackage: {args.package_name}\n"
            "Architecture: any\nDescription: Locally built VASP executables\n"
        )
        command = ["dpkg-shlibdeps", "-O"]
        if args.shlibs_local:
            command.append("-L" + str(args.shlibs_local.resolve()))
        command.extend("-l" + str(p.resolve()) for p in args.library_dir)
        command.extend("-e" + str(p) for p in binaries)
        try:
            output = capture(command, log, cwd=work)
        except PackagingError as error:
            raise PackagingError(
                str(error) + "\nDependency detection needs Debian library package metadata. "
                "For custom libraries use --shlibs-local, or explicitly supply "
                "--no-auto-depends with --depends."
            ) from error
        lines = [
            line.removeprefix("shlibs:Depends=")
            for line in output.splitlines()
            if line.startswith("shlibs:Depends=")
        ]
        if not lines:
            raise PackagingError("dpkg-shlibdeps returned no shlibs:Depends result")
        dependencies.extend(line for line in lines if line)
    if args.command == "build" and not args.makefile_include:
        dependencies.append("openmpi-bin")
    dependencies.extend(args.depends)
    return ", ".join(dependencies)


def dependency_preflight(args: argparse.Namespace, work: Path, log: TextIO) -> None:
    """Check the GNU C++ runtime's metadata before a costly upstream build.

    This compiles but never executes a tiny original probe. Other runtime
    libraries are still checked against the actual resulting VASP executables.
    """
    source = work / "runtime-probe.cpp"
    binary = work / "runtime-probe"
    source.write_text("int main() { return 0; }\n")
    capture(["g++", str(source), "-Wl,--no-as-needed", "-o", str(binary)], log)
    try:
        runtime_dependencies([binary], args, work, log)
    except PackagingError as error:
        raise PackagingError(
            "dependency preflight failed before VASP compilation:\n" + str(error)
        ) from error


def recovery_command(args: argparse.Namespace, binary_dir: Path, upstream: str) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "vasp_deb",
        "package",
        str(binary_dir),
        "--upstream-version",
        upstream,
        "--revision",
        args.revision,
        "--package-name",
        args.package_name,
        "--maintainer",
        args.maintainer,
        "--variants",
        *args.variants,
        "--output-dir",
        str(args.output_dir.resolve()),
    ]
    profile = getattr(args, "dependency_profile", None)
    if profile:
        command.extend(["--dependency-profile", profile])
    for option, value in [
        ("--shlibs-local", None if profile else args.shlibs_local),
        ("--copyright-file", args.copyright_file),
    ]:
        if value:
            command.extend([option, str(value.resolve())])
    for folder in args.library_dir:
        command.extend(["--library-dir", str(folder.resolve())])
    for dependency in args.depends:
        command.extend(["--depends", dependency])
    if args.command == "build" and not args.makefile_include:
        command.extend(["--depends", "openmpi-bin"])
    if args.no_auto_depends:
        command.append("--no-auto-depends")
    if args.overwrite:
        command.append("--overwrite")
    return command


def install_metadata(
    stage: Path,
    args: argparse.Namespace,
    version: str,
    architecture: str,
    dependencies: str,
    info: dict,
) -> None:
    control = stage / "DEBIAN"
    control.mkdir()
    docs = stage / "usr/share/doc" / args.package_name
    docs.mkdir(parents=True)
    (docs / "copyright").write_text(
        "Upstream: Vienna Ab initio Simulation Package (VASP)\n"
        "Copyright: VASP Software GmbH and the respective original authors;\n"
        " see the licensed upstream distribution for full notices.\n"
        "License: Proprietary; governed by the user's VASP license agreement.\n"
        "This locally generated package grants no additional use or redistribution rights.\n"
        "It does not include source code or pseudopotential/PAW datasets.\n"
    )
    if args.copyright_file:
        shutil.copyfile(args.copyright_file, docs / "copyright")
    (docs / "README.Debian").write_text(
        "Locally built VASP executables. Use requires an appropriate VASP license.\n"
        "Use vasp_std, vasp_gam or vasp_ncl as selected during packaging.\n"
        "Potential datasets are configured separately and are not included.\n"
        "This package does not change MPI, OpenMP, stack limits or user groups.\n"
        "Run the upstream validation suite in your licensed build environment\n"
        "before relying on the build for scientific calculations.\n"
        "Build provenance is recorded in build-info.json.\n"
    )
    (docs / "build-info.json").write_text(json.dumps(info, indent=2, sort_keys=True) + "\n")
    for path in stage.rglob("*"):
        path.chmod(0o755 if path.is_dir() or path.parent == stage / "usr/bin" else 0o644)
    size = sum(path.stat().st_size for path in stage.rglob("*") if path.is_file())
    fields = [
        f"Package: {args.package_name}",
        f"Version: {version}",
        "Section: non-free/science",
        "Priority: optional",
        f"Architecture: {architecture}",
        f"Maintainer: {args.maintainer}",
        f"Installed-Size: {(size + 1023) // 1024}",
    ]
    if dependencies:
        fields.append("Depends: " + dependencies)
    fields.extend(
        [
            "Description: Locally built Vienna Ab initio Simulation Package",
            " VASP executables compiled or supplied locally for licensed use.",
            " Source code and potential datasets are not included.",
        ]
    )
    (control / "control").write_text("\n".join(fields) + "\n")
    payload = sorted(
        path for path in stage.rglob("*") if path.is_file() and control not in path.parents
    )
    (control / "md5sums").write_text(
        "".join(
            f"{digest(path, 'md5')}  {path.relative_to(stage).as_posix()}\n" for path in payload
        )
    )
    for path in control.iterdir():
        path.chmod(0o644)
    if "SOURCE_DATE_EPOCH" in os.environ:
        try:
            epoch = int(os.environ["SOURCE_DATE_EPOCH"])
            if epoch < 0:
                raise ValueError
        except ValueError as error:
            raise PackagingError("SOURCE_DATE_EPOCH must be a nonnegative integer") from error
        for path in [*stage.rglob("*"), stage]:
            os.utime(path, (epoch, epoch), follow_symlinks=False)


def publish_package(built: Path, destination: Path, overwrite: bool) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".vasp-deb-", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle, built.open("rb") as incoming:
            shutil.copyfileobj(incoming, handle)
        if overwrite:
            os.replace(temporary, destination)
        else:
            try:
                os.link(temporary, destination)
            except FileExistsError as error:
                raise PackagingError(
                    f"output exists: {destination}; use --overwrite to replace it"
                ) from error
    finally:
        temporary.unlink(missing_ok=True)


def package(args: argparse.Namespace) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", args.package_name):
        raise PackagingError("invalid Debian package name")
    single_line(args.maintainer, "maintainer")
    if not re.fullmatch(r"[^<>]+ <[^<>\s]+@[^<>\s]+>", args.maintainer):
        raise PackagingError("maintainer must have the form Name <email@example.org>")
    for dependency in args.depends:
        single_line(dependency, "dependency")
    if args.no_auto_depends and not args.depends:
        raise PackagingError("--no-auto-depends requires an explicit --depends declaration")
    if len(set(args.variants)) != len(args.variants):
        raise PackagingError("duplicate variants are not allowed")
    for path in (args.shlibs_local, args.copyright_file, getattr(args, "makefile_include", None)):
        if path is not None and not path.is_file():
            raise PackagingError(f"input file does not exist: {path}")
    commands = ["dpkg", "dpkg-deb"]
    if not args.no_auto_depends:
        commands.append("dpkg-shlibdeps")
    if args.command == "build":
        commands.append("make")
        if not args.archive.is_file():
            raise PackagingError(f"source archive does not exist: {args.archive}")
        if args.jobs < 1:
            raise PackagingError("jobs must be positive")
    require_commands(commands)
    output = args.output_dir.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.work_dir:
        args.work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="vasp-deb-", dir=args.work_dir)).resolve()
    descriptor, log_name = tempfile.mkstemp(prefix="build-", suffix=".log", dir=output)
    log_path = Path(log_name)
    print(f"Private build log: {log_path}", flush=True)
    succeeded = False
    recovery = None
    try:
        with os.fdopen(descriptor, "w") as log:
            architecture = capture(["dpkg", "--print-architecture"], log)
            info = {
                "packager_version": TOOL_VERSION,
                "architecture": architecture,
                "variants": args.variants,
                "mode": args.command,
            }
            if args.command == "build":
                print("Unpacking the local archive in a private workspace...", flush=True)
                source = extract_source(args.archive, work / "source")
                upstream = args.upstream_version or infer_version(args.archive, source)
                info.update(source_archive=args.archive.name, source_sha256=digest(args.archive))
                configuration = configure(source, args)
                info.update(
                    makefile_include_sha256=digest(configuration),
                    profile="custom" if args.makefile_include else "debian-gnu",
                    make_overrides=args.make_var,
                    jobs=args.jobs,
                )
                binary_dir = source / "bin"
            else:
                upstream = args.upstream_version
                binary_dir = args.bin_dir.resolve()
            single_line(upstream, "upstream version")
            single_line(args.revision, "Debian revision")
            if not re.fullmatch(r"[0-9][A-Za-z0-9.+~]*", upstream):
                raise PackagingError(
                    "upstream version must start with a digit and contain only letters, digits, . + ~"
                )
            if not re.fullmatch(r"[A-Za-z0-9+.~]+", args.revision):
                raise PackagingError("invalid Debian revision")
            version = f"{upstream}-{args.revision}"
            capture(["dpkg", "--validate-version", version], log)
            destination = output / f"{args.package_name}_{version}_{architecture}.deb"
            if destination.exists() and not args.overwrite:
                raise PackagingError(f"output exists: {destination}; use --overwrite to replace it")
            if args.command == "build":
                if not args.no_auto_depends and not args.makefile_include:
                    print(
                        "Checking GNU runtime dependency metadata before compilation...", flush=True
                    )
                    dependency_preflight(args, work, log)
                for variant in args.variants:
                    print(f"Building {variant} with {args.jobs} job(s)...", flush=True)
                    run_build(["make", "DEPS=1", f"-j{args.jobs}", variant], source, log)
            stage = work / "package"
            binaries_path = stage / "usr/bin"
            binaries_path.mkdir(parents=True)
            binaries = []
            binary_hashes = {}
            for variant in args.variants:
                original = binary_dir / f"vasp_{variant}"
                validate_elf(original, architecture)
                target = binaries_path / original.name
                shutil.copyfile(original, target)
                target.chmod(0o755)
                binaries.append(target)
                binary_hashes[target.name] = digest(target)
            recovery = recovery_command(args, binaries_path, upstream)
            dependencies = runtime_dependencies(binaries, args, work, log)
            info.update(
                package=args.package_name,
                version=version,
                depends=dependencies,
                binaries_sha256=binary_hashes,
                dependency_mode=(
                    "manual"
                    if args.no_auto_depends
                    else "bundled-profile"
                    if getattr(args, "dependency_profile", None)
                    else "explicit-shlibs"
                    if args.shlibs_local
                    else "installed-metadata"
                ),
            )
            if args.shlibs_local:
                info["shlibs_local_sha256"] = digest(args.shlibs_local)
            if getattr(args, "dependency_profile", None):
                info["dependency_profile"] = args.dependency_profile
            install_metadata(stage, args, version, architecture, dependencies, info)
            built = work / "result.deb"
            capture(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(built)], log)
            publish_package(built, destination, args.overwrite)
            print(f"Created: {destination}", flush=True)
            print(
                "Install locally with: sudo apt install " + shlex.quote(str(destination)),
                flush=True,
            )
            succeeded = True
            return destination
    except (PackagingError, OSError, tarfile.TarError) as error:
        raise PackagingError(f"{error}\nBuild log: {log_path}") from error
    finally:
        if args.keep_work or not succeeded:
            print(f"Retained private workspace: {work}", flush=True)
            if not succeeded and recovery:
                print(
                    "Retry packaging without recompiling (adjust dependency options as needed):\n"
                    + shlex.join(recovery),
                    flush=True,
                )
        else:
            shutil.rmtree(work)
