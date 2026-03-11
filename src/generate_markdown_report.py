import json
from pathlib import Path
from datetime import datetime


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def safe_text(value):
    if value is None:
        return ""
    return str(value).strip()


def format_number(value, decimals=2):
    try:
        num = float(value)
        formatted = f"{num:,.{decimals}f}"
        return formatted.replace(",", " ").replace(".", ",")
    except Exception:
        return str(value)


def format_int(value):
    try:
        num = int(float(value))
        return f"{num:,}".replace(",", " ")
    except Exception:
        return str(value)


def top_negative_articles(articles, limit=5):
    filtered = [a for a in articles if a.get("score", 0) < 0]
    filtered.sort(key=lambda x: x.get("score", 0))
    return filtered[:limit]


def top_positive_articles(articles, limit=5):
    filtered = [a for a in articles if a.get("score", 0) > 0]
    filtered.sort(key=lambda x: x.get("score", 0), reverse=True)
    return filtered[:limit]


def extract_keyword_summary(articles):
    keyword_counter = {}

    for article in articles:
        for match in article.get("matched_keywords", []):
            keyword = safe_text(match.get("keyword"))
            category = safe_text(match.get("category"))
            if not keyword:
                continue
            key = (keyword, category)
            keyword_counter[key] = keyword_counter.get(key, 0) + 1

    ranked = sorted(keyword_counter.items(), key=lambda x: x[1], reverse=True)
    return ranked[:12]


def theme_counts(articles):
    themes = {
        "frontline": [
            "frontline", "battle", "offensive", "advance", "assault",
            "donetsk", "luhansk", "kherson", "zaporizhzhia", "kursk", "crimea"
        ],
        "air_strikes": [
            "missile", "missiles", "drone", "drones", "air raid",
            "strike", "strikes", "shelling", "bombing", "explosion", "explosions"
        ],
        "diplomacy": [
            "ceasefire", "truce", "negotiation", "negotiations", "talks",
            "peace", "agreement", "dialogue", "diplomacy", "summit", "mediation"
        ],
        "support": [
            "military aid", "weapons package", "air defense", "f-16",
            "atacms", "himars", "sanctions", "nato support", "eu support"
        ],
        "leadership": [
            "putin", "zelensky", "kremlin", "moscow", "kyiv"
        ]
    }

    counts = {theme: 0 for theme in themes}

    for article in articles:
        title = safe_text(article.get("title")).lower()
        for theme, keywords in themes.items():
            if any(keyword in title for keyword in keywords):
                counts[theme] += 1

    return counts


def translate_assessment(assessment: str) -> str:
    mapping = {
        "strong escalation": "erős eszkaláció",
        "moderate escalation": "mérsékelt eszkaláció",
        "mixed / unstable": "vegyes / instabil",
        "moderate de-escalation": "mérsékelt enyhülés",
        "strong de-escalation": "erősebb enyhülés",
    }
    return mapping.get(assessment, assessment)


def build_lead_summary(total_score, assessment, article_count, escalation_count, deescalation_count, neutral_count):
    if assessment == "strong escalation":
        return (
            f"A napi médiakép összességében erősen eszkalációs képet mutatott. "
            f"A feldolgozott {article_count} cikk közül {escalation_count} hordozott kifejezetten konfliktuserősítő mintázatot, "
            f"miközben a deeszkalációra utaló hírek száma mindössze {deescalation_count} volt. "
            f"Ez arra utal, hogy a napirendet elsősorban a katonai aktivitás, a csapásmérések és a harctéri nyomás fennmaradása alakította."
        )

    if assessment == "moderate escalation":
        return (
            f"A napi hírkép mérsékelt, de jól érzékelhető eszkalációs túlsúlyt mutatott. "
            f"A katonai és biztonsági fejlemények dominálták a médiateret, ugyanakkor korlátozott számban "
            f"enyhülésre vagy politikai mozgásra utaló jelzések is megjelentek."
        )

    if assessment == "mixed / unstable":
        return (
            f"A napi kép vegyes és instabil volt. "
            f"Az összesen {article_count} cikkből {escalation_count} eszkalációs, {deescalation_count} deeszkalációs "
            f"és {neutral_count} semleges mintázatot mutatott, vagyis a médiás környezet nem rajzolt ki egyértelmű elmozdulást. "
            f"A katonai nyomás és a politikai-diplomáciai zaj egyszerre maradt jelen."
        )

    if assessment == "moderate de-escalation":
        return (
            f"A napi médiakép mérsékelt enyhülési irányt mutatott. "
            f"A harctéri fejlemények mellett hangsúlyosabban jelentek meg a diplomáciai, tárgyalási vagy politikai rendezésre utaló elemek."
        )

    return (
        f"A napi hírek alapján erősebb deeszkalációs tendencia körvonalazódott. "
        f"A konfliktusról szóló beszámolókban az egyeztetés, a politikai rendezés és az enyhülés jelei voltak hangsúlyosabbak, "
        f"mint a közvetlen katonai eszkaláció."
    )


def build_main_trends(escalation_count, deescalation_count, neutral_count):
    return (
        f"A napi cikkmegoszlás alapján **{escalation_count}** eszkalációs, "
        f"**{deescalation_count}** deeszkalációs és **{neutral_count}** semleges hír került a mintába. "
        f"Ez a megoszlás rövid távú képet ad az információs környezet irányáról: minél nagyobb az eszkalációs arány, "
        f"annál inkább katonai és biztonsági fejlemények uralják a napirendet, míg a pozitívabb elmozdulás inkább a diplomáciai nyitás jele."
    )


def build_operational_picture(counts):
    frontline = counts.get("frontline", 0)
    air = counts.get("air_strikes", 0)

    if frontline == 0 and air == 0:
        return (
            "A médiás mintában a fronthelyzetre és csapásjellegű eseményekre utaló kulcsszavak nem alkottak különösen erős blokkot. "
            "Ez inkább a hírcímek szerkezetét tükrözi, mintsem azt, hogy a terepen ne lett volna aktivitás."
        )

    if air > frontline:
        return (
            f"A napi tudósításokban a rakéta-, drón- és egyéb légi csapások hangsúlyosabb szerepet kaptak ({air} releváns cím), "
            f"miközben a klasszikus frontvonalhoz kötődő hírek kisebb súllyal jelentek meg ({frontline} cím). "
            f"Ez arra utal, hogy a konfliktus napi médiaképe inkább a mélységi csapásmérés és az infrastruktúra elleni támadások irányába tolódott."
        )

    if frontline > air:
        return (
            f"A napi médiaképben a fronthelyzethez, szárazföldi műveletekhez és előretörésekhez kapcsolódó hírek voltak hangsúlyosabbak ({frontline} releváns cím), "
            f"miközben a légi csapásokról szóló tudósítások is jelentős számban jelen maradtak ({air} cím). "
            f"Ez a harctéri dinamika folyamatos napirenden maradására utal."
        )

    return (
        f"A fronthelyzethez és a légi csapásokhoz kötődő hírek közel azonos súllyal jelentek meg ({frontline} illetve {air} releváns cím). "
        f"Ez kiegyensúlyozott, de továbbra is feszült hadműveleti képet jelez."
    )


def build_external_brief_text(brief_data):
    if not brief_data or not isinstance(brief_data, dict):
        return None

    occupied_km2 = brief_data.get("occupied_km2")
    daily_delta_km2 = brief_data.get("daily_delta_km2")
    daily_interpretation = safe_text(brief_data.get("daily_interpretation"))
    weekly_delta_km2 = brief_data.get("weekly_delta_km2")
    weekly_interpretation = safe_text(brief_data.get("weekly_interpretation"))
    ground_raw_total = brief_data.get("ground_raw_total")
    ground_kept_points = brief_data.get("ground_kept_points")
    ground_kept_lines = brief_data.get("ground_kept_lines")
    uav_events_total = brief_data.get("uav_events_total")
    uav_events_7d = brief_data.get("uav_events_7d")
    gained_sector = safe_text(brief_data.get("gained_sector"))
    lost_sector = safe_text(brief_data.get("lost_sector"))

    parts = []

    if occupied_km2 is not None:
        parts.append(
            f"A külső fronthelyzeti adatok alapján az orosz erők által ellenőrzött terület nagysága "
            f"megközelítőleg {format_number(occupied_km2)} km²."
        )

    if daily_delta_km2 is not None and daily_interpretation:
        if abs(float(daily_delta_km2)) < 1:
            parts.append(
                f"Napi összevetésben csak korlátozott területi elmozdulás látszott ({format_number(daily_delta_km2)} km²), "
                f"ami összességében {daily_interpretation} irányába mutat."
            )
        else:
            parts.append(
                f"Napi összevetésben a területi változás {format_number(daily_delta_km2)} km² volt, "
                f"ami {daily_interpretation} irányába mutat."
            )

    if weekly_delta_km2 is not None and weekly_interpretation:
        if abs(float(weekly_delta_km2)) < 5:
            parts.append(
                f"Heti távlatban a mozgás visszafogott maradt ({format_number(weekly_delta_km2)} km²), "
                f"de az összkép továbbra is {weekly_interpretation} felé mutat."
            )
        else:
            parts.append(
                f"Heti összevetésben a változás {format_number(weekly_delta_km2)} km², "
                f"ami már jól érzékelhetően {weekly_interpretation} képet rajzol ki."
            )

    sector_parts = []
    if gained_sector:
        sector_parts.append(f"a legfontosabb előretörési irány {gained_sector} térségében jelent meg")
    if lost_sector:
        sector_parts.append(f"a legkedvezőtlenebb elmozdulás {lost_sector} környezetében volt megfigyelhető")

    if sector_parts:
        parts.append("Területi értelemben " + ", miközben ".join(sector_parts) + ".")

    activity_fragments = []
    if ground_raw_total is not None:
        activity_fragments.append(f"a nyers földi események száma {format_int(ground_raw_total)}")
    if ground_kept_points is not None:
        activity_fragments.append(f"a szűrés után {format_int(ground_kept_points)} releváns pontszerű elem maradt")
    if ground_kept_lines is not None:
        activity_fragments.append(f"a vonalas elemek száma {format_int(ground_kept_lines)}")

    if activity_fragments:
        parts.append(
            "A földi aktivitási rétegben " + ", ".join(activity_fragments) + "."
        )

    if uav_events_total is not None or uav_events_7d is not None:
        details = []
        if uav_events_total is not None:
            details.append(f"az összes rögzített UAV-esemény száma {format_int(uav_events_total)}")
        if uav_events_7d is not None:
            details.append(f"ebből {format_int(uav_events_7d)} az elmúlt hét naphoz köthető")

        if details:
            parts.append(
                "A dróntevékenység továbbra is jelentős: " + ", ".join(details) + "."
            )

    if not parts:
        return None

    return " ".join(parts)


def normalize_external_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                t = item.strip()
                if t:
                    parts.append(t)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("title") or item.get("summary") or ""
                text = safe_text(text)
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        for key in ["text", "summary", "brief", "content", "description"]:
            if key in value and safe_text(value[key]):
                return safe_text(value[key])
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value).strip()


def extract_change_summary(change_data):
    if not change_data:
        return None

    candidates = [
        change_data.get("summary"),
        change_data.get("changes"),
        change_data.get("latest_change"),
        change_data.get("text"),
        change_data.get("description"),
        change_data.get("content"),
    ]

    for candidate in candidates:
        text = normalize_external_text(candidate)
        if text:
            return text

    collected = []
    for key, value in change_data.items():
        text = normalize_external_text(value)
        if text and len(text) > 10:
            collected.append(f"**{key}**: {text}")

    if collected:
        return "\n\n".join(collected[:5])

    return None


def build_diplomatic_section(counts):
    diplomacy = counts.get("diplomacy", 0)
    leadership = counts.get("leadership", 0)

    if diplomacy == 0 and leadership == 0:
        return (
            "A diplomáciai és politikai dimenzió a napi híranyagban háttérbe szorult. "
            "A konfliktus értelmezését így elsősorban a katonai fejlemények és a biztonsági megfontolások alakították."
        )

    if diplomacy > 0 and leadership > 0:
        return (
            f"A diplomáciai-politikai dimenzió korlátozott, de érzékelhető súllyal maradt jelen: "
            f"{diplomacy} cím utalt tárgyalásokra, egyeztetésekre vagy rendezési törekvésekre, "
            f"miközben {leadership} cím vezetői szintű politikai kommunikációt vagy döntéshozói kontextust emelt be. "
            f"Ez azt mutatja, hogy a napi napirend nem kizárólag a harctéri események köré szerveződött."
        )

    return (
        f"A diplomáciai-politikai szál visszafogottan jelent meg a napi hírekben ({diplomacy} releváns cím). "
        f"A hangsúly továbbra is a konfliktus operatív és katonai vetületén maradt."
    )


def build_support_section(counts):
    support = counts.get("support", 0)

    if support == 0:
        return (
            "A külső támogatáshoz, fegyverszállításokhoz és szankciós környezethez kapcsolódó hírek nem alkottak külön domináns blokkot a vizsgált napon."
        )

    return (
        f"A nemzetközi támogatási környezet a napi médiaképben is látható maradt ({support} releváns cím). "
        f"Ez arra utal, hogy a konfliktus értelmezésében továbbra is fontos szerepet játszik a nyugati katonai támogatás, "
        f"a védelmi képességek fenntartása és a gazdasági nyomásgyakorlás dimenziója."
    )


def media_narrative(articles):
    escalation = len([a for a in articles if a.get("score", 0) < 0])
    deesc = len([a for a in articles if a.get("score", 0) > 0])

    if escalation > deesc * 2:
        return (
            "A médiakép erősen konfliktuscentrikus volt: a címek többsége katonai eseményeket, "
            "csapásokat vagy harctéri fejleményeket hangsúlyozott, miközben a diplomáciai jelzések háttérben maradtak."
        )

    if deesc > escalation:
        return (
            "A médiában a szokásosnál erősebben jelentek meg a diplomáciai és politikai fejlemények. "
            "Ez részben a konfliktus politikai kezelésének és a tárgyalási lehetőségek narratíváját erősítheti."
        )

    return (
        "A napi hírek narratívája vegyes képet mutatott: a katonai események, a politikai reakciók és a stratégiai bizonytalanság egyszerre voltak jelen."
    )


def build_consistency_assessment(total_score, brief_text, change_text):
    if not brief_text and not change_text:
        return (
            "A mai jelentésben a médiás konfliktusindex önállóan adott képet az intenzitásról; külső operatív megerősítés nem állt rendelkezésre."
        )

    if total_score <= -15:
        return (
            "A médiás index egyértelműen feszült, eszkalációs képet jelez. "
            "A külső operatív réteg bevonása ezt nem pusztán kiegészíti, hanem segít elválasztani a médiás zajt a valós terepi elmozdulásoktól."
        )

    if total_score >= 10:
        return (
            "A médiás környezet viszonylag enyhébb vagy kiegyensúlyozottabb napi képet mutat, ezért különösen fontos figyelni, "
            "hogy a külső fronthelyzeti adatok mennyiben támasztják ezt alá vagy árnyalják."
        )

    return (
        "A médiás és az operatív réteg együtt összetett képet rajzol ki: "
        "az információs környezet és a terepi dinamika nem feltétlenül azonos intenzitással mozog, "
        "ezért a napi helyzet értelmezésében mindkét szempontot érdemes együtt kezelni."
    )


def risk_indicator(total_score):
    if total_score < -50:
        return "Rövid távon fokozott eszkalációs kockázat érzékelhető."
    if total_score < -20:
        return "A konfliktus intenzitása stabilan magas szinten marad."
    if total_score < 10:
        return "A helyzet rövid távon instabil, de nem mutat teljesen egyértelmű eszkalációs irányt."
    return "A médiakép alapján rövid távú enyhülési jelzések is megfigyelhetők."


def markdown_article_line(article):
    title = safe_text(article.get("title")) or "N/A"
    score = article.get("score", 0)
    source = safe_text(article.get("source")) or "N/A"
    link = safe_text(article.get("link"))
    return f"- **[{title}]({link})** — pontszám: `{score}`, forrás: {source}"


def main():
    base_dir = Path(__file__).resolve().parent.parent
    scored_path = base_dir / "data" / "processed" / "latest_scored.json"
    brief_path = base_dir / "data" / "external" / "brief_daily.json"
    change_path = base_dir / "data" / "external" / "change_latest.json"
    reports_dir = base_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    data = load_json(scored_path)
    if not data:
        raise RuntimeError("A latest_scored.json nem olvasható vagy hiányzik.")

    brief_data = load_json(brief_path)
    change_data = load_json(change_path)

    created_at = safe_text(data.get("created_at"))
    date_str = created_at[:10] if created_at else datetime.utcnow().date().isoformat()
    article_count = data.get("article_count", 0)
    total_score = data.get("total_score", 0)
    assessment = safe_text(data.get("assessment")) or "unknown"
    assessment_hu = translate_assessment(assessment)
    escalation_count = data.get("escalation_articles", 0)
    deescalation_count = data.get("deescalation_articles", 0)
    neutral_count = data.get("neutral_articles", 0)
    articles = data.get("articles", [])

    negative_articles = top_negative_articles(articles, limit=5)
    positive_articles = top_positive_articles(articles, limit=5)
    keywords = extract_keyword_summary(articles)
    counts = theme_counts(articles)

    lead_summary = build_lead_summary(
        total_score,
        assessment,
        article_count,
        escalation_count,
        deescalation_count,
        neutral_count
    )
    main_trends = build_main_trends(escalation_count, deescalation_count, neutral_count)
    operational_picture = build_operational_picture(counts)
    military_section = build_military_section(counts)
    diplomatic_section = build_diplomatic_section(counts)
    support_section = build_support_section(counts)
    narrative = media_narrative(articles)
    risk_text = risk_indicator(total_score)

    external_brief_text = build_external_brief_text(brief_data)
    external_change_text = extract_change_summary(change_data)
    consistency_text = build_consistency_assessment(total_score, external_brief_text, external_change_text)

    report_path = reports_dir / f"{date_str}_report.md"

    lines = []
    lines.append("# Napi konfliktusjelentés – Oroszország–Ukrajna")
    lines.append("")
    lines.append(f"**Dátum:** {date_str}")
    lines.append(f"**Feldolgozott cikkek száma:** {article_count}")
    lines.append(f"**Összesített konfliktusindex:** {total_score}")
    lines.append(f"**Minősítés:** {assessment_hu}")
    lines.append("")

    lines.append("## 1. Helyzetkép")
    lines.append("")
    lines.append(lead_summary)
    lines.append("")

    lines.append("## 2. Fő trendek")
    lines.append("")
    lines.append(main_trends)
    lines.append("")

    lines.append("## 3. Operatív helyzetkép")
    lines.append("")
    lines.append(operational_picture)
    lines.append("")

    lines.append("## 4. Külső fronthelyzeti napi brief")
    lines.append("")
    if external_brief_text:
        lines.append(external_brief_text)
    else:
        lines.append(
            "A mai futás során nem állt rendelkezésre olyan külső fronthelyzeti brief, amely érdemben kiegészíthette volna a médiás réteget."
        )
    lines.append("")

    lines.append("## 5. Külső változásjelző összefoglaló")
    lines.append("")
    if external_change_text:
        lines.append(external_change_text)
    else:
        lines.append(
            "A mai futás során nem érkezett külön változásjelző összefoglaló a külső adatforrásból."
        )
    lines.append("")

    lines.append("## 6. Katonai dimenzió")
    lines.append("")
    lines.append(military_section)
    lines.append("")

    lines.append("## 7. Diplomáciai és politikai dimenzió")
    lines.append("")
    lines.append(diplomatic_section)
    lines.append("")

    lines.append("## 8. Nemzetközi támogatás és külső környezet")
    lines.append("")
    lines.append(support_section)
    lines.append("")

    lines.append("## 9. Médiakeretezés")
    lines.append("")
    lines.append(narrative)
    lines.append("")

    lines.append("## 10. Média- és operatív kép összevetése")
    lines.append("")
    lines.append(consistency_text)
    lines.append("")

    lines.append("## 11. Domináns kulcsszavak")
    lines.append("")
    if keywords:
        for (keyword, category), count in keywords:
            lines.append(f"- `{keyword}` ({category}) – {count} előfordulás")
    else:
        lines.append("- Nem rajzolódott ki erős kulcsszó-koncentráció.")
    lines.append("")

    lines.append("## 12. Kiemelt eszkalációs jellegű hírek")
    lines.append("")
    if negative_articles:
        for article in negative_articles:
            lines.append(markdown_article_line(article))
    else:
        lines.append("- Nem volt markánsan eszkalációs cikk a mintában.")
    lines.append("")

    lines.append("## 13. Kiemelt deeszkalációs jellegű hírek")
    lines.append("")
    if positive_articles:
        for article in positive_articles:
            lines.append(markdown_article_line(article))
    else:
        lines.append("- Nem volt markánsan deeszkalációs cikk a mintában.")
    lines.append("")

    lines.append("## 14. Rövid távú kockázati indikátor")
    lines.append("")
    lines.append(risk_text)
    lines.append("")

    lines.append("## 15. Elemzői megjegyzés")
    lines.append("")
    lines.append(
        "A jelentés automatizált RSS-alapú hírgyűjtésre és kulcsszavas pontozásra épül, "
        "amelyet külső operatív és fronthelyzeti adatforrások egészíthetnek ki. "
        "Erőssége a gyors trendkövetés és a napi narratív változások megragadása, "
        "korlátja ugyanakkor, hogy a médiás és térképi források eltérő logikával működnek, "
        "ezért a végső következtetések mindig óvatos, többforrású értelmezést igényelnek."
    )
    lines.append("")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Integrated markdown report generated: {report_path}")


def build_military_section(counts):
    frontline = counts.get("frontline", 0)
    air_strikes = counts.get("air_strikes", 0)

    if frontline == 0 and air_strikes == 0:
        return (
            "A napi híranyagban a harctéri és csapásjellegű események nem alkottak különösen erős tematikus blokkot. "
            "Ez nem feltétlenül alacsonyabb intenzitásra utal, inkább arra, hogy a hírcímek más hangsúlyok mentén szerveződtek."
        )

    if air_strikes > frontline:
        return (
            f"A katonai dimenzióban a légi csapásokhoz, rakéta- és dróntámadásokhoz kapcsolódó hírek domináltak ({air_strikes} releváns cím), "
            f"miközben a klasszikus frontvonalhoz kötődő tudósítások kisebb súllyal jelentek meg ({frontline} cím). "
            f"Ez olyan napi képet jelez, amelyben a mélységi csapásmérés és az infrastruktúra elleni támadások erősebben tematizálták a konfliktust."
        )

    if frontline > air_strikes:
        return (
            f"A katonai dimenzióban a fronthelyzettel és szárazföldi műveletekkel összefüggő hírek jelentek meg hangsúlyosabban ({frontline} releváns cím), "
            f"miközben a légi csapásokkal összefüggő tudósítások is számottevőek maradtak ({air_strikes} cím). "
            f"Ez arra utal, hogy a napi híráramlásban a harctéri dinamika továbbra is meghatározó maradt."
        )

    return (
        f"A fronthelyzettel és a légi csapásokkal összefüggő hírek közel azonos súllyal jelentek meg ({frontline} illetve {air_strikes} releváns cím). "
        f"Ez kiegyensúlyozott, de továbbra is feszült katonai képet mutat."
    )


if __name__ == "__main__":
    main()
