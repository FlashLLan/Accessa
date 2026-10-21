"""scripts/seed_demo.py only ever talks to a local API and never hard-codes passwords."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "seed_demo.py"
spec = importlib.util.spec_from_file_location("seed_demo", SCRIPT)
seed_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_demo)


@pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1:8000", "https://localhost"])
def test_local_api_urls_are_accepted(url):
    seed_demo.assert_local_api(url)


@pytest.mark.parametrize("url", [
    "http://example.com:8000", "https://api.accessa.app", "http://10.0.0.5:8000",
    "http://localhost.evil.com", "ftp://localhost",
])
def test_non_local_api_urls_are_refused(url):
    with pytest.raises(SystemExit):
        seed_demo.assert_local_api(url)


def test_demo_password_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    with pytest.raises(SystemExit):
        seed_demo.demo_password()
    monkeypatch.setenv("DEMO_PASSWORD", "short")
    with pytest.raises(SystemExit):
        seed_demo.demo_password()
    monkeypatch.setenv("DEMO_PASSWORD", "long-enough")
    assert seed_demo.demo_password() == "long-enough"


def test_script_contains_no_password_literal():
    source = SCRIPT.read_text()
    assert "123456" not in source and "password=\"" not in source.replace(" ", "")
