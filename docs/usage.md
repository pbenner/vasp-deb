# Usage

## Prerequisites

Use Debian or Ubuntu with Python 3.12+, or a patched Python 3.11 providing
`tarfile.data_filter`. Build on the distribution release where you will install
the package so its compiler and library requirements match. Generated packages
use zstd compression (dpkg 1.21.18+, or a distribution with zstd support backported).

Packaging prebuilt binaries requires Python, `dpkg`, and `dpkg-deb`. Automatic
dependency discovery also needs `dpkg-shlibdeps` from `dpkg-dev`; it is not used
with `--no-auto-depends`. The GPU archive recipe needs no compiler installation.
Installing a generated package requires administrator privileges and the declared
runtime dependencies, including `adduser` for access-group creation.

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
`doctor` checks only the GNU CPU compilation environment and its dependency
metadata. Missing GNU compilers do not prevent packaging existing GPU binaries;
`doctor` does not check GPU availability, CUDA-aware MPI, or license eligibility.

## Build a package

```sh
vasp-deb build /path/to/vasp.6.5.0.tgz --jobs 4
```

The helper uses the compiler template shipped with that archive, applies local
Debian library bindings, and builds `std`, `gam`, and `ncl`. Only the resulting
executables and packaging documents enter the `.deb`. Optional features such
as HDF5 require a custom compiler configuration.
Existing `build/` and `bin/` trees in source archives are cleared before compilation,
so objects from a different compiler are never reused. Use `package` to retain
prebuilt GPU executables instead.

Versions are detected from the archive filename or source directory. For a
renamed archive, add `--upstream-version 6.5.0`. Reuse the same command with a
new archive for future releases that retain the documented make/bin interface.

Packages and logs default to `./dist` in your current working directory. Change
the destination with `--output-dir /private/packages`. Use `--revision local2`
for a changed build of the same version, or `--overwrite` to replace an existing
output explicitly.

## Install and inspect

On amd64, the example produces `vasp-6.5.0_6.5.0-local1_amd64.deb`:

```sh
dpkg-deb --info ./dist/vasp-6.5.0_6.5.0-local1_amd64.deb
dpkg-deb --contents ./dist/vasp-6.5.0_6.5.0-local1_amd64.deb
sudo apt install ./dist/vasp-6.5.0_6.5.0-local1_amd64.deb
```

The package stores executables in `/usr/lib/vasp-6.5.0/bin` and adds versioned
commands to `/usr/bin`, for example `vasp_std-6.5.0`. Installation creates an
empty `vasp-6-5-0` system group if needed. Only root and that group's members
can access the payload. After verifying a user's license eligibility:

```sh
sudo adduser alice vasp-6-5-0
```

The user must start a new login session. Supply potential datasets separately
and protect them too. See [licensing and user access](licensing.md) for revocation,
custom groups, and protecting archives. Building runs without root; it neither
installs packages nor changes host groups. These actions happen only when an
administrator installs the resulting package.

Run the upstream validation suite in your licensed environment before relying
on a build for scientific calculations.
If upgrading from an unversioned `vasp` or `vasp-local` package, first review the
[migration instructions](troubleshooting.md#migrating-earlier-packages).

## Multiple installed versions

Each upstream version has a different Debian package name and owns distinct
files. For example, `vasp-6.5.0` and `vasp-6.6.0` coexist. A new `--revision`
upgrades the same upstream version; removing one version leaves the other intact.
The default names are:

| Upstream release | Debian package | Standard command | Access group |
| --- | --- | --- | --- |
| 6.5.0 | `vasp-6.5.0` | `vasp_std-6.5.0` | `vasp-6-5-0` |
| 6.6.0 | `vasp-6.6.0` | `vasp_std-6.6.0` | `vasp-6-6-0` |

Once both packages have been built for the target system, install and list them:

```sh
sudo apt install ./dist/vasp-6.5.0_6.5.0-local1_amd64.deb \
  ./dist/vasp-6.6.0_6.6.0-local1_amd64.deb
dpkg-query -W -f='${binary:Package} ${Version} ${Status}\n' 'vasp-*'
```

Each user needs membership in the group for each version they are authorized to
use. Run calculations from a directory containing the appropriate VASP inputs,
and use explicit commands in reproducible job scripts:

```sh
vasp_std-6.5.0
vasp_std-6.6.0
```

For software expecting unversioned commands, select a release in that shell/job:

```sh
export PATH=/usr/lib/vasp-6.5.0/bin:$PATH
vasp_std
```

For packages built with `--mpi-prefix`, select the launchers instead:

```sh
export PATH=/usr/lib/vasp-6.6.0/launch:$PATH
mpirun -np 2 vasp_std
```

This selects both VASP wrappers and the matching `mpirun`. There is no implicit
system-wide default or automatic switch when another release is installed.

`--package-name` is a **prefix**, with the release appended automatically.
Use `--package-name vasp-gpu` to coexist with a CPU build of the same release:
it produces `vasp-gpu-6.6.0`, commands such as `vasp-gpu_std-6.6.0`, and default
group `vasp-gpu-6-6-0`. Keep the prefix consistent when upgrading that build.

### Upgrade or remove one version

To replace a build of the same upstream version, repeat its original `build` or
`package` command with `--revision local2`, retaining the compiler, runtime, and
dependency options. Then install the new revision:

```sh
sudo apt install ./dist/vasp-6.6.0_6.6.0-local2_amd64.deb
```

This upgrades `vasp-6.6.0`; `vasp-6.5.0` stays installed. `--overwrite` only allows
replacing an output file and does not increment the Debian version or cause APT
to upgrade an already installed package. Use a new revision for changed builds.

To remove only the older release:

```sh
sudo apt remove vasp-6.5.0
```

The other release, potential datasets, build archives, and access groups remain.
Jobs selecting the removed release must be updated explicitly. Groups are kept
to avoid changing access for other packages that share them.

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

The input can also be a tar archive with `bin/` at the top level or inside one
release directory. Versions are inferred from the archive or release directory;
binary directories require `--upstream-version`. Archive packaging streams only
the binaries and explicitly selected runtime directories into a private workspace.
It does not extract VASP sources, tests, potentials, or archived virtual environments.

`--bundle-runtime DIRECTORY` may be repeated for multiple sibling directories:
for input `/private/vasp/bin`, `--bundle-runtime hpc_sdk` includes
`/private/vasp/hpc_sdk`. Supply a directory name, not an absolute path. Relative
symlinks within that runtime are preserved; broken links or links outside it
are rejected. Each selected directory is included in full. The helper does not
automatically discover or bundle arbitrary external libraries.

### Prebuilt GPU archive

The supplied `vasp-6.6.0-gpu-a_h_100.tar.gz` contains all three VASP executables,
an NVIDIA HPC SDK 26.5 / CUDA 13.2 tree, and Open MPI 5. Its executable RUNPATHs
refer to `../hpc_sdk`. Preserve that directory with `--bundle-runtime hpc_sdk`.
This explicitly bundles the full selected SDK, including its notices and other
files, so the installed package is large (about 15 GiB). Allow at least 50 GiB
of workspace for extraction, staging, and the compressed output; use `--work-dir`
on a large disk rather than a small `/tmp`.

The following dependency declaration matches the tested Ubuntu 24.04 host with
GCC runtime 14, MKL 2020.4, and NVIDIA driver 615.71.10. It is a conservative
baseline for that stack, not a portable dependency profile or a claim about
minimum GPU driver support. Adjust the dependencies for other target systems:

```sh
vasp-deb package packages/vasp-6.6.0-gpu-a_h_100.tar.gz \
  --bundle-runtime hpc_sdk \
  --mpi-prefix hpc_sdk/Linux_x86_64/26.5/comm_libs/13.2/hpcx/hpcx-2.50/ompi5 \
  --no-auto-depends \
  --depends 'libc6 (>= 2.39), libstdc++6 (>= 14), libgcc-s1 (>= 14), libatomic1 (>= 14), zlib1g, libnuma1, libudev1, libmkl-intel-lp64 (>= 2020.4), libmkl-sequential (>= 2020.4), libmkl-meta-computational (>= 2020.4), libnvidia-compute (>= 615.71.10)' \
  --work-dir .work
sudo apt install ./dist/vasp-6.6.0_6.6.0-local1_amd64.deb
# After verifying that alice is authorized for this release:
sudo adduser alice vasp-6-6-0
```

Private SDK libraries have no matching Debian package metadata, so bundling
requires an explicit dependency declaration. MKL and the NVIDIA driver remain
external. The `debian13-gnu` mapping is for a different compiler/library stack
and must not be used for this GPU archive.

Run the build command as your ordinary account, then have an administrator
install the `.deb`. Replace `alice` with the verified user's account and start
a fresh login session after adding membership. See the
[GPU silicon-test example](smoke-test.md#verify-the-supplied-gpu-archive) for
extracting just the necessary potential from this archive.

`--mpi-prefix` generates VASP and `vasp_mpirun-6.6.0` launchers that set
`OPAL_PREFIX`, `PMIX_PREFIX`, `PRTE_PREFIX`, MPI's library path, and its command
path for that process. They retain argument boundaries and find their private
installation relative to their own location. Use the wrappers to avoid Open
MPI losing its CUDA components after relocation:

```sh
CUDA_VISIBLE_DEVICES=1 vasp-deb verify /private/Si/POTCAR --executable vasp_gam-6.6.0
vasp_mpirun-6.6.0 -np 2 vasp_std-6.6.0
```

Choose an allocated GPU with free memory; `1` is just an example. Remove
conflicting CUDA/MPI entries from `LD_LIBRARY_PATH` before using a different
stack. Multi-node execution also needs matching installation paths and group
membership on each node, scheduler integration, and site-specific validation.
The `--mpi-prefix` value is relative to the release root, must lie within one
of the selected runtime directories, and must contain `bin/mpirun` and `lib`.
The underlying ELF files remain in `/usr/lib/vasp-6.6.0/bin`; run the wrappers
in `launch/` or `/usr/bin` so MPI receives the required environment.

## Workspaces, dependencies, and provenance

Builds use private temporary workspaces. Choose their parent with `--work-dir`.
Successful builds remove the workspace unless `--keep-work` is set. Failures
retain it and, when executables are complete, print a command to retry packaging
without recompilation. See [recovery](troubleshooting.md#recover-a-failed-build).

`dpkg-shlibdeps` derives runtime dependencies from installed Debian metadata.
For external libraries, `--library-dir` adds a scanner search path and
`--shlibs-local` supplies custom package mappings. These options do not bundle
libraries or configure the target runtime linker.

The package includes checksums and `/usr/share/doc/vasp-<version>/build-info.json`
with version, architecture, dependencies, selected variants, and applicable
source/configuration/binary/mapping hashes, plus access group and runtime layout.
Use `--copyright-file` for complete upstream notices and `--maintainer` to change
the maintainer metadata. An archive package records the input archive's hash.

Packages and logs are created with mode 0600, and new output directories with
mode 0700. The payload's private root is root-owned mode 0700 in the archive;
`postinst` changes it to root and the authorized group, mode 0750. The directory
boundary protects binaries and bundled libraries, including direct access
without a wrapper. Interrupted configuration leaves it inaccessible to users.
`SOURCE_DATE_EPOCH` controls payload timestamps when supplied;
complete upstream build reproducibility is not claimed.

## References

- [VASP installation interface](https://vasp.at/wiki/Installing_VASP.6.X.X)
- [Release-specific compiler templates](https://vasp.at/wiki/Makefile.include)
- [Debian package construction](https://manpages.debian.org/trixie/dpkg/dpkg-deb.1.en.html)
- [Dependency discovery](https://manpages.debian.org/trixie/dpkg-dev/dpkg-shlibdeps.1.en.html)
- [Relocating Open MPI](https://docs.open-mpi.org/en/v5.0.x/installing-open-mpi/installation-location.html)
