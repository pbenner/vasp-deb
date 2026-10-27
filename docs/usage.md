# Usage

## Prerequisites

Use Debian or Ubuntu with Python 3.12+, or a patched Python 3.11 providing
`tarfile.data_filter`. Build on the distribution release where you will install
the package so its compiler and library requirements match.

The default GNU/OpenMPI CPU configuration needs:

```sh
sudo apt install build-essential gfortran openmpi-bin libopenmpi-dev \
  libopenblas-dev libscalapack-openmpi-dev libfftw3-dev rsync dpkg-dev python3
```

Inside a Python virtual environment, install the helper from its checkout:

```sh
python -m pip install .
vasp-deb doctor
```

`python -m vasp_deb` is equivalent to the installed `vasp-deb` command.

## Build a package

```sh
vasp-deb build /path/to/vasp.6.5.0.tgz --jobs 4
```

The helper uses the compiler template shipped with that archive, applies local
Debian library bindings, and builds `std`, `gam`, and `ncl`. Only the resulting
executables and packaging documents enter the `.deb`. Optional features such
as HDF5 require a custom compiler configuration.

Versions are detected from the archive filename or source directory. For a
renamed archive, add `--upstream-version 6.5.0`. Reuse the same command with a
new archive for future releases that retain the documented make/bin interface.

Packages and logs default to `./dist` in your current working directory. Change
the destination with `--output-dir /private/packages`. Use `--revision local2`
for a changed build of the same version, or `--overwrite` to replace an existing
output explicitly.

## Install and inspect

On amd64, the example produces `vasp_6.5.0-local1_amd64.deb`:

```sh
dpkg-deb --info ./dist/vasp_6.5.0-local1_amd64.deb
dpkg-deb --contents ./dist/vasp_6.5.0-local1_amd64.deb
sudo apt install ./dist/vasp_6.5.0-local1_amd64.deb
```

Executables are installed in `/usr/bin` as `vasp_std`, `vasp_gam`, and `vasp_ncl`.
Provide your potential datasets separately. On shared systems, restrict access
to authorized users. The helper runs without root and does not install its own
output, change user groups, or configure MPI, OpenMP, or stack limits.

Run the upstream validation suite in your licensed environment before relying
on a build for scientific calculations.

## Custom compiler configurations

Prepare a complete `makefile.include` from the templates supplied with the VASP
release you are compiling. Use it for Intel/oneAPI, GPUs, HDF5, libxc, other
optional libraries, or machine-specific tuning:

```sh
vasp-deb build /path/to/vasp.6.6.1.tgz \
  --makefile-include /private/path/makefile.include \
  --variants std gam --jobs 8
```

Custom configurations are used directly. Repeated `--make-var 'NAME=VALUE'`
options append explicit overrides. The default GNU configuration removes native
CPU-tuning flags; custom configurations retain your chosen flags. Compiler and
library ABI compatibility remain requirements for the target machine.

## Package existing binaries

```sh
vasp-deb package /private/vasp/bin \
  --upstream-version 6.6.1 --variants std gam ncl
```

This mode needs no compiler or source archive. Inputs must be native executable
ELF files. Scripts, symlinks, object files, and incompatible CPU architectures
are rejected. Add non-library runtime requirements explicitly, for example
`--depends openmpi-bin` for an existing MPI build.

## Workspaces, dependencies, and provenance

Builds use private temporary workspaces. Choose their parent with `--work-dir`.
Successful builds remove the workspace unless `--keep-work` is set. Failures
retain it and, when executables are complete, print a command to retry packaging
without recompilation. See [recovery](troubleshooting.md#recover-a-failed-build).

`dpkg-shlibdeps` derives runtime dependencies from installed Debian metadata.
For external libraries, `--library-dir` adds a scanner search path and
`--shlibs-local` supplies custom package mappings. These options do not bundle
libraries or configure the target runtime linker.

The package includes checksums and `/usr/share/doc/vasp/build-info.json`
with version, architecture, dependencies, selected variants, and applicable
source/configuration/binary/mapping hashes. Use `--copyright-file` for complete
upstream notices and `--package-name` or `--maintainer` to change package metadata.

Packages and logs are created with mode 0600, and new output directories with
mode 0700. The package payload has Debian root ownership and standard executable
permissions. `SOURCE_DATE_EPOCH` controls payload timestamps when supplied;
complete upstream build reproducibility is not claimed.

## References

- [VASP installation interface](https://vasp.at/wiki/Installing_VASP.6.X.X)
- [Release-specific compiler templates](https://vasp.at/wiki/Makefile.include)
- [Debian package construction](https://manpages.debian.org/trixie/dpkg/dpkg-deb.1.en.html)
- [Dependency discovery](https://manpages.debian.org/trixie/dpkg-dev/dpkg-shlibdeps.1.en.html)
