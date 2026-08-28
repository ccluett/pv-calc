# Release guide

This file records the maintainer steps for publishing pv-calc. It belongs in
the public repository so the release process can be reviewed and repeated.

The package version is defined in `pv_calc/__init__.py` and read by
`pyproject.toml`. A `v*` tag starts
[.github/workflows/publish.yml](.github/workflows/publish.yml), which publishes
through PyPI trusted publishing. The `pypi` GitHub environment and the matching
PyPI trusted-publisher entry must already exist.

1. Confirm `main` is green.
2. Set `__version__` in `pv_calc/__init__.py` and `version` in
   `CITATION.cff` (with `date-released`), and turn the `## [Unreleased]`
   block in `CHANGELOG.md` into `## [X.Y.Z] - YYYY-MM-DD`, leaving a fresh
   empty `## [Unreleased]` above it.
3. Regenerate the golden snapshot with
   `uv run python tests/test_pv_calc_golden.py` and review the diff. Every
   response carries `package_version`, so a version bump changes the snapshot.
   Record any other response changes in the changelog.
4. Commit, then tag and push:

   ```bash
   git tag vX.Y.Z && git push origin main vX.Y.Z
   ```

   The workflow first runs the full test suite on the tagged commit. It stops
   if the tag does not match `pv-calc --version`.
5. Check the PyPI release page and `pip install pv-calc==X.Y.Z` in a clean
   environment.
