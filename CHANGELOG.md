# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.3] - 2023-06-27

### Fixed

- Added `note` as an exception where braces are allowed.
- Workaround for https://github.com/sciunto-org/python-bibtexparser/issues/384

## [0.1.2] - 2023-04-12

### Fixed

- The exit code was not always set correctly. This is fixed.

## [0.1.1] - 2023-03-24

### Fixed

- When searching for aux files, only select those with corresponding tex files.

## [0.1.0] - 2023-03-21

### Added

- Initial `bibsane` program.
