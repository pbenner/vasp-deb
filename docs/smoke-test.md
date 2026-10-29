# Small silicon test

The installed Python package provides a verification command. Run it from any
working directory:

```sh
vasp-deb verify /private/path/to/Si/POTCAR --executable vasp_gam-6.5.0
```

Use an uncompressed, standard **Si PAW-PBE** potential from your licensed
distribution. [VASP distributes potentials through its portal](https://vasp.at/wiki/Available_pseudopotentials).
The command rejects other elements, potential flavors, and combined datasets.
Run as a licensed user with access to the selected package. Without
`--executable`, verification looks for the unversioned `vasp_gam` on `PATH`;
it does not choose an installed release automatically.

## Extract a CPU test potential

If you have the previously used VASP 6.5.0 archive, it contains a suitable test
potential. Extract only that file into an ignored, private directory:

```sh
mkdir -p .work/si-potential
chmod 700 .work/si-potential
tar -xOf /path/to/vasp.6.5.0.tgz \
  vasp.6.5.0/testsuite/POTCARS/POTCAR.kopt_si_path_scan \
  > .work/si-potential/POTCAR
vasp-deb verify .work/si-potential/POTCAR --executable vasp_gam-6.5.0
```

## Verify the supplied GPU archive

After following the [GPU package installation recipe](usage.md#prebuilt-gpu-archive)
and starting a login session with the required group membership, extract only
the silicon potential into a private directory. Run this from the checkout
containing the licensed archive:

```sh
mkdir -p .work/si-potential-6.6.0
chmod 700 .work/si-potential-6.6.0
tar -xOf packages/vasp-6.6.0-gpu-a_h_100.tar.gz \
  vasp.6.6.0/testsuite/POTCARS/POTCAR.kopt_si_path_scan \
  > .work/si-potential-6.6.0/POTCAR
chmod 600 .work/si-potential-6.6.0/POTCAR
CUDA_VISIBLE_DEVICES=1 vasp-deb verify .work/si-potential-6.6.0/POTCAR \
  --executable vasp_gam-6.6.0
```

Replace GPU index `1` with a GPU allocated to you that has enough free memory.
If your scheduler already sets `CUDA_VISIBLE_DEVICES`, retain its value instead
of overriding it. The archive owner can prepare the potential separately when
users have access only to the installed software and their licensed datasets.
The potential is not part of the `.deb` and must remain protected.

Repeat with `--executable vasp_std-6.6.0` to test the standard port. These
versioned launchers configure bundled MPI paths. The standard and Gamma-only
ports use the same small input; noncollinear calculations need their own
appropriate inputs and validation. See [GPU troubleshooting](troubleshooting.md#gpu-archive-runtime-failures)
for MPI component errors or NCCL failures.

## Test behavior and interpretation

The test uses a two-atom diamond silicon primitive cell, a single Gamma point,
a 300 eV cutoff, and a static PBE calculation. It invokes the selected command
with one process, one OpenMP/OpenBLAS thread, at most 40 electronic iterations,
and a 120-second wall time limit. Actual runtime depends on the machine.

Each invocation creates a private `.work/silicon-smoke-*` directory containing
the four inputs, executable/potential hashes, `vasp.log`, and VASP outputs.
Verification runs only when explicitly requested; installation and packaging
do not invoke VASP. Python unit tests use generated fixtures and fake programs.
Use `--executable vasp_std-6.5.0` to check that binary, or `--timeout 60` to change the
limit. Use `--work-dir /private/runs` to change the parent directory; the default
is `.work` under the caller's current directory. The package includes the
original INCAR, POSCAR, and KPOINTS inputs, and requires a user-supplied POTCAR.

`python -m vasp_deb verify ...` is equivalent. In a checkout,
`python examples/silicon_smoke.py ...` remains a compatibility wrapper and
requires the Python package to be installed in the active environment.

`PASS` requires a zero exit status, reported electronic convergence before
the iteration limit, and finite free energy (`F`) and zero-smearing energy
(`E0`) in [OSZICAR](https://vasp.at/wiki/OSZICAR). The
[EDIFF setting](https://vasp.at/wiki/EDIFF) is `1E-5` eV.
On timeout or failure, the command exits nonzero and retains the files.

This checks that a small SCF calculation completes. The coarse k-point mesh
does not establish convergence with respect to Brillouin-zone sampling or
cutoff, and there is no fixed reference-energy assertion. Use the
[upstream validation suite](https://vasp.at/wiki/Testsuite) for broader validation.
