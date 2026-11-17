"""端到端冒烟测试：小批量同步 CT.gov → 解析样例病历 → 匹配 → 输出摘要。

运行：python -m oncopilot.smoke_test
"""
from __future__ import annotations

import json

from oncopilot import config, db
from oncopilot.collectors import ctgov
from oncopilot.pipeline import matcher, parser


def main() -> None:
    db.init_db()
    with db.get_conn() as conn:
        # 小批量拉取，仅用于验证链路；max_pages 限制分页
        stat = ctgov.sync(
            conn,
            term="non-small cell lung cancer",
            max_pages=2,
        )
        total = conn.execute("SELECT COUNT(*) AS c FROM studies").fetchone()["c"]
        print("[同步]", json.dumps(stat, ensure_ascii=False))
        print("[本地库条数]", total)

        profile = parser.parse_text(
            (config.SAMPLE_DIR / "sample_case.txt").read_text(encoding="utf-8"),
            source_file="sample_case.txt",
        )
        print("[画像]", json.dumps(profile.to_dict(), ensure_ascii=False, indent=2))

        studies = matcher.load_studies(conn)
        results = matcher.match(profile, studies, top_n=10)
        print(f"[候选] {len(results)} 条")
        for r in results:
            print(f"- [{r.verdict}|{r.tier}] {r.registry_id} {r.title[:60]} "
                  f"| 癌种命中:{r.condition_hit} 靶点命中:{r.biomarker_hit} | {r.flags}")


if __name__ == "__main__":
    main()
