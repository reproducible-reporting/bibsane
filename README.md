# BibSane

Sanitize BibTeX files without going insane.

BibSane is comparable to [bibexport](https://www.ctan.org/pkg/bibexport) and [checkcites](https://www.ctan.org/tex-archive/support/checkcites), but has a few important improvements.

Features:

- A single new cleaned bib file is written to replace the old ones.
  - Unused entries are discarded.
  - Missing entries result in an error.
  - Duplicates are reported and merged if safe.
  - Check for BibTeX keys that differ only by case.
  - Remove redundant braces (not in author, editor and title)
  - Optional configurable BibTeX database policies:
    - Drop irrelevant entry types
    - Remove cruft from BibTeX entries.
      One may add a field, such as `bibsane = {misc.url}` to support multiple policies for one
      BibTeX entry
    - Restrict the types of entries.
    - Disallow `@preamble`.
    - Strip newlines and redundant whitespace in fields.
    - Normalize DOI (lowercase and strip proxy)
    - Merge entries based on DOI and/or BibTeX ID.
    - Normalize page double hyphen
    - Abbreviated Journals, using [abbreviso](https://abbreviso.toolforge.org/).
    - Sort by year + author last name
- Hackable: written in Python and built on top of
  [`bibtexparser`](https://github.com/sciunto-org/python-bibtexparser).
- Configurable
- Cheerful terminal output
- Usable as a [`pre-commit`](https://pre-commit.com/) hook.


## Installation as standalone tool

```
pip install BibSane
```

## Usage

```bash
bibsane somefile.aux [-c someconfig.yaml]
```

The file [`exampleconfig.yaml`] can be used as a starting point for your configuration.

## Usage as a pre-commit hook

Add the following to your `.pre-commit-config.yaml`

```yaml
- repo: https://github.com/reproducible-reporting/bibsane
  rev: v0.1.0
  hooks:
    - id: bibsane
      # You may want to pass in a config file
      args ["-c someconfig.yaml"]
```

You also need to commit the `.aux` files to your Git history.

## Development

If you would like to contribute, please read [CONTRIBUTING.md](https://github.com/reproducible-reporting/.github/blob/main/CONTRIBUTING.md).
