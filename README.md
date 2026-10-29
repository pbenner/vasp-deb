# vasp-deb

Build a Debian package from your licensed VASP archive or existing executables.
Use Python 3.12+ on Debian/Ubuntu. The helper is MIT licensed; VASP retains its
own license conditions.

## Install

From this directory, inside your Python virtual environment:

```sh
python -m pip install .
```

## Choose the packaging workflow

| Your input | Workflow |
| --- | --- |
| VASP source archive | [`vasp-deb build`](docs/usage.md#build-a-package) compiles the selected variants. |
| Existing executable directory | [`vasp-deb package`](docs/usage.md#package-existing-binaries) packages binaries without compilation. |
| `packages/vasp-6.6.0-gpu-a_h_100.tar.gz` | Follow the [GPU archive recipe](docs/usage.md#prebuilt-gpu-archive), including the bundled SDK and MPI options. |

The GPU archive already contains compiled binaries. `build` would compile a new
build using the chosen compiler configuration. `doctor` checks the GNU CPU build
environment; use the GPU recipe and smoke test to check a prebuilt GPU installation.

## Build and install VASP

Example for **Debian 13, GCC/GFortran 14 and OpenMPI 5**:

```sh
vasp-deb doctor --dependency-profile debian13-gnu
vasp-deb build /path/to/vasp.6.5.0.tgz \
  --dependency-profile debian13-gnu --jobs 4
sudo apt install ./dist/vasp-6.5.0_6.5.0-local1_amd64.deb
# Only after checking that alice is a registered, licensed user of this release:
sudo adduser alice vasp-6-5-0
```

Replace the archive path/version as needed. Packages and logs go to `./dist`.
Versions install side by side, with commands such as `vasp_std-6.5.0`,
`vasp_gam-6.5.0`, and `vasp_ncl-6.5.0`. Each release has its own restricted
Unix group; users must log in again after being added. Use `--access-group`
to select an existing license group. Potential datasets are supplied separately.
See [licensing and access](docs/licensing.md). For other environments, omit
`--dependency-profile` and follow the [setup guide](docs/usage.md).
If you have an older `vasp` or `vasp-local` package, follow the
[migration steps](docs/troubleshooting.md#migrating-earlier-packages) to remove
its unrestricted executables.

## Verify installation

```sh
vasp-deb verify /path/to/Si/POTCAR --executable vasp_gam-6.5.0
```

Runs the [small silicon test](docs/smoke-test.md)
with your Si PAW-PBE potential.

## Package existing binaries

```sh
vasp-deb package /path/to/vasp/bin --upstream-version 6.5.0
```

See [multiple versions and upgrades](docs/usage.md#multiple-installed-versions),
[granting and revoking access](docs/licensing.md#grant-and-revoke-access), and
[troubleshooting](docs/troubleshooting.md). The [documentation index](docs/index.md)
also links development and publishing instructions. Run `vasp-deb build --help`
or `vasp-deb package --help` for all command options.
