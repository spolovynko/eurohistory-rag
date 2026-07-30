"""Proves the package is installed and importable, not merely present on disk.

Under the src/ layout this test can only pass if `uv sync` installed the
project into the environment. If it fails with ImportError, the environment
is wrong -- not the code.
"""

import eurohistory_rag


def test_package_is_importable() -> None:
    assert eurohistory_rag.__version__ == "0.1.0"
