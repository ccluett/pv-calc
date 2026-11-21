"""Check what a release exposes: the built distributions and the change text.

    check_distribution.py dist DIST_DIR   the sdist and wheel in DIST_DIR
    check_distribution.py text            change text read from standard input

`dist` fails when an archive holds a file outside the lists below, so a new
shipped file is added here on purpose, and when a shipped text file carries
an authoring-tool name or attribution line. `text` applies the same text
rule to commit messages, a pull-request title and description, and a branch
name. Standard library only, so it runs before anything is installed.
"""

from __future__ import annotations

import re
import sys
import tarfile
import zipfile
from collections.abc import Callable
from pathlib import Path

# Relative to the sdist's single top-level directory.
SDIST_FILES = frozenset({
    "CHANGELOG.md", "CITATION.cff", "LICENSE", "MANIFEST.in", "PKG-INFO",
    "README.md", "pyproject.toml", "setup.cfg",
})
SDIST_METADATA = "pv_calc.egg-info/"
PACKAGE = "pv_calc/"
PACKAGE_DATA = frozenset({"pv_calc/py.typed", "pv_calc/data/materials.yaml"})

# Release text describes the change. It does not name the tool that wrote it
# or credit one as an author.
TOOL_TEXT = re.compile(
    r"\b(claude|anthropic|codex|openai|chatgpt|copilot)\b"
    r"|co-authored-by:"
    r"|generated (with|by)\b",
    re.IGNORECASE,
)


def _package_file(name: str) -> bool:
    return name.startswith(PACKAGE) and (name.endswith(".py") or name in PACKAGE_DATA)


def _text_findings(label: str, text: str) -> list[str]:
    return [
        f"{label}:{number}: {line.strip()[:120]}"
        for number, line in enumerate(text.splitlines(), start=1)
        if TOOL_TEXT.search(line)
    ]


def _check_members(
    label: str, members: dict[str, bytes], allowed: Callable[[str], bool],
) -> list[str]:
    findings = []
    for name, content in sorted(members.items()):
        if not allowed(name):
            findings.append(f"{label}: unexpected file {name}")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            findings.append(f"{label}: {name} is not UTF-8 text")
            continue
        findings += _text_findings(f"{label}:{name}", text)
    return findings


def check_sdist(path: Path) -> list[str]:
    with tarfile.open(path) as archive:
        files = [member for member in archive.getmembers() if member.isfile()]
        roots = {member.name.split("/", 1)[0] for member in archive.getmembers()}
        if len(roots) != 1:
            return [f"{path.name}: expected one top-level directory, found {sorted(roots)}"]
        members = {}
        for member in files:
            content = archive.extractfile(member)
            assert content is not None
            members[member.name.split("/", 1)[1]] = content.read()

    def allowed(name: str) -> bool:
        return name in SDIST_FILES or name.startswith(SDIST_METADATA) or _package_file(name)

    return _check_members(path.name, members, allowed)


def check_wheel(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        members = {
            name: archive.read(name) for name in archive.namelist() if not name.endswith("/")
        }
    metadata = re.compile(r"pv_calc-[^/]+\.dist-info/")

    def allowed(name: str) -> bool:
        return bool(metadata.match(name)) or _package_file(name)

    return _check_members(path.name, members, allowed)


def check_dist(directory: Path) -> list[str]:
    sdists = sorted(directory.glob("*.tar.gz"))
    wheels = sorted(directory.glob("*.whl"))
    if len(sdists) != 1 or len(wheels) != 1:
        return [
            f"{directory}: expected one sdist and one wheel, "
            f"found {len(sdists)} and {len(wheels)}"
        ]
    return check_sdist(sdists[0]) + check_wheel(wheels[0])


def main(arguments: list[str]) -> int:
    if len(arguments) == 2 and arguments[0] == "dist":
        findings = check_dist(Path(arguments[1]))
    elif arguments == ["text"]:
        findings = _text_findings("change text", sys.stdin.read())
    else:
        print(__doc__, file=sys.stderr)
        return 2
    for finding in findings:
        print(finding, file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
