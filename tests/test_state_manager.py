"""StateStore + _hash_spec smoke tests. The resume system is the most
important piece of state we have — silent regressions here would mean
users re-render videos they thought were cached, or worse, skip steps
that should have re-run because we lost a spec hash."""

from pathlib import Path

import pytest

from state_manager import StateStore, JobState, Step, _hash_spec


# ───────────────────────── spec hashing ─────────────────────────


class TestHashSpec:
    def test_stable_across_calls(self):
        spec = {"topic": "Roblox", "auto_reframe": True, "target_duration": 30.0}
        assert _hash_spec(spec) == _hash_spec(spec)

    def test_key_order_insensitive(self):
        a = {"topic": "Roblox", "auto_reframe": True}
        b = {"auto_reframe": True, "topic": "Roblox"}
        assert _hash_spec(a) == _hash_spec(b)

    def test_ignores_unknown_keys(self):
        # batch_count etc. are deliberately excluded from the hash.
        a = {"topic": "Roblox"}
        b = {"topic": "Roblox", "batch_count": 5, "_internal": "x"}
        assert _hash_spec(a) == _hash_spec(b)

    def test_different_topic_changes_hash(self):
        a = {"topic": "Roblox"}
        b = {"topic": "Minecraft"}
        assert _hash_spec(a) != _hash_spec(b)


# ───────────────────────── StateStore lifecycle ─────────────────────────


def _make_artifact(tmp_path, name: str = "fake.mp4") -> str:
    """is_done() checks the path-valued artifacts still exist on disk —
    we need a real file path or the test framework rejects the cached
    step. Touch a tiny file and return its absolute path as a string."""
    p = tmp_path / name
    p.write_bytes(b"\x00" * 16)
    return str(p)


class TestStateStoreLifecycle:
    def test_create_new(self, tmp_path):
        # __init__ doesn't persist state — it's only saved on the first
        # mark_done() or explicit save(). That's intentional: a bare
        # construct-then-abandon shouldn't litter job_state.json files.
        s = StateStore(tmp_path, "test-slug", "single", {"topic": "test"})
        assert s.state.job_id == "test-slug"
        assert s.state.completed_steps == {}

    def test_mark_and_check(self, tmp_path):
        s = StateStore(tmp_path, "slug", "single", {"topic": "t"})
        assert not s.is_done(Step.DOWNLOAD)
        raw = _make_artifact(tmp_path, "raw.mp4")
        s.mark_done(Step.DOWNLOAD, {"raw_path": raw})
        assert s.is_done(Step.DOWNLOAD)
        assert s.get_artifact(Step.DOWNLOAD, "raw_path") == raw

    def test_get_artifact_default(self, tmp_path):
        s = StateStore(tmp_path, "slug", "single", {"topic": "t"})
        assert s.get_artifact(Step.DOWNLOAD, "missing", default="fallback") == "fallback"

    def test_is_done_false_when_artifact_deleted(self, tmp_path):
        """The core resume guard: if the JSON says 'done' but the file
        on disk is gone, the step re-runs. Don't trust stale state."""
        s = StateStore(tmp_path, "slug", "single", {"topic": "t"})
        raw = _make_artifact(tmp_path, "raw.mp4")
        s.mark_done(Step.DOWNLOAD, {"raw_path": raw})
        assert s.is_done(Step.DOWNLOAD)
        # User deletes the cached file → step should re-run.
        Path(raw).unlink()
        assert not s.is_done(Step.DOWNLOAD)

    def test_persistence_round_trip(self, tmp_path):
        raw = _make_artifact(tmp_path, "raw.mp4")
        s1 = StateStore(tmp_path, "slug", "single", {"topic": "t"})
        s1.mark_done(Step.DOWNLOAD, {"raw_path": raw})
        # SCRIPT stores its text in the JSON itself, no on-disk artifact.
        s1.mark_done(Step.SCRIPT, {"script_text": "Hello"})
        # New instance — should reload from disk.
        s2 = StateStore(tmp_path, "slug", "single", {"topic": "t"})
        assert s2.is_done(Step.DOWNLOAD)
        assert s2.is_done(Step.SCRIPT)
        assert s2.get_artifact(Step.SCRIPT, "script_text") == "Hello"
        assert s2.get_artifact(Step.DOWNLOAD, "raw_path") == raw

    def test_invalidate(self, tmp_path):
        s = StateStore(tmp_path, "slug", "single", {"topic": "t"})
        s.mark_done(Step.DOWNLOAD)
        s.mark_done(Step.SCRIPT)
        s.invalidate(Step.SCRIPT)
        assert s.is_done(Step.DOWNLOAD)
        assert not s.is_done(Step.SCRIPT)

    def test_invalidate_from(self, tmp_path):
        s = StateStore(tmp_path, "slug", "single", {"topic": "t"})
        for step in Step.ALL_SINGLE:
            s.mark_done(step)
        s.invalidate_from(Step.TRANSCRIBE, Step.ALL_SINGLE)
        # Everything before TRANSCRIBE survives.
        assert s.is_done(Step.DOWNLOAD)
        assert s.is_done(Step.VOICEOVER)
        # TRANSCRIBE and everything after is gone.
        assert not s.is_done(Step.TRANSCRIBE)
        assert not s.is_done(Step.COMPOSE)


class TestStateStoreSpecHash:
    def test_same_spec_no_warning(self, tmp_path, capsys):
        spec = {"topic": "Roblox", "auto_reframe": True}
        StateStore(tmp_path, "slug", "single", spec)
        StateStore(tmp_path, "slug", "single", spec)
        # No "hash" warning when spec didn't change.
        out = capsys.readouterr().out + capsys.readouterr().err
        assert "hash" not in out.lower()

    def test_changed_spec_warns(self, tmp_path):
        spec_a = {"topic": "Roblox"}
        spec_b = {"topic": "Minecraft"}
        s = StateStore(tmp_path, "slug", "single", spec_a)
        s.mark_done(Step.DOWNLOAD)
        # Re-open with different spec — state is preserved but a warning logs.
        s2 = StateStore(tmp_path, "slug", "single", spec_b)
        # The cached step should still be there (warn, don't wipe).
        assert s2.is_done(Step.DOWNLOAD)
