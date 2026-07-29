#!/usr/bin/env python3
"""Generate bilingual USA-Iran Strategic Intelligence Report PDFs.

Default inputs:
  docs/conflict_forecast_live.json
  docs/strategic_pressure.json
  docs/interest_achievement.json
  docs/strategic_success.json
  data/strategic/strategic_interests.json
  data/strategic/strategic_indicators.json
  data/strategic/interest_impact_map.json

Default outputs:
  docs/reports/latest-hu.pdf
  docs/reports/latest-en.pdf
  docs/reports/archive/YYYY-MM-DD-hu.pdf
  docs/reports/archive/YYYY-MM-DD-en.pdf
  docs/reports/reports_index.json

Examples:
  python src/generate_daily_assessment_pdf.py
  python src/generate_daily_assessment_pdf.py --lang hu
  python src/generate_daily_assessment_pdf.py --lang en
  python src/generate_daily_assessment_pdf.py --lang all
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        BaseDocTemplate,
        CondPageBreak,
        Frame,
        KeepTogether,
        PageTemplate,
        Paragraph,
        PageBreak,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "ReportLab is required. Install it with: pip install reportlab"
    ) from exc


PROJECT_NAME = "Törésvonalak Intelligence Hub"
REPORT_SERIES = "USA–Iran Strategic Intelligence Report"
REPORT_VERSION = "2.4"
TAGLINE = "Turning Open-Source Information into Strategic Intelligence through Semantic Analysis and Quantitative Assessment"
BLOG_URL = "toresvonalak.blog"
DEFAULT_FORECAST = Path("docs/conflict_forecast_live.json")
DEFAULT_PRESSURE = Path("docs/strategic_pressure.json")
DEFAULT_INTEREST = Path("docs/interest_achievement.json")
DEFAULT_SUCCESS = Path("docs/strategic_success.json")
DEFAULT_STRATEGIC_INTERESTS = Path("data/strategic/strategic_interests.json")
DEFAULT_STRATEGIC_INDICATORS = Path("data/strategic/strategic_indicators.json")
DEFAULT_INTEREST_IMPACT_MAP = Path("data/strategic/interest_impact_map.json")
DEFAULT_OUTPUT_DIR = Path("docs/reports")

LANGUAGES = ("hu", "en")

TEXT = {
    "hu": {
        "at_glance": "A jelentés egy oldalon",
        "input_models": "Elemzési bemenetek és konfigurációs állományok",
        "input_models_intro": (
            "A jelentés az alábbi napi modellkimenetekből és stratégiai konfigurációs állományokból épül fel. "
            "A táblázat a felhasznált fájlokat, verziókat, referencia-időpontokat és szerepüket mutatja."
        ),
        "overall_assessment": "Átfogó értékelés",
        "main_findings": "Fő megállapítások",
        "assessment_confidence": "Értékelési megbízhatóság",
        "model_name": "Modell vagy állomány",
        "file_path": "Fájlútvonal",
        "version": "Verzió",
        "status": "Státusz",
        "role": "Szerep",
        "reference": "Referencia",
        "strategic_configuration": "Stratégiai konfiguráció",
        "model_outputs": "Napi modellkimenetek",

        "report_title": "USA–Irán stratégiai hírszerzési jelentés",
        "conflict": "Egyesült Államok – Irán",
        "daily_assessment": "Napi értékelés",
        "about": "A jelentésről",
        "about_intro": (
            "Az USA–Irán stratégiai hírszerzési jelentés a Törésvonalak Intelligence Hub elemző kiadványa. "
            "Célja az Egyesült Államok és Irán közötti konfliktus változó stratégiai dinamikájának napi értékelése."
        ),
        "about_method": (
            "A rendszer nem az egyes eseményeket elszigetelten kezeli. Nyílt forrású információkat dolgoz fel, "
            "majd szemantikai elemzéssel stratégiai jelentést rendel azokhoz. Az így kialakított indikátorokat "
            "pontozási, aggregációs és idősoros módszerek alakítják összehasonlítható kvantitatív értékeléssé."
        ),
        "about_purpose": (
            "A jelentés célja, hogy a napi hírek mögött húzódó folyamatokat átlátható, reprodukálható és "
            "adatvezérelt módon mutassa be. A kimenet kutatók, elemzők és döntéshozók számára ad strukturált "
            "helyzetképet, de nem helyettesít önálló szakértői mérlegelést."
        ),
        "workflow": "Nyílt forrású információ → szemantikai elemzés → stratégiai indikátorok → kvantitatív értékelés → integrált stratégiai helyzetkép",
        "auto": "Automatikusan generált OSINT elemzés",
        "executive": "Vezetői összefoglaló",
        "forecast": "Forecast értékelés",
        "pressure": "Stratégiai nyomás értékelése",
        "interest": "Stratégiai érdekérvényesülés",
        "success": "Stratégiai eredményesség",
        "integrated": "Integrált stratégiai értékelés",
        "combined": "Összevont elemző értékelés",
        "drivers": "Legfontosabb stratégiai mozgatórugók",
        "method": "Módszertan és korlátok",
        "sources": "A napi értékelésben felhasznált fő események",
        "date": "Referencia-nap",
        "generated": "Generálva",
        "model": "Modellek",
        "page": "oldal",
        "usa": "Egyesült Államok",
        "iran": "Irán",
        "overall": "Összesített",
        "index": "Index",
        "trend": "Trend",
        "level": "Szint",
        "event": "Esemény",
        "actor": "Szereplő",
        "indicator": "Indikátor",
        "score": "Pont",
        "source": "Forrás",
        "no_data": "Nincs elérhető adat.",
        "disclaimer": (
            "Az előrejelzés az összesített katonai aktivitás várható irányát becsüli "
            "történeti mintázatok alapján. Nem konkrét támadás, célpont vagy katonai "
            "művelet előrejelzése. A Strategic Pressure mutató stratégiai ösztönzőket "
            "és nyomásgyakorlási jeleket értékel; nem eseményvalószínűség."
        ),
    },
    "en": {
        "at_glance": "Report at a Glance",
        "input_models": "Analytical Inputs and Configuration Files",
        "input_models_intro": (
            "The report is built from the following daily model outputs and strategic configuration files. "
            "The table identifies the files, versions, reference dates, and analytical roles used in production."
        ),
        "overall_assessment": "Overall Assessment",
        "main_findings": "Main Findings",
        "assessment_confidence": "Assessment Confidence",
        "model_name": "Model or file",
        "file_path": "File path",
        "version": "Version",
        "status": "Status",
        "role": "Role",
        "reference": "Reference",
        "strategic_configuration": "Strategic Configuration",
        "model_outputs": "Daily Model Outputs",

        "report_title": "USA–Iran Strategic Intelligence Report",
        "conflict": "United States – Iran",
        "daily_assessment": "Daily Assessment",
        "about": "About this Report",
        "about_intro": (
            "The USA–Iran Strategic Intelligence Report is an analytical publication of the Törésvonalak Intelligence Hub. "
            "Its purpose is to assess the evolving strategic dynamics of the confrontation between the United States and Iran."
        ),
        "about_method": (
            "The system does not treat individual events in isolation. It processes open-source information, assigns strategic "
            "meaning through semantic analysis, and converts the resulting indicators into comparable quantitative assessments "
            "through scoring, aggregation, and time-series methods."
        ),
        "about_purpose": (
            "The report is designed to reveal the processes behind daily headlines in a transparent, reproducible, and data-driven "
            "form. It provides researchers, analysts, and decision-makers with a structured situational picture, but it does not "
            "replace independent expert judgement."
        ),
        "workflow": "Open-source information → semantic analysis → strategic indicators → quantitative assessment → integrated strategic intelligence",
        "auto": "Automatically generated OSINT assessment",
        "executive": "Executive Summary",
        "forecast": "Forecast Assessment",
        "pressure": "Strategic Pressure Assessment",
        "interest": "Strategic Interest Achievement",
        "success": "Strategic Success",
        "integrated": "Integrated Strategic Assessment",
        "combined": "Combined Analytical Assessment",
        "drivers": "Key Strategic Drivers",
        "method": "Methodology and Limitations",
        "sources": "Principal Events Used in the Daily Assessment",
        "date": "Reference date",
        "generated": "Generated",
        "model": "Models",
        "page": "page",
        "usa": "United States",
        "iran": "Iran",
        "overall": "Overall",
        "index": "Index",
        "trend": "Trend",
        "level": "Level",
        "event": "Event",
        "actor": "Actor",
        "indicator": "Indicator",
        "score": "Score",
        "source": "Source",
        "no_data": "No data available.",
        "disclaimer": (
            "The forecast estimates the expected direction of aggregate military activity "
            "from historical patterns. It does not predict a specific attack, target, or "
            "military operation. Strategic Pressure evaluates strategic incentives and "
            "signals of coercion; it is not an event-probability measure."
        ),
    },
}

TREND_LABELS = {
    "hu": {
        "strong_increase": "erős emelkedés",
        "increase": "emelkedés",
        "slight_increase": "mérsékelt emelkedés",
        "stable": "lényegében változatlan",
        "slight_decrease": "mérsékelt csökkenés",
        "decrease": "csökkenés",
        "strong_decrease": "erős csökkenés",
    },
    "en": {
        "strong_increase": "strong increase",
        "increase": "increase",
        "slight_increase": "moderate increase",
        "stable": "broadly stable",
        "slight_decrease": "moderate decrease",
        "decrease": "decrease",
        "strong_decrease": "strong decrease",
    },
}

LEVEL_LABELS = {
    "hu": {
        "very_low": "nagyon alacsony",
        "low": "alacsony",
        "reduced": "csökkent",
        "moderate": "közepes",
        "elevated": "emelkedett",
        "high": "magas",
        "very_high": "nagyon magas",
    },
    "en": {
        "very_low": "very low",
        "low": "low",
        "reduced": "reduced",
        "moderate": "moderate",
        "elevated": "elevated",
        "high": "high",
        "very_high": "very high",
    },
}

DIRECTION_LABELS = {
    "hu": {
        "increase": "növekvő katonai aktivitás",
        "stable": "lényegében változatlan katonai aktivitás",
        "decrease": "csökkenő katonai aktivitás",
        "no_signal": "nincs egyértelmű jelzés",
    },
    "en": {
        "increase": "increasing military activity",
        "stable": "broadly stable military activity",
        "decrease": "decreasing military activity",
        "no_signal": "no clear signal",
    },
}

MONTHS_HU = (
    "január", "február", "március", "április", "május", "június",
    "július", "augusztus", "szeptember", "október", "november", "december",
)


@dataclass(frozen=True)
class ReportPaths:
    latest: Path
    archive: Path


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Top-level JSON value must be an object: {path}")
    return data


def nested(data: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, Mapping) or key not in current:
            return default
        current = current[key]
    return current


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def pct(value: Any, digits: int = 1) -> str:
    return f"{number(value) * 100:.{digits}f}%"


def fmt_num(value: Any, digits: int = 1) -> str:
    return f"{number(value):.{digits}f}"


def escape(value: Any) -> str:
    text = str(value if value is not None else "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def report_date(
    forecast: Mapping[str, Any],
    pressure: Mapping[str, Any],
    interest: Mapping[str, Any],
    success: Mapping[str, Any],
) -> str:
    dates = {
        "forecast": str(forecast.get("forecast_reference_date") or ""),
        "strategic_pressure": str(nested(pressure, "current", "date", default="") or pressure.get("latest_complete_utc_day") or ""),
        "interest_achievement": str(nested(interest, "current", "date", default="") or nested(interest, "metadata", "reference_date", default="") or ""),
        "strategic_success": str(nested(success, "current", "date", default="") or nested(success, "metadata", "current_date", default="") or ""),
    }
    populated = {name: value for name, value in dates.items() if value}
    unique = set(populated.values())
    if len(unique) > 1:
        details = ", ".join(f"{name}={value}" for name, value in populated.items())
        raise ValueError(f"Input date mismatch: {details}. All model outputs must refer to the same day.")
    value = next(iter(unique), "")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"Missing or invalid report reference date: {value!r}") from exc
    return value


def localized_date(iso_date: str, lang: str) -> str:
    dt = datetime.strptime(iso_date, "%Y-%m-%d")
    if lang == "hu":
        return f"{dt.year}. {MONTHS_HU[dt.month - 1]} {dt.day}."
    return dt.strftime("%d %B %Y")


def localized_datetime(value: Any, lang: str) -> str:
    if not value:
        return "-"
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return str(value)
    if lang == "hu":
        return f"{dt.year}. {MONTHS_HU[dt.month - 1]} {dt.day}. {dt:%H:%M} UTC"
    return dt.strftime("%d %B %Y, %H:%M UTC")


def direction(horizon: Mapping[str, Any], lang: str, public: bool = True) -> str:
    section = horizon.get("public_signal") if public else horizon.get("raw_prediction")
    section = section if isinstance(section, Mapping) else {}
    code = str(section.get("direction") or "no_signal")
    return DIRECTION_LABELS[lang].get(code, code.replace("_", " "))


def trend_label(value: Any, lang: str) -> str:
    code = str(value or "stable")
    return TREND_LABELS[lang].get(code, code.replace("_", " "))


def level_label(value: Any, lang: str) -> str:
    code = str(value or "moderate")
    return LEVEL_LABELS[lang].get(code, code.replace("_", " "))


def pressure_actor(pressure: Mapping[str, Any], actor: str) -> Mapping[str, Any]:
    value = nested(pressure, "current", actor, default={})
    return value if isinstance(value, Mapping) else {}


def horizon_data(forecast: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = nested(forecast, "horizons", key, default={})
    return value if isinstance(value, Mapping) else {}


def analyse_forecast(forecast: Mapping[str, Any], lang: str) -> list[str]:
    h48 = horizon_data(forecast, "48h")
    h72 = horizon_data(forecast, "72h")
    raw48 = h48.get("raw_prediction") if isinstance(h48.get("raw_prediction"), Mapping) else {}
    raw72 = h72.get("raw_prediction") if isinstance(h72.get("raw_prediction"), Mapping) else {}
    pub48 = h48.get("public_signal") if isinstance(h48.get("public_signal"), Mapping) else {}
    pub72 = h72.get("public_signal") if isinstance(h72.get("public_signal"), Mapping) else {}

    p48 = number(raw48.get("top_probability"))
    c48 = number(raw48.get("confidence_score"))
    p72 = number(raw72.get("top_probability"))
    c72 = number(raw72.get("confidence_score"))
    d48_raw = str(raw48.get("direction") or "no_signal")
    d72_raw = str(raw72.get("direction") or "no_signal")
    s48 = bool(pub48.get("has_signal"))
    s72 = bool(pub72.get("has_signal"))

    if lang == "hu":
        paragraphs = [
            (
                f"A 48 órás nyers előrejelzés legvalószínűbb iránya a(z) "
                f"<b>{escape(DIRECTION_LABELS['hu'].get(d48_raw, d48_raw))}</b>. "
                f"A vezető valószínűség {pct(p48)}, a konfidenciaérték {fmt_num(c48, 3)}. "
                + (
                    "A jelzés átlépte a publikációs kaput, ezért nyilvános forecastként megjelenhet."
                    if s48
                    else "A jelzés nem teljesítette a publikációs kapu minden követelményét, ezért a nyilvános kimenet óvatosabb."
                )
            ),
            (
                f"A 72 órás modell nyers iránya a(z) "
                f"<b>{escape(DIRECTION_LABELS['hu'].get(d72_raw, d72_raw))}</b>, "
                f"{pct(p72)} vezető valószínűséggel és {fmt_num(c72, 3)} konfidenciával. "
                + (
                    "Ez a horizont is kiadható nyilvános jelzésként."
                    if s72
                    else "A rendszer ezt nem adta ki egyértelmű nyilvános jelzésként, mert a horizont szigorúbb kapuját nem érte el."
                )
            ),
        ]
        if d48_raw != d72_raw:
            paragraphs.append(
                "A két időtáv eltérő iránya nem feltétlenül ellentmondás. Rövid aktivitási hullám után "
                "mérséklődés, vagy átmeneti visszaesés után újabb erősödés is kialakulhat. A 72 órás "
                "nyers eredményt csak akkor szabad erős állításként kezelni, ha a publikus kapu is átengedi."
            )
        else:
            paragraphs.append(
                "A két időtáv azonos iránya erősíti a trend folytonosságának lehetőségét, de az eredmény "
                "továbbra is valószínűségi becslés, nem konkrét katonai esemény előrejelzése."
            )
    else:
        paragraphs = [
            (
                f"The most likely raw 48-hour direction is <b>{escape(DIRECTION_LABELS['en'].get(d48_raw, d48_raw))}</b>. "
                f"Its leading probability is {pct(p48)}, with a confidence score of {fmt_num(c48, 3)}. "
                + (
                    "The result passed the publication gate and is therefore released as a public forecast signal."
                    if s48
                    else "The result did not satisfy every publication-gate requirement, so the public output remains more cautious."
                )
            ),
            (
                f"The raw 72-hour direction is <b>{escape(DIRECTION_LABELS['en'].get(d72_raw, d72_raw))}</b>, "
                f"with a leading probability of {pct(p72)} and confidence of {fmt_num(c72, 3)}. "
                + (
                    "This horizon also qualifies as a public signal."
                    if s72
                    else "The system withheld a clear public signal because the result did not reach the stricter horizon-specific gate."
                )
            ),
        ]
        if d48_raw != d72_raw:
            paragraphs.append(
                "Different directions across the two horizons are not necessarily contradictory. They may describe a short operational surge "
                "followed by moderation, or a temporary decline followed by renewed activity. The 72-hour raw result should not be presented "
                "as a firm public conclusion unless it also passes the gate."
            )
        else:
            paragraphs.append(
                "The shared direction across both horizons supports the possibility of trend persistence, but the result remains a probabilistic "
                "estimate rather than a prediction of a specific military event."
            )
    return paragraphs


def analyse_pressure(pressure: Mapping[str, Any], lang: str) -> list[str]:
    usa = pressure_actor(pressure, "usa")
    iran = pressure_actor(pressure, "iran")
    overall = nested(pressure, "current", "overall", default={})
    overall = overall if isinstance(overall, Mapping) else {}

    ui = number(usa.get("pressure_index_7d"), 50)
    ii = number(iran.get("pressure_index_7d"), 50)
    oi = number(overall.get("pressure_index_7d"), (ui + ii) / 2)
    ut = trend_label(usa.get("trend"), lang)
    it = trend_label(iran.get("trend"), lang)
    ot = trend_label(overall.get("trend"), lang)
    ul = level_label(usa.get("pressure_level"), lang)
    il = level_label(iran.get("pressure_level"), lang)
    ol = level_label(overall.get("pressure_level"), lang)

    if lang == "hu":
        lead = "az Egyesült Államok" if ui > ii else "Irán" if ii > ui else "egyik fél sem"
        paragraphs = [
            (
                f"A hét napra súlyozott amerikai stratégiai nyomásindex <b>{ui:.1f}</b> ({escape(ul)}), "
                f"az iráni index <b>{ii:.1f}</b> ({escape(il)}), az összesített érték pedig <b>{oi:.1f}</b> ({escape(ol)}). "
                f"Az amerikai trend {escape(ut)}, az iráni trend {escape(it)}, az összesített trend {escape(ot)}."
            ),
            (
                f"A magasabb aktuális nyomás {lead} oldalán látható. Ez nem automatikusan kezdeményező szerepet vagy támadási szándékot jelent, "
                "hanem azt, hogy a modell ezen az oldalon erősebb stratégiai kényszereket, elrettentő vagy érdekérvényesítési jelzéseket azonosít."
            ),
        ]
        if oi < 40:
            paragraphs.append(
                "Az összesített index csökkent tartománya arra utal, hogy a tárgyalási, visszafogási vagy háborúelkerülési ösztönzők jelenleg "
                "erősebbek az egyértelmű stratégiai eszkalációs jeleknél. Ez nem zár ki korlátozott katonai műveleteket."
            )
        elif oi > 60:
            paragraphs.append(
                "Az összesített index emelkedett tartománya fokozott stratégiai nyomásgyakorlásra utal. Ilyen környezetben nagyobb a kockázata annak, "
                "hogy a katonai, diplomáciai és gazdasági eszközök egyszerre szolgálják az alkupozíció javítását."
            )
        else:
            paragraphs.append(
                "Az összesített index középső tartománya vegyes stratégiai környezetet jelez: a visszafogás és a nyomásgyakorlás egyszerre lehet jelen."
            )
    else:
        lead = "the United States" if ui > ii else "Iran" if ii > ui else "neither actor"
        paragraphs = [
            (
                f"The seven-day weighted US Strategic Pressure Index is <b>{ui:.1f}</b> ({escape(ul)}), "
                f"Iran's index is <b>{ii:.1f}</b> ({escape(il)}), and the overall reading is <b>{oi:.1f}</b> ({escape(ol)}). "
                f"The US trend is {escape(ut)}, the Iranian trend is {escape(it)}, and the overall trend is {escape(ot)}."
            ),
            (
                f"The higher current pressure is associated with {lead}. This does not automatically imply initiative or intent to attack; "
                "it means the model identifies stronger strategic constraints, deterrent signals, or instruments of leverage on that side."
            ),
        ]
        if oi < 40:
            paragraphs.append(
                "The reduced overall range suggests that incentives for negotiation, restraint, or war avoidance currently outweigh clear strategic-escalation signals. "
                "This does not rule out limited military operations."
            )
        elif oi > 60:
            paragraphs.append(
                "The elevated overall range indicates intensified strategic pressure. In such an environment, military, diplomatic, and economic tools may be used together "
                "to improve bargaining leverage."
            )
        else:
            paragraphs.append(
                "The middle range indicates a mixed strategic environment in which restraint and coercive pressure may operate simultaneously."
            )
    return paragraphs


def combined_assessment(forecast: Mapping[str, Any], pressure: Mapping[str, Any], lang: str) -> list[str]:
    h48 = horizon_data(forecast, "48h")
    raw48 = h48.get("raw_prediction") if isinstance(h48.get("raw_prediction"), Mapping) else {}
    pub48 = h48.get("public_signal") if isinstance(h48.get("public_signal"), Mapping) else {}
    d48 = str(raw48.get("direction") or "no_signal")
    signal48 = bool(pub48.get("has_signal"))
    overall = nested(pressure, "current", "overall", default={})
    overall = overall if isinstance(overall, Mapping) else {}
    oi = number(overall.get("pressure_index_7d"), 50)
    ot = str(overall.get("trend") or "stable")

    if lang == "hu":
        if signal48 and d48 == "increase" and oi < 40:
            core = (
                "A 48 órás aktivitásnövekedési jelzés és a csökkent stratégiai nyomás együtt arra utalhat, hogy a következő műveleti hullám "
                "korlátozott marad, vagy elsősorban tárgyalási pozíciójavítást és elrettentést szolgál. A rövid távú katonai aktivitás ezért nem "
                "azonosítható automatikusan egy tartós eszkalációs ciklus kezdeteként."
            )
        elif signal48 and d48 == "increase" and oi >= 60:
            core = (
                "A növekvő 48 órás katonai aktivitás és az emelkedett stratégiai nyomás azonos irányba mutat. Ez megerősíti a rövid távú eszkaláció "
                "kockázatát, különösen akkor, ha a legfontosabb mozgatórugók katonai előkészületekhez vagy közvetlen fenyegetésekhez kapcsolódnak."
            )
        elif signal48 and d48 == "decrease" and oi > 60:
            core = (
                "A csökkenő rövid távú aktivitási forecast és a magas stratégiai nyomás eltérő szintű folyamatot jelez. A katonai műveletek ideiglenesen "
                "mérséklődhetnek, miközben a politikai, katonai vagy gazdasági kényszerítés továbbra is erős marad."
            )
        elif signal48 and d48 == "decrease" and oi < 40:
            core = (
                "A csökkenő 48 órás aktivitási jelzés és az alacsony stratégiai nyomás egymást erősítő deeszkalációs képet ad. Ettől függetlenül a modell "
                "nem képes kizárni egyedi válaszcsapásokat vagy váratlan külső sokkokat."
            )
        else:
            core = (
                "A Forecast és a Strategic Pressure jelenleg nem ad egyszerű, egyirányú képet. A publikus forecast hiánya vagy a középső nyomástartomány "
                "azt jelzi, hogy több versengő forgatókönyv marad nyitva, ezért a napi események minősége fontosabb lehet azok puszta számánál."
            )
        return [
            core,
            (
                f"Az összesített stratégiai trend {escape(trend_label(ot, 'hu'))}. Az értelmezésnél külön kell választani a műveleti aktivitás várható "
                "változását a felek hosszabb távú politikai érdekeitől. A két modell együtt használva adja a legjobb helyzetképet."
            ),
        ]
    if signal48 and d48 == "increase" and oi < 40:
        core = (
            "A public 48-hour increase signal combined with reduced strategic pressure may indicate that the next operational surge will remain limited "
            "or will primarily serve deterrence and bargaining leverage. Near-term military activity should therefore not automatically be read as the start of a sustained escalation cycle."
        )
    elif signal48 and d48 == "increase" and oi >= 60:
        core = (
            "The 48-hour increase signal and elevated strategic pressure point in the same direction. Together they reinforce the risk of near-term escalation, "
            "particularly when the leading drivers involve military preparation or explicit threats."
        )
    elif signal48 and d48 == "decrease" and oi > 60:
        core = (
            "A declining near-term activity forecast alongside high strategic pressure indicates processes operating at different levels. Military operations may ease temporarily "
            "while political, military, or economic coercion remains strong."
        )
    elif signal48 and d48 == "decrease" and oi < 40:
        core = (
            "A declining 48-hour activity signal and low strategic pressure provide mutually reinforcing evidence of de-escalation. The model nevertheless cannot exclude isolated retaliation or an external shock."
        )
    else:
        core = (
            "The Forecast and Strategic Pressure layers do not currently produce a simple one-directional picture. The absence of a public signal, or an overall reading in the middle range, "
            "means that several competing scenarios remain open and that the quality of events may matter more than their number."
        )
    return [
        core,
        (
            f"The overall strategic trend is {escape(trend_label(ot, 'en'))}. Interpretation must distinguish expected changes in operational activity from the actors' longer-term political interests. "
            "The two models provide the strongest situational picture when used together."
        ),
    ]



def executive_summary(
    forecast: Mapping[str, Any],
    pressure: Mapping[str, Any],
    interest: Mapping[str, Any],
    success: Mapping[str, Any],
    lang: str,
) -> dict[str, Any]:
    h48 = horizon_data(forecast, "48h")
    h72 = horizon_data(forecast, "72h")
    raw48 = h48.get("raw_prediction") if isinstance(h48.get("raw_prediction"), Mapping) else {}
    raw72 = h72.get("raw_prediction") if isinstance(h72.get("raw_prediction"), Mapping) else {}
    pub48 = h48.get("public_signal") if isinstance(h48.get("public_signal"), Mapping) else {}
    pub72 = h72.get("public_signal") if isinstance(h72.get("public_signal"), Mapping) else {}

    overall = nested(pressure, "current", "overall", default={})
    overall = overall if isinstance(overall, Mapping) else {}
    achievement = achievement_summary(interest)
    success_data = success_summary(success)

    d48 = str(raw48.get("direction") or "no_signal")
    d72 = str(raw72.get("direction") or "no_signal")
    s48 = bool(pub48.get("has_signal"))
    s72 = bool(pub72.get("has_signal"))
    pressure_index = number(overall.get("pressure_index_7d"), 50.0)
    pressure_trend = str(overall.get("trend") or "stable")
    usa_achievement = number(achievement.get("usa_achievement_index"), 50.0)
    iran_achievement = number(achievement.get("iran_achievement_index"), 50.0)
    achievement_gap = number(achievement.get("achievement_gap"), usa_achievement - iran_achievement)
    usa_success = number(success_data.get("usa_success_index"), 50.0)
    iran_success = number(success_data.get("iran_success_index"), 50.0)
    success_gap = number(success_data.get("success_gap"), usa_success - iran_success)
    strategic_advantage = str(success_data.get("strategic_advantage") or "balanced")
    maturity = str(nested(success, "current", "data_maturity", "status", default="unknown"))
    observations = integer(nested(success, "current", "data_maturity", "observations", default=0))
    confidence_percent = number(nested(success, "current", "data_maturity", "confidence_percent", default=0.0))

    if lang == "hu":
        if pressure_index < 40:
            environment = "a stratégiai nyomás alacsony és csökkenő környezetet jelez"
        elif pressure_index > 60:
            environment = "a stratégiai nyomás emelkedett és fokozott kényszerítési környezetet jelez"
        else:
            environment = "a stratégiai nyomás vegyes, középső tartományban marad"

        if strategic_advantage == "usa":
            balance = "az Egyesült Államok mérsékelt stratégiai előnye"
        elif strategic_advantage == "iran":
            balance = "Irán mérsékelt stratégiai előnye"
        else:
            balance = "kiegyensúlyozott stratégiai erőviszony"

        overall_text = (
            f"A napi összkép szerint {environment}. A rövid távú Forecast "
            f"{escape(DIRECTION_LABELS['hu'].get(d48, d48))} irányt jelez 48 órára"
            + (" és publikálható jelzést adott. " if s48 else ", de a jelzés nem érte el a teljes publikációs küszöböt. ")
            + f"A stratégiai eredményességi modell {balance} állapotát mutatja. "
            f"Az érdekérvényesülési különbség {achievement_gap:+.2f} pont, a Strategic Success különbsége {success_gap:+.2f} pont."
        )
        findings = [
            f"A 48 órás Forecast: {DIRECTION_LABELS['hu'].get(d48, d48)}; a 72 órás irány: {DIRECTION_LABELS['hu'].get(d72, d72)}.",
            f"Az összesített Strategic Pressure index {pressure_index:.1f}, trendje {trend_label(pressure_trend, 'hu')}.",
            f"Az Interest Achievement az USA esetében {usa_achievement:.1f}, Irán esetében {iran_achievement:.1f}; a napi előny {advantage_label(achievement.get('daily_strategic_advantage'), 'hu')}.",
            f"A Strategic Success az USA esetében {usa_success:.1f}, Irán esetében {iran_success:.1f}; a modell {advantage_label(strategic_advantage, 'hu')} helyzetet jelez.",
            "A napi események értelmezésében a diplomáciai, katonai és gazdasági jeleket együtt kell kezelni; egyetlen modell önmagában nem ad teljes konfliktusképet.",
        ]
        confidence = (
            f"<b>{'MAGAS' if confidence_percent >= 80 else 'KÖZEPES' if confidence_percent >= 50 else 'ALACSONY'}</b><br/>"
            f"Adatérettség: {escape(maturity)}<br/>"
            f"Felhasznált megfigyelések: {observations}<br/>"
            f"Érettségi konfidencia: {confidence_percent:.0f}%<br/>"
            "Elemzési rétegek: 4"
        )
    else:
        if pressure_index < 40:
            environment = "strategic pressure indicates a low and declining coercive environment"
        elif pressure_index > 60:
            environment = "strategic pressure indicates an elevated coercive environment"
        else:
            environment = "strategic pressure remains in a mixed middle range"

        if strategic_advantage == "usa":
            balance = "a modest US strategic advantage"
        elif strategic_advantage == "iran":
            balance = "a modest Iranian strategic advantage"
        else:
            balance = "a broadly balanced strategic position"

        overall_text = (
            f"The daily picture indicates that {environment}. The near-term Forecast points to "
            f"{escape(DIRECTION_LABELS['en'].get(d48, d48))} over 48 hours"
            + (" and passed the publication gate. " if s48 else ", but did not meet the full publication threshold. ")
            + f"The Strategic Success model indicates {balance}. "
            f"The Interest Achievement gap is {achievement_gap:+.2f} points and the Strategic Success gap is {success_gap:+.2f} points."
        )
        findings = [
            f"The 48-hour Forecast indicates {DIRECTION_LABELS['en'].get(d48, d48)}; the 72-hour direction is {DIRECTION_LABELS['en'].get(d72, d72)}.",
            f"The overall Strategic Pressure Index is {pressure_index:.1f}, with a {trend_label(pressure_trend, 'en')} trend.",
            f"Interest Achievement is {usa_achievement:.1f} for the United States and {iran_achievement:.1f} for Iran; the daily position is {advantage_label(achievement.get('daily_strategic_advantage'), 'en')}.",
            f"Strategic Success is {usa_success:.1f} for the United States and {iran_success:.1f} for Iran; the model indicates a {advantage_label(strategic_advantage, 'en')} position.",
            "Diplomatic, military, and economic signals must be interpreted together; no single model provides a complete conflict picture.",
        ]
        confidence = (
            f"<b>{'HIGH' if confidence_percent >= 80 else 'MEDIUM' if confidence_percent >= 50 else 'LOW'}</b><br/>"
            f"Data maturity: {escape(maturity)}<br/>"
            f"Observations used: {observations}<br/>"
            f"Maturity confidence: {confidence_percent:.0f}%<br/>"
            "Analytical layers: 4"
        )

    return {"overall": overall_text, "findings": findings, "confidence": confidence}

def principal_drivers(pressure: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for actor in ("usa", "iran"):
        actor_data = pressure_actor(pressure, actor)
        items = actor_data.get("strongest_contributors") or actor_data.get("contributors") or []
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            score = number(item.get("final_score"))
            if score == 0:
                continue
            title = str(item.get("title") or "Untitled event")
            key = (actor, title)
            if key in seen:
                continue
            seen.add(key)
            indicators = item.get("indicators") if isinstance(item.get("indicators"), Sequence) else []
            indicator = "-"
            if indicators and isinstance(indicators[0], Mapping):
                indicator = str(indicators[0].get("name") or indicators[0].get("id") or "-")
            rows.append(
                {
                    "actor": actor,
                    "title": title,
                    "indicator": indicator,
                    "score": score,
                    "source": str(item.get("source") or "-"),
                    "link": str(item.get("link") or ""),
                    "date": str(item.get("date") or ""),
                }
            )
    rows.sort(key=lambda item: abs(number(item["score"])), reverse=True)
    return rows[:8]


def analogue_summary(forecast: Mapping[str, Any], horizon: str, limit: int = 5) -> list[Mapping[str, Any]]:
    raw = nested(forecast, "horizons", horizon, "raw_prediction", default={})
    raw = raw if isinstance(raw, Mapping) else {}
    items = raw.get("nearest_analogues") or []
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return []
    return [item for item in items[:limit] if isinstance(item, Mapping)]



def achievement_summary(interest: Mapping[str, Any]) -> Mapping[str, Any]:
    value = nested(interest, "current", "summary", default={})
    return value if isinstance(value, Mapping) else {}


def success_summary(success: Mapping[str, Any]) -> Mapping[str, Any]:
    value = nested(success, "current", "summary", default={})
    return value if isinstance(value, Mapping) else {}


def success_actor(success: Mapping[str, Any], actor: str) -> Mapping[str, Any]:
    value = nested(success, "current", "actors", actor, default={})
    return value if isinstance(value, Mapping) else {}


def interest_actor(interest: Mapping[str, Any], actor: str) -> Mapping[str, Any]:
    value = nested(interest, "current", "actors", actor, default={})
    return value if isinstance(value, Mapping) else {}


def advantage_label(value: Any, lang: str) -> str:
    code = str(value or "balanced").lower()
    labels = {
        "hu": {"usa": "amerikai", "iran": "iráni", "balanced": "kiegyensúlyozott"},
        "en": {"usa": "US", "iran": "Iranian", "balanced": "balanced"},
    }
    return labels[lang].get(code, code.replace("_", " "))


def build_interest_table(interest: Mapping[str, Any], lang: str, styles: Mapping[str, ParagraphStyle]) -> Table:
    labels = TEXT[lang]
    summary = achievement_summary(interest)
    if lang == "hu":
        header = ["Szereplő", "Érdekérvényesülési index", "Semlegeshez képest", "Trend", "Bizonyított érdekek"]
    else:
        header = ["Actor", "Achievement index", "Change from neutral", "Trend", "Interests with evidence"]
    data: list[list[Any]] = [[Paragraph(escape(x), styles["table_bold"]) for x in header]]
    for actor, display in (("usa", labels["usa"]), ("iran", labels["iran"])):
        obj = interest_actor(interest, actor)
        data.append([
            Paragraph(escape(display), styles["table"]),
            Paragraph(fmt_num(obj.get("achievement_index"), 2), styles["table"]),
            Paragraph(f"{number(obj.get('change_from_neutral')):+.2f}", styles["table"]),
            Paragraph(escape(trend_label(obj.get("trend"), lang)), styles["table"]),
            Paragraph(f"{integer(obj.get('interests_with_evidence'))}/{integer(obj.get('interest_count'))}", styles["table"]),
        ])
    gap = number(summary.get("achievement_gap"))
    data.append([
        Paragraph(escape(labels["overall"]), styles["table"]),
        Paragraph(f"{gap:+.2f}", styles["table"]),
        Paragraph("-", styles["table"]),
        Paragraph(escape(advantage_label(summary.get("daily_strategic_advantage"), lang)), styles["table"]),
        Paragraph("-", styles["table"]),
    ])
    table = Table(data, colWidths=[38*mm, 39*mm, 34*mm, 35*mm, 28*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1B4D7A")),
        ("GRID", (0,0), (-1,-1), 0.35, colors.HexColor("#CAD6E2")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F5F8FB")]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 4), ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    return table


def build_success_table(success: Mapping[str, Any], lang: str, styles: Mapping[str, ParagraphStyle]) -> Table:
    labels = TEXT[lang]
    if lang == "hu":
        header = ["Szereplő", "Success index", "Érdek", "Momentum", "Stabilitás", "Konzisztencia"]
    else:
        header = ["Actor", "Success index", "Achievement", "Momentum", "Stability", "Consistency"]
    data: list[list[Any]] = [[Paragraph(escape(x), styles["table_bold"]) for x in header]]
    for actor, display in (("usa", labels["usa"]), ("iran", labels["iran"])):
        obj = success_actor(success, actor)
        components = obj.get("components") if isinstance(obj.get("components"), Mapping) else {}
        data.append([
            Paragraph(escape(display), styles["table"]),
            Paragraph(fmt_num(obj.get("success_index"), 2), styles["table"]),
            Paragraph(fmt_num(nested(components, "achievement", "value", default=0), 2), styles["table"]),
            Paragraph(fmt_num(nested(components, "momentum", "score", default=0), 2), styles["table"]),
            Paragraph(fmt_num(nested(components, "stability", "score", default=0), 2), styles["table"]),
            Paragraph(fmt_num(nested(components, "consistency", "score", default=0), 2), styles["table"]),
        ])
    table = Table(data, colWidths=[38*mm, 29*mm, 27*mm, 27*mm, 27*mm, 27*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1B4D7A")),
        ("GRID", (0,0), (-1,-1), 0.35, colors.HexColor("#CAD6E2")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F5F8FB")]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 4), ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    return table



def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    """Yield every mapping in an arbitrarily nested JSON-compatible value."""
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            yield from _walk_mappings(child)


def _interest_result(interest: Mapping[str, Any], actor: str, interest_id: str) -> Mapping[str, Any]:
    """Find the daily result object for one strategic interest without assuming one fixed schema."""
    actor_root = interest_actor(interest, actor)
    candidates: list[Mapping[str, Any]] = []
    for obj in _walk_mappings(actor_root):
        oid = str(obj.get("interest_id") or obj.get("id") or obj.get("strategic_interest_id") or "")
        if oid == interest_id:
            candidates.append(obj)
    if not candidates:
        return {}
    # Prefer the richest object because it usually contains score, evidence and rationale.
    return max(candidates, key=lambda item: len(item))


def _evidence_count(obj: Mapping[str, Any]) -> int:
    for key in ("evidence_count", "matched_events", "event_count", "observations", "sources_count"):
        if key in obj:
            value = obj.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return len(value)
            return integer(value)
    for key in ("evidence", "events", "sources", "drivers"):
        value = obj.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return len(value)
    return 0


def _interest_effect(obj: Mapping[str, Any]) -> float | None:
    for key in ("weighted_effect", "net_effect", "effect", "impact", "score", "contribution", "change"):
        if key in obj and obj.get(key) is not None:
            try:
                return float(obj.get(key))
            except (TypeError, ValueError):
                pass
    return None


def _interest_status(effect: float | None, evidence: int, lang: str) -> str:
    if evidence == 0 and effect is None:
        return "nincs közvetlen napi bizonyíték" if lang == "hu" else "no direct daily evidence"
    value = effect or 0.0
    if value >= 1.5:
        return "erősen támogatott" if lang == "hu" else "strongly supported"
    if value > 0.15:
        return "támogatott" if lang == "hu" else "supported"
    if value <= -1.5:
        return "erősen gyengült" if lang == "hu" else "strongly weakened"
    if value < -0.15:
        return "gyengült" if lang == "hu" else "weakened"
    return "semleges vagy vegyes" if lang == "hu" else "neutral or mixed"


def _interest_rationale(obj: Mapping[str, Any], lang: str) -> str:
    for key in ("assessment", "rationale", "explanation", "interpretation", "summary", "reason"):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    evidence = obj.get("evidence") or obj.get("events") or obj.get("drivers")
    if isinstance(evidence, Sequence) and not isinstance(evidence, (str, bytes)):
        parts = []
        for item in evidence[:2]:
            if isinstance(item, Mapping):
                text = item.get("title") or item.get("event") or item.get("description") or item.get("indicator_name")
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        if parts:
            return "; ".join(parts)
    return (
        "A napi modell nem rendelt részletes szöveges indoklást ehhez az érdekhez."
        if lang == "hu" else
        "The daily model did not provide a detailed textual rationale for this interest."
    )


def build_interest_detail_section(
    interest: Mapping[str, Any],
    strategic_interests: Mapping[str, Any],
    lang: str,
    styles: Mapping[str, ParagraphStyle],
) -> list[Any]:
    """Create actor-by-actor analysis of every defined strategic interest."""
    labels = TEXT[lang]
    flow: list[Any] = []
    actors = strategic_interests.get("actors") if isinstance(strategic_interests.get("actors"), Mapping) else {}
    for actor, display in (("usa", labels["usa"]), ("iran", labels["iran"])):
        actor_cfg = actors.get(actor) if isinstance(actors.get(actor), Mapping) else {}
        definitions = actor_cfg.get("interests") if isinstance(actor_cfg.get("interests"), Sequence) else []
        actor_daily = interest_actor(interest, actor)
        idx = number(actor_daily.get("achievement_index"), 50)
        trend = trend_label(actor_daily.get("trend"), lang)
        flow.append(CondPageBreak(70 * mm))
        flow.append(Paragraph(
            (f"{display}: stratégiai érdekek részletes helyzete" if lang == "hu" else f"{display}: detailed status of strategic interests"),
            styles["h2"],
        ))
        intro = (
            f"A szereplő napi indexe <b>{idx:.2f}</b>, trendje {escape(trend)}. Az alábbi bontás nemcsak a végső indexet, hanem a modellben rögzített célokat, azok súlyát, a napi bizonyítékot és az aktuális értelmezést is bemutatja."
            if lang == "hu" else
            f"The actor's daily index is <b>{idx:.2f}</b>, with a {escape(trend)} trend. The breakdown below presents not only the final index but also the defined objectives, their weights, daily evidence, and current interpretation."
        )
        flow.append(Paragraph(intro, styles["body"]))
        header = (["Stratégiai érdek", "Súly", "Napi helyzet", "Bizonyíték", "Értelmezés"] if lang == "hu"
                  else ["Strategic interest", "Weight", "Daily status", "Evidence", "Interpretation"])
        rows: list[list[Any]] = [[Paragraph(escape(x), styles["table_bold"]) for x in header]]
        for definition in definitions:
            if not isinstance(definition, Mapping):
                continue
            iid = str(definition.get("id") or "")
            result = _interest_result(interest, actor, iid)
            effect = _interest_effect(result)
            evidence = _evidence_count(result)
            status = _interest_status(effect, evidence, lang)
            name = str(definition.get("name") or iid)
            description = str(definition.get("description") or "")
            interest_cell = f"<b>{escape(name)}</b><br/><font size='7.5'>{escape(description)}</font>"
            evidence_text = str(evidence) if evidence else ("0" if result else "-")
            interpretation = _interest_rationale(result, lang) if result else (
                "A jelenlegi napi események alapján nincs közvetlenül azonosított hatás. Ez nem jelenti azt, hogy az érdek nem fontos; csak azt, hogy ezen a napon nem volt hozzá elég bizonyíték."
                if lang == "hu" else
                "No direct effect was identified from the current day's events. This does not make the interest unimportant; it means the day supplied insufficient evidence for a specific assessment."
            )
            rows.append([
                Paragraph(interest_cell, styles["table"]),
                Paragraph(str(integer(definition.get("weight"))), styles["table"]),
                Paragraph(escape(status), styles["table"]),
                Paragraph(escape(evidence_text), styles["table"]),
                Paragraph(escape(interpretation), styles["table"]),
            ])
        table = Table(rows, colWidths=[45*mm, 13*mm, 29*mm, 18*mm, 69*mm], repeatRows=1, splitByRow=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1B4D7A")),
            ("GRID", (0,0), (-1,-1), 0.35, colors.HexColor("#CAD6E2")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F5F8FB")]),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 4), ("RIGHTPADDING", (0,0), (-1,-1), 4),
            ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ]))
        flow.append(table)
        flow.append(Spacer(1, 4 * mm))
    return flow


def build_success_detail_section(success: Mapping[str, Any], lang: str, styles: Mapping[str, ParagraphStyle]) -> list[Any]:
    flow: list[Any] = []
    labels = TEXT[lang]
    component_names = {
        "achievement": ("Érdekérvényesülés", "Achievement"),
        "momentum": ("Momentum", "Momentum"),
        "stability": ("Stabilitás", "Stability"),
        "consistency": ("Konzisztencia", "Consistency"),
    }
    for actor, display in (("usa", labels["usa"]), ("iran", labels["iran"])):
        obj = success_actor(success, actor)
        components = obj.get("components") if isinstance(obj.get("components"), Mapping) else {}
        flow.append(CondPageBreak(55 * mm))
        flow.append(Paragraph((f"{display}: a siker összetevői" if lang == "hu" else f"{display}: components of success"), styles["h2"]))
        rows = [[Paragraph(x, styles["table_bold"]) for x in ((["Komponens", "Érték", "Mit jelent?"] if lang == "hu" else ["Component", "Value", "Meaning"]))]]
        explanations_hu = {
            "achievement": "A napi események mennyiben támogatják a szereplő súlyozott stratégiai érdekeit.",
            "momentum": "Javul-e vagy romlik-e a közelmúlt teljesítménye a hosszabb távú átlaghoz képest.",
            "stability": "Mennyire alacsony az index ingadozása; a magasabb érték kiszámíthatóbb teljesítményt jelez.",
            "consistency": "Mennyire tartósak és ismétlődők a kedvező napok, nem csupán egyszeri kiugrásról van-e szó.",
        }
        explanations_en = {
            "achievement": "How far the day's developments support the actor's weighted strategic interests.",
            "momentum": "Whether recent performance is improving or weakening relative to the longer-term average.",
            "stability": "How limited the index volatility is; a higher value indicates more predictable performance.",
            "consistency": "Whether favourable days are persistent and repeated rather than a single temporary spike.",
        }
        for key in ("achievement", "momentum", "stability", "consistency"):
            comp = components.get(key) if isinstance(components.get(key), Mapping) else {}
            val = comp.get("value", comp.get("score", comp.get("index", 0)))
            rows.append([
                Paragraph(component_names[key][0 if lang == "hu" else 1], styles["table"]),
                Paragraph(fmt_num(val, 2), styles["table"]),
                Paragraph((explanations_hu if lang == "hu" else explanations_en)[key], styles["table"]),
            ])
        table = Table(rows, colWidths=[35*mm, 24*mm, 115*mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1B4D7A")),
            ("GRID", (0,0), (-1,-1), 0.35, colors.HexColor("#CAD6E2")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F5F8FB")]),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 4), ("RIGHTPADDING", (0,0), (-1,-1), 4),
            ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ]))
        flow.append(table)
        flow.append(Paragraph(
            ("A végső Strategic Success érték ezért nem egyszerű napi rangsor: azt mutatja, hogy a kedvező vagy kedvezőtlen helyzet mennyire tartós, stabil és ismétlődő."
             if lang == "hu" else
             "The final Strategic Success reading is therefore not a simple daily ranking: it tests whether favourable or adverse performance is persistent, stable, and repeatable."),
            styles["body"],
        ))
    return flow

def analyse_interest(interest: Mapping[str, Any], lang: str) -> list[str]:
    summary = achievement_summary(interest)
    usa = interest_actor(interest, "usa")
    iran = interest_actor(interest, "iran")
    ui, ii = number(usa.get("achievement_index"), 50), number(iran.get("achievement_index"), 50)
    gap = number(summary.get("achievement_gap"), ui-ii)
    advantage = advantage_label(summary.get("daily_strategic_advantage"), lang)
    if lang == "hu":
        return [
            f"Az amerikai stratégiai érdekérvényesülési index <b>{ui:.2f}</b>, az iráni <b>{ii:.2f}</b>. A különbség {gap:+.2f} pont, ezért a napi helyzet <b>{escape(advantage)}</b>.",
            "Az index azt méri, hogy az adott napon azonosított fejlemények mennyiben támogatják vagy gyengítik az egyes szereplők saját, súlyozott stratégiai érdekeit. Nem katonai győzelmi mutató.",
        ]
    return [
        f"The US Strategic Interest Achievement Index is <b>{ui:.2f}</b>, while Iran's is <b>{ii:.2f}</b>. The gap is {gap:+.2f} points, producing a <b>{escape(advantage)}</b> daily balance.",
        "The index measures whether detected developments support or weaken each actor's own weighted strategic interests. It is not a military-victory indicator.",
    ]


def analyse_success(success: Mapping[str, Any], lang: str) -> list[str]:
    summary = success_summary(success)
    usa, iran = success_actor(success, "usa"), success_actor(success, "iran")
    ui, ii = number(usa.get("success_index"), 50), number(iran.get("success_index"), 50)
    gap = number(summary.get("success_gap"), ui-ii)
    advantage = advantage_label(summary.get("strategic_advantage"), lang)
    maturity = nested(success, "current", "data_maturity", "status", default="unknown")
    if lang == "hu":
        return [
            f"Az amerikai Strategic Success index <b>{ui:.2f}</b>, az iráni <b>{ii:.2f}</b>. A különbség {gap:+.2f} pont; a modell szerinti stratégiai előny: <b>{escape(advantage)}</b>.",
            f"A jelenlegi adatérettség státusza <b>{escape(maturity)}</b>. A mutató az érdekérvényesülést, a momentumot, a stabilitást és a konzisztenciát egyesíti, ezért a napi teljesítmény fenntarthatóságát is vizsgálja.",
        ]
    return [
        f"The US Strategic Success Index is <b>{ui:.2f}</b>, compared with <b>{ii:.2f}</b> for Iran. The gap is {gap:+.2f} points; the model's strategic advantage is <b>{escape(advantage)}</b>.",
        f"Current data maturity is <b>{escape(maturity)}</b>. The measure combines achievement, momentum, stability, and consistency, thereby testing whether daily performance appears sustainable.",
    ]


def integrated_assessment(forecast: Mapping[str, Any], pressure: Mapping[str, Any], interest: Mapping[str, Any], success: Mapping[str, Any], lang: str) -> list[str]:
    h48 = horizon_data(forecast, "48h")
    raw = h48.get("raw_prediction") if isinstance(h48.get("raw_prediction"), Mapping) else {}
    forecast_dir = str(raw.get("direction") or "no_signal")
    pressure_overall = number(nested(pressure, "current", "overall", "pressure_index_7d", default=50), 50)
    ia = achievement_summary(interest)
    ss = success_summary(success)
    ia_adv = advantage_label(ia.get("daily_strategic_advantage"), lang)
    ss_adv = advantage_label(ss.get("strategic_advantage"), lang)
    if lang == "hu":
        return [
            f"A 48 órás forecast nyers iránya <b>{escape(DIRECTION_LABELS['hu'].get(forecast_dir, forecast_dir))}</b>, miközben az összesített stratégiai nyomásindex <b>{pressure_overall:.1f}</b>. A napi érdekérvényesülési egyensúly {escape(ia_adv)}, a fenntartható stratégiai eredményesség pedig {escape(ss_adv)} képet mutat.",
            "A négy modell eltérő elemzési szintet mér: a Forecast a várható műveleti aktivitást, a Strategic Pressure a kényszerítő és visszafogó ösztönzőket, az Interest Achievement a napi stratégiai érdekilleszkedést, a Strategic Success pedig ennek tartósságát. Az integrált értékelés ezért nem egyetlen index egyszerű ismétlése.",
        ]
    return [
        f"The raw 48-hour forecast direction is <b>{escape(DIRECTION_LABELS['en'].get(forecast_dir, forecast_dir))}</b>, while the overall Strategic Pressure Index is <b>{pressure_overall:.1f}</b>. Daily interest achievement is {escape(ia_adv)}, and sustainable strategic success is {escape(ss_adv)}.",
        "The four models operate at different analytical levels: Forecast estimates operational activity, Strategic Pressure measures coercive and restraining incentives, Interest Achievement measures daily alignment with strategic interests, and Strategic Success evaluates sustainability. The integrated assessment is therefore not a repetition of a single index.",
    ]

def register_fonts() -> tuple[str, str]:
    candidates = [
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ),
        (
            Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
            Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
        ),
    ]
    for regular, bold in candidates:
        if regular.exists() and bold.exists():
            pdfmetrics.registerFont(TTFont("TV-Regular", str(regular)))
            pdfmetrics.registerFont(TTFont("TV-Bold", str(bold)))
            pdfmetrics.registerFontFamily(
                "TV", normal="TV-Regular", bold="TV-Bold", italic="TV-Regular", boldItalic="TV-Bold"
            )
            return "TV-Regular", "TV-Bold"
    return "Helvetica", "Helvetica-Bold"



def model_version(data: Mapping[str, Any], *paths: Sequence[str]) -> str:
    for path in paths:
        value = nested(data, *path, default=None)
        if value not in (None, ""):
            return str(value)
    return "-"


def file_status(data: Mapping[str, Any], lang: str) -> str:
    if not data:
        return "hiányzik" if lang == "hu" else "missing"
    status = str(data.get("status") or nested(data, "metadata", "status", default="") or "")
    if status:
        return status
    return "elérhető" if lang == "hu" else "available"


def build_input_files_table(
    forecast: Mapping[str, Any],
    pressure: Mapping[str, Any],
    interest: Mapping[str, Any],
    success: Mapping[str, Any],
    strategic_interests: Mapping[str, Any],
    strategic_indicators: Mapping[str, Any],
    interest_impact_map: Mapping[str, Any],
    lang: str,
    styles: Mapping[str, ParagraphStyle],
) -> Table:
    labels = TEXT[lang]
    header = [
        labels["model_name"], labels["file_path"], labels["version"],
        labels["reference"], labels["role"], labels["status"],
    ]
    rows: list[list[Any]] = [[Paragraph(escape(x), styles["table_bold"]) for x in header]]

    if lang == "hu":
        items = [
            ("Forecast", "docs/conflict_forecast_live.json", model_version(forecast, ("model_version",), ("forecast_model",)),
             str(forecast.get("forecast_reference_date") or "-"), "48 és 72 órás aktivitási irány", file_status(forecast, lang)),
            ("Strategic Pressure", "docs/strategic_pressure.json", model_version(pressure, ("model",)),
             str(nested(pressure, "current", "date", default=pressure.get("latest_complete_utc_day") or "-")),
             "Hét napos stratégiai nyomás és mozgatórugók", file_status(pressure, lang)),
            ("Interest Achievement", "docs/interest_achievement.json", model_version(interest, ("metadata", "model")),
             str(nested(interest, "current", "date", default=nested(interest, "metadata", "reference_date", default="-"))),
             "A súlyozott stratégiai érdekek napi teljesülése", file_status(interest, lang)),
            ("Strategic Success", "docs/strategic_success.json", model_version(success, ("metadata", "model_version")),
             str(nested(success, "current", "date", default=nested(success, "metadata", "current_date", default="-"))),
             "Érdekérvényesülés, momentum, stabilitás és konzisztencia", file_status(success, lang)),
            ("Strategic Interests", "data/strategic/strategic_interests.json", model_version(strategic_interests, ("model_version",), ("metadata", "model_version")),
             "konfiguráció", "A felek súlyozott stratégiai érdekeinek definíciója", file_status(strategic_interests, lang)),
            ("Strategic Indicators", "data/strategic/strategic_indicators.json", model_version(strategic_indicators, ("model_version",), ("metadata", "model_version")),
             "konfiguráció", "Szemantikai indikátorok és felismerési szabályok", file_status(strategic_indicators, lang)),
            ("Interest Impact Map", "data/strategic/interest_impact_map.json", model_version(interest_impact_map, ("model_version",), ("metadata", "model_version")),
             "konfiguráció", "Az indikátorok stratégiai érdekekre gyakorolt hatása", file_status(interest_impact_map, lang)),
        ]
    else:
        items = [
            ("Forecast", "docs/conflict_forecast_live.json", model_version(forecast, ("model_version",), ("forecast_model",)),
             str(forecast.get("forecast_reference_date") or "-"), "48- and 72-hour activity direction", file_status(forecast, lang)),
            ("Strategic Pressure", "docs/strategic_pressure.json", model_version(pressure, ("model",)),
             str(nested(pressure, "current", "date", default=pressure.get("latest_complete_utc_day") or "-")),
             "Seven-day strategic pressure and principal drivers", file_status(pressure, lang)),
            ("Interest Achievement", "docs/interest_achievement.json", model_version(interest, ("metadata", "model")),
             str(nested(interest, "current", "date", default=nested(interest, "metadata", "reference_date", default="-"))),
             "Daily performance of weighted strategic interests", file_status(interest, lang)),
            ("Strategic Success", "docs/strategic_success.json", model_version(success, ("metadata", "model_version")),
             str(nested(success, "current", "date", default=nested(success, "metadata", "current_date", default="-"))),
             "Achievement, momentum, stability, and consistency", file_status(success, lang)),
            ("Strategic Interests", "data/strategic/strategic_interests.json", model_version(strategic_interests, ("model_version",), ("metadata", "model_version")),
             "configuration", "Definitions and weights of actor interests", file_status(strategic_interests, lang)),
            ("Strategic Indicators", "data/strategic/strategic_indicators.json", model_version(strategic_indicators, ("model_version",), ("metadata", "model_version")),
             "configuration", "Semantic indicators and recognition rules", file_status(strategic_indicators, lang)),
            ("Interest Impact Map", "data/strategic/interest_impact_map.json", model_version(interest_impact_map, ("model_version",), ("metadata", "model_version")),
             "configuration", "Mapped effects of indicators on strategic interests", file_status(interest_impact_map, lang)),
        ]

    for item in items:
        rows.append([Paragraph(escape(value), styles["table"]) for value in item])

    table = Table(
        rows,
        colWidths=[29 * mm, 42 * mm, 27 * mm, 24 * mm, 43 * mm, 17 * mm],
        repeatRows=1,
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B4D7A")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CAD6E2")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F8FB")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def build_at_glance_table(
    forecast: Mapping[str, Any],
    pressure: Mapping[str, Any],
    interest: Mapping[str, Any],
    success: Mapping[str, Any],
    lang: str,
    styles: Mapping[str, ParagraphStyle],
) -> Table:
    labels = TEXT[lang]
    h48 = horizon_data(forecast, "48h")
    h72 = horizon_data(forecast, "72h")
    overall = nested(pressure, "current", "overall", default={})
    achievement = achievement_summary(interest)
    success_data = success_summary(success)

    if lang == "hu":
        data = [
            ["Konfliktus", labels["conflict"]],
            ["48 órás Forecast", direction(h48, lang, public=True)],
            ["72 órás Forecast", direction(h72, lang, public=True)],
            ["Strategic Pressure", f"{number(overall.get('pressure_index_7d'), 50):.1f} – {level_label(overall.get('pressure_level'), lang)}"],
            ["Interest Achievement", f"USA {number(achievement.get('usa_achievement_index'), 50):.1f} | Irán {number(achievement.get('iran_achievement_index'), 50):.1f}"],
            ["Strategic Success", f"USA {number(success_data.get('usa_success_index'), 50):.1f} | Irán {number(success_data.get('iran_success_index'), 50):.1f}"],
            ["Stratégiai helyzet", advantage_label(success_data.get("strategic_advantage"), lang)],
            ["Adatérettség", str(nested(success, "current", "data_maturity", "status", default="-"))],
        ]
    else:
        data = [
            ["Conflict", labels["conflict"]],
            ["48-hour Forecast", direction(h48, lang, public=True)],
            ["72-hour Forecast", direction(h72, lang, public=True)],
            ["Strategic Pressure", f"{number(overall.get('pressure_index_7d'), 50):.1f} – {level_label(overall.get('pressure_level'), lang)}"],
            ["Interest Achievement", f"US {number(achievement.get('usa_achievement_index'), 50):.1f} | Iran {number(achievement.get('iran_achievement_index'), 50):.1f}"],
            ["Strategic Success", f"US {number(success_data.get('usa_success_index'), 50):.1f} | Iran {number(success_data.get('iran_success_index'), 50):.1f}"],
            ["Strategic Position", advantage_label(success_data.get("strategic_advantage"), lang)],
            ["Data Maturity", str(nested(success, "current", "data_maturity", "status", default="-"))],
        ]

    rows = [[Paragraph(f"<b>{escape(k)}</b>", styles["table"]), Paragraph(escape(v), styles["table"])] for k, v in data]
    table = Table(rows, colWidths=[58 * mm, 116 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF1F7")),
        ("ROWBACKGROUNDS", (1, 0), (1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#7FA0BF")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CAD6E2")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table

def make_styles(regular_font: str, bold_font: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    navy = colors.HexColor("#102E4A")
    blue = colors.HexColor("#1E5B87")
    steel = colors.HexColor("#5E7487")
    ink = colors.HexColor("#172431")
    return {
        "brand": ParagraphStyle(
            "TVBrand", parent=base["Normal"], fontName=bold_font, fontSize=12,
            leading=14, textColor=navy, alignment=TA_CENTER, spaceAfter=1 * mm,
        ),
        "brand_sub": ParagraphStyle(
            "TVBrandSub", parent=base["Normal"], fontName=bold_font, fontSize=8,
            leading=10, textColor=blue, alignment=TA_CENTER, spaceAfter=1.5 * mm,
        ),
        "brand_categories": ParagraphStyle(
            "TVBrandCategories", parent=base["Normal"], fontName=regular_font, fontSize=7.5,
            leading=10, textColor=steel, alignment=TA_CENTER, spaceAfter=6 * mm,
        ),
        "title": ParagraphStyle(
            "TVTitle", parent=base["Title"], fontName=bold_font, fontSize=24,
            leading=29, textColor=navy, alignment=TA_CENTER, spaceAfter=4 * mm,
        ),
        "tagline": ParagraphStyle(
            "TVTagline", parent=base["Normal"], fontName=regular_font, fontSize=10.2,
            leading=15, textColor=blue, alignment=TA_CENTER, leftIndent=10 * mm,
            rightIndent=10 * mm, spaceAfter=5 * mm,
        ),
        "subtitle": ParagraphStyle(
            "TVSubtitle", parent=base["Normal"], fontName=bold_font, fontSize=13,
            leading=17, textColor=blue, alignment=TA_CENTER, spaceAfter=2 * mm,
        ),
        "meta": ParagraphStyle(
            "TVMeta", parent=base["Normal"], fontName=regular_font, fontSize=8.5,
            leading=12, textColor=steel, alignment=TA_CENTER,
        ),
        "h1": ParagraphStyle(
            "TVH1", parent=base["Heading1"], fontName=bold_font, fontSize=15,
            leading=19, textColor=navy, spaceBefore=5 * mm,
            spaceAfter=2.5 * mm, keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "TVBody", parent=base["BodyText"], fontName=regular_font, fontSize=9.4,
            leading=14.2, textColor=ink, spaceAfter=2.7 * mm, alignment=TA_JUSTIFY,
        ),
        "h2": ParagraphStyle(
            "TIHH2", parent=base["Heading2"], fontName=bold_font, fontSize=11.2,
            leading=14.5, textColor=colors.HexColor("#2F5F8F"), spaceBefore=3.5 * mm,
            spaceAfter=1.7 * mm, keepWithNext=True,
        ),
        "small": ParagraphStyle(
            "TVSmall", parent=base["BodyText"], fontName=regular_font, fontSize=7.7,
            leading=10.5, textColor=colors.HexColor("#455465"), spaceAfter=1.5 * mm, alignment=TA_JUSTIFY,
        ),
        "callout": ParagraphStyle(
            "TVCallout", parent=base["BodyText"], fontName=bold_font, fontSize=10,
            leading=15, textColor=navy, leftIndent=4 * mm, rightIndent=4 * mm,
            spaceBefore=2 * mm, spaceAfter=2 * mm,
        ),
        "workflow": ParagraphStyle(
            "TVWorkflow", parent=base["BodyText"], fontName=bold_font, fontSize=9.2,
            leading=14, textColor=navy, alignment=TA_CENTER,
        ),
        "table": ParagraphStyle(
            "TVTable", parent=base["BodyText"], fontName=regular_font, fontSize=7.1,
            leading=9.2, textColor=ink,
        ),
        "table_bold": ParagraphStyle(
            "TVTableBold", parent=base["BodyText"], fontName=bold_font, fontSize=7.1,
            leading=9.2, textColor=colors.white,
        ),
    }


def header_footer(canvas: Any, doc: Any, lang: str, report_iso_date: str, regular_font: str, bold_font: str) -> None:
    canvas.saveState()
    width, height = A4
    navy = colors.HexColor("#102E4A")
    blue = colors.HexColor("#1E5B87")
    muted = colors.HexColor("#617283")
    line = colors.HexColor("#C9D7E5")

    # The cover carries the full copied Törésvonalak masthead in the story.
    # From page 2 onward a compact version appears in the running header.
    if doc.page > 1:
        canvas.setFont(bold_font, 8.2)
        canvas.setFillColor(navy)
        canvas.drawString(18 * mm, height - 10.2 * mm, "TÖRÉSVONALAK")
        canvas.setFont(bold_font, 6.5)
        canvas.setFillColor(blue)
        canvas.drawString(18 * mm, height - 13.2 * mm, "INTELLIGENCE HUB")

        canvas.setFont(regular_font, 7.2)
        canvas.setFillColor(muted)
        canvas.drawRightString(width - 18 * mm, height - 10.2 * mm, REPORT_SERIES)
        canvas.drawRightString(width - 18 * mm, height - 13.2 * mm, localized_date(report_iso_date, lang))

        canvas.setStrokeColor(line)
        canvas.setLineWidth(0.5)
        canvas.line(18 * mm, height - 15.5 * mm, width - 18 * mm, height - 15.5 * mm)

    canvas.setStrokeColor(line)
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
    canvas.setFont(regular_font, 7.2)
    canvas.setFillColor(muted)
    canvas.drawString(18 * mm, 9.5 * mm, f"{BLOG_URL} | Törésvonalak Intelligence Hub")
    canvas.drawCentredString(width / 2, 9.5 * mm, "Semantic Analysis • Quantitative Assessment • Strategic Intelligence")
    canvas.drawRightString(width - 18 * mm, 9.5 * mm, f"{TEXT[lang]['page']} {doc.page}")
    canvas.restoreState()


def build_pressure_table(pressure: Mapping[str, Any], lang: str, styles: Mapping[str, ParagraphStyle]) -> Table:
    labels = TEXT[lang]
    header = [labels["actor"], labels["index"], labels["level"], labels["trend"]]
    data: list[list[Any]] = [[Paragraph(escape(cell), styles["table_bold"]) for cell in header]]
    for key, display in (("usa", labels["usa"]), ("iran", labels["iran"]), ("overall", labels["overall"])):
        obj = nested(pressure, "current", key, default={})
        obj = obj if isinstance(obj, Mapping) else {}
        data.append([
            Paragraph(escape(display), styles["table"]),
            Paragraph(fmt_num(obj.get("pressure_index_7d"), 1), styles["table"]),
            Paragraph(escape(level_label(obj.get("pressure_level"), lang)), styles["table"]),
            Paragraph(escape(trend_label(obj.get("trend"), lang)), styles["table"]),
        ])
    table = Table(data, colWidths=[50 * mm, 25 * mm, 42 * mm, 47 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B4D7A")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CAD6E2")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F5F8FB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def build_forecast_table(forecast: Mapping[str, Any], lang: str, styles: Mapping[str, ParagraphStyle]) -> Table:
    if lang == "hu":
        header = ["Időtáv", "Publikus jelzés", "Nyers irány", "Valószínűség", "Konfidencia", "Céldátum"]
    else:
        header = ["Horizon", "Public signal", "Raw direction", "Probability", "Confidence", "Target date"]
    data: list[list[Any]] = [[Paragraph(escape(cell), styles["table_bold"]) for cell in header]]
    for key in ("48h", "72h"):
        h = horizon_data(forecast, key)
        raw = h.get("raw_prediction") if isinstance(h.get("raw_prediction"), Mapping) else {}
        pub = h.get("public_signal") if isinstance(h.get("public_signal"), Mapping) else {}
        data.append([
            Paragraph(key, styles["table"]),
            Paragraph(escape(direction(h, lang, public=True)), styles["table"]),
            Paragraph(escape(direction(h, lang, public=False)), styles["table"]),
            Paragraph(pct(raw.get("top_probability")), styles["table"]),
            Paragraph(fmt_num(raw.get("confidence_score"), 3), styles["table"]),
            Paragraph(escape(h.get("target_date") or "-"), styles["table"]),
        ])
    table = Table(data, colWidths=[16 * mm, 38 * mm, 38 * mm, 27 * mm, 27 * mm, 27 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B4D7A")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CAD6E2")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F5F8FB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def build_drivers_table(pressure: Mapping[str, Any], lang: str, styles: Mapping[str, ParagraphStyle]) -> Table | Paragraph:
    rows = principal_drivers(pressure)
    if not rows:
        return Paragraph(TEXT[lang]["no_data"], styles["body"])
    labels = TEXT[lang]
    header = [labels["actor"], labels["indicator"], labels["score"], labels["event"], labels["source"]]
    data: list[list[Any]] = [[Paragraph(escape(cell), styles["table_bold"]) for cell in header]]
    for row in rows:
        actor = labels["usa"] if row["actor"] == "usa" else labels["iran"]
        source = escape(row["source"])
        if row["link"]:
            source = f'<link href="{escape(row["link"])}" color="#1B4D7A">{source}</link>'
        data.append([
            Paragraph(escape(actor), styles["table"]),
            Paragraph(escape(row["indicator"]), styles["table"]),
            Paragraph(f"{number(row['score']):+.1f}", styles["table"]),
            Paragraph(escape(row["title"]), styles["table"]),
            Paragraph(source, styles["table"]),
        ])
    table = Table(data, colWidths=[23 * mm, 28 * mm, 14 * mm, 67 * mm, 42 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B4D7A")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CAD6E2")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F8FB")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def analogue_table(forecast: Mapping[str, Any], horizon: str, lang: str, styles: Mapping[str, ParagraphStyle]) -> Table | None:
    items = analogue_summary(forecast, horizon)
    if not items:
        return None
    if lang == "hu":
        header = ["Analóg nap", "Távolság", "Megfigyelt irány"]
    else:
        header = ["Analogue date", "Distance", "Observed direction"]
    data: list[list[Any]] = [[Paragraph(escape(cell), styles["table_bold"]) for cell in header]]
    for item in items:
        code = str(item.get("observed_direction") or "stable")
        data.append([
            Paragraph(escape(item.get("date") or "-"), styles["table"]),
            Paragraph(fmt_num(item.get("distance"), 3), styles["table"]),
            Paragraph(escape(DIRECTION_LABELS[lang].get(code, code)), styles["table"]),
        ])
    table = Table(data, colWidths=[38 * mm, 30 * mm, 88 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#416F98")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D3DDE7")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FB")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def add_paragraphs(story: list[Any], paragraphs: Iterable[str], styles: Mapping[str, ParagraphStyle]) -> None:
    for text in paragraphs:
        story.append(Paragraph(text, styles["body"]))


def build_pdf(
    forecast: Mapping[str, Any],
    pressure: Mapping[str, Any],
    interest: Mapping[str, Any],
    success: Mapping[str, Any],
    strategic_interests: Mapping[str, Any],
    strategic_indicators: Mapping[str, Any],
    interest_impact_map: Mapping[str, Any],
    lang: str,
    output: Path,
    iso_date: str,
) -> None:
    regular_font, bold_font = register_fonts()
    styles = make_styles(regular_font, bold_font)
    labels = TEXT[lang]
    output.parent.mkdir(parents=True, exist_ok=True)

    doc = BaseDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=21 * mm,
        bottomMargin=18 * mm,
        title=f"{REPORT_SERIES} - {iso_date}",
        author=PROJECT_NAME,
        subject=labels["conflict"],
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    template = PageTemplate(
        id="daily",
        frames=[frame],
        onPage=lambda canvas, current_doc: header_footer(
            canvas, current_doc, lang, iso_date, regular_font, bold_font
        ),
    )
    doc.addPageTemplates([template])

    forecast_model = str(forecast.get("model_version") or forecast.get("forecast_model") or "-")
    pressure_model = str(pressure.get("model") or "-")
    interest_model = str(nested(interest, "metadata", "model", default="-") or "-")
    success_model = str(nested(success, "metadata", "model_version", default="-") or "-")
    generated = forecast.get("generated_at") or pressure.get("generated_at") or nested(interest, "metadata", "generated_at") or nested(success, "metadata", "generated_at")

    categories = (
        "Geopolitika • Biztonságpolitika • Ellátásbiztonság • OSINT-elemzés"
        if lang == "hu"
        else "Geopolitics • Security Policy • Supply Security • OSINT Analysis"
    )

    story: list[Any] = [
        Spacer(1, 9 * mm),
        Paragraph("TÖRÉSVONALAK", styles["brand"]),
        Paragraph("INTELLIGENCE HUB", styles["brand_sub"]),
        Paragraph(categories, styles["brand_categories"]),
        Spacer(1, 12 * mm),
        Paragraph(labels["report_title"], styles["title"]),
        Paragraph(TAGLINE, styles["tagline"]),
        Spacer(1, 5 * mm),
        Paragraph(labels["daily_assessment"], styles["subtitle"]),
        Paragraph(
            f"<b>{labels['date']}:</b> {escape(localized_date(iso_date, lang))}<br/>"
            f"<b>{labels['generated']}:</b> {escape(localized_datetime(generated, lang))}<br/>"
            f"<b>{labels['model']}:</b> {escape(forecast_model)} / {escape(pressure_model)} / {escape(interest_model)} / {escape(success_model)}<br/>"
            f"<b>Report ID:</b> USIR-{iso_date.replace('-', '')}<br/>"
            f"<b>Version:</b> {REPORT_VERSION}",
            styles["meta"],
        ),
        Spacer(1, 28 * mm),
        Paragraph(BLOG_URL, styles["meta"]),
        PageBreak(),

        Paragraph(labels["about"], styles["h1"]),
        Paragraph(labels["about_intro"], styles["body"]),
        Paragraph(labels["about_method"], styles["body"]),
        Paragraph(labels["about_purpose"], styles["body"]),
        Spacer(1, 3 * mm),
        Table(
            [[Paragraph(labels["workflow"], styles["workflow"])]],
            colWidths=[doc.width],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EAF1F7")),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#7FA0BF")),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]),
        ),
        Spacer(1, 5 * mm),

        Paragraph(labels["input_models"], styles["h1"]),
        Paragraph(labels["input_models_intro"], styles["body"]),
        build_input_files_table(
            forecast, pressure, interest, success,
            strategic_interests, strategic_indicators, interest_impact_map,
            lang, styles,
        ),
        PageBreak(),

        Paragraph(labels["at_glance"], styles["h1"]),
        build_at_glance_table(forecast, pressure, interest, success, lang, styles),
        Spacer(1, 5 * mm),
    ]

    executive = executive_summary(forecast, pressure, interest, success, lang)
    story.append(Paragraph(labels["executive"], styles["h1"]))
    story.append(Paragraph(labels["overall_assessment"], styles["h2"]))
    story.append(Paragraph(executive["overall"], styles["body"]))
    story.append(Paragraph(labels["main_findings"], styles["h2"]))
    findings = [[Paragraph(f"• {escape(item)}", styles["body"])] for item in executive["findings"]]
    story.append(Table(findings, colWidths=[doc.width], style=TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ])))
    story.append(Paragraph(labels["assessment_confidence"], styles["h2"]))
    story.append(Table(
        [[Paragraph(executive["confidence"], styles["callout"])]],
        colWidths=[doc.width],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EAF1F7")),
            ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#7FA0BF")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]),
    ))

    story.extend([
        PageBreak(),
        Paragraph(labels["forecast"], styles["h1"]),
        build_forecast_table(forecast, lang, styles),
        Spacer(1, 2 * mm),
    ])
    add_paragraphs(story, analyse_forecast(forecast, lang), styles)

    for horizon in ("48h", "72h"):
        table = analogue_table(forecast, horizon, lang, styles)
        if table is not None:
            heading = f"{horizon} - " + ("legközelebbi történeti analógok" if lang == "hu" else "nearest historical analogues")
            story.append(Paragraph(escape(heading), styles["h2"]))
            story.append(table)
            story.append(Spacer(1, 2 * mm))

    story.extend([
        CondPageBreak(75 * mm),
        Paragraph(labels["pressure"], styles["h1"]),
        build_pressure_table(pressure, lang, styles),
        Spacer(1, 2 * mm),
    ])
    add_paragraphs(story, analyse_pressure(pressure, lang), styles)

    story.extend([
        CondPageBreak(75 * mm),
        Paragraph(labels["interest"], styles["h1"]),
        build_interest_table(interest, lang, styles),
        Spacer(1, 2 * mm),
    ])
    add_paragraphs(story, analyse_interest(interest, lang), styles)
    story.extend(build_interest_detail_section(interest, strategic_interests, lang, styles))

    story.extend([
        CondPageBreak(75 * mm),
        Paragraph(labels["success"], styles["h1"]),
        build_success_table(success, lang, styles),
        Spacer(1, 2 * mm),
    ])
    add_paragraphs(story, analyse_success(success, lang), styles)
    story.extend(build_success_detail_section(success, lang, styles))

    story.extend([
        CondPageBreak(75 * mm),
        Paragraph(labels["integrated"], styles["h1"]),
    ])
    integrated = integrated_assessment(forecast, pressure, interest, success, lang)
    story.append(Table(
        [[Paragraph(integrated[0], styles["callout"])]],
        colWidths=[doc.width],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EAF1F7")),
            ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#7FA0BF")),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]),
    ))
    add_paragraphs(story, integrated[1:], styles)

    story.extend([
        CondPageBreak(65 * mm),
        Paragraph(labels["drivers"], styles["h1"]),
        build_drivers_table(pressure, lang, styles),
        PageBreak(),
        Paragraph(labels["method"], styles["h1"]),
    ])

    if lang == "hu":
        method_sections = [
            ("1. Adatgyűjtés és forráskör",
             "A rendszer nyílt forrású információkat használ. A nem kinetikus események híroldalakból, RSS-forrásokból és strukturált OSINT-adatfolyamokból származnak. "
             "A kinetikus események külön adatállományban szerepelnek. A jelentés csak a legutóbbi teljes UTC-napot értékeli, ezért a még nem lezárt nap adatai nem kerülnek a napi indexbe."),
            ("2. Szemantikai feldolgozás",
             "A feldolgozás első lépése nem matematikai pontozás, hanem szemantikai értelmezés. A rendszer szereplőket, eseménytípusokat, irányokat, kulcskifejezéseket és stratégiai összefüggéseket azonosít. "
             "A strategic_indicators.json határozza meg a felismerhető indikátorokat és azok szabályait. A nyelvi jelzésekből így strukturált, magyarázható stratégiai események jönnek létre."),
            ("3. Stratégiai érdekek",
             "A strategic_interests.json tartalmazza az Egyesült Államok és Irán súlyozott stratégiai érdekeit. Minden érdekhez név, leírás és súly tartozik. "
             "A súly azt fejezi ki, hogy az adott cél milyen jelentőséggel szerepel a modell összesített értékelésében."),
            ("4. Indikátor–érdek kapcsolat",
             "Az interest_impact_map.json kapcsolja össze a szemantikai indikátorokat a stratégiai érdekekkel. A kapcsolat pozitív, negatív vagy semleges lehet, és hatáserősséget is tartalmazhat. "
             "Ez teszi lehetővé, hogy ugyanaz az esemény a két szereplő számára eltérő stratégiai következményt hordozzon."),
            ("5. Strategic Pressure",
             "A Strategic Pressure minden eseménynél egyesíti a már meglévő operatív komponenst és a stratégiai módosítót. A hét napos súlyozott pontszámot 0–100 közötti indexre vetíti. "
             "Az 50 alatti érték csökkent nyomást, az 50 feletti érték fokozott nyomást jelez. Az index nem támadási valószínűség, hanem a kényszerítés, elrettentés és érdekérvényesítés intenzitásának közelítése."),
            ("6. Strategic Interest Achievement",
             "Az Interest Achievement azt méri, hogy a napi fejlemények mennyiben támogatják vagy gyengítik az egyes szereplők saját, súlyozott stratégiai érdekeit. "
             "Az 50-es érték semleges helyzet. Az 50 feletti érték támogató, az 50 alatti érték gyengítő környezetet jelez. A mutató nem katonai győzelmet és nem politikai legitimációt mér."),
            ("7. Strategic Success",
             "A Strategic Success az aktuális érdekérvényesülési szintet négy komponensben értékeli: achievement, momentum, stabilitás és konzisztencia. "
             "Az achievement súlya 50%, a momentumé 20%, a stabilitásé és a konzisztenciáé 15–15%. A momentum a 7 és 30 napos átlag közötti eltérést, a stabilitás az ingadozást, a konzisztencia pedig a pozitív napok tartósságát vizsgálja."),
            ("8. Forecast",
             "A Forecast történeti analóg napokat keres a jelenlegi helyzethez. A hasonló korábbi állapotokat követő katonai aktivitásból becsli a 48 és 72 órás irányt. "
             "A nyers eredmény csak akkor válik publikus jelzéssé, ha teljesíti az adott időtáv valószínűségi és konfidenciaküszöbeit. A modell nem konkrét támadást vagy célpontot jelez előre."),
            ("9. Duplikáció és bizonyítékkezelés",
             "Azonos szereplőhöz, naphoz és indikátorhoz tartozó ismétlődő hírek közül csak a legerősebb bizonyíték tartja meg a pontszámát. "
             "A többi elem átláthatósági okból látható marad, de nem növeli mesterségesen az indexeket. A kétoldalú tárgyalási és tűzszüneti események mindkét szereplő értékelésében megjelenhetnek."),
            ("10. Integrált értékelés",
             "Az integrált stratégiai értékelés négy eltérő kérdést kapcsol össze. A Forecast azt vizsgálja, merre változhat a rövid távú katonai aktivitás. "
             "A Strategic Pressure a kényszerítési környezetet méri. Az Interest Achievement a napi érdekilleszkedést, a Strategic Success pedig ennek tartósságát és minőségét vizsgálja. "
             "A jelentés végső következtetése ezért nem egyetlen indexből, hanem a négy modell közötti összhangból vagy eltérésből születik."),
            ("11. Korlátok",
             "A modell az elérhető nyílt források teljességétől és minőségétől függ. A szemantikai szabályok és az indikátor–érdek kapcsolatok elemzői ítéleteket tartalmaznak. "
             "Az alacsony forrásszám, a propaganda, a késleltetett jelentések és a hibás attribúció torzíthatják az eredményt. A jelentés döntéstámogató eszköz, nem önálló döntési mechanizmus."),
        ]
    else:
        method_sections = [
            ("1. Data Collection and Source Scope",
             "The system uses open-source information. Non-kinetic events are derived from news reporting, RSS sources, and structured OSINT feeds, while kinetic events are maintained in a separate dataset. "
             "Only the latest complete UTC day is assessed, so the still-open current day is excluded from the daily indices."),
            ("2. Semantic Processing",
             "The first analytical step is semantic interpretation rather than mathematical scoring. The system identifies actors, event types, directions, key expressions, and strategic relationships. "
             "The strategic_indicators.json file defines recognised indicators and their detection rules, converting language signals into structured and explainable strategic events."),
            ("3. Strategic Interests",
             "The strategic_interests.json file contains the weighted strategic interests of the United States and Iran. Each interest has a name, description, and weight. "
             "The weight represents the relative importance of that objective in the combined assessment."),
            ("4. Indicator-to-Interest Mapping",
             "The interest_impact_map.json file links semantic indicators to strategic interests. A relationship may be supportive, weakening, or neutral and may include an effect strength. "
             "This allows the same event to carry different strategic consequences for the two actors."),
            ("5. Strategic Pressure",
             "Strategic Pressure combines each event's existing operational component with a strategic modifier. The seven-day weighted score is mapped to a 0–100 index. "
             "Values below 50 indicate reduced pressure and values above 50 indicate elevated pressure. The index is not an attack probability; it approximates the intensity of coercion, deterrence, and leverage."),
            ("6. Strategic Interest Achievement",
             "Interest Achievement measures whether current developments support or weaken each actor's own weighted strategic interests. A score of 50 is neutral. "
             "Values above 50 indicate a supportive environment and values below 50 indicate weakening conditions. The measure does not represent military victory or political legitimacy."),
            ("7. Strategic Success",
             "Strategic Success evaluates current performance through four components: achievement, momentum, stability, and consistency. Achievement carries a 50% weight, momentum 20%, and stability and consistency 15% each. "
             "Momentum compares seven- and thirty-day averages, stability measures volatility, and consistency examines the persistence of positive performance."),
            ("8. Forecast",
             "The Forecast identifies historical analogue days resembling the present situation and estimates 48- and 72-hour direction from the military activity observed after those states. "
             "A raw result becomes a public signal only when horizon-specific probability and confidence thresholds are met. The model does not predict a specific attack or target."),
            ("9. Deduplication and Evidence Handling",
             "Among repeated reports assigned to the same actor, UTC date, and indicator, only the strongest evidence item retains its score. Other items remain visible for transparency but do not inflate the indices. "
             "Recognised bilateral negotiation and ceasefire events may contribute to both actors."),
            ("10. Integrated Assessment",
             "The integrated assessment connects four different questions. Forecast estimates near-term operational direction. Strategic Pressure measures the coercive environment. "
             "Interest Achievement evaluates daily alignment with strategic interests, while Strategic Success examines sustainability and quality. The final judgement is therefore based on convergence or divergence across the four models."),
            ("11. Limitations",
             "The models depend on the completeness and quality of available open sources. Semantic rules and indicator-to-interest mappings contain analytical judgement. "
             "Low source volume, propaganda, delayed reporting, and incorrect attribution may distort results. The report is a decision-support tool rather than an autonomous decision mechanism."),
        ]

    for heading, paragraph in method_sections:
        story.append(Paragraph(heading, styles["h2"]))
        story.append(Paragraph(paragraph, styles["body"]))
    story.append(Table(
        [[Paragraph(escape(labels["disclaimer"]), styles["small"])]],
        colWidths=[doc.width],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF8E8")),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#D3B76C")),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]),
    ))

    doc.build(story)


def report_paths(output_dir: Path, iso_date: str, lang: str) -> ReportPaths:
    archive_dir = output_dir / "archive"
    return ReportPaths(
        latest=output_dir / f"latest-{lang}.pdf",
        archive=archive_dir / f"{iso_date}-{lang}.pdf",
    )


def update_index(
    output_dir: Path,
    iso_date: str,
    created_languages: Sequence[str],
    forecast: Mapping[str, Any],
    pressure: Mapping[str, Any],
    interest: Mapping[str, Any],
    success: Mapping[str, Any],
) -> Path:
    index_path = output_dir / "reports_index.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {"generated_at": None, "reports": []}
    if index_path.exists():
        try:
            loaded = load_json(index_path)
            if isinstance(loaded.get("reports"), list):
                existing = loaded
        except (ValueError, FileNotFoundError):
            pass

    reports = [item for item in existing.get("reports", []) if isinstance(item, Mapping) and item.get("date") != iso_date]
    h48 = horizon_data(forecast, "48h")
    h72 = horizon_data(forecast, "72h")
    overall = nested(pressure, "current", "overall", default={})
    overall = overall if isinstance(overall, Mapping) else {}

    files: dict[str, str] = {}
    for lang in LANGUAGES:
        archive = output_dir / "archive" / f"{iso_date}-{lang}.pdf"
        if archive.exists():
            files[lang] = f"archive/{archive.name}"

    reports.append({
        "date": iso_date,
        "files": files,
        "forecast": {
            "48h": {
                "direction": nested(h48, "public_signal", "direction", default="no_signal"),
                "has_signal": bool(nested(h48, "public_signal", "has_signal", default=False)),
                "raw_direction": nested(h48, "raw_prediction", "direction", default="no_signal"),
                "top_probability": number(nested(h48, "raw_prediction", "top_probability", default=0.0)),
            },
            "72h": {
                "direction": nested(h72, "public_signal", "direction", default="no_signal"),
                "has_signal": bool(nested(h72, "public_signal", "has_signal", default=False)),
                "raw_direction": nested(h72, "raw_prediction", "direction", default="no_signal"),
                "top_probability": number(nested(h72, "raw_prediction", "top_probability", default=0.0)),
            },
        },
        "strategic_pressure": {
            "usa": number(nested(pressure, "current", "usa", "pressure_index_7d", default=50.0)),
            "iran": number(nested(pressure, "current", "iran", "pressure_index_7d", default=50.0)),
            "overall": number(overall.get("pressure_index_7d"), 50.0),
            "trend": str(overall.get("trend") or "stable"),
        },
        "interest_achievement": {
            "usa": number(nested(interest, "current", "summary", "usa_achievement_index", default=50.0)),
            "iran": number(nested(interest, "current", "summary", "iran_achievement_index", default=50.0)),
            "gap": number(nested(interest, "current", "summary", "achievement_gap", default=0.0)),
            "advantage": str(nested(interest, "current", "summary", "daily_strategic_advantage", default="balanced")),
        },
        "strategic_success": {
            "usa": number(nested(success, "current", "summary", "usa_success_index", default=50.0)),
            "iran": number(nested(success, "current", "summary", "iran_success_index", default=50.0)),
            "gap": number(nested(success, "current", "summary", "success_gap", default=0.0)),
            "advantage": str(nested(success, "current", "summary", "strategic_advantage", default="balanced")),
            "data_maturity": str(nested(success, "current", "data_maturity", "status", default="unknown")),
        },
    })
    reports.sort(key=lambda item: str(item.get("date") or ""), reverse=True)

    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "latest_date": reports[0]["date"] if reports else None,
        "latest": {
            lang: f"latest-{lang}.pdf"
            for lang in LANGUAGES
            if (output_dir / f"latest-{lang}.pdf").exists()
        },
        "reports": reports,
    }
    with index_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return index_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate bilingual USA-Iran Strategic Intelligence Report PDFs.")
    parser.add_argument("--forecast", type=Path, default=DEFAULT_FORECAST, help="Path to forecast JSON.")
    parser.add_argument("--pressure", type=Path, default=DEFAULT_PRESSURE, help="Path to strategic pressure JSON.")
    parser.add_argument("--interest", type=Path, default=DEFAULT_INTEREST, help="Path to interest achievement JSON.")
    parser.add_argument("--success", type=Path, default=DEFAULT_SUCCESS, help="Path to strategic success JSON.")
    parser.add_argument("--strategic-interests", type=Path, default=DEFAULT_STRATEGIC_INTERESTS, help="Path to strategic interests JSON.")
    parser.add_argument("--strategic-indicators", type=Path, default=DEFAULT_STRATEGIC_INDICATORS, help="Path to strategic indicators JSON.")
    parser.add_argument("--interest-impact-map", type=Path, default=DEFAULT_INTEREST_IMPACT_MAP, help="Path to interest impact map JSON.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Reports output directory.")
    parser.add_argument("--lang", choices=("hu", "en", "all"), default="all", help="Language to generate.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Compatibility option. Reports are always regenerated with the current code.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        forecast = load_json(args.forecast)
        pressure = load_json(args.pressure)
        interest = load_json(args.interest)
        success = load_json(args.success)
        strategic_interests = load_json(args.strategic_interests)
        strategic_indicators = load_json(args.strategic_indicators)
        interest_impact_map = load_json(args.interest_impact_map)
        iso_date = report_date(forecast, pressure, interest, success)
        languages = LANGUAGES if args.lang == "all" else (args.lang,)

        created: list[str] = []
        for lang in languages:
            paths = report_paths(args.output_dir, iso_date, lang)
            paths.archive.parent.mkdir(parents=True, exist_ok=True)

            # Always rebuild the dated report with the current generator code.
            # This guarantees that visual or content changes appear immediately,
            # even when a report for the same reference date already exists.
            build_pdf(
                forecast, pressure, interest, success,
                strategic_interests, strategic_indicators, interest_impact_map,
                lang, paths.archive, iso_date,
            )
            print(f"Created or refreshed archive: {paths.archive}")

            # latest is refreshed from the newly generated dated report.
            shutil.copy2(paths.archive, paths.latest)
            print(f"Updated latest: {paths.latest}")
            created.append(lang)

        index_path = update_index(args.output_dir, iso_date, created, forecast, pressure, interest, success)
        print(f"Updated archive index: {index_path}")
        return 0
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
