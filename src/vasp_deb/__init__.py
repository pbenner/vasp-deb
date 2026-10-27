"""Local VASP-to-Debian packaging utilities."""

from ._version import __version__
from .errors import PackagingError

__all__ = ["PackagingError", "__version__"]
