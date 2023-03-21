# Development notes

## How to make releases

- Mark release in `CHANGELOG.md`
- Modify version in `pyproject.toml`
- Run `python3 -m build`
- Run `python3 -m twine upload dist/*`
