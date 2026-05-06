import pytest

def test_import_main():
    from api.main import app
    assert app is not None
