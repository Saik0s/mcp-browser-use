"""Pydantic models for recipe-learning pipeline artifacts.

Artifacts are intended to be persisted to disk and moved between stages.
They must be:
- Strictly typed (no Any)
- Strict at the persistence boundary (unknown fields forbidden)
- Self-identifying by stored schema hash for safe migrations
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import ClassVar, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


def _prune_schema_hash(schema: object, *, container_key: str | None = None) -> object:
    """Remove schema_hash from a JSON schema object.

    We compute a schema hash from the model's JSON schema, but exclude the schema_hash field itself
    so the hash does not become self-referential.
    """
    if isinstance(schema, dict):
        out: dict[str, object] = {}
        for k, v in schema.items():
            if container_key == "properties" and k == "schema_hash":
                continue
            out[k] = _prune_schema_hash(v, container_key=k)
        return out

    if isinstance(schema, list):
        items = [_prune_schema_hash(v, container_key=container_key) for v in schema]
        if container_key == "required":
            return [v for v in items if v != "schema_hash"]
        return items

    return schema


def _schema_hash_for_model(model_cls: type[BaseModel]) -> str:
    schema_obj = model_cls.model_json_schema()
    pruned = _prune_schema_hash(schema_obj)
    payload = json.dumps(pruned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactModel(StrictModel):
    """Base for persisted pipeline artifacts."""

    _SCHEMA_HASH: ClassVar[str | None] = None

    # Persisted in artifact JSON, never recomputed on load.
    # When not provided, we default it at creation time from the model schema.
    schema_hash: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _default_schema_hash(cls, data: object) -> object:
        if isinstance(data, cls):
            return data
        if isinstance(data, dict) and "schema_hash" not in data:
            return {**data, "schema_hash": cls.schema_hash_value()}
        return data

    @classmethod
    def schema_hash_value(cls) -> str:
        cached = cls._SCHEMA_HASH
        if cached is not None:
            return cached
        computed = _schema_hash_for_model(cls)
        cls._SCHEMA_HASH = computed
        return computed


class NetworkRequest(StrictModel):
    url: str
    method: str
    headers: dict[str, str] = Field(default_factory=dict)
    post_data: str | None = None
    resource_type: str = ""
    timestamp: float = 0.0
    request_id: str = ""


class NetworkResponse(StrictModel):
    url: str
    status: int
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    mime_type: str = ""
    timestamp: float = 0.0
    request_id: str = ""


class SessionRecording(ArtifactModel):
    """Captured browser session used as the learning input."""

    task: str
    result: str
    requests: list[NetworkRequest] = Field(default_factory=list)
    responses: list[NetworkResponse] = Field(default_factory=list)
    navigation_urls: list[str] = Field(default_factory=list)
    start_time: datetime
    end_time: datetime | None = None


class RequestSignal(StrictModel):
    """Per-request signals derived from a SessionRecording (sanitized, bounded)."""

    url: str
    method: str
    status: int
    content_type: str
    response_size_bytes: int
    structural_summary: str
    duration_ms: float | None = None
    request_timestamp: float
    response_timestamp: float
    initiator_page_url: str
    resource_type: str


class SignalSet(ArtifactModel):
    """Signals extracted from a SessionRecording."""

    recording: SessionRecording
    signals: list[RequestSignal] = Field(default_factory=list)


class CandidateReason(str, Enum):
    """Coarse reason labels for why a request is a candidate."""

    STATUS_OK = "status_ok"
    JSON_RESPONSE = "json_response"
    LARGE_RESPONSE = "large_response"
    URL_MATCH = "url_match"
    HEURISTIC = "heuristic"


class RequestCandidate(StrictModel):
    rank: int
    score: float = Field(ge=0.0, le=1.0)
    reason: CandidateReason = CandidateReason.HEURISTIC
    signal: RequestSignal
    notes: str = ""


class CandidateSet(ArtifactModel):
    """Ranked candidate requests likely to be the 'money request'."""

    signals: SignalSet
    candidates: list[RequestCandidate] = Field(default_factory=list)


ResponseType = Literal["json", "html", "text"]


class RecipeRequestSpec(StrictModel):
    """Direct execution request spec (portable representation)."""

    url: str
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    body_template: str | None = None
    response_type: ResponseType = "json"
    extract_path: str | None = None
    html_selectors: dict[str, str] | None = None
    allowed_domains: list[str] = Field(default_factory=list)


class AnalysisResult(ArtifactModel):
    """LLM analysis output for selecting/extracting the recipe request."""

    candidates: CandidateSet
    selected_rank: int | None = None
    request_spec: RecipeRequestSpec | None = None
    recipe_name_suggestion: str | None = None
    notes: str = ""
    raw_llm_output: str = ""


class ValidationErrorCode(str, Enum):
    MISSING_REQUEST = "missing_request"
    INVALID_URL = "invalid_url"
    DISALLOWED_DOMAIN = "disallowed_domain"
    UNSUPPORTED_METHOD = "unsupported_method"
    INVALID_SELECTORS = "invalid_selectors"
    OTHER = "other"


class ValidationIssue(StrictModel):
    code: ValidationErrorCode
    message: str


class ValidationResult(ArtifactModel):
    """Deterministic validation of analysis output and request spec."""

    analysis: AnalysisResult
    ok: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)


class JsonValueType(str, Enum):
    OBJECT = "object"
    ARRAY = "array"
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    NULL = "null"


class FingerprintEntry(StrictModel):
    path: tuple[str, ...]
    value_type: JsonValueType


class BaselineFingerprint(ArtifactModel):
    """Baseline response fingerprint for later comparison during verification."""

    validation: ValidationResult
    max_depth: int = 6
    entries: list[FingerprintEntry] = Field(default_factory=list)
    sample_count: int = 0


class MinimizationStep(StrictModel):
    description: str
    changed: bool = False


class MinimizationResult(ArtifactModel):
    """Minimized request spec and the steps taken to reach it."""

    baseline: BaselineFingerprint
    original_request: RecipeRequestSpec
    minimized_request: RecipeRequestSpec
    steps: list[MinimizationStep] = Field(default_factory=list)
    notes: str = ""


class VerificationAttempt(StrictModel):
    timestamp: datetime
    ok: bool
    http_status: int | None = None
    similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    error: str | None = None
    output_excerpt: str = ""


class VerificationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    PARTIAL = "partial"


class VerificationReport(ArtifactModel):
    """Final verification results for a minimized recipe."""

    minimization: MinimizationResult
    status: VerificationStatus
    attempts: list[VerificationAttempt] = Field(default_factory=list)
    notes: str = ""
