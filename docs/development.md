# Development

From the package checkout, inside a Python virtual environment:

```sh
python -m pip install -e '.[dev,docs]'
pre-commit install
pre-commit run --all-files
python -m unittest discover -s tests -v
ruff check .
ruff format --check .
mkdocs build --strict
python -m build --outdir python-dist
```

The Git hook runs `ruff format` on staged Python files. If it reformats a file,
review and stage the changes before retrying the commit. Pre-commit manages
the pinned formatter in its own environment.

Code is under `src/vasp_deb`: `cli.py` provides the entry points, `builder.py`
handles compilation and Debian packaging, and `resources.py` loads bundled
profiles and verification inputs. `verification.py` implements the explicitly
invoked `vasp-deb verify` command. `_version.py` is the version source. The
installed runtime uses only Python's standard library.

Tests use generated archives and original C/C++/Fortran probes with real Debian
tools where available. Distribution tests inspect wheel/sdist allowlists and
install a wheel into a fresh environment outside the checkout. They require no
VASP source or potential data.

Python distributions go into `python-dist/`; VASP packages and logs go into
`dist/`. Generated sites go into `site/`. Keep these outputs and virtual
environments outside version control. Source distributions include the Markdown
documentation and MkDocs configuration; wheels contain runtime code, profiles,
and the original silicon verification inputs. Potentials are supplied separately.

The VASP 6.5.0 archive has been compiled for all three variants and packaged with
the Debian 13 mapping. Package contents, dependencies, ownership, and executable
hashes were checked. The [small silicon test](smoke-test.md) has also completed
with the installed VASP 6.5.0 Gamma and standard binaries. The upstream scientific
validation suite has not been run.
