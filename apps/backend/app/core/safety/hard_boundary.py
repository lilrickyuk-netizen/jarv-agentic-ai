"""
JARV Backend - Hard Boundary Detection

Deterministic detection of the Design section 6 / CLAUDE.md "HARD BOUNDARIES"
that JARV must PAUSE for (never abandon). Detection inspects real input text and
an optional structured action/metadata payload and reports:

- which boundary rules were actually checked,
- which (if any) matched,
- the honest coverage limitations of this detector.

This is deterministic keyword/pattern matching, NOT semantic understanding. It is
intentionally conservative (flags for human review) and explicitly documents what
it cannot do. It does not claim full Design compliance: it covers the textual /
structured signals of the hard-boundary categories, not every possible phrasing
or an action's true real-world effect.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# The hard-boundary categories from Design section 6 / CLAUDE.md. Each rule has a
# stable key, a human title, and the regex signals used to detect it in text.
# Keys mirror the Design "HARD BOUNDARIES" list so reports are traceable.
HARD_BOUNDARY_RULES: List[Dict[str, Any]] = [
    {"key": "bank_details", "title": "Entering bank details",
     "patterns": [r"\bbank account\b", r"\brouting number\b", r"\bsort code\b",
                  r"\biban\b", r"\bswift code\b", r"\baccount number\b"]},
    {"key": "spend_over_budget", "title": "Spending money beyond approved budget",
     "patterns": [r"\bexceed(s|ed)? .{0,20}budget\b", r"\bover budget\b",
                  r"\bspend .{0,20}(beyond|above|over) .{0,20}budget\b",
                  r"\bunbudgeted spend\b", r"\bpurchase\b", r"\bbuy\b", r"\bcheckout\b"]},
    {"key": "passwords", "title": "Entering passwords",
     "patterns": [r"\benter (a |the |your )?password\b", r"\btype (a |the |your )?password\b",
                  r"\bpassword[\s:=]+\S", r"\blog ?in with password\b"]},
    {"key": "password_manager", "title": "Accessing password managers",
     "patterns": [r"\bpassword manager\b", r"\b1password\b", r"\blastpass\b",
                  r"\bbitwarden\b", r"\bdashlane\b", r"\bkeepass\b", r"\bvault\b"]},
    {"key": "private_keys", "title": "Accessing private keys",
     "patterns": [r"private key", r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                  r"\bid_rsa\b", r"\b\.pem\b", r"\bsigning key\b"]},
    {"key": "seed_phrase", "title": "Accessing seed phrases",
     "patterns": [r"\bseed phrase\b", r"\bmnemonic\b", r"\brecovery phrase\b",
                  r"\b(12|24)[- ]word phrase\b"]},
    {"key": "crypto_wallet", "title": "Accessing crypto wallets",
     "patterns": [r"\bcrypto wallet\b", r"\bmetamask\b", r"\bledger\b", r"\btrezor\b",
                  r"\bprivate wallet\b", r"\bwallet seed\b"]},
    {"key": "sign_contract", "title": "Signing contracts",
     "patterns": [r"\bsign (the |a |this )?contract\b", r"\bsign (the |a |this )?agreement\b",
                  r"\bdocusign\b", r"\bexecute (the |a |this )?agreement\b"]},
    {"key": "binding_commitment", "title": "Sending binding legal/commercial commitments",
     "patterns": [r"\bbinding (legal|commercial|commitment)\b", r"\blegally binding\b",
                  r"\bcommit (the )?(company|business) to\b", r"\bpurchase order\b"]},
    {"key": "delete_production_data", "title": "Deleting production data",
     "patterns": [r"\bdelete .{0,20}prod(uction)?\b", r"\bdrop .{0,20}prod(uction)?\b",
                  r"\btruncate .{0,20}prod(uction)?\b", r"\bwipe .{0,20}prod(uction)?\b",
                  r"\bdrop database\b", r"\btruncate table\b"]},
    {"key": "irreversible_db_change", "title": "Making irreversible database changes",
     "patterns": [r"\birreversible\b.{0,20}\b(database|db|migration)\b",
                  r"\bdrop column\b", r"\bdrop table\b", r"\bdestructive migration\b"]},
    {"key": "public_live_release", "title": "Publishing public live release without release authority",
     "patterns": [r"\bpublic (live )?release\b", r"\bpublish .{0,20}(live|public|production)\b",
                  r"\bgo live\b", r"\bproduction release\b", r"\bship to production\b"]},
    {"key": "mass_email", "title": "Sending mass emails from Richard's accounts",
     "patterns": [r"\bmass email\b", r"\bbulk email\b", r"\bemail (all|every) (user|customer|subscriber)",
                  r"\bsend .{0,20}newsletter\b", r"\bblast email\b"]},
    {"key": "public_post", "title": "Posting publicly from Richard's accounts",
     "patterns": [r"\bpost (publicly|to (twitter|x|linkedin|facebook|instagram))\b",
                  r"\bpublish (a )?(tweet|post)\b", r"\bgo public on social\b"]},
    {"key": "run_unknown_executable", "title": "Running unknown executable files",
     "patterns": [r"\brun .{0,20}unknown .{0,20}(executable|binary|script)\b",
                  r"\bexecute .{0,20}downloaded\b", r"\bcurl .{0,40}\|\s*(sh|bash)\b",
                  r"\bchmod \+x .{0,40} && \./"]},
    {"key": "change_security_settings", "title": "Changing account security settings",
     "patterns": [r"\bchange .{0,20}security settings\b", r"\bdisable (2fa|mfa|two[- ]factor)\b",
                  r"\bturn off .{0,20}(2fa|mfa)\b", r"\bsecurity settings\b"]},
    {"key": "change_passwords", "title": "Changing passwords",
     "patterns": [r"\bchange (the |a |your )?password\b", r"\breset (the |a |your )?password\b",
                  r"\brotate .{0,20}password\b"]},
    {"key": "disable_audit_logs", "title": "Disabling audit logs",
     "patterns": [r"\bdisable .{0,20}audit log\b", r"\bturn off .{0,20}audit\b",
                  r"\bstop .{0,20}audit log\b"]},
    {"key": "disable_verifier", "title": "Disabling verifier checks",
     "patterns": [r"\bdisable .{0,20}verif(ier|ication)\b", r"\bskip .{0,20}verif(ier|ication)\b",
                  r"\bturn off .{0,20}verif"]},
    {"key": "disable_boundary_reports", "title": "Disabling boundary reports",
     "patterns": [r"\bdisable .{0,20}boundary report\b", r"\bturn off .{0,20}boundary\b"]},
    {"key": "weaken_authority", "title": "Weakening authority rules",
     "patterns": [r"\bweaken .{0,20}authority\b", r"\bbypass .{0,20}authority\b",
                  r"\bescalate .{0,20}authority\b", r"\bincrease .{0,20}authority\b"]},
    {"key": "remove_hard_boundaries", "title": "Removing hard-boundary rules",
     "patterns": [r"\bremove .{0,20}hard[- ]boundary\b", r"\bdelete .{0,20}boundary rule\b",
                  r"\bremove .{0,20}boundary rule\b"]},
    {"key": "subagent_authority_escalation", "title": "Allowing sub-agent authority escalation",
     "patterns": [r"\bsub[- ]?agent .{0,20}escalat", r"\bescalate .{0,20}sub[- ]?agent\b",
                  r"\bsub[- ]?agent .{0,20}exceed .{0,20}authority\b"]},
    {"key": "subagent_workspace_escape", "title": "Allowing sub-agent workspace escape",
     "patterns": [r"\bsub[- ]?agent .{0,20}escape\b", r"\bescape .{0,20}workspace\b",
                  r"\bsub[- ]?agent .{0,20}outside .{0,20}workspace\b"]},
    {"key": "unlawful_activity", "title": "Performing unlawful activity",
     "patterns": [r"\bunlawful\b", r"\billegal\b", r"\bfraud(ulent)?\b", r"\bmoney laundering\b"]},
    {"key": "unauthorised_testing", "title": "Testing systems without authorisation",
     "patterns": [r"\bunauthori[sz]ed (testing|access|pentest)\b",
                  r"\bpenetration test\b.{0,30}\bwithout (authori|permission)\b",
                  r"\bhack into\b", r"\bexploit .{0,20}without permission\b"]},
]


# Compile once at import time.
for _rule in HARD_BOUNDARY_RULES:
    _rule["_compiled"] = [re.compile(p, re.IGNORECASE) for p in _rule["patterns"]]


COVERAGE_LIMITATIONS = (
    "Deterministic keyword/regex detection over the provided text and structured "
    "fields only. It detects textual SIGNALS of the Design section 6 hard-boundary "
    "categories; it does NOT perform semantic intent analysis, does not evaluate an "
    "action's true real-world effect, and may miss novel phrasings (false negatives) "
    "or over-flag innocuous matches (false positives). A match means the action "
    "MUST be paused for human review, not that a violation is certain. Detection of "
    "spend/budget breaches that depend on live numeric budget state is signal-only "
    "here and must be confirmed against the real budget by the caller."
)


def _gather_text(
    text: Optional[str],
    action: Optional[str],
    metadata: Optional[Dict[str, Any]],
) -> str:
    """Flatten the inspectable input into a single lowercased blob for scanning."""
    parts: List[str] = []
    if text:
        parts.append(str(text))
    if action:
        parts.append(str(action))
    if metadata:
        for k, v in metadata.items():
            parts.append(f"{k}={v}")
    return "\n".join(parts)


def detect_hard_boundaries(
    text: Optional[str] = None,
    action: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Inspect real input and report which hard boundaries were detected.

    Returns a dict with:
      - detected: list of {key, title, matched_patterns}
      - rules_checked: list of every boundary rule key that was evaluated
      - requires_pause: True if any boundary matched
      - highest_severity: "critical" if any match else "none"
      - coverage_limitations: honest statement of what this detector can/can't do
      - input_inspected: which inputs were actually present (no fabrication)
    """
    blob = _gather_text(text, action, metadata)
    detected: List[Dict[str, Any]] = []
    rules_checked: List[str] = []

    for rule in HARD_BOUNDARY_RULES:
        rules_checked.append(rule["key"])
        if not blob:
            continue
        matched = [c.pattern for c in rule["_compiled"] if c.search(blob)]
        if matched:
            detected.append({
                "key": rule["key"],
                "title": rule["title"],
                "matched_patterns": matched,
            })

    return {
        "detected": detected,
        "detected_count": len(detected),
        "rules_checked": rules_checked,
        "rules_checked_count": len(rules_checked),
        "requires_pause": len(detected) > 0,
        "highest_severity": "critical" if detected else "none",
        "coverage_limitations": COVERAGE_LIMITATIONS,
        "input_inspected": {
            "text": bool(text),
            "action": bool(action),
            "metadata_keys": sorted(list(metadata.keys())) if metadata else [],
        },
    }
