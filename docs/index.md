# vasp-deb documentation

`vasp-deb` compiles a locally supplied VASP archive and creates a Debian package.
It can also package executables you have already built. It detects the release
version, checks native ELF binaries, and records build hashes and dependencies.

- [Usage](usage.md): prerequisites, builds, installation, and custom configurations.
- [Small silicon test](smoke-test.md): the installed `vasp-deb verify` command.
- [Troubleshooting](troubleshooting.md): missing dependency metadata and recovery.
- [Development](development.md): tests and Python distribution builds.
- [Publish these docs](publishing.md): local preview and GitHub Pages deployment.

The helper uses Python's standard library at runtime and native Debian tools.
VASP remains separately licensed. Generated packages are for your authorized
installation; source code and potential datasets are not included in them.
