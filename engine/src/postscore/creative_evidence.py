"""Evidence required for a current editorial assessment."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Evidence = Annotated[str, Field(min_length=2), StringConstraints(strip_whitespace=True)]
HOOK = {"主体与动作": 4, "受众相关": 4, "继续观看理由": 5, "前三秒可信线索": 4}
HOOK_DIM = "前3秒语言心理钩子"


class Form(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Mark(Form):
    score: Annotated[int, Field(strict=True, ge=0)]
    evidence: Evidence


def hook_score(marks: dict[str, Mark], payoff: str) -> int:
    if set(marks) != set(HOOK) or any(marks[k].score > w for k, w in HOOK.items()):
        raise ValueError("前三秒须给四项依据，满分分别为 4、4、5、4")
    if any(m.evidence in {"待核", "待填", "未知"} and m.score for m in marks.values()):
        raise ValueError("前三秒有分项须有可复核的证据")
    total = sum(m.score for m in marks.values())
    if total >= 14 and (
        marks["继续观看理由"].score < 4
        or marks["前三秒可信线索"].score < 3
        or payoff in {"", "待核", "未兑现", "未知"}
    ):
        raise ValueError("高钩子分须有继续看理由、可见线索和后文兑现")
    return total


class Beat(Form):
    subject: Text
    picture: Text
    audio: Text
    caption: Text


class Opening(Form):
    motive: Text
    beats: Annotated[list[Beat], Field(min_length=3, max_length=3)]
    next_shot: Text


class Design(Form):
    motive: Text
    source_frame: Text
    headline: Text
    crop: Text
    focus: Text
    placement: Text
    rationale: Text
    failure: Text


class CoverSource(Form):
    independent: Literal["有独立封面", "无独立封面", "待核"]
    displayed: Literal["独立封面", "平台选帧", "待核"]
    evidence: Text


class Preview(Form):
    source: Text
    size: Text
    subject: Literal["正确", "错误或缺失", "待核"]
    benefit: Literal["可辨", "不清", "待核"]
    topic: Text


class TrackDecision(Form):
    name: Text
    source: Text
    value: Text
    picture: Literal["保留", "微调", "替换", "删除"]
    display: Text
    graphics: Text
    sound: Text
    output: Text
    reason: Text
    loss: Literal["保留价值", "有据取舍", "无据丢失"]


class Identity(Form):
    sound_on: Literal["清楚", "误认", "待核"]
    muted: Literal["清楚", "误认", "待核"]
    evidence: Text
    fix: Text


class Display(Form):
    time: Text
    action: Text
    expected: Text
    observed: Text
    reference: Text
    timing_reference: Text
    status: Literal["符合", "错误", "擦空", "待核"]
    timing: Literal["已核", "待核"]
    fix: Text


class Criteria(Form):
    primary_task: Text
    secondary_angle: Text
    reveal_order: Text
    cover_source: CoverSource
    previews: dict[str, Preview]
    cover_plans: list[Design]
    hook: dict[str, Mark]
    payoff: Text
    openings: list[Opening]
    identity: Identity
    assets: list[TrackDecision]
    no_assets_reason: str = ""
    displays: list[Display]
    no_display_reason: str = ""

    @model_validator(mode="after")
    def validate_assessment(self):
        hook_score(self.hook, self.payoff)
        if (
            self.cover_source.displayed == "独立封面"
            and self.cover_source.independent != "有独立封面"
        ):
            raise ValueError("平台实显与独立封面来源矛盾")
        if not self.assets and not self.no_assets_reason.strip():
            raise ValueError("须登记有保留价值的源镜头或写明原因")
        if len({a.name for a in self.assets}) != len(self.assets):
            raise ValueError("保留资产名称重复")
        if not self.displays and not self.no_display_reason.strip():
            raise ValueError("须核对实际屏显或写明不适用原因")
        if any(
            a.picture in {"删除", "替换"} and a.loss == "保留价值" for a in self.assets
        ):
            raise ValueError("删除或替换价值镜头须写明取舍")
        if self.hook_total < 14:
            self.require_choices(self.openings, "开场")
        return self

    @property
    def hook_total(self):
        return sum(m.score for m in self.hook.values())

    @staticmethod
    def require_choices(rows, name):
        if len({r.motive.strip() for r in rows}) < 2:
            raise ValueError(name + "须提供至少两种不同的观看动机")

    def covers(self, entries, target):
        roles = {c["name"]: c["role"] for c in entries}
        if len(roles) != len(entries) or set(self.previews) != set(roles):
            raise ValueError("每个封面对象须逐一对应来源、缩略尺寸和识别判断")
        actual = [c for c in entries if c["role"] == "发布封面"]
        if bool(actual) != (self.cover_source.displayed != "待核"):
            raise ValueError("已证实的平台实显图与发布封面评分须一一对应")
        independent = [c for c in entries if c["role"] == "独立封面"]
        if independent and self.cover_source.independent != "有独立封面":
            raise ValueError("独立封面素材与来源状态矛盾")
        if self.cover_source.independent == "有独立封面" and not (
            independent or self.cover_source.displayed == "独立封面"
        ):
            raise ValueError("已提供的独立封面需要对应图像")
        primary_roles = (
            {"发布封面"} if actual else {"独立封面"} if independent else {"首帧"}
        )
        weak = not (actual or independent)
        for c in entries:
            v = self.previews[c["name"]]
            if v.subject == "错误或缺失" or v.benefit == "不清":
                c["gate"] = "须修"
            elif "待核" in (v.subject, v.benefit) and c["gate"] == "已核":
                c["gate"] = "待核"
            c["decision"] = {
                "已核": "可用" if c["total"] >= target else "需优化",
                "须修": "淘汰",
                "待核": "待核",
            }[c["gate"]]
            if c["role"] in primary_roles:
                weak |= c["total"] < target or c["gate"] != "已核"
        if weak:
            self.require_choices(self.cover_plans, "封面")
        return {
            "无独立封面": "无独立封面 · N/A",
            "待核": "独立封面待核",
            "有独立封面": "有独立封面",
        }[self.cover_source.independent]

    def findings(self):
        def finding(topic, stage, evidence, action):
            return {
                "topic": topic,
                "stage": stage,
                "level": "发布前须改",
                "evidence": evidence,
                "action": action,
                "acceptance": "以正常速度和静音逐镜复核该处",
                "confidence": "编辑判断",
                "cost": "现有素材剪辑",
                "technical_issue": "",
            }

        if "误认" in (self.identity.sound_on, self.identity.muted):
            yield finding(
                "主体切换导致误认", "前3秒", self.identity.evidence, self.identity.fix
            )
        for d in self.displays:
            if d.status in {"错误", "擦空"}:
                yield finding(
                    "产品屏显错误 · " + d.time,
                    "事实依据",
                    d.observed + " · " + d.reference,
                    d.fix,
                )
        for a in self.assets:
            if a.loss == "无据丢失":
                yield finding(
                    "价值镜头丢失 · " + a.name,
                    "画面与包装",
                    a.source + " · " + a.value,
                    a.reason,
                )

    def pending(self):
        return "待核" in (self.identity.sound_on, self.identity.muted) or any(
            d.status == "待核" or d.timing == "待核" for d in self.displays
        )


def template():
    return {
        "primary_task": "",
        "secondary_angle": "",
        "reveal_order": "",
        "cover_source": {"independent": "待核", "displayed": "待核", "evidence": ""},
        "previews": {},
        "cover_plans": [],
        "hook": {k: {"score": None, "evidence": ""} for k in HOOK},
        "payoff": "",
        "openings": [],
        "identity": {"sound_on": "待核", "muted": "待核", "evidence": "", "fix": ""},
        "assets": [],
        "no_assets_reason": "",
        "displays": [],
        "no_display_reason": "",
    }
