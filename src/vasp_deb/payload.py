"""Select prebuilt archive payloads without extracting sources or potentials."""

from __future__ import annotations

import re
import shlex
import shutil
import tarfile
from pathlib import Path, PurePosixPath

from .errors import PackagingError


def validate_runtime_names(names: list[str]) -> None:
    for name in names:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or name == "bin":
            raise PackagingError("--bundle-runtime requires a sibling directory name, e.g. hpc_sdk")
    if len(names) != len(set(names)):
        raise PackagingError("duplicate runtime directories are not allowed")


def extract_binaries(archive: Path, destination: Path, runtimes: list[str]) -> Path:
    """Stream even large archives; keep only bin/ and explicitly selected runtimes."""
    if not hasattr(tarfile, "data_filter"):
        raise PackagingError("Python with tarfile.data_filter is required")
    destination.mkdir(mode=0o700)
    selected = {"bin", *runtimes}

    def payload_filter(member: tarfile.TarInfo, target: str) -> tarfile.TarInfo | None:
        name = PurePosixPath(member.name)
        if name.is_absolute() or ".." in name.parts:
            raise PackagingError(f"unsafe archive member: {member.name!r}")
        parts = name.parts
        if parts and (parts[0] in selected or (len(parts) > 1 and parts[1] in selected)):
            return tarfile.data_filter(member, target)
        return None

    with tarfile.open(archive, "r|*") as handle:
        handle.extractall(destination, filter=payload_filter)
    candidates = [destination, *(p for p in destination.iterdir() if p.is_dir())]
    roots = [p for p in candidates if (p / "bin").is_dir()]
    if len(roots) != 1:
        raise PackagingError("expected one prebuilt archive root containing bin/vasp_*")
    return roots[0] / "bin"


def copy_runtime(source: Path, destination: Path) -> None:
    """Keep relocatable symlinks, rejecting links outside the selected runtime."""
    if source.is_symlink() or not source.is_dir():
        raise PackagingError(f"expected a regular runtime directory: {source}")
    root = source.resolve()
    for path in source.rglob("*"):
        if path.is_symlink():
            try:
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError) as error:
                raise PackagingError(f"broken runtime link: {path}") from error
            if Path(path.readlink()).is_absolute() or not resolved.is_relative_to(root):
                raise PackagingError(f"runtime link must stay within its directory: {path}")
        elif not path.is_file() and not path.is_dir():
            raise PackagingError(f"unsupported runtime file: {path}")
    shutil.copytree(source, destination, symlinks=True)


def mpi_launchers(private: Path, prefix: str, variants: list[str]) -> Path:
    """Point Open MPI, PMIx and PRRTE at the relocated vendor installation."""
    mpi = private / prefix
    if not all((mpi / name).exists() for name in ("bin/mpirun", "lib")):
        raise PackagingError("--mpi-prefix must contain bin/mpirun and lib")
    launch = private / "launch"
    launch.mkdir()
    targets = {f"vasp_{variant}": f"bin/vasp_{variant}" for variant in variants}
    targets["mpirun"] = f"{prefix}/bin/mpirun"
    for name, target in targets.items():
        script = launch / name
        script.write_text(
            "#!/bin/sh\nset -eu\n"
            'root=$(dirname "$(dirname "$(readlink -f "$0")")")\n'
            f'export OPAL_PREFIX="$root"/{shlex.quote(prefix)}\n'
            'export PMIX_PREFIX="$OPAL_PREFIX" PRTE_PREFIX="$OPAL_PREFIX"\n'
            'export PATH="$OPAL_PREFIX/bin:$PATH"\n'
            'export LD_LIBRARY_PATH="$OPAL_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'
            f'exec "$root"/{shlex.quote(target)} "$@"\n'
        )
        script.chmod(0o755)
    return launch
