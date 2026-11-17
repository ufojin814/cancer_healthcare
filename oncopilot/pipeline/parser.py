"""病历解析与患者画像抽取。

流程：文件读取（PDF/TXT）→ PII 粗脱敏 → 规则模板抽取 → 归一化标签。
预留可插拔 LLM 适配器：未配置时仅使用规则抽取；配置后可在规则结果上补全字段。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from . import normalize

# 常见抗肿瘤药物关键词（用于识别既往治疗；非处方推荐用途）
KNOWN_DRUGS = [
    "奥希替尼", "吉非替尼", "厄洛替尼", "阿美替尼", "伏美替尼", "埃克替尼",
    "克唑替尼", "阿来替尼", "塞瑞替尼", "洛拉替尼", "布格替尼", "恩曲替尼",
    "塞普替尼", "达拉非尼", "曲美替尼", "维莫非尼", "帕博利珠单抗", "纳武利尤单抗",
    "替雷利珠单抗", "信迪利单抗", "卡瑞利珠单抗", "特瑞普利单抗", "阿替利珠单抗",
    "度伐利尤单抗", "贝伐珠单抗", "安罗替尼", "仑伐替尼", "索拉非尼", "瑞戈非尼",
    "奥拉帕利", "尼拉帕利", "氟唑帕利", "曲妥珠单抗", "帕妥珠单抗", "德曲妥珠单抗",
    "t-dxd", "戈沙妥珠单抗", "维迪西妥单抗", "斯鲁利单抗", "阿得贝利单抗",
    "依沃西", "卡度尼利单抗", "氟泽雷塞", "格索雷塞", "索托雷塞", "阿达格拉西布",
    "多西他赛", "培美曲塞", "紫杉醇", "吉西他滨", "铂类", "顺铂", "卡铂", "奈达铂",
]

STAGE_PATTERNS = [
    (r"\bIV\b|IV期|Ⅳ期|4期|晚期|转移性|metastatic", "IV 期/晚期（转移性）"),
    (r"\bIII\b|III期|3期|局部晚期|locally advanced", "III 期/局部晚期"),
    (r"\bII\b|II期|2期", "II 期"),
    (r"\bI\b|I期|1期", "I 期"),
]

_ID_RE = re.compile(r"\b\d{17}[\dXx]\b")
_PHONE_RE = re.compile(r"\b1[3-9]\d{9}\b")


@dataclass
class PatientProfile:
    age: int | None = None
    sex: str | None = None
    condition_raw: str = ""
    conditions: list[str] = field(default_factory=list)
    pathology: str = ""
    stage: str = ""
    biomarkers: list[str] = field(default_factory=list)
    prior_lines: list[str] = field(default_factory=list)
    prior_drugs: list[str] = field(default_factory=list)
    ecog: int | None = None
    comorbidities: str = ""
    city: str = ""
    notes: str = ""
    raw_text: str = ""
    source_file: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PatientProfile":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def mask_pii(text: str) -> str:
    """粗脱敏：身份证号、手机号替换为占位符；姓名需人工在上传前删除。"""
    text = _ID_RE.sub("[身份证号已隐去]", text)
    text = _PHONE_RE.sub("[手机号已隐去]", text)
    return text


def _extract_age(text: str) -> int | None:
    m = re.search(r"(\d{2})\s*岁", text)
    return int(m.group(1)) if m else None


def _extract_sex(text: str) -> str | None:
    m = re.search(r"性\s*别\s*[:：]\s*(男|女)", text)
    if m:
        return m.group(1)
    if re.search(r"男性|男，|男\s*$", text):
        return "男"
    if re.search(r"女性|女，|女\s*$", text):
        return "女"
    return None


def _extract_city(text: str) -> str:
    m = re.search(r"(?:所在)?城\s*市\s*[:：]\s*([一-龥]{2,6})", text)
    return m.group(1) if m else ""


def _extract_ecog(text: str) -> int | None:
    m = re.search(r"ECOG\s*评分?\s*[:：]?\s*(\d)", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"PS\s*评分?\s*[:：]?\s*(\d)", text)
    return int(m.group(1)) if m else None


def _extract_stage(text: str) -> str:
    for pattern, label in STAGE_PATTERNS:
        if re.search(pattern, text, re.I):
            return label
    return ""


def _extract_drugs(text: str) -> list[str]:
    low = text.lower()
    hits = [d for d in KNOWN_DRUGS if d.lower() in low]
    return sorted(set(hits))


def _extract_lines(text: str) -> list[str]:
    lines: list[str] = []
    for label in ["一线", "二线", "三线", "四线", "首程", "维持治疗"]:
        if label in text:
            lines.append(label)
    return lines


def parse_text(text: str, source_file: str | None = None) -> PatientProfile:
    text = text.strip()
    profile = PatientProfile(
        age=_extract_age(text),
        sex=_extract_sex(text),
        condition_raw=text[:200],
        conditions=normalize.normalize_conditions(text),
        stage=_extract_stage(text),
        biomarkers=normalize.normalize_biomarkers(text),
        prior_lines=_extract_lines(text),
        prior_drugs=_extract_drugs(text),
        ecog=_extract_ecog(text),
        city=_extract_city(text),
        raw_text=mask_pii(text),
        source_file=source_file,
    )
    # 病理类型粗提取
    m = re.search(r"(腺癌|鳞癌|小细胞癌|大细胞癌|导管癌|乳头状癌|黏液癌)", text)
    if m:
        profile.pathology = m.group(1)
    return profile


def read_pdf(path: str) -> str:
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def extract_text(path: str) -> str:
    """按扩展名读取病历文本；扫描件图片需先 OCR（预留接口）。"""
    lower = path.lower()
    if lower.endswith(".pdf"):
        return read_pdf(path)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


class LLMAdapter:
    """可插拔大模型适配器（预留）。

    配置示例（境内合规服务，病历先脱敏）：
        adapter.configure(base_url="https://<境内服务域名>", api_key=..., model=...)
    未配置时 extract 返回 None，匹配流程回退到规则画像。
    """

    def __init__(self) -> None:
        self.configured = False
        self._base_url: str | None = None
        self._api_key: str | None = None
        self._model: str | None = None

    def configure(self, base_url: str, api_key: str, model: str) -> None:
        self._base_url, self._api_key, self._model = base_url, api_key, model
        self.configured = True

    def extract(self, text: str) -> dict | None:
        if not self.configured:
            return None
        # 接入境内大模型 API 时在此实现结构化抽取；返回字段对齐 PatientProfile
        raise NotImplementedError("LLM 抽取接口待接入境内服务后实现")
