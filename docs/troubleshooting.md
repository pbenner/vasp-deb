# Troubleshooting

## Missing dependency metadata

An error such as `no dependency information found for libstdc++.so.6` means the
library was found but its Debian package dependency could not be determined.
A working compiler alone does not supply the symbols/shlibs metadata required
by the scanner. Prefer an environment with its Debian package metadata intact.

For the standard **Debian 13 / GCC and GFortran 14 / OpenMPI 5** stack, use the
bundled mapping:

```sh
vasp-deb doctor --dependency-profile debian13-gnu
vasp-deb build /path/to/vasp.6.5.0.tgz \
  --dependency-profile debian13-gnu --jobs 4
```

This still scans actual ELF dependencies and fails on unknown libraries. Its
version floors describe the Debian 13 baseline, rather than each executable's
minimum symbol versions. Use it only with the matching build and target stack.
For another distribution or toolchain, use installed metadata or an appropriate
custom file through `--shlibs-local`.

When you can provide a complete dependency declaration yourself, the explicit
fallback is `--no-auto-depends --depends 'package1, package2'`. The package names
and minimum versions must match the real runtime; they cannot be inferred from
that declaration. This option bypasses automatic dependency scanning.

## Recover a failed build

Failed runs retain their private workspace and print the log location. If all
executables were built, use the printed `package` command and correct its
dependency options. This reuses the binaries without compiling again.

For a compiler failure, inspect the private build log and adjust the supplied
configuration. Retained source/object files can also be used for a manual build
retry. Do not publish compiler logs containing proprietary source excerpts.

Version 0.1.0 deleted failed workspaces; binaries lost with that version must be
rebuilt. Current versions retain failures by default.

## Existing output

Use a new `--revision` to distinguish changed builds of the same VASP release.
Use `--overwrite` only when you intend to replace the existing `.deb`.

## Migrating earlier packages

Earlier packages named `vasp` or `vasp-local` installed world-executable,
unversioned `/usr/bin/vasp_*` files. Check which are installed:

```sh
dpkg-query -W -f='${binary:Package} ${Version} ${Status}\n' vasp vasp-local
```

Missing packages may produce a query error. Remove only names reported as
installed; for example, if the old package is `vasp`:

```sh
sudo apt remove vasp
```

Use `vasp-local` instead if that is the installed package, or both names if both
are installed. New packages such as
`vasp-6.5.0` use separate paths, so there is no file conflict, but leaving the old
copy installed leaves unrestricted access to it. New group restrictions do not
protect that copy. Update job scripts to use versioned commands or select the
desired private command directory in `PATH`. `--package-name` now specifies a
prefix; the upstream version is always appended.

## GPU archive runtime failures

Use the [prebuilt GPU archive recipe](usage.md#prebuilt-gpu-archive). Missing
`libqd`, NVIDIA compiler, MPI, or CUDA libraries usually mean the `hpc_sdk`
directory was not bundled, or incompatible paths were inherited from the shell.
MKL is external to this archive and must be installed separately.

`CHECK_MPI: your MPI is not CUDA-aware` after moving the files can mean Open MPI
cannot find its components. Generate launchers using `--mpi-prefix` and invoke
the versioned VASP command. Invoke `vasp_mpirun-6.6.0` for the matching MPI launcher;
using an unrelated system `mpirun` can mix installations.

If NCCL initialization fails, inspect the private verification log with
`NCCL_DEBUG=INFO`. During local validation, a nearly full H100 caused CUDA
out-of-memory at initialization. Selecting an allocated GPU with enough free
memory resolved it. Check actual diagnostics before changing MPI or NCCL settings.

## Permission denied

Verify membership in the package's access group and start a fresh login session
after an administrator grants access. An unpacked but unconfigured package
remains root-only until `sudo dpkg --configure <package-name>` succeeds.
Do not solve an access error by making VASP world-readable or executable.
See [licensing and access](licensing.md).

## Command not found after installing a versioned package

New packages do not install a global unversioned `vasp_std`, `vasp_gam`, or
`vasp_ncl`. Use `vasp_std-6.6.0`, for example, or select the release's command
directory in `PATH` as described in [multiple versions](usage.md#multiple-installed-versions).
For `verify`, pass `--executable vasp_gam-6.6.0` unless you have selected an
unversioned command in `PATH`. Custom package prefixes also change command names.
Consult the installed `README.Debian` or `build-info.json` under
`/usr/share/doc/<package-name>/` for the names produced by a particular build.

## Start again

Once no build is running, remove generated outputs and caches from the package
checkout:

```sh
rm -rf -- dist .work __pycache__ src/vasp_deb/__pycache__ tests/__pycache__
find /tmp -maxdepth 1 -type d -uid "$(id -u)" \
  -name 'vasp-deb-*' -exec rm -rf -- {} +
```

This also removes retained temporary workspaces owned by you. Your source
archive and package code are preserved. Remove an installed VASP package
separately with `sudo apt remove vasp-6.6.0` (or the appropriate version) if needed.
