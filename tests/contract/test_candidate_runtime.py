"""Runtime and core package import compatibility contract."""

import platform
import sys
from importlib.metadata import version

import jsonschema
import yaml

import aegisquant


def test_runtime_is_supported_and_core_packages_import() -> None:
    assert sys.version_info[:2] in {(3, 13), (3, 14)}
    assert platform.python_implementation() == "CPython"
    assert aegisquant.__version__ == "3.1.0.dev0"
    assert jsonschema.__name__ == "jsonschema"
    assert version("jsonschema") == "4.26.0"
    assert yaml.__version__ == "6.0.3"
