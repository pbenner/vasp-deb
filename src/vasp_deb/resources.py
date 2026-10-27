"""Bundled dependency mappings and original verification inputs."""

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path

from .errors import PackagingError

PROFILE_NAMES = ("debian13-gnu",)


def silicon_inputs() -> dict[str, str]:
    """Load the original silicon test inputs; potentials are supplied separately."""
    root = files("vasp_deb").joinpath("data", "verification", "silicon")
    return {
        name: root.joinpath(name).read_text(encoding="utf-8")
        for name in ("INCAR", "POSCAR", "KPOINTS")
    }


def profile_text(name: str) -> str:
    """Read the complete declaration for a supported dependency profile."""
    if name not in PROFILE_NAMES:
        raise PackagingError(f"unknown dependency profile: {name}")
    return (
        files("vasp_deb").joinpath("data", "profiles", f"{name}.shlibs").read_text(encoding="utf-8")
    )


@contextmanager
def profile_file(name: str) -> Iterator[Path]:
    """Keep a profile's filesystem path valid while a scanner uses it."""
    if name not in PROFILE_NAMES:
        raise PackagingError(f"unknown dependency profile: {name}")
    resource = files("vasp_deb").joinpath("data", "profiles", f"{name}.shlibs")
    with as_file(resource) as path:
        yield path
