"""Unit tests for monitor.state — JSON round-trip + resilience."""

from monitor.state import _gcs_split, load_state, save_state


def test_gcs_split():
    assert _gcs_split("gs://my-bucket/path/to/state.json") == ("my-bucket", "path/to/state.json")
    assert _gcs_split("gs://only-bucket") == ("only-bucket", "")


def test_roundtrip(tmp_path):
    p = str(tmp_path / "state.json")
    state = {"date": "2026-06-08", "baseline": {"SPY": 589.25}, "refs": {"SPY": 589.25}}
    save_state(p, state)
    assert load_state(p) == state


def test_missing_returns_empty(tmp_path):
    assert load_state(str(tmp_path / "nope.json")) == {}


def test_corrupt_returns_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json")
    assert load_state(str(p)) == {}
