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

## Earlier package name

If you installed an earlier package named `vasp-local`, remove it with
`sudo apt remove vasp-local` before installing the newly named `vasp` package.
Both provide the same executable paths. The package name can still be overridden
with `--package-name`.

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
separately with `sudo apt remove vasp` if needed.
