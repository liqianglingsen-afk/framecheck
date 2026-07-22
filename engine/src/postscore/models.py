from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


Severity = Literal["low", "medium", "high", "critical"]


class VideoInfo(BaseModel):
    source: str
    resolved_path: str
    filename: str
    duration_seconds: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    video_codec: str = "unknown"
    audio_codec: str = "none"
    bitrate: int = 0
    file_size: int = 0
    audio_sample_rate: int = 0
    audio_channels: int = 0


class Keyframe(BaseModel):
    path: str
    timestamp_seconds: float
    timestamp_label: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)


class Issue(BaseModel):
    module: str
    severity: Severity
    score_impact: float
    timestamp_start: float | None = None
    timestamp_end: float | None = None
    evidence_image: str | None = None
    metric_value: Any = None
    threshold: Any = None
    problem: str
    recommendation: str
    priority: Literal["P0", "P1", "P2"] = "P2"


class AudioMetrics(BaseModel):
    approx_loudness_db: float | None = None
    peak_db: float | None = None
    silence_segments: list[dict[str, float]] = Field(default_factory=list)
    too_quiet: bool = False
    too_loud: bool = False
    channel_imbalance: float | None = None
    clipping_risk: bool = False
    has_audio: bool = True
    recommendations: list[str] = Field(default_factory=list)


class ReviewReport(BaseModel):
    video_info: VideoInfo
    overall_score: float
    grade: str
    publish_recommendation: str
    module_scores: dict[str, float]
    module_score_max: dict[str, float]
    module_names: dict[str, str]
    issues: list[Issue] = Field(default_factory=list)
    keyframes: list[Keyframe] = Field(default_factory=list)
    audio_metrics: AudioMetrics = Field(default_factory=AudioMetrics)
    export_recommendations: list[str] = Field(default_factory=list)
    revision_checklist: dict[str, list[str]] = Field(default_factory=dict)
    preset: str = "default"
    mode: str = "deep"
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    """Return a pydantic model as a plain dict across pydantic v1/v2."""
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()
