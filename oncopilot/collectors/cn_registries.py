"""国内/区域登记库适配层。

说明：CDE 药物临床试验登记与信息公示平台、ChiCTR 均无公开开放 API，
本模块不做全站自动爬取；负责生成可点击的检索链接（供人工核对），
并预留定向采集接口。公开登记信息以研究中心答复为准。
"""
from __future__ import annotations

import urllib.parse

from .. import config


def _q(text: str) -> str:
    return urllib.parse.quote(text.strip())


def build_registry_links(condition: str = "", biomarker: str = "", city: str = "") -> list[dict]:
    """按病症/靶点/城市生成各登记库检索入口链接。"""
    kw = " ".join(p for p in [condition, biomarker] if p).strip()
    links: list[dict] = [
        {
            "source": "cde",
            "label": "CDE 药物临床试验登记与信息公示平台（国内注册药物试验）",
            "url": config.CDE_SEARCH,
            "query_hint": f"病症/关键词：{kw or '请输入癌种或药物名'}；城市：{city or '不限'}",
            "note": "需在页面检索框手动输入；入排标准与参加机构以详情页公示为准",
        },
        {
            "source": "chictr",
            "label": "中国临床试验注册中心 ChiCTR（研究者发起研究）",
            "url": f"{config.CHICTR_SEARCH}?projTitle={_q(kw)}" if kw else config.CHICTR_SEARCH,
            "query_hint": f"关键词：{kw or '请输入癌种'}",
            "note": "WHO 一级注册机构；更新节奏为月度批次",
        },
        {
            "source": "eu_ctr",
            "label": "EU Clinical Trials Register / CTIS（欧盟区域试验）",
            "url": f"{config.CTIS_SEARCH}?query={_q(kw)}" if kw else config.CTIS_SEARCH,
            "query_hint": f"Keyword: {kw or 'condition/drug'}",
            "note": "2023-02 后新药试验经 CTIS 门户登记；成人 I 期部分不公开",
        },
    ]
    return links


def collect_cde(condition: str, biomarker: str = "") -> list[dict]:
    """预留：按癌种/靶点定向采集 CDE 详情条目。

    当前版本不启用自动采集；如需启用，须先核实平台使用条款与 robots 规则，
    并按低频、定向（非全站）方式实现。
    """
    raise NotImplementedError(
        "CDE 平台无公开 API；当前版本生成检索链接供人工核对，定向采集待授权后实现"
    )


def collect_chictr(condition: str, biomarker: str = "") -> list[dict]:
    """预留：ChiCTR 定向采集接口，同上。"""
    raise NotImplementedError("ChiCTR 定向采集待授权后实现；当前使用检索链接")
