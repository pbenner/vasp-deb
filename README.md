# vasp-deb

Build a Debian package from your licensed VASP archive or existing executables.
Use Python 3.12+ on Debian/Ubuntu. The helper is MIT licensed; VASP retains its
own license conditions.

## Install

From this directory, inside your Python virtual environment:

```sh
python -m pip install .
```

## Build and install VASP

Example for **Debian 13, GCC/GFortran 14 and OpenMPI 5**:

```sh
vasp-deb doctor --dependency-profile debian13-gnu
vasp-deb build ../reference/vasp.6.5.0.tgz \
  --dependency-profile debian13-gnu --jobs 4
sudo apt install ./dist/vasp_6.5.0-local1_amd64.deb
```

Replace the archive path/version as needed. Packages and logs go to `./dist`.
The package installs `vasp_std`, `vasp_gam`, and `vasp_ncl`; potential datasets
are supplied separately. For other environments, omit `--dependency-profile`
and follow the [setup guide](https://pbenner.github.io/vasp-deb/usage/).

## Verify installation

```sh
vasp-deb verify /path/to/Si/POTCAR
```

Runs the [small silicon test](https://pbenner.github.io/vasp-deb/smoke-test/)
with your Si PAW-PBE potential.

## Package existing binaries

```sh
vasp-deb package /path/to/vasp/bin --upstream-version 6.5.0
```

See the [documentation](https://pbenner.github.io/vasp-deb/) for prerequisites,
custom compilers, troubleshooting, and GitHub Pages setup.
Run `vasp-deb build --help` for options.
