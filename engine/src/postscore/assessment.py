"""Evidence and frozen evaluation scope for the 0.6 editorial format."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .creative_evidence import HOOK
from .creative_evidence import Beat, Criteria, Display, Form, Mark, Opening, Text

Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Interval(Form):
    start: Seconds
    end: Seconds

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("证据时段的出点须晚于入点")
        return self


class Brief(Form):
    commission: Literal["综合评分", "修改方案", "执行改剪", "封面", "开场", "批量评分"]
    entry_type: Literal["自动播放", "列表", "混合", "待核"]
    audio_intent: Literal["必需", "可选", "设计无声", "待核"]
    action_required: bool
    purpose: Text
    target_duration: Text
    placements: list[Text]
    constraints: Text
    export_context: Literal["平台发布", "保留源规格", "待核"] = "待核"
    shot_style: Literal["常规", "有意长镜或静止", "待核"] = "待核"
    color_style: Literal["常规", "有意风格化", "待核"] = "待核"


class HookMark(Mark):
    time: Seconds | None


class TimedBeat(Beat, Interval):
    pass


class TimedOpening(Opening):
    beats: Annotated[list[TimedBeat], Field(min_length=1)]


class State(Display):
    precondition: Text
    expected_state: Text
    observed_state: Text
    sequence: Interval | None = None


class Moment(Interval):
    purpose: Text
    evidence: Text
    events: list[Text]
    framing: str = ""
    motion: str = ""
    sound: str = ""
    graphics: str = ""
    replication: str = ""


class CurrentCriteria(Criteria):
    hook: dict[str, HookMark]
    openings: list[TimedOpening]
    displays: list[State]
    shots: list[Moment]
    inspect_spans: list[Interval] = Field(default_factory=list)
    source_kind: Literal["实片", "文字稿", "图帧及文字", "部分证据"]
    verified_frames: bool
    audio_evidence: bool
    highlight_uses_audio: bool
    payoff_time: Seconds | None = None
    ending_action: Literal["可执行", "缺失", "待核", "不适用"]

    @model_validator(mode="before")
    @classmethod
    def omit_unobserved_hook_marks(cls, value):
        if isinstance(value, dict) and isinstance(value.get("hook"), dict):
            return value | {
                "hook": {
                    k: m
                    for k, m in value["hook"].items()
                    if not isinstance(m, dict) or m.get("score") is not None
                }
            }
        return value

    def validate_hook(self):
        if len(self.hook) == len(HOOK):
            return super().validate_hook()
        if any(
            k not in HOOK or m.score > HOOK[k] or m.evidence in {"待核", "未知", "待填"}
            for k, m in self.hook.items()
        ):
            raise ValueError("开场分项证据或权重不符")

    def needs_openings(self):
        # The commission and verified duration are checked together after decoding.
        return False

    def check_context(self, brief, duration, content, cover_required):
        if (
            brief.entry_type == "自动播放"
            and cover_required
            and brief.commission != "封面"
        ):
            raise ValueError("仅自动播放的简报与必需发布封面矛盾")
        if brief.action_required and self.ending_action == "不适用":
            raise ValueError("目标行动已被指定，须核对其存在或标待核")
        if self.payoff_time is not None and self.payoff_time >= duration:
            raise ValueError("兑现时码须位于实际视频内")
        if (
            content
            and "前3秒语言心理钩子" in content.marks
            and set(self.hook) != set(HOOK)
        ):
            raise ValueError("开场四项尚未核齐，须将开场维度标为待核")
        limit = min(3.0, duration)
        if any(m.time is not None and m.time >= limit for m in self.hook.values()):
            raise ValueError("开场证据须位于原片前三秒以内")
        if self.hook_total > 5 and any(
            m.score and m.time is None for m in self.hook.values()
        ):
            raise ValueError("开场超过 5 分须逐项提供窗口内源时码")
        if (
            brief.commission != "封面"
            and self.hook_total < 14
            and content
            and "前3秒语言心理钩子" in content.marks
        ):
            self.require_choices(self.openings, "开场")
        if self.openings:
            if (
                len(
                    {
                        tuple((b.picture, b.audio, b.caption) for b in o.beats)
                        for o in self.openings
                    }
                )
                < 2
            ):
                raise ValueError("开场备选须有不同的实际剪法")
            for o in self.openings:
                cursor = 0
                for beat in o.beats:
                    if abs(beat.start - cursor) > 0.001 or beat.end > 3.001:
                        raise ValueError("开场方案时间须从零连续并处于成片开场内")
                    cursor = beat.end
                if brief.target_duration == "保持原时长" and cursor > duration + 0.001:
                    raise ValueError("开场方案超过约定片长")
        if self.source_kind == "实片" and not self.shots:
            raise ValueError("实片审片须登记实际镜头")
        cursor = 0
        for shot in self.shots:
            if abs(cursor - shot.start) > 0.001 or shot.end > duration + 0.001:
                raise ValueError("实际镜头时段有缺口、重叠或越界")
            cursor = shot.end
        if self.source_kind == "实片" and abs(cursor - duration) > 0.001:
            raise ValueError("实际镜头未覆盖片尾")
        for state in self.displays:
            if state.sequence and state.sequence.end > duration + 0.001:
                raise ValueError("状态切换证据超出实片")

    def pending(self):
        return super().pending() or any(
            (s.status == "符合" and s.expected_state != s.observed_state)
            or (s.timing == "已核" and not s.sequence)
            for s in self.displays
        )

    def findings(self):
        for item in super().findings():
            item["topic"] = item["topic"].replace("产品屏显错误", "状态展示错误")
            yield item
        for s in self.displays:
            if s.status == "符合" and s.expected_state != s.observed_state:
                yield {
                    "topic": "状态观察与结论矛盾",
                    "stage": "事实依据",
                    "level": "发布前须改",
                    "evidence": f"{s.time} · {s.expected_state} / {s.observed_state}",
                    "action": s.fix,
                    "acceptance": "核对连续画面和状态依据后重评",
                    "confidence": "编辑判断",
                    "cost": "现有素材剪辑",
                    "technical_issue": "",
                }

    def caps(self, brief, weights):
        limits = {}
        if not any(m.time is not None for m in self.hook.values()):
            limits["前3秒语言心理钩子"] = 5
        if self.highlight_uses_audio and not self.audio_evidence:
            limits["高光句音画同步"] = 4
        if brief.action_required and self.ending_action == "缺失":
            limits["转化/关注/评论引导"] = 2
        for k in ("视觉画面与审美", "拍摄与运镜", "剪辑节奏与留存", "字幕与包装"):
            if self.source_kind == "文字稿":
                limits[k] = weights[k] / 2
            elif not self.verified_frames:
                limits[k] = weights[k] - 0.0001
        return limits
