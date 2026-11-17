"""本地 Web 应用：数据刷新、病历解析、匹配结果与报告导出。"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .. import config, db
from ..collectors import cn_registries, ctgov
from ..pipeline import matcher, parser
from ..reports import exporter

TEMPLATE_DIR = Path(__file__).parent / "templates"
TMP_DIR = config.DATA_DIR / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="OncoPilot 本地临床试验匹配（个人自用）")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# 单用户自用：最近一次画像与结果暂存内存
_LAST: dict = {"profile": None, "results": [], "meta": {}}


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"disclaimer": config.DISCLAIMER}
    )


@app.post("/api/refresh")
def refresh(term: str | None = Form(None)):
    """触发数据同步：增量拉取自上次更新以来变更的试验；无历史则全量（可按关键词限定）。"""
    db.init_db()
    with db.get_conn() as conn:
        stat = ctgov.sync(conn, term=(term or None), overall_status=None)
        total = conn.execute("SELECT COUNT(*) AS c FROM studies").fetchone()["c"]
        last = db.latest_sync(conn, "ctgov")
    return JSONResponse({**stat, "local_total": total, "last_sync": last})


@app.post("/api/match")
async def match_endpoint(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
):
    db.init_db()
    raw_text = ""
    source_file = None

    if file is not None and file.filename:
        suffix = Path(file.filename).suffix
        tmp = TMP_DIR / f"upload_{next(tempfile._get_candidate_names())}{suffix}"
        tmp.write_bytes(await file.read())
        source_file = file.filename
        try:
            raw_text = parser.extract_text(str(tmp))
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": f"病历解析失败：{exc}"}, status_code=400)
    elif text and text.strip():
        raw_text = text.strip()
    else:
        return JSONResponse({"error": "请上传病历文件或粘贴病历文本"}, status_code=400)

    profile = parser.parse_text(raw_text, source_file=source_file)

    with db.get_conn() as conn:
        studies = matcher.load_studies(conn)
        results = matcher.match(profile, studies)
        links = cn_registries.build_registry_links(
            condition=" ".join(profile.conditions),
            biomarker=" ".join(profile.biomarkers),
            city=profile.city,
        )
        last = db.latest_sync(conn, "ctgov")
        conn.execute(
            "INSERT INTO match_history (created_at, profile_json, result_json) VALUES (?,?,?)",
            (db.now_iso(), json.dumps(profile.to_dict(), ensure_ascii=False),
             json.dumps([r.to_dict() for r in results], ensure_ascii=False)),
        )

    _LAST["profile"] = profile.to_dict()
    _LAST["results"] = [r.to_dict() for r in results]
    _LAST["meta"] = {"data_timestamp": (last or {}).get("data_timestamp"),
                      "last_sync": (last or {}).get("finished_at"),
                      "local_total": len(studies)}

    return JSONResponse({
        "profile": profile.to_dict(),
        "results": [r.to_dict() for r in results],
        "registry_links": links,
        "meta": _LAST["meta"],
    })


@app.get("/api/export")
def export(fmt: str):
    if not _LAST["results"]:
        return JSONResponse({"error": "暂无匹配结果，请先完成匹配"}, status_code=400)
    profile = parser.PatientProfile.from_dict(_LAST["profile"] or {})
    stamp = db.now_iso().replace(":", "").replace("-", "")
    if fmt == "csv":
        path = config.REPORT_DIR / f"match_report_{stamp}.csv"
        exporter.export_csv([matcher.MatchResult(**r) for r in _LAST["results"]], str(path))
        return JSONResponse({"file": str(path), "format": "csv"})
    path = config.REPORT_DIR / f"match_report_{stamp}.html"
    exporter.export_html(
        [matcher.MatchResult(**r) for r in _LAST["results"]], profile, _LAST["meta"], str(path)
    )
    return JSONResponse({"file": str(path), "format": "html"})


@app.get("/api/history")
def history():
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, created_at, profile_json FROM match_history ORDER BY id DESC LIMIT 20"
        ).fetchall()
    return JSONResponse([dict(r) for r in rows])
