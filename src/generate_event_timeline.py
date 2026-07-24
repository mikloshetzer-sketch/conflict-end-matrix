import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# =====================================================================
# Conflict End Matrix -> historical non-kinetic event timeline V3.1
#
# V3.1 refinements:
# - Explicit reversal phrases such as:
#     "calls off ultimatum"
#     "retracts threat"
#     "withdraws threat"
#     "backs away from threat"
#   are treated as de-escalatory.
#
# - When meaningful positive AND negative signals coexist in the same
#   headline, the event can become MIXED instead of being forced into
#   escalation/de-escalation.
#
# - Event TYPE and event DIRECTION remain separate analytical questions.
# =====================================================================

SCORED_RELATIVE_PATH = "data/processed/latest_scored.json"

DIPLOMACY_TERMS = {
    "peace", "talks", "negotiation", "negotiations", "diplomacy",
    "diplomatic", "mediator", "mediation", "dialogue",
}

CEASEFIRE_TERMS = {
    "ceasefire", "truce", "agreement", "deal", "pause", "settlement",
    "de-escalation", "deescalation",
}

THREAT_TERMS = {
    "threat", "threatens", "warning", "warns", "ultimatum",
    "retaliation", "escalation",
}

GENERIC_RISK_CONTEXT = {
    "poverty", "children", "economy", "economic", "markets", "market",
    "oil prices", "food security", "humanitarian", "health", "climate",
    "trade", "shipping", "tourism", "jobs", "inflation", "growth",
    "recession", "supply chain",
}

THREAT_PATTERNS = [
    r"\bthreatens?\s+(?:to\s+)?(?:attack|strike|retaliate|respond|hit|target|destroy|close|block|escalate|punish)\b",
    r"\bwarns?\s+(?:of|that|against|it will|they will|he will|she will|to)\b",
    r"\bwarns?\b.*\b(?:attack|strike|retaliat|response|consequences|military|force)\b",
    r"\bretaliat(?:e|es|ion|ory)\b",
    r"\bultimatum\b",
    r"\bvows?\s+(?:to\s+)?(?:retaliate|respond|strike|attack)\b",
    r"\bpromises?\s+(?:a\s+)?(?:response|retaliation)\b",
]

ESCALATION_POSTURE_PATTERNS = [
    r"\b(?:plans?|planning|ready|prepares?|preparing|intends?|intention)\b.*\b(?:intensify|escalate|expand|broaden)\b",
    r"\b(?:intensify|intensifies|intensified|escalate|escalates|escalated|escalation)\b.*\b(?:conflict|war|campaign|pressure|response|operations?)\b",
    r"\b(?:deploys?|deployment|sends?|sending|moves?|moving)\b.*\b(?:troops?|forces?|aircraft|bombers?|warships?|carrier|missiles?|air defence|air defense)\b",
    r"\b(?:raises?|raised|increases?|increased)\b.*\b(?:alert|readiness|military readiness|force posture)\b",
    r"\b(?:mobilises?|mobilizes?|mobilisation|mobilization)\b",
    r"\b(?:rejects?|rejected|rules out|ruled out)\b.*\b(?:ceasefire|truce|talks?|negotiations?|deal|peace proposal|peace plan)\b",
    r"\b(?:suspends?|suspended|halts?|halted|breaks off|broke off|withdraws?|withdrew)\b.*\b(?:talks?|negotiations?|dialogue|agreement|deal|ceasefire)\b",
    r"\b(?:talks?|negotiations?)\b.*\b(?:collapse|collapsed|fail|failed|break down|broke down|deadlock|stalemate)\b",
    r"\b(?:imposes?|imposed|announces?|announced)\b.*\b(?:new sanctions|sanctions|blockade|embargo)\b",
    r"\b(?:tightens?|tightened|expands?|expanded)\b.*\b(?:sanctions|blockade|embargo|restrictions)\b",
    r"\b(?:red line|red lines)\b",
    r"\b(?:serious|grave|severe)\s+consequences\b",
]

DIPLOMACY_PATTERNS = [
    r"\bpeace talks?\b",
    r"\bcease[- ]?fire\b",
    r"\btruce\b",
    r"\bnegotiat(?:e|es|ed|ing|ion|ions)\b",
    r"\bmediat(?:e|es|ed|ing|or|ors|ion)\b",
    r"\bdiplomat(?:ic|ically|s)?\b",
    r"\bdialogue\b",
    r"\bpeace proposal\b",
    r"\bpeace plan\b",
    r"\bagreement\b",
    r"\bde[- ]?escalat(?:e|es|ed|ing|ion)\b",
]

KINETIC_ACTION_PATTERNS = [
    r"\b(?:launches?|launched|carries out|carried out|conducts?|conducted)\b.*\b(?:attack|strike|airstrike|missile|drone)\b",
    r"\b(?:attacks?|strikes?|bombs?|bombed|hits?|hit)\b.*\b(?:iran|israel|usa|u\.s\.|us|base|facility|site|city|target)\b",
    r"\b(?:missile|drone|airstrike|strike|attack)\b.*\b(?:kills?|killed|hits?|hit|damages?|destroyed)\b",
    r"\b(?:troops?|soldiers?|civilians?)\b.*\b(?:killed|dead|injured)\b",
]


# =====================================================================
# DIRECTION MODEL V3.1
# =====================================================================

# Strong reversal language must be evaluated before generic "threat" rules.
REVERSAL_DEESCALATION_RULES = [
    (5, "calls_off_ultimatum",
     r"\b(?:calls?|called)\s+off\b.*\b(?:ultimatum|threat|strike|attack|military action)\b"),
    (5, "retracts_threat",
     r"\b(?:retracts?|retracted|withdraws?|withdrew|withdrawn)\b.*\b(?:threat|ultimatum|warning)\b"),
    (5, "backs_away_from_threat",
     r"\b(?:backs?|backed)\s+away\s+from\b.*\b(?:threat|ultimatum|strike|attack|military action)\b"),
    (5, "drops_threat",
     r"\b(?:drops?|dropped|abandons?|abandoned)\b.*\b(?:threat|ultimatum|military option)\b"),
    (4, "stands_down",
     r"\b(?:stands?|stood)\s+down\b.*\b(?:forces?|troops?|military|strike|attack)\b"),
]

POSITIVE_DIRECTION_RULES = [
    (4, "ceasefire_takes_effect",
     r"\bcease[- ]?fire\b.*\b(?:takes? effect|begins?|starts?|implemented|implementation|holds?|holding|extended|renewed)\b"),
    (4, "truce_agreed",
     r"\b(?:agree|agrees|agreed|reach|reaches|reached|sign|signs|signed)\b.*\b(?:cease[- ]?fire|truce|peace deal|peace agreement|agreement)\b"),
    (4, "peace_deal_reached",
     r"\b(?:peace deal|peace agreement|settlement)\b.*\b(?:agreed|reached|signed|accepted|approved|implemented)\b"),
    (3, "talks_begin_resume",
     r"\b(?:talks?|negotiations?|dialogue)\b.*\b(?:begin|begins|began|start|starts|started|resume|resumes|resumed|continue|continues|continued)\b"),
    (3, "actor_resumes_talks",
     r"\b(?:resume|resumes|resumed|begin|begins|began|start|starts|started|continue|continues)\b.*\b(?:talks?|negotiations?|dialogue)\b"),
    (2, "mediation_active",
     r"\b(?:mediator|mediators|mediation)\b.*\b(?:effort|efforts|push|initiative|talks?|meeting|meetings)\b"),
    (3, "peace_proposal_positive",
     r"\b(?:accepts?|accepted|backs?|backed|supports?|supported|welcomes?|welcomed)\b.*\b(?:peace proposal|peace plan|cease[- ]?fire|truce|deal|agreement)\b"),
    (3, "deescalation_explicit",
     r"\bde[- ]?escalat(?:e|es|ed|ing|ion)\b"),
    (2, "diplomatic_progress",
     r"\b(?:progress|breakthrough|constructive|productive|rapid pace)\b.*\b(?:talks?|negotiations?|diplomacy|dialogue)\b"),
    (2, "open_to_talks",
     r"\b(?:open|ready|willing)\s+to\b.*\b(?:talk|negotiate|dialogue)\b"),
    (2, "deal_close",
     r"\b(?:deal|agreement)\b.*\b(?:close|near|imminent|expected to be signed|shortly)\b"),
]

NEGATIVE_DIRECTION_RULES = [
    (-5, "deal_voided_cancelled",
     r"\b(?:peace deal|deal|agreement|cease[- ]?fire|truce)\b.*\b(?:voided|cancelled|canceled|terminated|abandoned|scrapped|dead)\b"),
    (-5, "actor_voids_deal",
     r"\b(?:voids?|voided|cancels?|cancelled|canceled|terminates?|terminated|abandons?|abandoned|scraps?|scrapped)\b.*\b(?:peace deal|deal|agreement|cease[- ]?fire|truce)\b"),
    (-5, "ceasefire_collapses",
     r"\b(?:cease[- ]?fire|truce|peace deal|agreement)\b.*\b(?:collapse|collapses|collapsed|breaks down|broke down|fails?|failed|shatters?|shattered)\b"),
    (-4, "proposal_rejected",
     r"\b(?:rejects?|rejected|rules out|ruled out|refuses?|refused)\b.*\b(?:cease[- ]?fire|truce|peace proposal|peace plan|deal|agreement|talks?|negotiations?)\b"),
    (-4, "talks_stall_fail",
     r"\b(?:talks?|negotiations?|diplomatic efforts?|dialogue)\b.*\b(?:stall|stalls|stalled|fail|fails|failed|collapse|collapsed|deadlock|stalemate|break down|broke down|suspended|halted)\b"),
    (-4, "efforts_stall",
     r"\b(?:stall|stalls|stalled|fail|fails|failed|collapse|collapsed)\b.*\b(?:talks?|negotiations?|diplomatic efforts?|dialogue)\b"),
    (-3, "threat_direct",
     r"\b(?:threatens?|threat|ultimatum|retaliation|retaliatory)\b"),
    (-3, "red_line", r"\bred lines?\b"),
    (-3, "warning_consequences",
     r"\bwarns?\b.*\b(?:attack|strike|retaliat|response|consequences|military|force)\b"),
    (-2, "escalation_explicit", r"\bescalat(?:e|es|ed|ing|ion)\b"),
    (-2, "attacks_intensify",
     r"\b(?:attacks?|strikes?|fighting|war|hostilities)\b.*\b(?:intensify|intensifies|intensified|expand|expands|expanded|spiral|spiraling|spiralling)\b"),
    (-2, "intensify_attacks",
     r"\b(?:intensify|intensifies|intensified|expand|expands|expanded)\b.*\b(?:attacks?|strikes?|fighting|war|hostilities)\b"),
    (-2, "military_posture",
     r"\b(?:deploys?|deployment|mobilizes?|mobilises?|raises? readiness|military buildup|build-up)\b"),
    (-2, "sanctions_pressure",
     r"\b(?:new sanctions|tightens? sanctions|expands? sanctions|blockade|embargo)\b"),
    (-1, "existential_war", r"\bexistential war\b"),
]

SPECULATIVE_POSITIVE_GUARDS = [
    ("speculative_hope",
     r"\b(?:hope|hopes|hoping|prospect|prospects|possibility|possible)\b.*\b(?:de[- ]?escalation|cease[- ]?fire|truce|deal|peace)\b"),
]

# These combinations are analytically useful as MIXED rather than
# forcing the stronger raw score to one side.
EXPLICIT_MIXED_PATTERNS = [
    (
        "talks_progress_plus_threat",
        r"\b(?:talks?|negotiations?)\b.*\b(?:continue|continuing|progress|rapid pace|resume|resumed)\b.*\b(?:threat|threatens|warns|other fronts|retaliat)\b"
    ),
    (
        "threat_plus_talks_progress",
        r"\b(?:threat|threatens|warns|other fronts|retaliat)\b.*\b(?:talks?|negotiations?)\b.*\b(?:continue|continuing|progress|rapid pace|resume|resumed)\b"
    ),
    (
        "deal_progress_plus_warning",
        r"\b(?:deal|agreement)\b.*\b(?:close|near|expected to be signed|shortly)\b.*\b(?:warns?|consequences|violations?)\b"
    ),
    (
        "ceasefire_plus_active_attacks",
        r"\b(?:cease[- ]?fire|truce|agreement)\b.*\b(?:attacks?|strikes?|fighting|hostilities)\b"
    ),
    (
        "active_attacks_plus_ceasefire",
        r"\b(?:attacks?|strikes?|fighting|hostilities)\b.*\b(?:cease[- ]?fire|truce|agreement)\b"
    ),
]


def run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout


def load_current_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def git_commits_for_file(repo_root: Path, relative_path: str) -> list[str]:
    output = run_git(
        ["log", "--follow", "--format=%H", "--", relative_path],
        cwd=repo_root,
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def load_file_at_commit(
    repo_root: Path,
    commit: str,
    relative_path: str,
) -> dict[str, Any] | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def article_identity(article: dict[str, Any]) -> str:
    link = str(article.get("link", "")).strip()
    if link:
        return "link:" + link
    title = str(article.get("title", "")).strip().lower()
    published = str(article.get("published", "")).strip()
    return f"title:{title}|published:{published}"


def collect_historical_articles(
    repo_root: Path,
    current_data: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    versions_seen = 0
    unique: dict[str, dict[str, Any]] = {}

    commits = git_commits_for_file(repo_root, SCORED_RELATIVE_PATH)

    for commit in commits:
        snapshot = load_file_at_commit(repo_root, commit, SCORED_RELATIVE_PATH)
        if not snapshot:
            continue
        versions_seen += 1
        for article in snapshot.get("articles", []) or []:
            key = article_identity(article)
            if key not in unique:
                unique[key] = article

    for article in current_data.get("articles", []) or []:
        unique[article_identity(article)] = article

    return list(unique.values()), versions_seen


def matched_terms(article: dict[str, Any]) -> set[str]:
    return {
        str(match.get("keyword", "")).strip().lower()
        for match in (article.get("matched_keywords", []) or [])
        if str(match.get("keyword", "")).strip()
    }


def regex_any(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def is_generic_threat_context(title_lower: str) -> bool:
    return any(term in title_lower for term in GENERIC_RISK_CONTEXT)


def is_real_threat_statement(title: str, terms: set[str]) -> bool:
    title_lower = title.lower()
    if not (terms & THREAT_TERMS):
        return False
    if is_generic_threat_context(title_lower):
        return regex_any(THREAT_PATTERNS, title_lower)
    return regex_any(THREAT_PATTERNS, title_lower)


def is_escalation_posture(title: str, terms: set[str]) -> bool:
    title_lower = title.lower()
    if regex_any(KINETIC_ACTION_PATTERNS, title_lower):
        return False
    return regex_any(ESCALATION_POSTURE_PATTERNS, title_lower)


def is_diplomatic_event(title: str, terms: set[str]) -> bool:
    title_lower = title.lower()
    if not ((terms & DIPLOMACY_TERMS) or (terms & CEASEFIRE_TERMS)):
        return False
    if regex_any(DIPLOMACY_PATTERNS, title_lower):
        return True
    return not regex_any(KINETIC_ACTION_PATTERNS, title_lower)


def classify_non_kinetic_event(article: dict[str, Any]) -> dict[str, str] | None:
    title = str(article.get("title", "")).strip()
    terms = matched_terms(article)

    if not title:
        return None

    title_lower = title.lower()

    if terms & CEASEFIRE_TERMS:
        if regex_any(DIPLOMACY_PATTERNS, title_lower) or not regex_any(
            KINETIC_ACTION_PATTERNS,
            title_lower,
        ):
            primary = sorted(terms & CEASEFIRE_TERMS)[0]
            return {
                "event_type": "ceasefire",
                "subtype": primary,
                "primary_keyword": primary,
            }

    if is_diplomatic_event(title, terms):
        primary = sorted(terms & DIPLOMACY_TERMS)[0]
        return {
            "event_type": "diplomatic",
            "subtype": primary,
            "primary_keyword": primary,
        }

    if is_escalation_posture(title, terms):
        matched_escalation_terms = sorted(terms & THREAT_TERMS)
        primary = matched_escalation_terms[0] if matched_escalation_terms else "escalatory_posture"
        return {
            "event_type": "threat",
            "subtype": primary,
            "primary_keyword": primary,
        }

    if is_real_threat_statement(title, terms):
        matched_threat_terms = sorted(terms & THREAT_TERMS)
        primary = matched_threat_terms[0] if matched_threat_terms else "threat"
        return {
            "event_type": "threat",
            "subtype": primary,
            "primary_keyword": primary,
        }

    return None


def legacy_direction(event_type: str) -> str:
    return "escalation" if event_type == "threat" else "de-escalation"


def collect_rule_hits(
    title: str,
    rules: list[tuple[int, str, str]],
) -> tuple[int, list[dict[str, Any]]]:
    score = 0
    reasons: list[dict[str, Any]] = []

    for weight, name, pattern in rules:
        if re.search(pattern, title, flags=re.IGNORECASE):
            score += weight
            reasons.append({"rule": name, "points": weight})

    return score, reasons


def classify_direction(
    title: str,
    article_score: int,
    event_type: str,
) -> dict[str, Any]:
    text = title.lower()

    # 1) Strong reversal language first.
    reversal_score, reversal_reasons = collect_rule_hits(
        text,
        REVERSAL_DEESCALATION_RULES,
    )

    positive_score, positive_reasons = collect_rule_hits(
        text,
        POSITIVE_DIRECTION_RULES,
    )

    negative_score, negative_reasons = collect_rule_hits(
        text,
        NEGATIVE_DIRECTION_RULES,
    )

    reasons = reversal_reasons + positive_reasons + negative_reasons

    # If a threat/ultimatum was explicitly called off/retracted/withdrawn,
    # suppress generic threat penalties that refer to the same phrase.
    if reversal_score > 0:
        suppressed = {"threat_direct", "red_line", "warning_consequences"}
        negative_removed = sum(
            int(r["points"])
            for r in reasons
            if r["rule"] in suppressed and int(r["points"]) < 0
        )
        if negative_removed:
            negative_score -= negative_removed
            reasons = [r for r in reasons if r["rule"] not in suppressed]
            reasons.append({
                "rule": "reversal_suppresses_generic_threat",
                "points": -negative_removed,
            })

    score = reversal_score + positive_score + negative_score

    # Weak topic prior.
    if event_type == "threat" and score > -2 and reversal_score == 0:
        score -= 1
        reasons.append({"rule": "threat_topic_prior", "points": -1})

    # Existing index score is only a weak tie-breaker.
    if article_score <= -4:
        score -= 1
        reasons.append({"rule": "existing_score_negative_tiebreak", "points": -1})
    elif article_score >= 4:
        score += 1
        reasons.append({"rule": "existing_score_positive_tiebreak", "points": 1})

    # Speculative positive language receives less weight.
    if score > 0:
        for name, pattern in SPECULATIVE_POSITIVE_GUARDS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                score -= 1
                reasons.append({"rule": name, "points": -1})

    explicit_mixed_reason = None
    for name, pattern in EXPLICIT_MIXED_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            explicit_mixed_reason = name
            break

    has_positive = (reversal_score + positive_score) >= 2
    has_negative = negative_score <= -2

    # Strong coexistence of positive and negative signals -> MIXED.
    if explicit_mixed_reason:
        direction = "mixed"
        reasons.append({"rule": explicit_mixed_reason, "points": 0})
    elif has_positive and has_negative:
        # If one side is overwhelmingly stronger, keep that direction.
        positive_strength = reversal_score + positive_score
        negative_strength = abs(negative_score)

        if positive_strength >= negative_strength + 4:
            direction = "de-escalation"
        elif negative_strength >= positive_strength + 4:
            direction = "escalation"
        else:
            direction = "mixed"
            reasons.append({"rule": "competing_signals_mixed", "points": 0})
    elif score >= 2:
        direction = "de-escalation"
    elif score <= -2:
        direction = "escalation"
    else:
        direction = "mixed"

    return {
        "direction": direction,
        "direction_score": score,
        "direction_reasons": reasons,
        "positive_signal_score": reversal_score + positive_score,
        "negative_signal_score": negative_score,
    }


def build_event(
    article: dict[str, Any],
    sequence: int,
) -> dict[str, Any] | None:
    classification = classify_non_kinetic_event(article)
    if classification is None:
        return None

    terms = sorted(matched_terms(article))
    title = str(article.get("title", ""))
    article_score = int(article.get("score", 0) or 0)

    direction_result = classify_direction(
        title=title,
        article_score=article_score,
        event_type=classification["event_type"],
    )

    old_direction = legacy_direction(classification["event_type"])

    published = (
        article.get("published")
        or article.get("timestamp")
        or article.get("created_at")
        or ""
    )

    return {
        "event_id": f"INFO-{sequence:06d}",
        "timestamp": published,
        "event_type": classification["event_type"],
        "subtype": classification["subtype"],
        "title": title,
        "diplomatic_event": title,
        "military_event": "",
        "direction": direction_result["direction"],
        "direction_score": direction_result["direction_score"],
        "positive_signal_score": direction_result["positive_signal_score"],
        "negative_signal_score": direction_result["negative_signal_score"],
        "direction_reasons": direction_result["direction_reasons"],
        "old_direction": old_direction,
        "direction_changed": old_direction != direction_result["direction"],
        "actors": [],
        "target": "",
        "location": "",
        "keywords": terms,
        "primary_keyword": classification["primary_keyword"],
        "source": article.get("source", ""),
        "link": article.get("link", ""),
        "score": article_score,
        "linked_event_id": "",
        "linked_statement": "",
        "linked_military_event": "",
        "relation_type": "",
        "lag_minutes": None,
        "link_confidence": "",
    }


def parse_datetime(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)

    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(value)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    except Exception:
        pass

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def count_by(events: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        key = str(event.get(field, "unknown"))
        counts[key] = counts.get(key, 0) + 1
    return counts


def create_validation_report(events: list[dict[str, Any]]) -> dict[str, Any]:
    changed = [e for e in events if e.get("direction_changed")]

    # Explicitly surface known tricky semantic cases.
    tricky_terms = (
        "calls off", "retract", "withdraw", "backs away",
        "rapid pace", "continuing", "stall", "voided",
        "threat", "ultimatum", "ceasefire", "deal"
    )

    tricky = [
        e for e in events
        if any(term in str(e.get("title", "")).lower() for term in tricky_terms)
    ]

    examples = sorted(
        tricky,
        key=lambda e: (
            abs(int(e.get("direction_score", 0))),
            parse_datetime(str(e.get("timestamp", ""))),
        ),
        reverse=True,
    )[:40]

    transition_counts: dict[str, int] = {}
    for event in events:
        transition = f"{event.get('old_direction')} -> {event.get('direction')}"
        transition_counts[transition] = transition_counts.get(transition, 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "context_direction_v3_1",
        "event_count": len(events),
        "old_direction_counts": count_by(events, "old_direction"),
        "new_direction_counts": count_by(events, "direction"),
        "changed_count": len(changed),
        "changed_share": round((len(changed) / len(events) * 100), 2) if events else 0,
        "transition_counts": transition_counts,
        "review_examples": [
            {
                "event_id": e.get("event_id"),
                "timestamp": e.get("timestamp"),
                "title": e.get("title"),
                "event_type": e.get("event_type"),
                "old_direction": e.get("old_direction"),
                "new_direction": e.get("direction"),
                "direction_score": e.get("direction_score"),
                "positive_signal_score": e.get("positive_signal_score"),
                "negative_signal_score": e.get("negative_signal_score"),
                "direction_reasons": e.get("direction_reasons"),
                "score": e.get("score"),
                "link": e.get("link"),
            }
            for e in examples
        ],
    }


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    current_path = repo_root / SCORED_RELATIVE_PATH

    output_dir = repo_root / "docs"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "event_timeline.json"
    validation_path = output_dir / "event_direction_validation.json"

    current_data = load_current_json(current_path)

    all_articles, historical_versions = collect_historical_articles(
        repo_root,
        current_data,
    )

    events: list[dict[str, Any]] = []

    for article in all_articles:
        event = build_event(article, len(events) + 1)
        if event is not None:
            events.append(event)

    events.sort(
        key=lambda event: parse_datetime(str(event.get("timestamp", ""))),
        reverse=True,
    )

    for index, event in enumerate(events, start=1):
        event["event_id"] = f"INFO-{index:06d}"

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Conflict End Matrix Git history + current latest_scored.json",
        "scope": "historical non-kinetic diplomatic, ceasefire and threat/statement events",
        "direction_model": "context_direction_v3_1",
        "military_events_included": False,
        "historical_scored_versions_read": historical_versions,
        "unique_articles_scanned": len(all_articles),
        "event_count": len(events),
        "event_type_counts": count_by(events, "event_type"),
        "direction_counts": count_by(events, "direction"),
        "events": events,
    }

    validation = create_validation_report(events)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    with validation_path.open("w", encoding="utf-8") as f:
        json.dump(validation, f, indent=2, ensure_ascii=False)

    print("Historical non-kinetic event timeline V3.1 generated.")
    print(f"Historical scored versions read: {historical_versions}")
    print(f"Unique articles scanned: {len(all_articles)}")
    print(f"Events extracted: {len(events)}")
    print(f"Event types: {payload['event_type_counts']}")
    print(f"Old directions: {validation['old_direction_counts']}")
    print(f"New directions: {validation['new_direction_counts']}")
    print(f"Changed: {validation['changed_count']} ({validation['changed_share']}%)")
    print(f"Timeline: {output_path}")
    print(f"Validation: {validation_path}")


if __name__ == "__main__":
    main()

