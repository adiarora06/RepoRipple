import json
import urllib.error

import pytest

from reporipple.cli import main
from reporipple.explain import (
    MAX_COMPLETION_PRICE_PER_MILLION,
    MAX_PROMPT_PRICE_PER_MILLION,
    REQUEST_TIMEOUT_SECONDS,
    ExplanationError,
    build_evidence_bundle,
    build_openrouter_request,
    explain_report,
    render_explanation_markdown,
)
from reporipple.models import ImpactedFile, ImpactReport


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return json.dumps(self.payload).encode()


def private_report() -> ImpactReport:
    return ImpactReport(
        repository="alice-private-checkout",
        changed_files=["src/alice/payment/secret.py"],
        impacted_files=[
            ImpactedFile(
                "src/alice/payment/handler.py",
                1,
                ("src/alice/payment/secret.py", "src/alice/payment/handler.py"),
            )
        ],
        suggested_tests=["tests/test_payment_handler.py"],
        documentation_to_review=["README.private.md"],
        risk_level="high",
        risk_reasons=["Sensitive area changed: payment"],
        graph_files=14,
        graph_edges=22,
        warnings=["Could not parse src/alice/payment/secret.py: private token"],
    )


def api_response(evidence_id="E001"):
    explanation = {
        "summary": "The deterministic analysis marks this as high risk.",
        "findings": [
            {"text": "The change has a direct dependent.", "evidence_ids": [evidence_id, "E002"]}
        ],
        "actions": [{"text": "Run the suggested verification.", "evidence_ids": ["E003"]}],
        "caveats": ["This narrative does not inspect source code."],
    }
    return {
        "model": "openai/gpt-5-mini-2026-08-07",
        "choices": [{"message": {"content": json.dumps(explanation)}}],
        "usage": {
            "prompt_tokens": 181,
            "completion_tokens": 72,
            "total_tokens": 253,
            "cost": 0.000189,
        },
    }


def test_evidence_payload_excludes_private_repository_data():
    bundle = build_evidence_bundle(private_report())
    request = build_openrouter_request(bundle)
    serialized = json.dumps(request, sort_keys=True)

    for private_value in (
        "alice-private-checkout",
        "src/",
        "alice",
        "payment",
        "secret.py",
        "handler.py",
        "README.private.md",
        "private token",
    ):
        assert private_value not in serialized

    assert set(bundle.local_labels) == {"E001", "E002", "E003", "E004"}
    assert bundle.payload["impacted"][0]["via"] == ["E001", "E002"]
    assert bundle.payload["risk_signals"] == [{"evidence_id": "E004", "category": "sensitive_area"}]


def test_request_enforces_privacy_schema_and_price_controls():
    request = build_openrouter_request(build_evidence_bundle(private_report()))

    assert request["provider"] == {
        "zdr": True,
        "data_collection": "deny",
        "require_parameters": True,
        "max_price": {
            "prompt": MAX_PROMPT_PRICE_PER_MILLION,
            "completion": MAX_COMPLETION_PRICE_PER_MILLION,
        },
    }
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["usage"] == {"include": True}
    assert "OPENROUTER_API_KEY" not in json.dumps(request)
    assert "user" not in request
    assert "metadata" not in request


def test_explanation_uses_environment_key_and_reports_usage(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret-key")
    seen = {}

    def opener(request, *, timeout):
        seen["authorization"] = request.headers["Authorization"]
        seen["payload"] = json.loads(request.data)
        seen["timeout"] = timeout
        return FakeResponse(api_response())

    bundle, result = explain_report(private_report(), opener=opener)

    assert seen["authorization"] == "Bearer test-secret-key"
    assert seen["timeout"] == REQUEST_TIMEOUT_SECONDS
    assert "alice" not in json.dumps(seen["payload"])
    assert result.model == "openai/gpt-5-mini-2026-08-07"
    assert result.usage.total_tokens == 253
    assert result.usage.cost_usd == 0.000189
    assert bundle.local_labels["E001"] == "changed file: src/alice/payment/secret.py"


def test_unknown_model_evidence_is_rejected(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret-key")

    with pytest.raises(ExplanationError, match="cited invalid evidence"):
        explain_report(
            private_report(),
            opener=lambda *args, **kwargs: FakeResponse(api_response("E999")),
        )


def test_extra_model_fields_are_rejected_locally(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret-key")
    response = api_response()
    explanation = json.loads(response["choices"][0]["message"]["content"])
    explanation["unexpected"] = "not allowed"
    response["choices"][0]["message"]["content"] = json.dumps(explanation)

    with pytest.raises(ExplanationError, match="required schema"):
        explain_report(private_report(), opener=lambda *args, **kwargs: FakeResponse(response))


def test_transient_failure_retries_only_once(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret-key")
    calls = []
    delays = []

    def opener(request, *, timeout):
        calls.append((request, timeout))
        if len(calls) == 1:
            raise urllib.error.URLError("temporary outage")
        return FakeResponse(api_response())

    explain_report(private_report(), opener=opener, sleep=delays.append)

    assert len(calls) == 2
    assert delays == [0.25]


def test_authentication_failure_is_not_retried(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret-key")
    calls = []
    delays = []

    def opener(request, *, timeout):
        calls.append((request, timeout))
        raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, None)

    with pytest.raises(ExplanationError, match="HTTP 401"):
        explain_report(private_report(), opener=opener, sleep=delays.append)

    assert len(calls) == 1
    assert delays == []


def test_missing_key_is_a_local_error_without_network(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(ExplanationError, match="OPENROUTER_API_KEY is not set"):
        explain_report(
            private_report(),
            opener=lambda *args, **kwargs: pytest.fail("network should not be called"),
        )


def test_markdown_maps_evidence_locally_and_shows_cost(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret-key")
    bundle, result = explain_report(
        private_report(), opener=lambda *args, **kwargs: FakeResponse(api_response())
    )

    rendered = render_explanation_markdown(result, bundle.local_labels)

    assert "changed file: src/alice/payment/secret.py" in rendered
    assert "suggested verification: tests/test_payment_handler.py" in rendered
    assert "253 total (181 input / 72 output)" in rendered
    assert "cost: $0.000189" in rendered
    assert "cannot change the risk level or exit status" in rendered


def test_ai_failure_never_changes_core_fail_on_exit(monkeypatch, tmp_path, capsys):
    source = tmp_path / "src" / "auth" / "session.py"
    source.parent.mkdir(parents=True)
    source.write_text("TOKEN = 'example'\n", encoding="utf-8")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    exit_code = main(
        [
            str(tmp_path),
            "--changed",
            "src/auth/session.py",
            "--explain",
            "--fail-on",
            "high",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "**Risk:** `high`" in captured.out
    assert "optional OpenRouter explanation unavailable" in captured.err
    assert "deterministic report is unchanged" in captured.err


def test_unexpected_ai_failure_never_changes_core_exit(monkeypatch, tmp_path, capsys):
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    def fail_unexpectedly(report):
        raise RuntimeError("internal secret that should not be printed")

    monkeypatch.setattr("reporipple.cli.explain_report", fail_unexpectedly)

    exit_code = main([str(tmp_path), "--changed", "src/app.py", "--explain"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "# RepoRipple impact report" in captured.out
    assert "optional OpenRouter explanation failed unexpectedly" in captured.err
    assert "internal secret" not in captured.err


def test_preview_never_requires_a_key_or_network(monkeypatch, tmp_path, capsys):
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    exit_code = main(
        [
            str(tmp_path),
            "--changed",
            "src/app.py",
            "--explain-preview",
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["openrouter_preview"]["request_sent"] is False
    assert payload["openrouter_preview"]["request"]["provider"]["zdr"] is True
    assert "src/app.py" not in json.dumps(payload["openrouter_preview"])
    assert payload["deterministic_report"]["changed_files"] == ["src/app.py"]
