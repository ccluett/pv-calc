# pv-calc

A command-line tool and Python library for external-pressure housing
calculations. The package is `pv_calc/`. Tests are in `tests/`, including
independent reference implementations of the source equations in
`tests/reference/`. Example requests are in `examples/`.

## Checks

- `uv run pytest`
- `uvx ruff@0.16.3 check`
- `uv run --isolated --python 3.11 --with mypy==2.3.1 mypy pv_calc` (Python 3.11,
  as in CI; `--isolated` leaves the project environment alone)
- When model output changes on purpose, regenerate the golden responses with
  `uv run python tests/test_pv_calc_golden.py` and review the diff.

## Conventions

- Keep the repository to the tool. Research notes and exploratory studies stay
  outside it.
- Record user-facing changes in `CHANGELOG.md` under Unreleased.
