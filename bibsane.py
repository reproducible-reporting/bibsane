#!/usr/bin/env python3
# BibSane helps you sanitize BibTeX files without going insane.
# Copyright (C) 2023 Toon Verstraelen
#
# This file is part of BibSane.
#
# BibSane is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.
#
# BibSane is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>
#
# --
"""BibSane main program."""


import argparse
import enum
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
from glob import glob

import attrs
import bibtexparser
import cattrs
import yaml


@enum.unique
class DuplicatePolicy(enum.Enum):
    """The three policies for duplicate entries."""

    FAIL = "fail"
    MERGE = "merge"
    IGNORE = "ignore"


@enum.unique
class FieldPolicy(enum.Enum):
    """The two policies for bibliography fields."""

    MUST = "must"
    MAY = "may"


@attrs.define
class Config:
    """The configuration object controling BibSane behavior.

    Note that the settings default the most permissive and least invasive ones.
    We recommend the opposite settings, but you have to switch knowingly in the config file.
    """

    root: str = attrs.field(init=False, default=None)

    bibtex_out: str = attrs.field(default="references.bib")
    drop_entry_types: list[str] = attrs.field(default=attrs.Factory(list))
    normalize_doi: bool = attrs.field(default=False)
    duplicate_id: DuplicatePolicy = attrs.field(default=DuplicatePolicy.IGNORE)
    duplicate_doi: DuplicatePolicy = attrs.field(default=DuplicatePolicy.IGNORE)
    preambles_allowed: bool = attrs.field(default=True)
    normalize_whitespace: bool = attrs.field(default=False)
    normalize_names: bool = attrs.field(default=False)
    fix_page_double_hyphen: bool = attrs.field(default=False)
    abbreviate_journal: str = attrs.field(default=None)
    # sort key = {year}{first author lowercase last name}
    sort: bool = attrs.field(default=False)
    citation_policies: dict[str, dict[str, FieldPolicy]] = attrs.field(default=attrs.Factory(dict))

    @classmethod
    def from_file(cls, fn_yaml):
        if fn_yaml is None:
            config = Config()
            config.root = os.getcwd()
        else:
            with open(fn_yaml) as f:
                data = yaml.safe_load(f)
                config = cattrs.structure(data, Config)
            config.root = os.path.dirname(fn_yaml)
        return config


RETURN_CODE_UNCHANGED = 0
RETURN_CODE_CHANGED = 1
RETURN_CODE_BROKEN = 2


def main():
    fns_aux, config, verbose = parse_args()
    if len(fns_aux) == 0:
        # Only select aux files for which corresponding tex files exist.
        fns_aux = [
            fn for fn in glob("**/*.aux", recursive=True) if os.path.isfile(fn[:-4] + ".tex")
        ]
    first = True
    for fn_aux in fns_aux:
        if first:
            first = False
        else:
            print()
        process_aux(fn_aux, config, verbose)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser("bibsane")
    parser.add_argument("aux", nargs="*", help="The LaTeX aux file of your document")
    parser.add_argument("-q", "--quiet", default=False, action="store_true")
    parser.add_argument("-c", "--config", help="An optional configuration file")
    args = parser.parse_args()
    config = Config.from_file(args.config)
    return args.aux, config, not args.quiet


def process_aux(fn_aux, config, verbose):
    """Main program."""
    # Load the aux file.
    if not fn_aux.endswith(".aux"):
        if verbose:
            print("Please, give an aux file as command-line argument, got:", fn_aux)
        return RETURN_CODE_BROKEN
    else:
        if verbose:
            print("📂 Loading", fn_aux)
        citations, fns_bib = parse_aux(fn_aux)

    if verbose:
        print(f"   Found {len(citations)} citations")
    citations = set(citations)
    if verbose:
        print(f"   Found {len(citations)} unique citations")
    if len(citations) == 0:
        if verbose:
            print("   ❓ Ignoring aux file because there are no citations.")
        return RETURN_CODE_UNCHANGED
    if len(fns_bib) == 0:
        if verbose:
            print("   ❓ Ignoring aux file because it does not refer to no BibTeX files.")
        return RETURN_CODE_UNCHANGED

    # Collect entries
    if verbose:
        print("📂 Loading", " ".join(fns_bib))
    entries, valid_duplicates = collect_entries(fns_bib, config)
    if verbose:
        print(f"   Found {len(entries)} BibTeX entries")
    retcode = RETURN_CODE_CHANGED if valid_duplicates else RETURN_CODE_BROKEN

    # Drop unused and check for missing
    if verbose:
        print("🔨 Checking unused and missing citations")
    entries, bibdata_complete = drop_check_citations(entries, citations, config.drop_entry_types)
    if not bibdata_complete:
        retcode = RETURN_CODE_BROKEN
    if verbose:
        print(f"   Found {len(entries)} used BibTeX entries")

    # Clean entries
    if len(config.citation_policies) > 0:
        if verbose:
            print("🔨 Validating citation policies")
        entries, valid_fields = clean_entries(entries, config.citation_policies)
        if not valid_fields:
            retcode = RETURN_CODE_BROKEN

    # Clean up things that should never be there, not optional
    if verbose:
        print("🔨 Fixing bad practices")
    entries = fix_bad_practices(entries)

    # Check for potential problems that cannot be fixed automatically, not optional.
    if verbose:
        print("🔨 Checking for potential mistakes in BibTeX keys")
    if potential_mistakes(entries):
        retcode = RETURN_CODE_BROKEN

    # Normalize the DOIs (lowercase and remove prefix)
    if config.normalize_doi:
        if verbose:
            print("🔨 Normalizing dois")
        entries, valid_dois = normalize_doi(entries)
        if not valid_dois:
            retcode = RETURN_CODE_BROKEN

    # Remove newlines
    if config.normalize_whitespace:
        if verbose:
            print("🔨 Normalizing whitespace")
        entries = normalize_whitespace(entries)

    # Normalize author and editor names
    if config.normalize_names:
        if verbose:
            print("🔨 Normalizing author and editor names")
        entries = normalize_names(entries)

    # Fix page double hyphen
    if config.fix_page_double_hyphen:
        if verbose:
            print("🔨 Fixing double hyphen in page ranges")
        entries = fix_page_double_hyphen(entries)

    # Abbreviate journal names
    if config.abbreviate_journal is not None:
        if verbose:
            print("🔨 Abbreviating journal names")
        fn_cache = os.path.join(config.root, config.abbreviate_journal)
        entries = abbreviate_journal_iso(entries, fn_cache)

    # Merge entries
    if config.duplicate_id == DuplicatePolicy.MERGE:
        if verbose:
            print("🔨 Merging references by BibTeX ID")
        entries, merge_conflict = merge_entries(entries, "ID")
        if merge_conflict:
            retcode = RETURN_CODE_BROKEN
        if verbose:
            print(f"   Reduced to {len(entries)} BibTeX entries by merging duplicate BibTeX IDs")
    if config.duplicate_doi == DuplicatePolicy.MERGE:
        if verbose:
            print("🔨 Merging references by DOI")
        entries, merge_conflict = merge_entries(entries, "doi")
        if merge_conflict:
            retcode = RETURN_CODE_BROKEN
        if verbose:
            print(f"   Reduced to {len(entries)} BibTeX entries by merging duplicate DOIs")

    # Sort entries
    if config.sort:
        if verbose:
            print("🔨 Sorting by Year + First author")
        entries = sort_entries(entries)

    # Overwrite if needed.
    fn_out = os.path.join(os.path.dirname(fn_aux), config.bibtex_out)
    return write_output(entries, fn_out, retcode, verbose)


def parse_aux(fn_aux):
    """Parse the relevant parts of a LaTeX aux file."""
    root = os.path.dirname(fn_aux)
    citations = []
    bibdata = []
    with open(fn_aux) as f:
        for line in f:
            parse_aux_line("citation", line, citations)
            parse_aux_line("bibdata", line, bibdata)
    fns_bib = []
    for fn_bib in bibdata:
        if not fn_bib.endswith(".bib"):
            fn_bib += ".bib"
        fns_bib.append(os.path.join(root, fn_bib))
    return citations, fns_bib


def parse_aux_line(prefix, line, words):
    """Parse a (simple) line from a LaTeX aux file."""
    if line.startswith(rf"\{prefix}{{"):
        assert line.endswith("}\n")
        assert line.count("{") == 1
        assert line.count("}") == 1
        words.extend(line[line.find("{") + 1 : -2].split(","))


def collect_entries(fns_bib, config):
    """Collect entries from multiple BibTeX files."""
    # Collect stuff
    seen_ids = set()
    seen_dois = set()
    entries = []
    valid = True
    for fn_bib in fns_bib:
        bibtex_parser = bibtexparser.bparser.BibTexParser(
            homogenize_fields=True,
            ignore_nonstandard_types=False,
        )
        with open(fn_bib) as f:
            db_in = bibtexparser.load(f, bibtex_parser)
        if len(db_in.preambles) > 0 and not config.preambles_allowed:
            print("   🤖 @preamble is not allowed")
            valid = False
        for entry in db_in.entries:
            if entry["ID"] in seen_ids and config.duplicate_id == DuplicatePolicy.FAIL:
                print(f"  ‼️ Duplicate BibTeX entry: {entry['ID']}")
                valid = False
            if "doi" in entry:
                if entry["doi"] in seen_dois and config.duplicate_doi == DuplicatePolicy.FAIL:
                    print(f"‼  ️ Duplicate DOI: {entry['doi']}")
                    valid = False
                seen_dois.add(entry["doi"])
            entries.append(entry)
            seen_ids.add(entry["ID"])
    return entries, valid


def drop_check_citations(entries, citations, drop):
    """Drop unused citations and complain about missing ones."""
    # Drop unused entries
    result = []
    for entry in entries:
        if entry["ID"] not in citations:
            print("     Dropping unused id:", entry["ID"])
            continue
        if entry["ENTRYTYPE"] in drop:
            print("     Dropping irrelevant entry type:", entry["ENTRYTYPE"])
            continue
        result.append(entry)

    # Check for undefined references
    defined = {entry["ID"] for entry in entries}
    valid = True
    for citation in citations:
        if citation not in defined:
            print("   💀 Missing reference:", citation)
            valid = False

    return result, valid


def clean_entries(entries, citation_policies):
    """Clean the irrelevant fields in each entry and complain about missing ones."""
    cleaned = []
    valid = True
    for old_entry in entries:
        eid = old_entry.pop("ID")
        etype = old_entry.pop("ENTRYTYPE")
        new_entry = {"ENTRYTYPE": etype, "ID": eid}
        if "bibsane" in old_entry:
            etype = old_entry.pop("bibsane")
            new_entry["bibsane"] = etype
        policy = citation_policies.get(etype)
        if policy is None:
            print(f"   🤔 {eid}: @{etype} is not configured")
            valid = False
            continue
        cleaned.append(new_entry)
        for field, policy in policy.items():
            if policy == FieldPolicy.MUST:
                if field not in old_entry:
                    print(f"   🫥 {eid}: @{etype} missing field {field}")
                    valid = False
                else:
                    new_entry[field] = old_entry.pop(field)
            else:
                assert policy == FieldPolicy.MAY
                if field in old_entry:
                    new_entry[field] = old_entry.pop(field)
        if len(old_entry) > 0:
            for field in old_entry:
                print(f"   💨 {eid}: @{etype} discarding field {field}")
    return cleaned, valid


def fix_bad_practices(entries):
    """Fix unwarranted use of braces."""
    result = []
    for old_record in entries:
        # Strip all braces
        new_record = {
            key: value.replace("{", "").replace("}", "") for (key, value) in old_record.items()
        }
        # Except from the author, editor or title
        for field in "author", "editor", "title":
            if field in old_record:
                new_record[field] = old_record[field]
        result.append(new_record)
    return result


def potential_mistakes(entries):
    id_case_map = {}
    for entry in entries:
        id_case_map.setdefault(entry["ID"].lower(), []).append(entry["ID"])

    mistakes = False
    for groups in id_case_map.values():
        if len(groups) > 1:
            print("   👻 BibTeX entry keys that only differ by case:", " ".join(groups))
            mistakes = True
    return mistakes


DOI_PROXIES = [
    "https://doi.org/",
    "http://doi.org/",
    "http://dx.doi.org/",
    "https://dx.doi.org/",
    "doi:",
]


def normalize_doi(entries):
    """Normalize the DOIs in the entries."""
    result = []
    value = True
    for entry in entries:
        doi = entry.get("doi")
        if doi is not None:
            doi = doi.lower()
            for proxy in DOI_PROXIES:
                if doi.startswith(proxy):
                    doi = doi[len(proxy) :]
                    break
            if doi.count("/") == 0 or not doi.startswith("10."):
                print("   🤕 invalid DOI:", doi)
                value = False
            entry = entry | {"doi": doi}
        result.append(entry)
    return result, value


def normalize_whitespace(entries):
    """Normalize the whitespace inside the field values."""
    return [{key: re.sub(r"\s+", " ", value) for key, value in entry.items()} for entry in entries]


def normalize_names(entries):
    """Normalize the author and editor names."""
    raise NotImplementedError("processing of names is not robust in BibtexParser 1.4.0")
    result = []
    for entry in entries:
        # Warning: bibtexparser modifies entries in place.
        # It does not hurt in this case, but it can otherwise give unexpected results.
        for field in "author", "editor":
            if field in entry:
                splitter = getattr(bibtexparser.customization, field)
                entry = splitter(entry)
                names = entry[field]
                names = [bibtexparser.latexenc.latex_to_unicode(name) for name in names]
                names = [bibtexparser.latexenc.string_to_latex(name) for name in names]
                entry[field] = " and ".join(names)
        result.append(entry)
    return result


def fix_page_double_hyphen(entries):
    """Fix page ranges for which no double hyphen is used."""
    result = []
    for entry in entries:
        # Warning: bibtexparser modifies entries in place.
        # It does not hurt in this case, but it can otherwise give unexpected results.
        entry = bibtexparser.customization.page_double_hyphen(entry)
        result.append(entry)
    return result


def abbreviate_journal_iso(entries, fn_cache):
    """Replace journal names by their ISO abbreviation."""

    # Initialize cache
    if fn_cache is None or not os.path.isfile(fn_cache):
        cache = {}
    else:
        with open(fn_cache) as f:
            cache = json.load(f)

    # Abbreviate journals
    result = []
    for entry in entries:
        journal = entry.get("journal")
        if journal is not None and "." not in journal:
            abbrev = cache.get(journal)
            if abbrev is None:
                abbrev = download_abbrev(journal)
                cache[journal] = abbrev
            entry = entry | {"journal": abbrev}
        result.append(entry)

    # Store cache
    if fn_cache is not None:
        with open(fn_cache, "w") as f:
            json.dump(cache, f, indent=2)
            f.write("\n")
    return result


def download_abbrev(journal):
    print("   Downloading abbreviation for:", journal)
    journal_quote = urllib.parse.quote(journal)
    prefix = "https://abbreviso.toolforge.org/abbreviso/a/"
    with urllib.request.urlopen(prefix + journal_quote) as f:
        return f.read().decode()


def merge_entries(entries, field):
    """Merge entries who have the same value for the given field. (case-insensitive)"""
    lookup = {}
    missing_key = []
    merge_conflict = False
    for entry in entries:
        identifier = entry.get(field)
        if identifier is None:
            print(f"   👽 Cannot merge entry without {field}:", entry["ID"])
            missing_key.append(entry)
        else:
            other = lookup.setdefault(identifier, {})
            for key, value in entry.items():
                if key not in other:
                    other[key] = value
                elif other[key] != value:
                    print(f"   😭 Same {field}={identifier}, different {key}:", value, other[key])
                    merge_conflict = True
    return list(lookup.values()) + missing_key, merge_conflict


def sort_entries(entries):
    """Sort the entries in convenient way: by year, then by author."""

    def keyfn(entry):
        # Make a fake entry to avoid in-place modification.
        entry = {"author": entry.get("author", "Aaaa Aaaa"), "year": entry.get("year", "0000")}
        first_author = bibtexparser.customization.author(entry)["author"][0].lower()
        key = entry["year"] + first_author
        return key

    return sorted(entries, key=keyfn)


def write_output(entries, fn_out, retcode, verbose):
    if retcode == RETURN_CODE_CHANGED:
        # Write out a single BibTeX database.
        db_out = bibtexparser.bibdatabase.BibDatabase()
        db_out.entries = entries
        writer = bibtexparser.bwriter.BibTexWriter()
        writer.order_entries_by = None
        with tempfile.TemporaryDirectory("bibsane") as dn_tmp:
            fn_tmp = os.path.join(dn_tmp, "tmp.bib")
            with open(fn_tmp, "w") as f:
                bibtexparser.dump(db_out, f, writer)
            if os.path.isfile(fn_out):
                old_hash = checksum(fn_out)
                new_hash = checksum(fn_tmp)
                if old_hash == new_hash:
                    retcode = RETURN_CODE_UNCHANGED
            if retcode == RETURN_CODE_CHANGED:
                print("💾 Please check the new or corrected file:", fn_out)
                shutil.copy(fn_tmp, fn_out)
            elif verbose:
                print("😀 No changes to", fn_out)
    else:
        print(f"💥 Broken bibliography. Not writing: {fn_out}")

    return retcode


def checksum(path):
    """Compute the SHA256 checksum from the contents of a file."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).digest()


if __name__ == "__main__":
    main()
