#!/usr/bin/env python3
"""Compatibility wrapper for the installed ``vasp-deb verify`` command."""

import sys

from vasp_deb.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["verify", *sys.argv[1:]]))
