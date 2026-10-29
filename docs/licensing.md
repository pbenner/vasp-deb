# Licensing and user access

VASP requires access controls on shared machines. Its official FAQ says access
must be limited to the group's [authorized VASP users](https://vasp.at/info/faq/page/2/),
and that everyone using VASP under a license must be
[officially registered](https://vasp.at/info/faq/vasp_access/). Unix group membership is a
local enforcement mechanism; it does not register a user with VASP or grant a
license. The group leader or designated contact manages the official user list.

The [public FAQ](https://vasp.at/info/faq/) describes licenses for defined research groups, rather than
whole departments or institutions. It also distinguishes the purchased release
and covered upgrades from later upgrades requiring renewal. Confirm that your
actual agreement covers **each release**, especially 6.6.0, before granting access.
This repository has not verified your signed license or registered user list.
For uncertain entitlement or a central installation serving several groups,
ask the license holder or VASP's licensing office at `licensing@vasp.at`.

## Grant and revoke access

By default, each version has a separate group, for example `vasp-6-6-0` for
package `vasp-6.6.0`. Installation creates that group if absent, without adding
any members. Choose a dedicated existing or new group using `--access-group`
when building, for example `--access-group vasp-lab-a`. Reuse a group across
versions only when all its members are eligible for every included release.
Custom group names must be at most 32 characters, start with a lowercase letter
or underscore, and contain only lowercase letters, digits, underscores, and
hyphens. Existing membership is preserved when a group already exists.

After installation, an administrator can grant access to a verified user:

```sh
sudo adduser alice vasp-6-6-0
getent group vasp-6-6-0
```

Replace `alice` with the verified user's local account. For a package built with
`--access-group vasp-lab-a`, use `vasp-lab-a` in these commands instead.

The user must log out and in again; compute nodes must also see the updated
membership. Remove access when eligibility ends:

```sh
sudo deluser alice vasp-6-6-0
```

Existing sessions and jobs retain their supplementary groups. Coordinate ending
those sessions/jobs to make revocation effective; removing a group entry alone
does not revoke already running processes or copies the user previously made.
The license contact must update the official VASP user list as well.

Package removal deliberately retains the group and its membership, because
other installations may use it. Reinstalling a version reuses an existing group;
administrators should review its members. To change a package's group, rebuild
with `--access-group` and a new `--revision`, then install the revision. The
package's configuration script enforces that group and mode 0750 on its private
root; do not use a permissive `dpkg-statoverride` to make it world-accessible.

## Check installed access

After a successful installation, inspect the configured boundary and membership:

```sh
stat -c '%U:%G %a %n' /usr/lib/vasp-6.6.0
getent group vasp-6-6-0
id alice
```

For the default group, the first command should report
`root:vasp-6-6-0 750 /usr/lib/vasp-6.6.0`. The installed
`/usr/share/doc/vasp-6.6.0/build-info.json` records `access_group` and
`command_directory` if you need to check a custom build.

An administrator can check a fresh authorized user's ability to read and execute
the actual ELF file without starting a calculation:

```sh
sudo -u alice -- test -r /usr/lib/vasp-6.6.0/bin/vasp_std
sudo -u alice -- test -x /usr/lib/vasp-6.6.0/bin/vasp_std
```

Both commands should exit successfully. Repeat with an existing account outside
the authorized group: both should return a nonzero status. Use `echo $?`
immediately after a check to display its exit status. Check the ELF path as well
as the user-facing launcher; restrictions must protect direct file access.
These checks use fresh credentials and do not revoke or inspect older sessions.

## What is protected

The private installation root is `/usr/lib/<versioned-package-name>`. It ships
as root:root, mode 0700, and becomes root:authorized-group, mode 0750, during
configuration. All binaries and bundled runtime directories lie beneath that
boundary, so unlisted users cannot read, copy, or execute the installed payload
by bypassing a launcher. No setuid or setgid executable is used. System root
and privileged administrators remain able to access it.

Protect other copies separately: source archives, extracted trees, failed build
workspaces, POTCAR datasets, backups, `.deb` files, and package repository caches.
Anyone who can read a `.deb` can extract its payload without running its install
scripts. An ordinary public or world-readable APT repository/cache therefore
defeats the installed group restriction. Use private delivery and check retained
copies on the target machines. New helper outputs are private, but existing input
directories and archive permissions are not changed automatically.

For an archive owned by the packaging account in this checkout, for example:

```sh
chmod 700 packages
chmod 600 packages/vasp-6.6.0-gpu-a_h_100.tar.gz
```

These permissions restrict the archive to its owner and administrators. Use a
separately managed licensed group if sharing input archives is required. Also
review pre-existing `dist/` directories and any copied package files; the helper
does not repair permissions on pre-existing directories or third-party caches.

The helper's MIT license covers the packaging code only. It does not change VASP's
terms or grant permission to redistribute VASP. `--bundle-runtime` also includes
third-party software whose license and redistribution terms remain applicable;
its original notices are retained. Keep generated packages within the scope of
your agreements.

## Official sources

Reviewed on 29 October 2026:

- [Installation and access restriction](https://vasp.at/info/faq/page/2/).
- [Official user registration and departure from a group](https://vasp.at/info/faq/vasp_access/).
- [Group scope and release/upgrade coverage](https://vasp.at/info/faq/).
