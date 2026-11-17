"""全局配置：路径、数据源端点、请求参数。"""
from __future__ import annotations

from pathlib import Path

# 项目根目录（oncopilot 的上一级）
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "oncopilot" / "data"
SAMPLE_DIR = BASE_DIR / "oncopilot" / "samples"
REPORT_DIR = BASE_DIR / "oncopilot" / "reports"

DATA_DIR.mkdir(parents=True, exist_ok=True)
SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "oncopilot.db"

# ClinicalTrials.gov API v2
CTGOV_API = "https://clinicaltrials.gov/api/v2/studies"
CTGOV_VERSION = "https://clinicaltrials.gov/api/v2/version"
CTGOV_PAGE_SIZE = 100
HTTP_TIMEOUT = 30
HTTP_HEADERS = {
    "User-Agent": "OncoPilot-Personal/0.1 (personal clinical-trial matching; contact: local-user)",
    "Accept": "application/json",
}

# 国内/区域登记库检索基址（仅生成检索链接，供人工核对）
CDE_SEARCH = "https://www.chinadrugtrials.org.cn/clinicaltrials.searchlist.dhtml"
CHICTR_SEARCH = "https://www.chictr.org.cn/searchproj.html"
CTIS_SEARCH = "https://clinicaltrialsregister.eu/ctr-search/search"

# 状态时效分级阈值（天）
FRESH_DAYS = 90

# 免责声明（所有对外输出附带）
DISCLAIMER = (
    "本工具仅整理公开临床试验信息，不构成诊断、治疗建议或用药推荐；"
    "匹配结果不代表入组资格，是否符合条件以研究团队筛查与书面知情同意为准，"
    "请以主治肿瘤科医生意见为首要依据。"
)
