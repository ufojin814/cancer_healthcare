"""报告导出：自包含 HTML 与 CSV。"""
from __future__ import annotations

import csv
import html
from datetime import datetime

from .. import config
from ..pipeline.matcher import MatchResult
from ..pipeline.parser import PatientProfile

HEADERS = [
    "登记号", "来源", "标题", "判定", "时效分级", "状态", "期别",
    "癌种命中", "靶点命中", "干预/方案", "研究中心", "申办方",
    "状态更新日期", "匹配理由", "存疑/风险提示", "链接",
]


def _row(r: MatchResult) -> list[str]:
    return [
        r.registry_id, r.source, r.title, r.verdict, r.tier_label, r.status_label,
        r.phase, "、".join(r.condition_hit), "、".join(r.biomarker_hit),
        r.intervention, r.location_text, r.sponsor, str(r.status_date or ""),
        "；".join(r.reasons), "；".join(r.flags), r.url,
    ]


def export_csv(results: list[MatchResult], path: str) -> str:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADERS)
        for r in results:
            writer.writerow(_row(r))
    return path


def export_html(results: list[MatchResult], profile: PatientProfile, meta: dict, path: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    profile_bits = [
        f"年龄：{profile.age or '未识别'}", f"性别：{profile.sex or '未识别'}",
        f"癌种：{'、'.join(profile.conditions) or '未识别'}",
        f"靶点：{'、'.join(profile.biomarkers) or '未识别'}",
        f"分期：{profile.stage or '未识别'}", f"城市：{profile.city or '未填写'}",
    ]
    rows = []
    for r in results:
        rows.append(
            "<tr>" + "".join(
                f"<td>{html.escape(str(v))}</td>" for v in _row(r)[:-1]
            ) + f'<td><a href="{html.escape(r.url)}" target="_blank" rel="noopener">链接</a></td></tr>'
        )
    table = "\n".join(rows)
    doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>临床试验匹配报告 {now}</title>
<style>
body{{font-family:-apple-system,"Microsoft YaHei",sans-serif;margin:24px;color:#1a1a1a}}
h1{{font-size:20px}} .meta{{color:#555;font-size:13px;margin-bottom:12px}}
table{{border-collapse:collapse;width:100%;font-size:12px}}
th,td{{border:1px solid #ddd;padding:6px;vertical-align:top}}
th{{background:#f3f5f9}} .note{{background:#fff7e6;border:1px solid #ffd591;padding:10px;margin:16px 0;font-size:13px}}
</style></head><body>
<h1>临床试验匹配报告（个人自用）</h1>
<div class="meta">生成时间：{now}　数据批次：{html.escape(str(meta.get('data_timestamp') or '本地快照'))}</div>
<div class="meta">{html.escape('　'.join(profile_bits))}</div>
<table><thead><tr>{''.join(f'<th>{html.escape(h)}</th>' for h in HEADERS)}</tr></thead>
<tbody>{table}</tbody></table>
<div class="note">{html.escape(config.DISCLAIMER)}</div>
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path
