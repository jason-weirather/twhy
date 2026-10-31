"""Protect NumPy compatibility and standard PDF support for CLI installations."""

from pathlib import Path
import tomllib

import pytest
from packaging.requirements import Requirement


PROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def numpy_requirement() -> Requirement:
    project = tomllib.loads(PROJECT.read_text(encoding="utf-8"))["project"]
    requirements = (Requirement(item) for item in project["dependencies"])
    matches = [item for item in requirements if item.name.lower() == "numpy"]
    assert len(matches) == 1
    return matches[0]


@pytest.mark.parametrize("version", ["1.26.4", "2.0.2", "2.2.6"])
def test_numpy_range_accepts_common_scientific_environments(version: str) -> None:
    # Numba 0.60 accepts NumPy 1.26.4 or 2.0.2; newer environments need 2.2 too.
    assert version in numpy_requirement().specifier


@pytest.mark.parametrize("version", ["1.26.3", "3.0.0"])
def test_numpy_range_respects_backend_floor_and_major_cap(version: str) -> None:
    assert version not in numpy_requirement().specifier


def test_pdfium_is_required_in_plain_install_and_s3_stays_optional() -> None:
    project = tomllib.loads(PROJECT.read_text(encoding="utf-8"))["project"]
    runtime = [Requirement(item) for item in project["dependencies"]]
    pdfium = [item for item in runtime if item.name.lower() == "pypdfium2"]
    assert len(pdfium) == 1
    assert "4.30" in pdfium[0].specifier
    assert "5.8.0" in pdfium[0].specifier
    assert "6.0.0" not in pdfium[0].specifier
    extras = project["optional-dependencies"]
    assert "pdf" not in extras
    assert "s3" in extras


def test_default_pdf_engine_is_importable() -> None:
    # PDF support is a normal runtime dependency, not an optional test lane.
    from pypdfium2 import PdfDocument

    assert callable(PdfDocument)


def test_distribution_import_and_command_share_twhy_name() -> None:
    project = tomllib.loads(PROJECT.read_text(encoding="utf-8"))["project"]
    assert project["name"] == "twhy"
    assert project["scripts"] == {"twhy": "twhy.cli:main"}
    assert project["urls"]["Repository"] == "https://github.com/jason-weirather/twhy"
    root = PROJECT.parent / "src"
    assert (root / "twhy" / "__init__.py").is_file()
    assert (root / "twhy" / "py.typed").is_file()
    assert [p.name for p in root.iterdir() if (p / "__init__.py").is_file()] == ["twhy"]


def test_zt_branch_requires_updated_omeify_for_both_plain_and_s3_installs():
    project = tomllib.loads(PROJECT.read_text(encoding="utf-8"))["project"]
    runtime = next(Requirement(r) for r in project["dependencies"]
                   if Requirement(r).name == "omeify")
    s3 = next(Requirement(r) for r in project["optional-dependencies"]["s3"]
              if Requirement(r).name == "omeify")
    for requirement in (runtime, s3):
        assert "0.22.1" not in requirement.specifier
        assert "0.22.2" in requirement.specifier
    assert "s3" in s3.extras
