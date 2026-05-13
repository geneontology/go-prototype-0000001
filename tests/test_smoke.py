"""Smoke test: the package imports cleanly."""


def test_package_imports() -> None:
    import gocam_prototype

    assert gocam_prototype.__version__
