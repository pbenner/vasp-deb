# Preview and publish the documentation

## Local preview

From the package checkout:

```sh
python -m pip install -e '.[docs]'
mkdocs serve
```

Open the URL printed by MkDocs. To check the static output:

```sh
mkdocs build --strict
```

The generated site is in `site/`. Only files under this package's `docs/`
directory are used as documentation input.

## GitHub Pages

The repository includes a manual **Publish documentation** workflow at
`.github/workflows/docs.yml`, targeting
`https://pbenner.github.io/vasp-deb/`.

1. Commit and push the package source, docs, and workflow to `pbenner/vasp-deb`.
2. In the repository's **Settings → Pages**, select **GitHub Actions** as the source.
3. In **Actions → Publish documentation**, select **Run workflow**.

The workflow builds the site with strict checks and uploads only the generated
documentation. It does not compile VASP or upload source archives, `.deb` files,
build logs, or virtual environments. Deployment runs only when manually triggered.
Once it succeeds, the workflow reports the live site URL.

If the repository or domain changes, update `site_url` and `repo_url` in
`mkdocs.yml`. Until the workflow is run successfully, the configured URL is a
deployment target rather than a published site.

See [GitHub's workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
for Pages permissions and repository settings.
