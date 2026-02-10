"""Tests for recipe artifact Pydantic models and schema hash stability."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from mcp_server_browser_use.recipes.artifacts.models import (
    AnalysisResult,
    BaselineFingerprint,
    CandidateSet,
    MinimizationResult,
    SessionRecording,
    SignalSet,
    ValidationErrorCode,
    ValidationIssue,
    ValidationResult,
    VerificationAttempt,
    VerificationReport,
    VerificationStatus,
)


def test_models_validate_and_dump_schema_hash() -> None:
    recording = SessionRecording(
        task="t",
        result="r",
        requests=[],
        responses=[],
        navigation_urls=["https://example.com"],
        start_time=datetime(2026, 1, 1, 0, 0, 0),
        end_time=None,
    )

    signals = SignalSet(
        recording=recording,
        signals=[
            {
                "url": "https://api.example.com/items?q=x",
                "method": "GET",
                "status": 200,
                "content_type": "application/json",
                "response_size_bytes": 123,
                "structural_summary": "object(keys=items)",
                "duration_ms": 12.5,
                "request_timestamp": 1.0,
                "response_timestamp": 1.1,
                "initiator_page_url": "https://example.com",
                "resource_type": "xhr",
            }
        ],
    )

    candidates = CandidateSet(
        signals=signals,
        candidates=[
            {
                "rank": 1,
                "score": 0.9,
                "notes": "looks like the money request",
                "signal": signals.signals[0],
            }
        ],
    )

    analysis = AnalysisResult(
        candidates=candidates,
        selected_rank=1,
        request_spec={
            "url": "https://api.example.com/items?q={query}",
            "method": "GET",
            "headers": {"Accept": "application/json"},
            "response_type": "json",
            "extract_path": "items[*].id",
            "allowed_domains": ["example.com"],
        },
        recipe_name_suggestion="example-items",
        raw_llm_output='{"ok": true}',
    )

    validation = ValidationResult(
        analysis=analysis,
        ok=True,
        errors=[],
        warnings=[
            ValidationIssue(
                code=ValidationErrorCode.OTHER,
                message="test warning",
            )
        ],
    )

    baseline = BaselineFingerprint(
        validation=validation,
        max_depth=6,
        entries=[
            {"path": ("items", "[]", "id"), "value_type": "number"},
            {"path": ("items",), "value_type": "array"},
        ],
        sample_count=1,
    )

    minimization = MinimizationResult(
        baseline=baseline,
        original_request=analysis.request_spec,
        minimized_request=analysis.request_spec,
        steps=[{"description": "no-op", "changed": False}],
        notes="",
    )

    report = VerificationReport(
        minimization=minimization,
        status=VerificationStatus.PASSED,
        attempts=[
            VerificationAttempt(
                timestamp=datetime(2026, 1, 1, 0, 0, 1),
                ok=True,
                http_status=200,
                similarity=1.0,
                error=None,
                output_excerpt="ok",
            )
        ],
    )

    dumped = report.model_dump(mode="json")
    assert "schema_hash" in dumped
    assert isinstance(dumped["schema_hash"], str)
    assert dumped["schema_hash"]
    loaded = VerificationReport.model_validate(dumped)
    assert loaded.schema_hash == dumped["schema_hash"]


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        SessionRecording.model_validate(
            {
                "task": "t",
                "result": "r",
                "requests": [],
                "responses": [],
                "navigation_urls": [],
                "start_time": "2026-01-01T00:00:00",
                "end_time": None,
                "nope": 123,
            }
        )


def test_schema_hash_stable_snapshot() -> None:
    expected = {
        "SessionRecording": "536d71ab0ab798c783d6158e1a0c463979e943e8229b02cdd0b2a120d5bd9e7e",
        "SignalSet": "2e85e14972cb907e0345e228ab609b6bddf7148ae5f22c6c603dfb1208bfe3ff",
        "CandidateSet": "7ea6b9ffce0b62791893744740c20217df6e0eefdbac662924b54ef57ad078c2",
        "AnalysisResult": "b565f2f6614ae221551a14bff61158efe9c123079f6c45686e15ea2e170bd4b0",
        "ValidationResult": "76131c13ab1a7ea695e835b0b06fc24f7989ac762a249d91eb4a78463772dbbf",
        "BaselineFingerprint": "53af2cab793dee2a97e98c633ad105cd70be18868c9aab9e3ff04b096a3b6c38",
        "MinimizationResult": "1aba6fc6ec658a4e1441f2cff2a7545e037629aef93b9353097c3a8b5f57e0e1",
        "VerificationReport": "3582f7e77762b20414d7ae0e6896cdbc26c573bdca58ae8544a973292b43b15c",
    }

    assert SessionRecording.schema_hash_value() == expected["SessionRecording"]
    assert SignalSet.schema_hash_value() == expected["SignalSet"]
    assert CandidateSet.schema_hash_value() == expected["CandidateSet"]
    assert AnalysisResult.schema_hash_value() == expected["AnalysisResult"]
    assert ValidationResult.schema_hash_value() == expected["ValidationResult"]
    assert BaselineFingerprint.schema_hash_value() == expected["BaselineFingerprint"]
    assert MinimizationResult.schema_hash_value() == expected["MinimizationResult"]
    assert VerificationReport.schema_hash_value() == expected["VerificationReport"]


def test_schema_hash_independent_of_instance_values() -> None:
    a = SessionRecording(
        task="t1",
        result="r1",
        requests=[],
        responses=[],
        navigation_urls=[],
        start_time=datetime(2026, 1, 1, 0, 0, 0),
        end_time=None,
    )
    b = SessionRecording(
        task="t2",
        result="r2",
        requests=[],
        responses=[],
        navigation_urls=["https://x.example"],
        start_time=datetime(2026, 2, 1, 0, 0, 0),
        end_time=datetime(2026, 2, 1, 0, 0, 1),
    )

    assert a.schema_hash == b.schema_hash
    assert a.schema_hash == SessionRecording.schema_hash_value()


def test_artifact_roundtrip_json_dump_validate() -> None:
    recording = SessionRecording(
        task="t",
        result="r",
        requests=[],
        responses=[],
        navigation_urls=["https://example.com"],
        start_time=datetime(2026, 1, 1, 0, 0, 0),
        end_time=None,
    )

    signals = SignalSet(
        recording=recording,
        signals=[
            {
                "url": "https://api.example.com/items?q=x",
                "method": "GET",
                "status": 200,
                "content_type": "application/json",
                "response_size_bytes": 123,
                "structural_summary": "object(keys=items)",
                "duration_ms": 12.5,
                "request_timestamp": 1.0,
                "response_timestamp": 1.1,
                "initiator_page_url": "https://example.com",
                "resource_type": "xhr",
            }
        ],
    )

    candidates = CandidateSet(
        signals=signals,
        candidates=[
            {
                "rank": 1,
                "score": 0.9,
                "notes": "looks like the money request",
                "signal": signals.signals[0],
            }
        ],
    )

    analysis = AnalysisResult(
        candidates=candidates,
        selected_rank=1,
        request_spec={
            "url": "https://api.example.com/items?q={query}",
            "method": "GET",
            "headers": {"Accept": "application/json"},
            "response_type": "json",
            "extract_path": "items[*].id",
            "allowed_domains": ["example.com"],
        },
        recipe_name_suggestion="example-items",
        raw_llm_output='{"ok": true}',
    )

    validation = ValidationResult(
        analysis=analysis,
        ok=True,
        errors=[],
        warnings=[
            ValidationIssue(
                code=ValidationErrorCode.OTHER,
                message="test warning",
            )
        ],
    )

    baseline = BaselineFingerprint(
        validation=validation,
        max_depth=6,
        entries=[
            {"path": ("items", "[]", "id"), "value_type": "number"},
            {"path": ("items",), "value_type": "array"},
        ],
        sample_count=1,
    )

    minimization = MinimizationResult(
        baseline=baseline,
        original_request=analysis.request_spec,
        minimized_request=analysis.request_spec,
        steps=[{"description": "no-op", "changed": False}],
        notes="",
    )

    report = VerificationReport(
        minimization=minimization,
        status=VerificationStatus.PASSED,
        attempts=[
            VerificationAttempt(
                timestamp=datetime(2026, 1, 1, 0, 0, 1),
                ok=True,
                http_status=200,
                similarity=1.0,
                error=None,
                output_excerpt="ok",
            )
        ],
    )

    for artifact in [
        recording,
        signals,
        candidates,
        analysis,
        validation,
        baseline,
        minimization,
        report,
    ]:
        dumped = artifact.model_dump(mode="json")
        loaded = artifact.__class__.model_validate(dumped)
        assert loaded.model_dump(mode="json") == dumped


def test_schema_hash_preserved_when_provided() -> None:
    forced = "deadbeef"
    recording = SessionRecording(
        schema_hash=forced,
        task="t",
        result="r",
        requests=[],
        responses=[],
        navigation_urls=[],
        start_time=datetime(2026, 1, 1, 0, 0, 0),
        end_time=None,
    )

    dumped = recording.model_dump(mode="json")
    assert dumped["schema_hash"] == forced
    loaded = SessionRecording.model_validate(dumped)
    assert loaded.schema_hash == forced
