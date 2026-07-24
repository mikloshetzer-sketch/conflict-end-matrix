import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# =====================================================================
# Conflict End Matrix -> historical non-kinetic event timeline
#
# IMPORTANT:
# 1) The repo stores only the current data/processed/latest_scored.json.
# 2) Historical daily versions are reconstructed from Git history.
# 3) This generator extracts ONLY non-kinetic informational events:
#    diplomacy, talks, mediation, ceasefire, peace, warnings, threats,
#    retaliation statements, political/military announcements.
# 4) It does NOT create kinetic/military events.
# 5) It does NOT modify the existing scoring model or conflict index.
# =====================================================================

SCored_RELATIVE_PATH = "data/processed/latest_scored.json"

# ---------------------------------------------------------------------
# Strong non-kinetic concepts.
# These are analytical labels only; they do not change scoring.
# ---------------------------------------------------------------------
DIPLOMACY_TERMS = {
    "peace",
    "talks",
    "negotiation",
    "negotiations",
    "diplomacy",
    "diplomatic",
    "mediator",
    "mediation",
    "dialogue",
}

CEASEFIRE_TERMS = {
    "ceasefire",
    "truce",
    "agreement",
    "deal",
    "pause",
    "settlement",
    "de-escalation",
    "deescalation",
}

THREAT_TERMS = {
    "threat",
    "threatens",
    "warning",
    "warns",
    "ultimatum",
    "retaliation",
    "escalation",
}

# Titles containing these ideas are usually descriptive reporting about
# effects/risks, not an actor issuing a threat. This protects against
# examples such as "conflict threatens to drive children into poverty".
GENERIC_RISK_CONTEXT = {
    "poverty",
    "children",
    "economy",
    "economic",
    "markets",
    "market",
    "oil prices",
    "food security",
    "humanitarian",
    "health",
    "climate",
    "trade",
    "shipping",
    "tourism",
    "jobs",
    "inflation",
    "growth",
    "recession",
    "supply chain",
}

# Direct threat / warning language. A generic word "threat/threatens"
# alone is not enough; a title must show actor-directed intent.
THREAT_PATTERNS = [
    r"\bthreatens?\s+(?:to\s+)?(?:attack|strike|retaliate|respond|hit|target|destroy|close|block|escalate|punish)\b",
    r"\bwarns?\s+(?:of|that|against|it will|they will|he will|she will|to)\b",
    r"\bwarns?\b.*\b(?:attack|strike|retaliat|response|consequences|military|force)\b",
    r"\bretaliat(?:e|es|ion|ory)\b",
    r"\bultimatum\b",
    r"\bvows?\s+(?:to\s+)?(?:retaliate|respond|strike|attack)\b",
    r"\bpromises?\s+(?:a\s+)?(?:response|retaliation)\b",
]

# Broader NON-KINETIC escalation signals. These capture political/military
# posture and breakdown of diplomacy without treating an actual attack
# as an informational event.
ESCALATION_POSTURE_PATTERNS = [
    # Explicit intensification / escalation announcements
    r"\b(?:plans?|planning|ready|prepares?|preparing|intends?|intention)\b.*\b(?:intensify|escalate|expand|broaden)\b",
    r"\b(?:intensify|intensifies|intensified|escalate|escalates|escalated|escalation)\b.*\b(?:conflict|war|campaign|pressure|response|operations?)\b",

    # Military posture without an actual strike
    r"\b(?:deploys?|deployment|sends?|sending|moves?|moving)\b.*\b(?:troops?|forces?|aircraft|bombers?|warships?|carrier|missiles?|air defence|air defense)\b",
    r"\b(?:raises?|raised|increases?|increased)\b.*\b(?:alert|readiness|military readiness|force posture)\b",
    r"\b(?:mobilises?|mobilizes?|mobilisation|mobilization)\b",

    # Diplomatic breakdown / rejection
    r"\b(?:rejects?|rejected|rules out|ruled out)\b.*\b(?:ceasefire|truce|talks?|negotiations?|deal|peace proposal|peace plan)\b",
    r"\b(?:suspends?|suspended|halts?|halted|breaks off|broke off|withdraws?|withdrew)\b.*\b(?:talks?|negotiations?|dialogue|agreement|deal|ceasefire)\b",
    r"\b(?:talks?|negotiations?)\b.*\b(?:collapse|collapsed|fail|failed|break down|broke down|deadlock|stalemate)\b",

    # Coercive political/economic pressure
    r"\b(?:imposes?|imposed|announces?|announced)\b.*\b(?:new sanctions|sanctions|blockade|embargo)\b",
    r"\b(?:tightens?|tightened|expands?|expanded)\b.*\b(?:sanctions|blockade|embargo|restrictions)\b",

    # Red-line / consequence language
    r"\b(?:red line|red lines)\b",
    r"\b(?:serious|grave|severe)\s+consequences\b",
]

# Strong diplomatic language in title.
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

# Headlines that clearly describe completed/ongoing kinetic action.
# If a diplomatic signal is also present, we retain only when diplomatic
# language is the clear subject of the headline.
KINETIC_ACTION_PATTERNS = [
    r"\b(?:launches?|launched|carries out|carried out|conducts?|conducted)\b.*\b(?:attack|strike|airstrike|missile|drone)\b",
    r"\b(?:attacks?|strikes?|bombs?|bombed|hits?|hit)\b.*\b(?:iran|israel|usa|u\.s\.|us|base|facility|site|city|target)\b",
    r"\b(?:missile|drone|airstrike|strike|attack)\b.*\b(?:kills?|killed|hits?|hit|damages?|destroyed)\b",
    r"\b(?:troops?|soldiers?|civilians?)\b.*\b(?:killed|dead|injured)\b",
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
        raise RuntimeError(
            f"git {' '.join(args)} failed:\n{result.stderr.strip()}"
        )

    return result.stdout


def load_current_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def git_commits_for_file(repo_root: Path, relative_path: str) -> list[str]:
    output = run_git(
        [
            "log",
            "--follow",
            "--format=%H",
            "--",
            relative_path,
        ],
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
    """
    Stable de-duplication key.

    Prefer the canonical article link. Fall back to title + published time.
    """
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
    """
    Reconstruct all unique articles from historical committed versions
    of latest_scored.json plus the current working-tree version.
    """
    versions_seen = 0
    unique: dict[str, dict[str, Any]] = {}

    commits = git_commits_for_file(repo_root, SCored_RELATIVE_PATH)

    for commit in commits:
        snapshot = load_file_at_commit(
            repo_root,
            commit,
            SCored_RELATIVE_PATH,
        )
        if not snapshot:
            continue

        versions_seen += 1

        for article in snapshot.get("articles", []) or []:
            key = article_identity(article)
            if key not in unique:
                unique[key] = article

    # Always include the current working-tree version in case the workflow
    # generated it before committing.
    for article in current_data.get("articles", []) or []:
        key = article_identity(article)
        unique[key] = article

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
    """
    Context-aware threat detection.

    A scored keyword such as 'threatens' is not enough by itself.
    Require directed warning / retaliation language and reject common
    socioeconomic / humanitarian risk constructions.
    """
    title_lower = title.lower()

    if not (terms & THREAT_TERMS):
        return False

    if is_generic_threat_context(title_lower):
        # Allow only if there is an unmistakable direct-action pattern.
        return regex_any(THREAT_PATTERNS, title_lower)

    return regex_any(THREAT_PATTERNS, title_lower)


def is_escalation_posture(title: str, terms: set[str]) -> bool:
    """
    Detect non-kinetic escalatory posture such as military deployments,
    readiness increases, rejection/breakdown of talks, sanctions pressure,
    explicit plans to intensify operations, or red-line rhetoric.

    Completed kinetic actions remain excluded by KINETIC_ACTION_PATTERNS.
    """
    title_lower = title.lower()

    if regex_any(KINETIC_ACTION_PATTERNS, title_lower):
        return False

    return regex_any(ESCALATION_POSTURE_PATTERNS, title_lower)


def is_diplomatic_event(title: str, terms: set[str]) -> bool:
    title_lower = title.lower()

    if not ((terms & DIPLOMACY_TERMS) or (terms & CEASEFIRE_TERMS)):
        return False

    # Strong diplomatic phrase = keep.
    if regex_any(DIPLOMACY_PATTERNS, title_lower):
        return True

    # Existing scorer identified a diplomatic keyword but title may use
    # a simple form such as "mediator". Keep those unless the headline
    # is clearly a completed kinetic event.
    return not regex_any(KINETIC_ACTION_PATTERNS, title_lower)


def classify_non_kinetic_event(
    article: dict[str, Any],
) -> dict[str, str] | None:
    title = str(article.get("title", "")).strip()
    terms = matched_terms(article)

    if not title:
        return None

    title_lower = title.lower()

    # Highest priority: ceasefire / settlement.
    if terms & CEASEFIRE_TERMS:
        if regex_any(DIPLOMACY_PATTERNS, title_lower) or not regex_any(
            KINETIC_ACTION_PATTERNS,
            title_lower,
        ):
            primary = sorted(terms & CEASEFIRE_TERMS)[0]
            return {
                "event_type": "ceasefire",
                "subtype": primary,
                "direction": "de-escalation",
                "primary_keyword": primary,
            }

    # Diplomacy / talks / mediation.
    if is_diplomatic_event(title, terms):
        primary = sorted(terms & DIPLOMACY_TERMS)[0]
        return {
            "event_type": "diplomatic",
            "subtype": primary,
            "direction": "de-escalation",
            "primary_keyword": primary,
        }

    # Broader non-kinetic escalation posture:
    # deployment/readiness, rejection or collapse of talks, sanctions,
    # explicit plans to intensify operations, red-line rhetoric.
    if is_escalation_posture(title, terms):
        posture_keyword = "escalatory_posture"
        matched_escalation_terms = sorted(terms & THREAT_TERMS)
        if matched_escalation_terms:
            posture_keyword = matched_escalation_terms[0]

        return {
            "event_type": "threat",
            "subtype": posture_keyword,
            "direction": "escalation",
            "primary_keyword": posture_keyword,
        }

    # Threat / warning / retaliation statement.
    if is_real_threat_statement(title, terms):
        matched_threat_terms = sorted(terms & THREAT_TERMS)
        primary = matched_threat_terms[0] if matched_threat_terms else "threat"
        return {
            "event_type": "threat",
            "subtype": primary,
            "direction": "escalation",
            "primary_keyword": primary,
        }

    return None


def build_event(
    article: dict[str, Any],
    sequence: int,
) -> dict[str, Any] | None:
    classification = classify_non_kinetic_event(article)
    if classification is None:
        return None

    terms = sorted(matched_terms(article))

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
        "title": article.get("title", ""),
        "diplomatic_event": article.get("title", ""),
        "military_event": "",
        "direction": classification["direction"],
        "actors": [],
        "target": "",
        "location": "",
        "keywords": terms,
        "primary_keyword": classification["primary_keyword"],
        "source": article.get("source", ""),
        "link": article.get("link", ""),
        "score": int(article.get("score", 0) or 0),

        # Reserved for the future kinetic-event linkage layer.
        "linked_event_id": "",
        "linked_statement": "",
        "linked_military_event": "",
        "relation_type": "",
        "lag_minutes": None,
        "link_confidence": "",
    }


def parse_datetime(value: str) -> datetime:
    """
    Best-effort parser used only for output sorting.
    Invalid values go to the oldest end of the list.
    """
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)

    # RFC 2822 example from Google News:
    # Thu, 23 Jul 2026 01:05:00 GMT
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


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    current_path = repo_root / SCored_RELATIVE_PATH

    output_dir = repo_root / "docs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "event_timeline.json"

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

    # Re-number after sorting for a predictable display order.
    for index, event in enumerate(events, start=1):
        event["event_id"] = f"INFO-{index:06d}"

    type_counts: dict[str, int] = {}
    for event in events:
        event_type = str(event.get("event_type", "unknown"))
        type_counts[event_type] = type_counts.get(event_type, 0) + 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Conflict End Matrix Git history + current latest_scored.json",
        "scope": "historical non-kinetic diplomatic, ceasefire and threat/statement events",
        "military_events_included": False,
        "historical_scored_versions_read": historical_versions,
        "unique_articles_scanned": len(all_articles),
        "event_count": len(events),
        "event_type_counts": type_counts,
        "events": events,
    }

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print("Historical non-kinetic event timeline generated.")
    print(f"Historical scored versions read: {historical_versions}")
    print(f"Unique articles scanned: {len(all_articles)}")
    print(f"Events extracted: {len(events)}")
    print(f"Event types: {type_counts}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
