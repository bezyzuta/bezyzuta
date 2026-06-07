"""Tests for the local Claude CLI provider: claude_cli_complete() and the
_complete_text() dispatcher. All subprocess / network calls are mocked —
no real `claude` CLI or Gemini key needed.
"""

import json
import subprocess
from unittest.mock import patch, MagicMock

import pytest

import pipeline


class _Cfg:
    """Minimal stand-in for pipeline.Config."""
    def __init__(self, **kw):
        self.use_claude_cli = kw.get("use_claude_cli", True)
        self.claude_cli_model = kw.get("claude_cli_model", "sonnet")
        self.claude_cli_path = kw.get("claude_cli_path", "claude")
        self.gemini_api_key = kw.get("gemini_api_key", "AIza_fake")
        self.gemini_model = kw.get("gemini_model", "gemini-2.5-flash")


@pytest.fixture(autouse=True)
def _reset_cli_cache():
    """The resolved-path check is module-cached; reset between tests."""
    pipeline._CLAUDE_CLI_PATH = None
    yield
    pipeline._CLAUDE_CLI_PATH = None


def _completed(stdout="", returncode=0, stderr=""):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


class TestClaudeCliComplete:
    def test_not_installed_returns_none(self):
        with patch("shutil.which", return_value=None):
            assert pipeline.claude_cli_complete("hi", _Cfg()) is None

    def test_json_envelope_result_field(self):
        env = json.dumps({"type": "result", "result": "the answer", "is_error": False})
        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("subprocess.run", return_value=_completed(stdout=env)):
            assert pipeline.claude_cli_complete("hi", _Cfg()) == "the answer"

    def test_raw_text_stdout_fallback(self):
        # Some output formats print raw text, not JSON.
        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("subprocess.run", return_value=_completed(stdout="plain text answer")):
            assert pipeline.claude_cli_complete("hi", _Cfg()) == "plain text answer"

    def test_content_blocks_envelope(self):
        env = json.dumps({"content": [{"text": "part1 "}, {"text": "part2"}]})
        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("subprocess.run", return_value=_completed(stdout=env)):
            assert pipeline.claude_cli_complete("hi", _Cfg()) == "part1 part2"

    def test_nonzero_exit_returns_none(self):
        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("subprocess.run", return_value=_completed(stdout="", returncode=1, stderr="boom")):
            assert pipeline.claude_cli_complete("hi", _Cfg()) is None

    def test_timeout_returns_none(self):
        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 180)):
            assert pipeline.claude_cli_complete("hi", _Cfg()) is None

    def test_empty_stdout_returns_none(self):
        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("subprocess.run", return_value=_completed(stdout="   ")):
            assert pipeline.claude_cli_complete("hi", _Cfg()) is None

    def test_model_flag_passed(self):
        env = json.dumps({"result": "ok"})
        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("subprocess.run", return_value=_completed(stdout=env)) as run_mock:
            pipeline.claude_cli_complete("hi", _Cfg(claude_cli_model="opus"))
        cmd = run_mock.call_args[0][0]
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "opus"
        assert "-p" in cmd
        assert "--output-format" in cmd

    def test_no_model_flag_when_empty(self):
        env = json.dumps({"result": "ok"})
        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("subprocess.run", return_value=_completed(stdout=env)) as run_mock:
            pipeline.claude_cli_complete("hi", _Cfg(claude_cli_model=""))
        cmd = run_mock.call_args[0][0]
        assert "--model" not in cmd

    def test_prompt_passed_via_stdin_not_argv(self):
        """Windows command-line length safety: the (potentially huge)
        prompt must go through stdin, never as an argv element."""
        env = json.dumps({"result": "ok"})
        big_prompt = "TRANSCRIPT " * 10000  # ~110KB — over Windows' 32KB argv cap
        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("subprocess.run", return_value=_completed(stdout=env)) as run_mock:
            pipeline.claude_cli_complete(big_prompt, _Cfg())
        cmd = run_mock.call_args[0][0]
        kwargs = run_mock.call_args[1]
        # Prompt is on stdin...
        assert kwargs.get("input") == big_prompt
        # ...and NOT anywhere in argv.
        assert big_prompt not in cmd
        assert all(big_prompt not in str(arg) for arg in cmd)


class TestCompleteTextDispatch:
    """_complete_text: Claude-first when enabled, Gemini fallback otherwise."""

    def _gemini_body(self):
        return {"contents": [{"parts": [{"text": "prompt"}]}]}

    def test_claude_used_when_enabled_and_available(self):
        env = json.dumps({"result": "from claude"})
        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("subprocess.run", return_value=_completed(stdout=env)):
            out = pipeline._complete_text(
                "prompt", _Cfg(use_claude_cli=True),
                prefer_claude=True, gemini_body=self._gemini_body(),
            )
        assert out == "from claude"

    def test_falls_back_to_gemini_when_claude_unavailable(self):
        gem_resp = {"candidates": [{"content": {"parts": [{"text": "from gemini"}]}}]}
        with patch("shutil.which", return_value=None), \
             patch("pipeline._gemini_post", return_value=gem_resp):
            out = pipeline._complete_text(
                "prompt", _Cfg(use_claude_cli=True),
                prefer_claude=True, gemini_body=self._gemini_body(),
            )
        assert out == "from gemini"

    def test_falls_back_when_claude_errors(self):
        gem_resp = {"candidates": [{"content": {"parts": [{"text": "from gemini"}]}}]}
        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("subprocess.run", return_value=_completed(returncode=1, stderr="x")), \
             patch("pipeline._gemini_post", return_value=gem_resp):
            out = pipeline._complete_text(
                "prompt", _Cfg(use_claude_cli=True),
                prefer_claude=True, gemini_body=self._gemini_body(),
            )
        assert out == "from gemini"

    def test_gemini_used_when_claude_disabled(self):
        gem_resp = {"candidates": [{"content": {"parts": [{"text": "from gemini"}]}}]}
        # Even though prefer_claude=True, use_claude_cli=False → straight to Gemini.
        with patch("subprocess.run") as run_mock, \
             patch("pipeline._gemini_post", return_value=gem_resp):
            out = pipeline._complete_text(
                "prompt", _Cfg(use_claude_cli=False),
                prefer_claude=True, gemini_body=self._gemini_body(),
            )
        assert out == "from gemini"
        run_mock.assert_not_called()

    def test_prefer_claude_false_skips_cli(self):
        gem_resp = {"candidates": [{"content": {"parts": [{"text": "from gemini"}]}}]}
        with patch("subprocess.run") as run_mock, \
             patch("pipeline._gemini_post", return_value=gem_resp):
            out = pipeline._complete_text(
                "prompt", _Cfg(use_claude_cli=True),
                prefer_claude=False, gemini_body=self._gemini_body(),
            )
        assert out == "from gemini"
        run_mock.assert_not_called()

    def test_no_backend_raises(self):
        # Claude disabled + no gemini key → hard error.
        with pytest.raises(RuntimeError):
            pipeline._complete_text(
                "prompt", _Cfg(use_claude_cli=False, gemini_api_key=""),
                prefer_claude=True, gemini_body=self._gemini_body(),
            )
