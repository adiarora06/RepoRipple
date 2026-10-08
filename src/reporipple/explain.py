"""Optional, privacy-first OpenRouter explanations for deterministic reports."""

from __future__ import annotations

import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reporipple.models import ImpactReport

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-6-luna"
MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+/[A-Za-z0-9._:-]+$")
REQUEST_TIMEOUT_SECONDS = 10.0
RETRY_DELAY_SECONDS = 0.25
MAX_RETRY_DELAY_SECONDS = 2.0
MAX_RETRIES = 1
MAX_PROMPT_PRICE_PER_MILLION = 0.25
MAX_COMPLETION_PRICE_PER_MILLION = 1.0
MAX_COMPLETION_TOKENS = 450
MAX_RESPONSE_BYTES = 256 * 1024
RETRYABLE_HTTP_CODES = {408, 429, 500, 502, 503, 504}

SYSTEM_PROMPT = """You explain a deterministic change-impact report to an engineer.
The deterministic risk level and evidence are authoritative; never rescore or contradict them.
You receive anonymized evidence IDs, generic file types, counts, and graph relationships only.
Do not infer repository names, file paths, source code, business domains, or user identities.
Ground every finding and action in the supplied evidence IDs. Be concise and practical."""

EXPLANATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "maxLength": 500},
        "findings": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "maxLength": 400},
                    "evidence_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string", "pattern": "^E[0-9]{3,}$"},
                    },
                },
                "required": ["text", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "actions": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "maxLength": 400},
                    "evidence_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string", "pattern": "^E[0-9]{3,}$"},
                    },
                },
                "required": ["text", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "caveats": {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string", "maxLength": 300},
        },
    },
    "required": ["summary", "findings", "actions", "caveats"],
    "additionalProperties": False,
}


class ExplanationError(RuntimeError):
    """Raised when an optional explanation cannot be produced safely."""


@dataclass(frozen=True)
class EvidenceBundle:
    """Sanitized outbound evidence and its local-only labels."""

    payload: dict[str, Any]
    local_labels: dict[str, str]


@dataclass(frozen=True)
class ExplanationItem:
    text: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExplanationUsage:
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None


@dataclass(frozen=True)
class ExplanationResult:
    model: str
    summary: str
    findings: tuple[ExplanationItem, ...]
    actions: tuple[ExplanationItem, ...]
    caveats: tuple[str, ...]
    usage: ExplanationUsage


def build_evidence_bundle(report: ImpactReport) -> EvidenceBundle:
    """Create an anonymized payload while retaining evidence labels locally."""
    local_labels: dict[str, str] = {}

    def register(label: str) -> str:
        evidence_id = f"E{len(local_labels) + 1:03d}"
        local_labels[evidence_id] = label
        return evidence_id

    path_ids: dict[str, str] = {}
    for path in report.changed_files:
        path_ids[path] = register(f"changed file: {path}")
    for item in report.impacted_files:
        if item.path not in path_ids:
            path_ids[item.path] = register(f"impacted file: {item.path}")

    changed = [
        {"evidence_id": path_ids[path], "file_type": _file_type(path)}
        for path in report.changed_files
    ]
    impacted = [
        {
            "evidence_id": path_ids[item.path],
            "file_type": _file_type(item.path),
            "distance": item.distance,
            "via": [path_ids[path] for path in item.via if path in path_ids],
        }
        for item in report.impacted_files
    ]
    verification = []
    for item in report.suggested_tests:
        evidence_id = register(f"suggested verification: {item}")
        verification.append(
            {"evidence_id": evidence_id, "verification_type": _verification_type(item)}
        )
    risk_signals = []
    for reason in report.risk_reasons:
        evidence_id = register(f"risk signal: {reason}")
        risk_signals.append({"evidence_id": evidence_id, "category": _risk_category(reason)})

    payload = {
        "schema_version": 1,
        "authority": "deterministic",
        "risk_level": report.risk_level,
        "graph": {"file_count": report.graph_files, "edge_count": report.graph_edges},
        "changed": changed,
        "impacted": impacted,
        "verification": verification,
        "risk_signals": risk_signals,
        "documentation_review_count": len(report.documentation_to_review),
        "scanner_warning_count": len(report.warnings),
    }
    return EvidenceBundle(payload=payload, local_labels=local_labels)


def resolve_model(requested: str | None = None) -> str:
    """Resolve a pinned OpenRouter model without accepting arbitrary request text."""
    candidate = (
        requested
        or os.environ.get("REPORIPPLE_OPENROUTER_MODEL")
        or DEFAULT_OPENROUTER_MODEL
    )
    candidate = candidate.strip()
    if len(candidate) > 200 or not MODEL_PATTERN.fullmatch(candidate):
        raise ExplanationError("OpenRouter model must be a provider/model slug")
    return candidate


def build_openrouter_request(
    bundle: EvidenceBundle, *, model: str | None = None
) -> dict[str, Any]:
    """Build the exact request body used for both preview and live explanation."""
    return {
        "model": resolve_model(model),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(bundle.payload, separators=(",", ":"), sort_keys=True),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "reporipple_explanation",
                "strict": True,
                "schema": EXPLANATION_SCHEMA,
            },
        },
        "provider": {
            "zdr": True,
            "data_collection": "deny",
            "require_parameters": True,
            "sort": "price",
            "max_price": {
                "prompt": MAX_PROMPT_PRICE_PER_MILLION,
                "completion": MAX_COMPLETION_PRICE_PER_MILLION,
            },
        },
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "usage": {"include": True},
        "stream": False,
    }


def explain_report(
    report: ImpactReport,
    *,
    model: str | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[EvidenceBundle, ExplanationResult]:
    """Request an optional explanation using only an environment-provided key."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise ExplanationError("OPENROUTER_API_KEY is not set")

    bundle = build_evidence_bundle(report)
    request_payload = build_openrouter_request(bundle, model=model)
    response_payload = _post_openrouter(
        request_payload,
        api_key,
        opener=opener,
        sleep=sleep,
    )
    result = _parse_response(
        response_payload,
        set(bundle.local_labels),
        fallback_model=request_payload["model"],
    )
    return bundle, result


def render_explanation_markdown(result: ExplanationResult, local_labels: Mapping[str, str]) -> str:
    """Render an AI narrative while resolving opaque evidence IDs locally."""
    lines = [
        "## Optional OpenRouter explanation",
        "",
        "> The deterministic report above remains authoritative. This narrative cannot change "
        "the risk level or exit status.",
        "",
        result.summary,
    ]
    if result.findings:
        lines.extend(["", "### Findings", ""])
        lines.extend(_render_items(result.findings, local_labels))
    if result.actions:
        lines.extend(["", "### Suggested actions", ""])
        lines.extend(_render_items(result.actions, local_labels))
    if result.caveats:
        lines.extend(["", "### Caveats", ""])
        lines.extend(f"- {caveat}" for caveat in result.caveats)
    lines.extend(["", f"_Model: `{result.model}` · {_usage_text(result.usage)}_"])
    return "\n".join(lines).rstrip() + "\n"


def render_preview_markdown(request_payload: Mapping[str, Any]) -> str:
    """Render the exact key-free outbound request without making a network call."""
    preview = json.dumps(request_payload, indent=2, sort_keys=True)
    return "\n".join(
        [
            "## OpenRouter explanation preview",
            "",
            "> No request was sent. This is the exact JSON body that `--explain` would send; "
            "the API key is supplied only as an HTTP header.",
            "",
            "```json",
            preview,
            "```",
            "",
        ]
    )


def explanation_to_dict(
    result: ExplanationResult, local_labels: Mapping[str, str]
) -> dict[str, Any]:
    """Return a JSON-ready explanation with locally resolved evidence labels."""
    return {
        "authoritative": False,
        "model": result.model,
        "summary": result.summary,
        "findings": [_item_to_dict(item, local_labels) for item in result.findings],
        "actions": [_item_to_dict(item, local_labels) for item in result.actions],
        "caveats": list(result.caveats),
        "usage": {
            "prompt_tokens": result.usage.prompt_tokens,
            "completion_tokens": result.usage.completion_tokens,
            "total_tokens": result.usage.total_tokens,
            "cost_usd": result.usage.cost_usd,
        },
    }


def _post_openrouter(
    payload: Mapping[str, Any],
    api_key: str,
    *,
    opener: Callable[..., Any],
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    for attempt in range(MAX_RETRIES + 1):
        try:
            with opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                raw_response = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw_response) > MAX_RESPONSE_BYTES:
                    raise ExplanationError("OpenRouter response exceeded the safety limit")
                decoded = json.loads(raw_response.decode("utf-8"))
                if not isinstance(decoded, dict):
                    raise ExplanationError("OpenRouter returned a non-object response")
                return decoded
        except urllib.error.HTTPError as exc:
            if exc.code in RETRYABLE_HTTP_CODES and attempt < MAX_RETRIES:
                sleep(_retry_delay(exc))
                continue
            raise ExplanationError(f"OpenRouter request failed with HTTP {exc.code}") from exc
        except (TimeoutError, urllib.error.URLError, http.client.HTTPException, OSError) as exc:
            raise ExplanationError("OpenRouter request timed out or was unavailable") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExplanationError("OpenRouter returned invalid JSON") from exc

    raise ExplanationError("OpenRouter request failed")


def _parse_response(
    payload: Mapping[str, Any],
    allowed_evidence: set[str],
    *,
    fallback_model: str,
) -> ExplanationResult:
    if "error" in payload:
        raise ExplanationError("OpenRouter returned an error response")
    try:
        choices = payload["choices"]
        content = choices[0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ExplanationError("OpenRouter response did not contain an explanation") from exc
    if not isinstance(content, str):
        raise ExplanationError("OpenRouter explanation content was not text")
    try:
        explanation = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ExplanationError("OpenRouter explanation was not valid JSON") from exc
    if not isinstance(explanation, dict):
        raise ExplanationError("OpenRouter explanation was not a JSON object")

    expected = {"summary", "findings", "actions", "caveats"}
    if set(explanation) != expected:
        raise ExplanationError("OpenRouter explanation did not match the required schema")
    summary = _validated_text(explanation["summary"], "summary", 500)
    findings = _validated_items(explanation["findings"], "findings", allowed_evidence)
    actions = _validated_items(explanation["actions"], "actions", allowed_evidence)
    caveats = _validated_text_list(explanation["caveats"], "caveats", 3, 300)

    usage_payload = payload.get("usage", {})
    if not isinstance(usage_payload, dict):
        usage_payload = {}
    usage = ExplanationUsage(
        prompt_tokens=_optional_int(usage_payload.get("prompt_tokens")),
        completion_tokens=_optional_int(usage_payload.get("completion_tokens")),
        total_tokens=_optional_int(usage_payload.get("total_tokens")),
        cost_usd=_optional_float(usage_payload.get("cost")),
    )
    model = payload.get("model", fallback_model)
    if not isinstance(model, str) or not model.strip():
        model = fallback_model
    return ExplanationResult(
        model=model.strip(),
        summary=summary,
        findings=tuple(findings),
        actions=tuple(actions),
        caveats=tuple(caveats),
        usage=usage,
    )


def _validated_items(value: Any, field: str, allowed_evidence: set[str]) -> list[ExplanationItem]:
    if not isinstance(value, list) or len(value) > 5:
        raise ExplanationError(f"OpenRouter {field} did not match the required schema")
    items: list[ExplanationItem] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"text", "evidence_ids"}:
            raise ExplanationError(f"OpenRouter {field} did not match the required schema")
        text = _validated_text(item["text"], field, 400)
        evidence_ids = item["evidence_ids"]
        if (
            not isinstance(evidence_ids, list)
            or not 1 <= len(evidence_ids) <= 6
            or any(not isinstance(evidence_id, str) for evidence_id in evidence_ids)
            or len(set(evidence_ids)) != len(evidence_ids)
            or any(evidence_id not in allowed_evidence for evidence_id in evidence_ids)
        ):
            raise ExplanationError(f"OpenRouter {field} cited invalid evidence")
        items.append(ExplanationItem(text=text, evidence_ids=tuple(evidence_ids)))
    return items


def _validated_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ExplanationError(f"OpenRouter {field} did not match the required schema")
    return value.strip()


def _validated_text_list(value: Any, field: str, maximum_items: int, maximum: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise ExplanationError(f"OpenRouter {field} did not match the required schema")
    return [_validated_text(item, field, maximum) for item in value]


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return float(value)


def _retry_delay(exc: urllib.error.HTTPError) -> float:
    """Honor a small numeric Retry-After value without allowing long CLI stalls."""
    raw = exc.headers.get("Retry-After") if exc.headers else None
    try:
        requested = float(raw) if raw is not None else RETRY_DELAY_SECONDS
    except ValueError:
        requested = RETRY_DELAY_SECONDS
    return max(0.0, min(requested, MAX_RETRY_DELAY_SECONDS))


def _file_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".mts": "typescript",
        ".cts": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
    }.get(suffix, "other")


def _verification_type(item: str) -> str:
    if item == "pytest":
        return "python_test_command"
    if item == "npm test":
        return "javascript_test_command"
    file_type = _file_type(item)
    return f"{file_type}_test" if file_type != "other" else "test"


def _risk_category(reason: str) -> str:
    lowered = reason.lower()
    if lowered.startswith("sensitive area"):
        return "sensitive_area"
    if lowered.startswith("runtime, dependency, or deployment"):
        return "configuration_change"
    if lowered.startswith("wide blast radius"):
        return "wide_blast_radius"
    if lowered.startswith("moderate blast radius"):
        return "moderate_blast_radius"
    if lowered.startswith("no matching tests"):
        return "missing_verification"
    return "localized_change"


def _render_items(items: tuple[ExplanationItem, ...], local_labels: Mapping[str, str]) -> list[str]:
    rendered = []
    for item in items:
        evidence = ", ".join(f"`{local_labels[evidence_id]}`" for evidence_id in item.evidence_ids)
        rendered.append(f"- {item.text} — evidence: {evidence}")
    return rendered


def _item_to_dict(item: ExplanationItem, local_labels: Mapping[str, str]) -> dict[str, Any]:
    return {
        "text": item.text,
        "evidence": [
            {"id": evidence_id, "local_label": local_labels[evidence_id]}
            for evidence_id in item.evidence_ids
        ],
    }


def _usage_text(usage: ExplanationUsage) -> str:
    prompt = str(usage.prompt_tokens) if usage.prompt_tokens is not None else "unknown"
    completion = str(usage.completion_tokens) if usage.completion_tokens is not None else "unknown"
    total = str(usage.total_tokens) if usage.total_tokens is not None else "unknown"
    cost = f"${usage.cost_usd:.6f}" if usage.cost_usd is not None else "unavailable"
    return f"tokens: {total} total ({prompt} input / {completion} output) · cost: {cost}"
