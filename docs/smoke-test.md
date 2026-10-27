# Small silicon test

The installed Python package provides a verification command. Run it from any
working directory:

```sh
vasp-deb verify /private/path/to/Si/POTCAR
```

Use an uncompressed, standard **Si PAW-PBE** potential from your licensed
distribution. [VASP distributes potentials through its portal](https://vasp.at/wiki/Available_pseudopotentials).
The command rejects other elements, potential flavors, and combined datasets.

If you have the supplied VASP 6.5.0 archive, it already contains a suitable test
potential. Extract only that file into an ignored, private directory:

```sh
mkdir -p .work/si-potential
chmod 700 .work/si-potential
tar -xOf ../reference/vasp.6.5.0.tgz \
  vasp.6.5.0/testsuite/POTCARS/POTCAR.kopt_si_path_scan \
  > .work/si-potential/POTCAR
vasp-deb verify .work/si-potential/POTCAR
```

The test uses a two-atom diamond silicon primitive cell, a single Gamma point,
a 300 eV cutoff, and a static PBE calculation. It invokes `vasp_gam` directly
with one process, one OpenMP/OpenBLAS thread, at most 40 electronic iterations,
and a 120-second wall time limit. Actual runtime depends on the machine.

Each invocation creates a private `.work/silicon-smoke-*` directory containing
the four inputs, executable/potential hashes, `vasp.log`, and VASP outputs.
Verification runs only when explicitly requested; installation and packaging
do not invoke VASP. Python unit tests use generated fixtures and fake programs.
Use `--executable vasp_std` to check that binary, or `--timeout 60` to change the
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
