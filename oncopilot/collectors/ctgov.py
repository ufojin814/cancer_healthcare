"""ClinicalTrials.gov API v2 采集器：客户端增量同步到本地 SQLite。

API 文档：https://clinicaltrials.gov/data-api/api
- 数据工作日每日刷新（美东 9:00 / UTC 14:00），版本时间戳见 /api/v2/version
- v2 不支持按发布日期服务端过滤；增量策略：按 LastUpdatePostDate 倒序拉取，
  与本地快照的 status_date 比对，未变更记录跳过，实现客户端增量。
"""
from __future__ import annotations

import json
import logging

import requests

from .. import config, db

logger = logging.getLogger("oncopilot.ctgov")


def get_data_timestamp() -> str | None:
    """返回源库当前数据批次时间戳，用于校验刷新是否完成。"""
    try:
        resp = requests.get(
            config.CTGOV_VERSION, headers=config.HTTP_HEADERS, timeout=config.HTTP_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json().get("dataTimestamp")
    except requests.RequestException as exc:
        logger.warning("获取 CT.gov 版本时间戳失败: %s", exc)
        return None


def _parse_study(raw: dict) -> dict:
    ps = raw.get("protocolSection", {})
    ident = ps.get("identificationModule", {})
    status = ps.get("statusModule", {})
    cond = ps.get("conditionsModule", {})
    design = ps.get("designModule", {})
    elig = ps.get("eligibilityModule", {})
    contacts = ps.get("contactsLocationsModule", {})
    arms = ps.get("armsInterventionsModule", {})
    sponsor = ps.get("sponsorCollaboratorsModule", {})

    nct_id = ident.get("nctId", "")
    conditions = cond.get("conditions", []) or []
    interventions = [i.get("name", "") for i in arms.get("interventions", []) if i.get("name")]
    locations = contacts.get("locations", []) or []
    countries = sorted({loc.get("country", "") for loc in locations if loc.get("country")})
    cities = sorted({loc.get("city", "") for loc in locations if loc.get("city")})

    phases = design.get("phases", []) or []
    criteria = elig.get("eligibilityCriteria", "") or ""

    post_struct = status.get("lastUpdatePostDateStruct") or {}
    status_date = post_struct.get("date")

    return {
        "source": "ctgov",
        "registry_id": nct_id,
        "title": ident.get("briefTitle") or ident.get("officialTitle"),
        "condition": "; ".join(conditions),
        "biomarker": "",
        "phase": "; ".join(phases),
        "status": status.get("overallStatus", ""),
        "status_date": status_date,
        "last_update_submitted": status.get("lastUpdateSubmitDate"),
        "country": "; ".join(countries),
        "location_text": "; ".join(cities),
        "eligibility": criteria,
        "intervention": "; ".join(interventions),
        "sponsor": (sponsor.get("leadSponsor") or {}).get("name", ""),
        "gender": elig.get("sex", ""),
        "min_age": elig.get("minimumAge", ""),
        "max_age": "",
        "url": f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else "",
        "raw_json": json.dumps(raw, ensure_ascii=False),
    }


def fetch_studies(
    term: str | None = None,
    overall_status: str | None = None,
    max_pages: int | None = None,
) -> list[dict]:
    """分页拉取试验记录，按最近发布日期倒序。

    :param term: 病症/关键词检索词（query.term）
    :param overall_status: 试验状态过滤（如 RECRUITING）
    :param max_pages: 最大分页页数（测试/限流用），None 为不限制
    """
    params: dict = {
        "pageSize": config.CTGOV_PAGE_SIZE,
        "format": "json",
        "sort": "LastUpdatePostDate:desc",
    }
    if term:
        params["query.term"] = term
    if overall_status:
        params["filter.overallStatus"] = overall_status

    results: list[dict] = []
    page_token: str | None = None
    pages = 0
    while True:
        if page_token:
            params["pageToken"] = page_token
        else:
            params.pop("pageToken", None)
        resp = requests.get(
            config.CTGOV_API, params=params, headers=config.HTTP_HEADERS,
            timeout=config.HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
        for raw in payload.get("studies", []):
            results.append(_parse_study(raw))
        pages += 1
        page_token = payload.get("nextPageToken")
        if not page_token or (max_pages and pages >= max_pages):
            break
    return results


def _local_status_date(conn, registry_id: str) -> str | None:
    row = conn.execute(
        "SELECT status_date FROM studies WHERE source='ctgov' AND registry_id=?",
        (registry_id,),
    ).fetchone()
    return row["status_date"] if row else None


def sync(
    conn,
    term: str | None = None,
    overall_status: str | None = None,
    max_pages: int | None = None,
) -> dict:
    """客户端增量同步：与本地快照比对，仅落库新增或有变更的记录。"""
    started = db.now_iso()
    data_ts = get_data_timestamp()
    records = fetch_studies(term=term, overall_status=overall_status, max_pages=max_pages)

    upserted = 0
    unchanged = 0
    for rec in records:
        if not rec["registry_id"]:
            continue
        local_date = _local_status_date(conn, rec["registry_id"])
        if local_date and rec["status_date"] and local_date >= rec["status_date"]:
            unchanged += 1
            continue
        if db.upsert_study(conn, rec):
            upserted += 1
        else:
            upserted += 1  # 已存在但有更新，计入变更

    finished = db.now_iso()
    conn.execute(
        """
        INSERT INTO sync_log (source, started_at, finished_at, records_total,
            records_upserted, data_timestamp, note)
        VALUES (?,?,?,?,?,?,?)
        """,
        ("ctgov", started, finished, len(records), upserted, data_ts,
         f"term={term or 'all'}; status={overall_status or 'all'}; unchanged={unchanged}"),
    )
    logger.info("CT.gov 同步完成：拉取 %d 条，新增/变更 %d 条，未变更 %d 条",
                len(records), upserted, unchanged)
    return {
        "source": "ctgov",
        "fetched": len(records),
        "new_or_updated": upserted,
        "unchanged": unchanged,
        "data_timestamp": data_ts,
        "started_at": started,
        "finished_at": finished,
    }


def last_sync_info(conn) -> dict | None:
    """最近一次同步批次信息（供界面展示数据新鲜度）。"""
    return db.latest_sync(conn, "ctgov")
