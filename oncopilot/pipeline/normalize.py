"""医学术语归一化：癌种、靶点/生物标志物同义词映射，年龄阈值解析。

映射表为个人自用精简版，覆盖常见实体瘤与热门靶点；使用时以病历/登记原文为准。
"""
from __future__ import annotations

import re

CONDITION_SYNONYMS: dict[str, list[str]] = {
    "非小细胞肺癌": [
        "nsclc", "non-small cell lung cancer", "non small cell lung cancer",
        "非小细胞肺癌", "非小细胞肺癌", "腺癌", "肺腺癌",
    ],
    "小细胞肺癌": ["sclc", "small cell lung cancer", "小细胞肺癌"],
    "乳腺癌": ["breast cancer", "乳腺癌", "乳腺恶性肿瘤"],
    "结直肠癌": ["colorectal cancer", "colorectal", "结直肠癌", "大肠癌", "直肠癌", "结肠癌"],
    "肝细胞癌": ["hepatocellular carcinoma", "hcc", "肝细胞癌", "肝癌", "肝恶性肿瘤"],
    "胃癌": ["gastric cancer", "stomach cancer", "gastric", "胃癌", "胃腺癌"],
    "胃食管结合部癌": ["gastric gastroesophageal", "gej", "胃食管结合部", "贲门癌"],
    "食管癌": ["esophageal cancer", "oesophageal", "食管癌", "食道鳞癌"],
    "黑色素瘤": ["melanoma", "黑色素瘤", "恶黑"],
    "卵巢癌": ["ovarian cancer", "卵巢癌"],
    "胰腺癌": ["pancreatic cancer", "pancreatic", "胰腺癌"],
    "头颈鳞癌": ["head and neck squamous", "hnscc", "头颈鳞癌", "头颈部鳞癌"],
    "肾癌": ["renal cell carcinoma", "rcc", "肾癌", "肾透明细胞癌"],
    "膀胱癌": ["bladder cancer", "尿路上皮癌", "膀胱癌"],
    "宫颈癌": ["cervical cancer", "宫颈癌"],
    "前列腺癌": ["prostate cancer", "前列腺癌"],
    "胆管癌": ["cholangiocarcinoma", "biliary tract", "胆管癌", "胆道肿瘤"],
    "胶质瘤": ["glioma", "glioblastoma", "gbm", "胶质瘤", "胶质母细胞瘤"],
    "淋巴瘤": ["lymphoma", "淋巴瘤"],
    "多发性骨髓瘤": ["multiple myeloma", "mm", "多发性骨髓瘤"],
}

BIOMARKER_SYNONYMS: dict[str, list[str]] = {
    "EGFR": ["egfr", "egfr exon", "egfr突变", "19del", "l858r", "exon 20", "exon20", "t790m"],
    "ALK": ["alk fusion", "alk重排", "alk阳性", "alk rearrangement"],
    "ROS1": ["ros1 fusion", "ros1重排", "ros1阳性"],
    "BRAF": ["braf", "braf v600", "v600e"],
    "KRAS": ["kras", "kras g12", "g12c", "g12d", "g12v"],
    "HER2": ["her2", "erbb2", "her2阳性", "her2突变"],
    "PD-L1": ["pd-l1", "pdl1", "pd l1", "cps", "tps"],
    "MET": ["met exon 14", "metex14", "met扩增", "met amplification", "met阳性"],
    "RET": ["ret fusion", "ret重排", "ret阳性"],
    "NTRK": ["ntrk", "ntrk1", "ntrk2", "ntrk3", "ntrk融合"],
    "FGFR": ["fgfr", "fgfr2", "fgfr3", "fgfr融合", "fgfr扩增"],
    "BRCA": ["brca1", "brca2", "brca", "brca突变"],
    "PIK3CA": ["pik3ca"],
    "HER3": ["her3", "erbb3"],
    "TROP2": ["trop2"],
    "CLDN18.2": ["cldn18.2", "claudin18.2", "claudin 18.2"],
    "MSI-H/dMMR": ["msi-h", "msi h", "msih", "dmmr", "微卫星不稳定"],
    "TMB": ["tmb", "肿瘤突变负荷"],
}


def _match(text: str, mapping: dict[str, list[str]]) -> list[str]:
    if not text:
        return []
    low = text.lower()
    hits: list[str] = []
    for standard, aliases in mapping.items():
        for alias in aliases:
            if alias and alias in low:
                hits.append(standard)
                break
    return sorted(set(hits))


def normalize_conditions(text: str) -> list[str]:
    return _match(text, CONDITION_SYNONYMS)


def normalize_biomarkers(text: str) -> list[str]:
    return _match(text, BIOMARKER_SYNONYMS)


_AGE_RE = re.compile(r"(\d{1,3})\s*(?:years?|岁|周岁)", re.I)
_RANGE_RE = re.compile(r"(\d{1,3})\s*[-~至到]\s*(\d{1,3})\s*(?:years?|岁|周岁)?", re.I)


def parse_age_range(text: str) -> tuple[int | None, int | None]:
    """从入排文本兜底解析年龄区间；优先使用登记库结构化年龄字段。"""
    if not text:
        return None, None
    rng = _RANGE_RE.search(text)
    if rng:
        return int(rng.group(1)), int(rng.group(2))
    ages = [int(a) for a in _AGE_RE.findall(text)]
    if not ages:
        return None, None
    return min(ages), max(ages)


def age_from_field(field: str) -> int | None:
    """解析 '18 Years' 形式的结构化年龄字段。"""
    if not field:
        return None
    m = re.search(r"(\d{1,3})", field)
    return int(m.group(1)) if m else None
