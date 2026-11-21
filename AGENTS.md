# pv-calc

A command-line tool and Python library for external-pressure housing
calculations. The package is `pv_calc/`. Tests are in `tests/`, including
independent reference implementations of the source equations in
`tests/reference/`. Example requests are in `examples/`.

## Checks

- `uv run --extra test pytest`
- `uvx ruff@0.16.3 check`
- `uv run --isolated --python 3.11 --with mypy==2.3.1 mypy pv_calc` (Python 3.11,
  as in CI; `--isolated` leaves the project environment alone)
- When model output changes on purpose, regenerate the golden responses with
  `uv run python tests/test_pv_calc_golden.py` and review the diff.

## Conventions

- Keep the repository to the tool. Research notes and exploratory studies stay
  outside it.
- Record user-facing changes in `CHANGELOG.md` under Unreleased.

## Public text

Commit messages, pull-request titles and descriptions, the changelog, docs,
and code comments are read by people who see nothing else.

- Describe the change itself. Do not name the tool that wrote it, add tool
  co-author or "generated with" lines, or refer to a review, session, or
  conversation the reader cannot open.
- Claim only what was checked, and say how.
- Name a branch for its change, without a tool prefix. If a session starts
  on a branch that has one, rename it before the first push
  (`git branch -m <new-name>`). Pull requests are squash merged, so the
  title and description become the commit on `main`.
- The sdist and wheel ship only the files listed in
  `.github/scripts/check_distribution.py`; add a new shipped file there on
  purpose. CI runs that check on every build and again before publishing,
  and `change-text.yml` applies its text rule to each pull request.
