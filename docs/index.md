# vasp-deb documentation

`vasp-deb` compiles a locally supplied VASP archive and creates a Debian package.
It can also package executables you have already built, including prebuilt GPU
archives with selected runtime directories. It detects the release
version, checks native ELF binaries, and records build hashes and dependencies.
Generated packages support side-by-side releases with versioned commands and
group-based access to each installation.

- [Usage](usage.md): prerequisites, builds, installation, and custom configurations.
- [Prebuilt GPU archive](usage.md#prebuilt-gpu-archive): the VASP 6.6.0 A100/H100 recipe.
- [Multiple versions](usage.md#multiple-installed-versions): selection, upgrades, and removal.
- [Licensing and access](licensing.md): eligible users, version-specific groups, and revocation.
- [Small silicon test](smoke-test.md): the installed `vasp-deb verify` command.
- [Troubleshooting](troubleshooting.md): missing dependency metadata and recovery.
- [Development](development.md): tests and Python distribution builds.
- [Publish these docs](publishing.md): local preview and GitHub Pages deployment.

The helper uses Python's standard library at runtime and native Debian tools.
VASP remains separately licensed. Generated packages are for your authorized
installation; VASP source code and potential datasets are not included in them.
Explicitly selected third-party runtime directories are included in full.
