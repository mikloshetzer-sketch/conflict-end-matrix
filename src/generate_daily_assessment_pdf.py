#!/usr/bin/env python3
"""Generate bilingual daily Conflict End Matrix assessment PDFs.

Default inputs:
  docs/conflict_forecast_live.json
  docs/strategic_pressure.json

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
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        BaseDocTemplate,
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


PROJECT_NAME = "Conflict End Matrix"
REPORT_VERSION = "1.0"
DEFAULT_FORECAST = Path("docs/conflict_forecast_live.json")
DEFAULT_PRESSURE = Path("docs/strategic_pressure.json")
DEFAULT_OUTPUT_DIR = Path("docs/reports")

LANGUAGES = ("hu", "en")

TEXT = {
    "hu": {
        "report_title": "Napi konfliktuselemző jelentés",
        "conflict": "Egyesült Államok - Irán",
        "auto": "Automatikusan generált OSINT elemzés",
        "executive": "Vezetői összefoglaló",
        "forecast": "Forecast értékelés",
        "pressure": "Stratégiai nyomás értékelése",
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
        "report_title": "Daily Conflict Assessment",
        "conflict": "United States - Iran",
        "auto": "Automatically generated OSINT assessment",
        "executive": "Executive Summary",
        "forecast": "Forecast Assessment",
        "pressure": "Strategic Pressure Assessment",
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


def report_date(forecast: Mapping[str, Any], pressure: Mapping[str, Any]) -> str:
    f_date = str(forecast.get("forecast_reference_date") or "")
    p_date = str(nested(pressure, "current", "date", default="") or pressure.get("latest_complete_utc_day") or "")
    if f_date and p_date and f_date != p_date:
        raise ValueError(
            f"Input date mismatch: forecast={f_date}, strategic_pressure={p_date}. "
            "Both reports must refer to the same latest complete UTC day."
        )
    value = f_date or p_date
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


def executive_summary(forecast: Mapping[str, Any], pressure: Mapping[str, Any], lang: str) -> list[str]:
    h48 = horizon_data(forecast, "48h")
    h72 = horizon_data(forecast, "72h")
    raw48 = h48.get("raw_prediction") if isinstance(h48.get("raw_prediction"), Mapping) else {}
    raw72 = h72.get("raw_prediction") if isinstance(h72.get("raw_prediction"), Mapping) else {}
    pub48 = h48.get("public_signal") if isinstance(h48.get("public_signal"), Mapping) else {}
    pub72 = h72.get("public_signal") if isinstance(h72.get("public_signal"), Mapping) else {}
    overall = nested(pressure, "current", "overall", default={})
    overall = overall if isinstance(overall, Mapping) else {}

    d48 = str(raw48.get("direction") or "no_signal")
    d72 = str(raw72.get("direction") or "no_signal")
    p48 = number(raw48.get("top_probability"))
    p72 = number(raw72.get("top_probability"))
    s48 = bool(pub48.get("has_signal"))
    s72 = bool(pub72.get("has_signal"))
    oi = number(overall.get("pressure_index_7d"), 50)
    ot = trend_label(overall.get("trend"), lang)

    if lang == "hu":
        return [
            (
                f"A 48 órás modell nyers iránya <b>{escape(DIRECTION_LABELS['hu'].get(d48, d48))}</b> ({pct(p48)}), "
                + ("és a jelzés átment a publikációs kapun. " if s48 else "de nincs kiadható egyértelmű publikus jelzés. ")
                + f"A 72 órás nyers irány <b>{escape(DIRECTION_LABELS['hu'].get(d72, d72))}</b> ({pct(p72)}), "
                + ("amely szintén publikus jelzés. " if s72 else "amelyet a rendszer a bizonytalanság miatt visszatartott. ")
                + f"Az összesített Strategic Pressure index <b>{oi:.1f}</b>, trendje {escape(ot)}."
            ),
            combined_assessment(forecast, pressure, "hu")[0],
        ]
    return [
        (
            f"The raw 48-hour direction is <b>{escape(DIRECTION_LABELS['en'].get(d48, d48))}</b> ({pct(p48)}), "
            + ("and the result passed the publication gate. " if s48 else "but no clear public signal was released. ")
            + f"The raw 72-hour direction is <b>{escape(DIRECTION_LABELS['en'].get(d72, d72))}</b> ({pct(p72)}), "
            + ("which also qualifies as a public signal. " if s72 else "which was withheld because of uncertainty. ")
            + f"The overall Strategic Pressure Index is <b>{oi:.1f}</b>, with a {escape(ot)} trend."
        ),
        combined_assessment(forecast, pressure, "en")[0],
    ]


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
            pdfmetrics.registerFont(TTFont("CEM-Regular", str(regular)))
            pdfmetrics.registerFont(TTFont("CEM-Bold", str(bold)))
            pdfmetrics.registerFontFamily(
                "CEM", normal="CEM-Regular", bold="CEM-Bold", italic="CEM-Regular", boldItalic="CEM-Bold"
            )
            return "CEM-Regular", "CEM-Bold"
    return "Helvetica", "Helvetica-Bold"


def make_styles(regular_font: str, bold_font: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "CEMTitle", parent=base["Title"], fontName=bold_font, fontSize=23,
            leading=28, textColor=colors.HexColor("#123A63"), alignment=TA_CENTER,
            spaceAfter=4 * mm,
        ),
        "subtitle": ParagraphStyle(
            "CEMSubtitle", parent=base["Normal"], fontName=bold_font, fontSize=13,
            leading=17, textColor=colors.HexColor("#2F5F8F"), alignment=TA_CENTER,
            spaceAfter=2 * mm,
        ),
        "meta": ParagraphStyle(
            "CEMMeta", parent=base["Normal"], fontName=regular_font, fontSize=8.5,
            leading=12, textColor=colors.HexColor("#586777"), alignment=TA_CENTER,
        ),
        "h1": ParagraphStyle(
            "CEMH1", parent=base["Heading1"], fontName=bold_font, fontSize=15,
            leading=19, textColor=colors.HexColor("#123A63"), spaceBefore=5 * mm,
            spaceAfter=2.5 * mm, keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "CEMBody", parent=base["BodyText"], fontName=regular_font, fontSize=9.4,
            leading=14.2, textColor=colors.HexColor("#192633"), spaceAfter=2.7 * mm,
            alignment=TA_LEFT,
        ),
        "small": ParagraphStyle(
            "CEMSmall", parent=base["BodyText"], fontName=regular_font, fontSize=7.7,
            leading=10.5, textColor=colors.HexColor("#455465"), spaceAfter=1.5 * mm,
        ),
        "callout": ParagraphStyle(
            "CEMCallout", parent=base["BodyText"], fontName=bold_font, fontSize=10,
            leading=15, textColor=colors.HexColor("#143F68"), leftIndent=4 * mm,
            rightIndent=4 * mm, spaceBefore=2 * mm, spaceAfter=2 * mm,
        ),
        "table": ParagraphStyle(
            "CEMTable", parent=base["BodyText"], fontName=regular_font, fontSize=7.1,
            leading=9.2, textColor=colors.HexColor("#192633"),
        ),
        "table_bold": ParagraphStyle(
            "CEMTableBold", parent=base["BodyText"], fontName=bold_font, fontSize=7.1,
            leading=9.2, textColor=colors.white,
        ),
    }


def header_footer(canvas: Any, doc: Any, lang: str, report_iso_date: str, regular_font: str, bold_font: str) -> None:
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(colors.HexColor("#C9D7E5"))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, height - 15 * mm, width - 18 * mm, height - 15 * mm)
    canvas.setFont(bold_font, 8)
    canvas.setFillColor(colors.HexColor("#123A63"))
    canvas.drawString(18 * mm, height - 11.8 * mm, PROJECT_NAME)
    canvas.setFont(regular_font, 7.5)
    canvas.setFillColor(colors.HexColor("#617283"))
    canvas.drawRightString(width - 18 * mm, height - 11.8 * mm, localized_date(report_iso_date, lang))

    canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
    canvas.setFont(regular_font, 7.4)
    canvas.drawString(18 * mm, 9.5 * mm, TEXT[lang]["auto"])
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
        title=f"{PROJECT_NAME} - {labels['report_title']} - {iso_date}",
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
    generated = forecast.get("generated_at") or pressure.get("generated_at")

    story: list[Any] = [
        Spacer(1, 13 * mm),
        Paragraph(PROJECT_NAME, styles["title"]),
        Paragraph(labels["report_title"], styles["subtitle"]),
        Paragraph(labels["conflict"], styles["subtitle"]),
        Spacer(1, 3 * mm),
        Paragraph(
            f"<b>{labels['date']}:</b> {escape(localized_date(iso_date, lang))}<br/>"
            f"<b>{labels['generated']}:</b> {escape(localized_datetime(generated, lang))}<br/>"
            f"<b>{labels['model']}:</b> {escape(forecast_model)} / {escape(pressure_model)}<br/>"
            f"<b>Version:</b> {REPORT_VERSION}",
            styles["meta"],
        ),
        Spacer(1, 8 * mm),
        Paragraph(labels["executive"], styles["h1"]),
    ]
    add_paragraphs(story, executive_summary(forecast, pressure, lang), styles)

    story.extend([
        Spacer(1, 1 * mm),
        build_forecast_table(forecast, lang, styles),
        Paragraph(labels["forecast"], styles["h1"]),
    ])
    add_paragraphs(story, analyse_forecast(forecast, lang), styles)

    for horizon in ("48h", "72h"):
        table = analogue_table(forecast, horizon, lang, styles)
        if table is not None:
            heading = f"{horizon} - " + ("legközelebbi történeti analógok" if lang == "hu" else "nearest historical analogues")
            story.append(Paragraph(escape(heading), styles["small"]))
            story.append(table)
            story.append(Spacer(1, 2 * mm))

    story.extend([
        Paragraph(labels["pressure"], styles["h1"]),
        build_pressure_table(pressure, lang, styles),
        Spacer(1, 2 * mm),
    ])
    add_paragraphs(story, analyse_pressure(pressure, lang), styles)

    story.append(Paragraph(labels["combined"], styles["h1"]))
    combined = combined_assessment(forecast, pressure, lang)
    if combined:
        story.append(Table(
            [[Paragraph(combined[0], styles["callout"])]],
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
        add_paragraphs(story, combined[1:], styles)

    story.extend([
        Paragraph(labels["drivers"], styles["h1"]),
        build_drivers_table(pressure, lang, styles),
        Paragraph(labels["method"], styles["h1"]),
    ])

    if lang == "hu":
        method_paragraphs = [
            (
                "A Forecast történeti analóg napokat keres a jelenlegi helyzethez, majd a hasonló korábbi állapotok után megfigyelt katonai aktivitásból "
                "becsli a 48 és 72 órás irányt. A publikus jelzés csak akkor jelenik meg, ha a valószínűség és a konfidencia teljesíti a horizont kapufeltételeit."
            ),
            (
                "A Strategic Pressure index az esemény operatív komponensét és stratégiai módosítóját egyesíti. A hét napra súlyozott pontszámot egy 0-100-as indexre "
                "vetíti. Az 50 alatti érték csökkent, az 50 feletti érték fokozott stratégiai nyomást jelez."
            ),
            (
                "A rendszer kizárja az aktuális, még nem teljes UTC-napot. Azonos szereplőhöz, naphoz és indikátorhoz tartozó ismétlődő hírek közül csak a legerősebb "
                "bizonyíték tartja meg a pontszámát; a többi átláthatósági okból látható marad, de nem torzítja az indexet."
            ),
        ]
    else:
        method_paragraphs = [
            (
                "The Forecast identifies historical analogue days resembling the current situation and estimates the 48- and 72-hour direction from the military activity "
                "observed after those earlier states. A public signal is released only when probability and confidence satisfy the horizon-specific gate."
            ),
            (
                "Strategic Pressure combines each event's operational component with a strategic modifier. The seven-day weighted score is mapped to a 0-100 index. "
                "Values below 50 indicate reduced pressure; values above 50 indicate elevated pressure."
            ),
            (
                "The current incomplete UTC day is excluded. Among repeated reports assigned to the same actor, date, and indicator, only the strongest evidence retains its score; "
                "the remaining evidence stays visible for transparency but does not inflate the index."
            ),
        ]
    add_paragraphs(story, method_paragraphs, styles)
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
    parser = argparse.ArgumentParser(description="Generate bilingual daily Conflict End Matrix PDF reports.")
    parser.add_argument("--forecast", type=Path, default=DEFAULT_FORECAST, help="Path to forecast JSON.")
    parser.add_argument("--pressure", type=Path, default=DEFAULT_PRESSURE, help="Path to strategic pressure JSON.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Reports output directory.")
    parser.add_argument("--lang", choices=("hu", "en", "all"), default="all", help="Language to generate.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing dated archive PDF. Without this flag, an existing archive is preserved.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        forecast = load_json(args.forecast)
        pressure = load_json(args.pressure)
        iso_date = report_date(forecast, pressure)
        languages = LANGUAGES if args.lang == "all" else (args.lang,)

        created: list[str] = []
        for lang in languages:
            paths = report_paths(args.output_dir, iso_date, lang)
            paths.archive.parent.mkdir(parents=True, exist_ok=True)

            if paths.archive.exists() and not args.force:
                print(f"Archive already exists, preserving it: {paths.archive}")
            else:
                build_pdf(forecast, pressure, lang, paths.archive, iso_date)
                print(f"Created archive: {paths.archive}")

            # latest is always refreshed from the dated archive so both paths stay identical.
            shutil.copy2(paths.archive, paths.latest)
            print(f"Updated latest: {paths.latest}")
            created.append(lang)

        index_path = update_index(args.output_dir, iso_date, created, forecast, pressure)
        print(f"Updated archive index: {index_path}")
        return 0
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
