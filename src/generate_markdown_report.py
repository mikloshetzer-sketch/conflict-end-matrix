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
            keyword = match.get("keyword", "").strip()
            category = match.get("category", "").strip()
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
        title = article.get("title", "").lower()
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


def assessment_to_brief(total_score, assessment, article_count, escalation_count, deescalation_count):
    if assessment == "strong escalation":
        return (
            f"A napi médiakép összességében egyértelműen eszkalációs karakterű volt. "
            f"A feldolgozott {article_count} cikk közül {escalation_count} hordozott konfliktuserősítő mintázatot, "
            f"miközben a deeszkalációra utaló hírek száma {deescalation_count} maradt. "
            f"Ez arra utal, hogy a vizsgált időszakban a katonai aktivitás, a csapások és a fronthelyzettel kapcsolatos fejlemények uralták a napirendet."
        )
    if assessment == "moderate escalation":
        return (
            f"A napi hírkép mérsékelt eszkalációs túlsúlyt mutatott. "
            f"A katonai események és támadások dominálták a tudósításokat, de ezzel párhuzamosan korlátozott számú tárgyalásos vagy politikai enyhülésre utaló jelzés is megjelent."
        )
    if assessment == "mixed / unstable":
        return (
            f"A napi kép vegyes és instabil volt. "
            f"A hírek egyszerre tükrözték a katonai nyomás fennmaradását és bizonyos korlátozott diplomáciai vagy politikai mozgásokat, "
            f"ezért nem rajzolódott ki egyértelmű elmozdulás sem az eszkaláció, sem a deeszkaláció irányába."
        )
    if assessment == "moderate de-escalation":
        return (
            f"A napi hírkép mérsékelt enyhülési irányt mutatott. "
            f"Bár a harctéri fejlemények továbbra is jelen voltak, a tudósításokban a tárgyalási, egyeztetési és politikai rendezésre utaló elemek hangsúlyosabban jelentek meg."
        )
    return (
        f"A napi hírek alapján erősebb deeszkalációs tendencia volt megfigyelhető. "
        f"A konfliktusról szóló beszámolókban az egyeztetés, a politikai rendezés és az enyhülés jelei voltak hangsúlyosabbak, mint a közvetlen katonai eszkaláció."
    )


def build_military_section(counts):
    frontline = counts.get("frontline", 0)
    air_strikes = counts.get("air_strikes", 0)

    if frontline == 0 and air_strikes == 0:
        return (
            "A napi híranyagban a harctéri és csapásjellegű események nem alkottak különösen erős tematikus blokkot. "
            "Ez azonban nem feltétlenül jelent alacsonyabb intenzitást, inkább azt, hogy a címek megfogalmazása kevésbé koncentrálódott ezekre a kulcsszavakra."
        )

    if air_strikes > frontline:
        return (
            f"A katonai dimenzióban a légi csapásokhoz, rakéta- és dróntámadásokhoz kapcsolódó hírek domináltak ({air_strikes} releváns cím), "
            f"miközben a klasszikus frontvonalhoz kötődő tudósítások valamivel kisebb súllyal jelentek meg ({frontline} cím). "
            "Ez olyan médiaképet jelez, amelyben a távolsági csapásmérés és a városi vagy infrastrukturális célpontok elleni támadások erősebben tematizálták a konfliktust."
        )

    return (
        f"A katonai dimenzióban a fronthelyzettel és szárazföldi műveletekkel összefüggő hírek jelentek meg hangsúlyosabban ({frontline} releváns cím), "
        f"miközben a légi csapásokkal összefüggő tudósítások is számottevőek maradtak ({air_strikes} cím). "
        "Ez arra utal, hogy a napi híráramlásban egyszerre volt jelen a harctéri dinamika és a mélységi csapások kérdésköre."
    )


def build_diplomatic_section(counts):
    diplomacy = counts.get("diplomacy", 0)
    leadership = counts.get("leadership", 0)

    if diplomacy == 0 and leadership == 0:
        return (
            "A diplomáciai és politikai dimenzió a napi híranyagban háttérbe szorult. "
            "A konfliktus értelmezését így elsősorban a katonai fejlemények alakították, nem pedig a rendezési vagy tárgyalásos kezdeményezések."
        )

    if diplomacy > 0 and leadership > 0:
        return (
            f"A diplomáciai-politikai dimenzió korlátozott, de érzékelhető jelenléttel bírt: "
            f"{diplomacy} cím utalt tárgyalásokra, egyeztetésekre vagy rendezési törekvésekre, "
            f"miközben {leadership} cím a vezetői szintű politikai kommunikációt vagy döntéshozói kontextust emelte be. "
            "Ez arra utal, hogy a napi napirend nem kizárólag a harctéri események köré szerveződött."
        )

    return (
        f"A diplomáciai-politikai dimenzió visszafogottan jelent meg a napi hírekben ({diplomacy} releváns cím). "
        "A tudósítások fő súlypontja továbbra is a konfliktus operatív és katonai vetülete maradt."
    )


def build_support_section(counts):
    support = counts.get("support", 0)

    if support == 0:
        return (
            "A külső támogatáshoz, fegyverszállításokhoz és szankciós környezethez kapcsolódó hírek a vizsgált napon nem alkottak külön domináns blokkot."
        )

    return (
        f"A nemzetközi támogatási környezet a napi médiaképben is látható maradt ({support} releváns cím). "
        "Ez arra utal, hogy a konfliktus értelmezésében továbbra is fontos szerepet játszik a nyugati katonai támogatás, "
        "a védelmi képességek fenntartása és a gazdasági nyomásgyakorlási dimenzió."
    )


def build_operational_picture(counts):
    frontline = counts.get("frontline", 0)
    air = counts.get("air_strikes", 0)

    if frontline > air:
        return (
            "A médiaképet elsősorban a szárazföldi műveletek és frontvonalhoz kapcsolódó hírek határozták meg. "
            "Ez arra utal, hogy a konfliktus narratívájában a harctéri dinamika dominál, "
            "nem pedig a mélységi csapások vagy stratégiai infrastruktúra elleni támadások."
        )

    if air > frontline:
        return (
            "A napi tudósításokban a rakéta- és dróntámadások, valamint a légi csapások voltak hangsúlyosabbak. "
            "Ez a konfliktus azon dimenziójára utal, ahol a felek mélységi célpontok ellen alkalmaznak távolsági fegyverrendszereket."
        )

    return (
        "A napi médiakép kiegyensúlyozottan tükrözte a frontvonalon zajló harcokat és a légi csapásokat. "
        "Ez egy komplex, többdimenziós hadműveleti helyzet narratívájára utal."
    )


def media_narrative(articles):
    escalation = len([a for a in articles if a.get("score", 0) < 0])
    deesc = len([a for a in articles if a.get("score", 0) > 0])

    if escalation > deesc * 2:
        return (
            "A médiakép erősen konfliktuscentrikus volt: a címek többsége katonai eseményeket, "
            "csapásokat vagy harctéri fejleményeket hangsúlyozott."
        )

    if deesc > escalation:
        return (
            "A médiában viszonylag erősebb szerepet kaptak a diplomáciai és politikai fejlemények. "
            "Ez részben a konfliktus politikai kezelésének narratíváját erősítheti."
        )

    return (
        "A hírek narratívája vegyes képet mutatott, amelyben a katonai események és a politikai reakciók egyaránt jelen voltak."
    )


def risk_indicator(total_score):
    if total_score < -50:
        return "Rövid távon fokozott eszkalációs kockázat érzékelhető."
    if total_score < -20:
        return "A konfliktus intenzitása stabilan magas szinten marad."
    if total_score < 10:
        return "A helyzet rövid távon instabil, de nem mutat egyértelmű eszkalációs irányt."
    return "A médiakép alapján rövid távú enyhülési jelzések is megfigyelhetők."


def markdown_article_line(article):
    title = article.get("title", "N/A")
    score = article.get("score", 0)
    source = article.get("source", "N/A")
    link = article.get("link", "")
    return f"- **[{title}]({link})** — pontszám: `{score}`, forrás: {source}"


def normalize_external_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                item = item.strip()
                if item:
                    parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("title") or item.get("summary") or ""
                text = str(text).strip()
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        for key in ["text", "summary", "brief", "content", "description"]:
            if key in value and str(value[key]).strip():
                return str(value[key]).strip()
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value).strip()


def extract_external_brief(brief_data):
    if not brief_data:
        return None

    candidates = [
        brief_data.get("brief"),
        brief_data.get("summary"),
        brief_data.get("daily_brief"),
        brief_data.get("content"),
        brief_data.get("text"),
        brief_data.get("report"),
    ]

    for candidate in candidates:
        text = normalize_external_text(candidate)
        if text:
            return text

    # fallback: ha nincs ismert főmező, próbáljuk a teljes objektumból kiolvasni a fontosabb stringeket
    collected = []
    for key, value in brief_data.items():
        text = normalize_external_text(value)
        if text and len(text) > 20:
            collected.append(f"**{key}**: {text}")

    if collected:
        return "\n\n".join(collected[:5])

    return None


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


def build_external_operational_section(brief_text, change_text):
    if brief_text and change_text:
        return (
            "A külső operatív adatforrás és a médiakép együtt használva árnyaltabb napi helyzetképet ad. "
            "A fronthelyzeti réteg a terepi változásokra, míg a médiás réteg az információs környezet hangsúlyaira érzékeny."
        )
    if brief_text:
        return (
            "A külső napi operatív brief alapján a jelentés nemcsak médiás jelzéseket, hanem a fronthelyzetről szóló összefoglaló réteget is figyelembe veszi."
        )
    if change_text:
        return (
            "A külső változásjelző adat alapján a jelentés a napi médiaképet kiegészíti a legfrissebb terepi vagy térképi elmozdulások rövid összegzésével."
        )
    return (
        "Külső operatív forrás nem állt rendelkezésre, ezért a napi jelentés főként a médiás konfliktusjelzésekből épül fel."
    )


def build_consistency_assessment(total_score, brief_text, change_text):
    if not brief_text and not change_text:
        return (
            "A mai jelentésben a médiás konfliktusindex önállóan adott képet az intenzitásról; külső operatív megerősítés nem állt rendelkezésre."
        )

    if total_score <= -15:
        return (
            "A médiás index eszkalációs képet jelez, és a külső operatív források bevonása ezt nagy valószínűséggel megerősítő vagy legalábbis kontextualizáló szerepet játszik."
        )

    if total_score >= 10:
        return (
            "A médiás kép enyhébb vagy kiegyensúlyozottabb napi környezetet jelez, ezért különösen fontos figyelni, hogy a külső fronthelyzeti adatok mennyiben támasztják ezt alá."
        )

    return (
        "A napi médiás és operatív rétegek együtt vegyes, összetett képet rajzolnak ki, ahol az információs környezet és a terepi dinamika nem feltétlenül mozog azonos intenzitással."
    )


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

    created_at = data.get("created_at", "")
    date_str = created_at[:10] if created_at else datetime.utcnow().date().isoformat()
    article_count = data.get("article_count", 0)
    total_score = data.get("total_score", 0)
    assessment = data.get("assessment", "unknown")
    assessment_hu = translate_assessment(assessment)
    escalation_count = data.get("escalation_articles", 0)
    deescalation_count = data.get("deescalation_articles", 0)
    neutral_count = data.get("neutral_articles", 0)
    articles = data.get("articles", [])

    negative_articles = top_negative_articles(articles, limit=5)
    positive_articles = top_positive_articles(articles, limit=5)
    keywords = extract_keyword_summary(articles)
    counts = theme_counts(articles)

    brief = assessment_to_brief(
        total_score,
        assessment,
        article_count,
        escalation_count,
        deescalation_count
    )
    military_section = build_military_section(counts)
    diplomatic_section = build_diplomatic_section(counts)
    support_section = build_support_section(counts)
    operational_picture = build_operational_picture(counts)
    narrative = media_narrative(articles)
    risk_text = risk_indicator(total_score)

    external_brief_text = extract_external_brief(brief_data)
    external_change_text = extract_change_summary(change_data)
    external_operational_text = build_external_operational_section(
        external_brief_text,
        external_change_text
    )
    consistency_text = build_consistency_assessment(
        total_score,
        external_brief_text,
        external_change_text
    )

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
    lines.append(brief)
    lines.append("")

    lines.append("## 2. Fő trendek")
    lines.append("")
    lines.append(
        f"A napi cikkmegoszlás alapján **{escalation_count}** eszkalációs, "
        f"**{deescalation_count}** deeszkalációs és **{neutral_count}** semleges hír került a mintába. "
        "Ez a megoszlás rövid távú médiaképet ad a konfliktus intenzitásáról, nem pedig teljes körű hadműveleti helyzetképet."
    )
    lines.append("")

    lines.append("## 3. Operatív helyzetkép")
    lines.append("")
    lines.append(operational_picture)
    lines.append("")
    lines.append(external_operational_text)
    lines.append("")

    if external_brief_text:
        lines.append("## 4. Külső fronthelyzeti napi brief")
        lines.append("")
        lines.append(external_brief_text)
        lines.append("")
    else:
        lines.append("## 4. Külső fronthelyzeti napi brief")
        lines.append("")
        lines.append("A mai futás során nem állt rendelkezésre külön külső napi operatív brief.")
        lines.append("")

    if external_change_text:
        lines.append("## 5. Külső változásjelző összefoglaló")
        lines.append("")
        lines.append(external_change_text)
        lines.append("")
    else:
        lines.append("## 5. Külső változásjelző összefoglaló")
        lines.append("")
        lines.append("A mai futás során nem érkezett külön változásjelző összefoglaló a külső adatforrásból.")
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
        "ezért a végső következtetések mindig óvatos értelmezést igényelnek."
    )
    lines.append("")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Integrated markdown report generated: {report_path}")


if __name__ == "__main__":
    main()
