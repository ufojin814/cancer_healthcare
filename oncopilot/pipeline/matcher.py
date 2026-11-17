"""匹配引擎：规则硬筛 + 标签召回 + 评分重排 + 时效分级。

输出仅为公开试验信息的候选排序，不构成诊疗建议；资格以研究团队判定为准。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from .. import config, db
from . import normalize
from .parser import PatientProfile

logger = logging.getLogger("oncopilot.matcher")

STATUS_LABELS = {
    "RECRUITING": "招募中",
    "NOT_YET_RECRUITING": "尚未招募",
    "ENROLLING_BY_INVITATION": "受邀入组",
    "ACTIVE_NOT_RECRUITING": "进行中·停止招募",
    "SUSPENDED": "暂停",
    "TERMINATED": "已终止",
    "COMPLETED": "已完成",
    "WITHDRAWN": "已撤回",
    "UNKNOWN": "状态未知",
}

ACTIVE_STATUSES = {"RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION"}
RED_STATUSES = {"TERMINATED", "COMPLETED", "WITHDRAWN", "ACTIVE_NOT_RECRUITING", "SUSPENDED"}


@dataclass
class MatchResult:
    registry_id: str
    source: str
    title: str
    url: str
    score: float
    verdict: str  # 可能匹配 / 存疑待核 / 不符合
    tier: str  # green / yellow / red
    tier_label: str
    status_label: str
    phase: str
    condition: str
    biomarker_hit: list[str] = field(default_factory=list)
    condition_hit: list[str] = field(default_factory=list)
    location_text: str = ""
    intervention: str = ""
    sponsor: str = ""
    status_date: str | None = None
    reasons: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status or "未知")


def _tier(status: str, status_date: str | None) -> tuple[str, str]:
    if status in RED_STATUSES:
        return "red", "红：当前不可申请"
    days = _age_days(status_date)
    if status == "UNKNOWN" or status == "ENROLLING_BY_INVITATION":
        return "yellow", "黄：状态需向研究中心核实"
    if days is not None and days > config.FRESH_DAYS:
        return "yellow", f"黄：状态超过 {config.FRESH_DAYS} 天未更新，需核实"
    return "green", "绿：在招且近期有更新"


def _age_days(status_date: str | None) -> int | None:
    if not status_date:
        return None
    try:
        d = datetime.strptime(status_date[:10], "%Y-%m-%d").date()
        return (date.today() - d).days
    except ValueError:
        return None


def _study_conditions(rec: dict) -> list[str]:
    text = " ".join([rec.get("condition") or "", rec.get("eligibility") or "",
                     rec.get("intervention") or ""])
    return normalize.normalize_conditions(text)


def _study_biomarkers(rec: dict) -> list[str]:
    text = " ".join([rec.get("condition") or "", rec.get("eligibility") or "",
                     rec.get("intervention") or ""])
    return normalize.normalize_biomarkers(text)


def _age_blocked(profile: PatientProfile, rec: dict) -> bool:
    if profile.age is None:
        return False
    min_age = normalize.age_from_field(rec.get("min_age"))
    max_age = normalize.age_from_field(rec.get("max_age"))
    if min_age is None or max_age is None:
        lo, hi = normalize.parse_age_range(rec.get("eligibility"))
        min_age = min_age if min_age is not None else lo
        max_age = max_age if max_age is not None else hi
    if min_age is not None and profile.age < min_age:
        return True
    if max_age is not None and profile.age > max_age:
        return True
    return False


def _gender_blocked(profile: PatientProfile, rec: dict) -> bool:
    if not profile.sex:
        return False
    gender = (rec.get("gender") or "").upper()
    if gender == "FEMALE" and profile.sex != "女":
        return True
    if gender == "MALE" and profile.sex != "男":
        return True
    return False


def match(profile: PatientProfile, studies: list[dict], top_n: int = 20) -> list[MatchResult]:
    results: list[MatchResult] = []

    for rec in studies:
        study_conds = _study_conditions(rec)
        study_biomarks = _study_biomarkers(rec)
        cond_hit = sorted(set(profile.conditions) & set(study_conds))
        biom_hit = sorted(set(profile.biomarkers) & set(study_biomarks))

        reasons: list[str] = []
        flags: list[str] = []
        score = 0.0

        # 硬筛：年龄、性别
        if _age_blocked(profile, rec):
            verdict = "不符合"
            flags.append("年龄超出该试验入组范围")
            score -= 30
        elif _gender_blocked(profile, rec):
            verdict = "不符合"
            flags.append("性别不符合该试验限定")
            score -= 30
        else:
            # 癌种匹配
            if profile.conditions:
                if cond_hit:
                    score += 40 * len(cond_hit)
                    reasons.append(f"癌种匹配：{', '.join(cond_hit)}")
                else:
                    score -= 25
                    flags.append("癌种未命中该试验登记条件")
            else:
                flags.append("病历未识别出明确癌种，需人工核对")

            # 靶点匹配
            if profile.biomarkers:
                if biom_hit:
                    score += 30 * len(biom_hit)
                    reasons.append(f"靶点/标志物匹配：{', '.join(biom_hit)}")
                else:
                    flags.append("靶点/标志物未在该试验条件中检出")
            else:
                flags.append("病历未识别出靶点信息，需结合基因检测报告核对")

            # 既往用药冲突提示（试验药与已用药重叠，提示可能已暴露/耐药）
            if profile.prior_drugs and rec.get("intervention"):
                inter_low = rec["intervention"].lower()
                overlaps = [d for d in profile.prior_drugs if d.lower() in inter_low]
                if overlaps:
                    flags.append(f"既往已使用同类/同名药物：{', '.join(overlaps)}，需评估耐药与洗脱要求")
                    score -= 5

            # 分期冲突：晚期/转移性患者匹配到围手术期/辅助阶段试验时提示并降权
            stage_text = f"{rec.get('title') or ''} {rec.get('eligibility') or ''}".lower()
            is_advanced = any(k in profile.stage for k in ["IV", "晚期", "转移"])
            peri_kw = ["neoadjuvant", "adjuvant", "辅助", "新辅助", "围手术", "perioperative"]
            if is_advanced and any(k in stage_text for k in peri_kw):
                flags.append("试验为围手术期/辅助阶段，与晚期转移性病情可能不符，请核对分期")
                score -= 8

            # 城市就近
            if profile.city and rec.get("location_text") and profile.city in rec["location_text"]:
                score += 10
                reasons.append(f"研究中心城市含：{profile.city}")

            # 状态加减分
            status = rec.get("status") or ""
            if status in ACTIVE_STATUSES:
                score += 10
            elif status in RED_STATUSES:
                score -= 20

            # 判定
            if cond_hit and biom_hit and status in ACTIVE_STATUSES:
                verdict = "可能匹配"
            elif not cond_hit and not study_conds:
                verdict = "存疑待核"
                flags.append("该试验未标注明确适应症，需人工阅读方案")
            elif score < 0:
                verdict = "不符合"
            else:
                verdict = "存疑待核"

        tier, tier_label = _tier(rec.get("status") or "", rec.get("status_date"))

        missing: list[str] = []
        if profile.age is None:
            missing.append("年龄")
        if not profile.conditions:
            missing.append("癌种/病理诊断")
        if not profile.biomarkers:
            missing.append("基因/生物标志物")
        if not profile.stage:
            missing.append("分期")
        if not profile.city:
            missing.append("意向城市")

        results.append(
            MatchResult(
                registry_id=rec.get("registry_id") or "",
                source=rec.get("source") or "",
                title=rec.get("title") or "",
                url=rec.get("url") or "",
                score=round(score, 1),
                verdict=verdict,
                tier=tier,
                tier_label=tier_label,
                status_label=_status_label(rec.get("status") or ""),
                phase=rec.get("phase") or "",
                condition=rec.get("condition") or "",
                biomarker_hit=biom_hit,
                condition_hit=cond_hit,
                location_text=rec.get("location_text") or "",
                intervention=rec.get("intervention") or "",
                sponsor=rec.get("sponsor") or "",
                status_date=rec.get("status_date"),
                reasons=reasons,
                missing=missing,
                flags=flags,
            )
        )

    # 排序：可能匹配 > 存疑 > 不符合；同分按分数
    verdict_order = {"可能匹配": 0, "存疑待核": 1, "不符合": 2}
    results.sort(key=lambda r: (verdict_order.get(r.verdict, 3), -r.score))
    return results[:top_n]


def load_studies(conn, active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM studies"
    if active_only:
        sql += " WHERE status IN ('RECRUITING','NOT_YET_RECRUITING','ENROLLING_BY_INVITATION')"
    sql += " ORDER BY status_date DESC"
    return [dict(row) for row in conn.execute(sql).fetchall()]
