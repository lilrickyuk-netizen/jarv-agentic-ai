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


# =========================================================================== #
# Repair 10: structured, deterministic action evaluation
#
# evaluate_action() is the detector the central tool-permission layer calls
# BEFORE any tool executes. It composes, in strict precedence order:
#   1. protected-location paths (banking/crypto/passwords/keys fragments),
#   2. workspace scope (out-of-scope access/writes),
#   3. command risks (destructive/privileged, pipe-to-shell, unknown
#      executables, global installs) via the same classifier the runtime uses,
#   4. the Design section 6 hard-boundary text rules above,
#   5. high-confidence secret material in command/content/payload,
#   6. residual command classification (risky / gated build / gated install).
#
# It returns ONE structured decision (never raises) and redacts secrets in
# everything it emits, so its output is safe to persist, log, or return from
# an API. Outcomes are honest: "blocked" means never-runnable on this path;
# "requires_approval" means pause ONLY this action for Richard.
# =========================================================================== #

# Risk levels for structured decisions.
RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"
RISK_CRITICAL = "critical"

# High-confidence secret-material patterns (a strict subset of the redaction
# patterns in app.core.security): these almost never appear in legitimate
# non-secret tool input, so they gate for approval rather than only redact.
_SECRET_MATERIAL_PATTERNS = [
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # JWT
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s:/@]+@[^\s]+"),  # creds-in-URL
]

# Executable suffixes that indicate running a binary/script directly. Combined
# with "./", ".\" launch forms these are the "unknown executable" hard boundary.
_EXECUTABLE_SUFFIXES = (".exe", ".msi", ".bat", ".cmd", ".com", ".scr",
                        ".bin", ".run", ".app", ".ps1", ".vbs")

_PIPE_TO_SHELL_RE = re.compile(r"\|\s*(ba)?sh\b|\|\s*powershell\b|\|\s*pwsh\b", re.IGNORECASE)


def _contains_secret_material(*texts: Optional[str]) -> bool:
    for t in texts:
        if not t:
            continue
        for pat in _SECRET_MATERIAL_PATTERNS:
            if pat.search(str(t)):
                return True
    return False


def _is_unknown_executable(command: str) -> bool:
    """First token launches a local/unknown executable directly."""
    stripped = (command or "").strip()
    if not stripped:
        return False
    first = stripped.split()[0].strip("\"'").lower()
    if first.startswith("./") or first.startswith(".\\"):
        return True
    return first.endswith(_EXECUTABLE_SUFFIXES)


def _decision(
    *,
    allowed: bool,
    requires_approval: bool,
    boundary_type: Optional[str],
    boundary_reason: Optional[str],
    risk_level: str,
    safe_alternative: Optional[str],
    display: Optional[str],
    audit_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    # Redaction must never break detection; fall back to a coarse marker.
    try:
        from app.core.security import redact_text
        redacted_display = redact_text(display or "")[:500]
        redacted_reason = redact_text(boundary_reason or "") or None
    except Exception:  # noqa: BLE001
        redacted_display = "[REDACTED]"
        redacted_reason = boundary_reason
    return {
        "allowed": allowed,
        "requires_approval": requires_approval,
        "boundary_type": boundary_type,
        "boundary_reason": redacted_reason,
        "risk_level": risk_level,
        "safe_alternative": safe_alternative,
        "redacted_display": redacted_display,
        "audit_metadata": audit_metadata,
    }


def evaluate_action(
    *,
    tool_id: str,
    command: Optional[str] = None,
    target_path: Optional[str] = None,
    action_description: Optional[str] = None,
    content: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    workspace_scope_required: bool = False,
    path_in_scope: Optional[bool] = None,
    allow_build: bool = True,
    allow_install: bool = True,
) -> Dict[str, Any]:
    """Deterministically evaluate one tool action against the hard boundaries.

    ``path_in_scope`` is the caller's real scope verdict for ``target_path``
    (e.g. fs_inspector.host_to_container(...) is not None); None means the
    caller does not enforce path scope on this runtime path.

    Returns the structured decision dict described in the module header. This
    never raises and never returns a fabricated "allowed" for an unchecked
    category — every check that ran is named in ``audit_metadata.checks_run``.
    """
    from app.core.workspaces.fs_inspector import _is_banned, classify_command

    checks_run: List[str] = []
    display = command or action_description or target_path or tool_id
    meta: Dict[str, Any] = {"tool_id": tool_id, "checks_run": checks_run}

    # 1) Protected locations (banking / crypto / wallets / passwords / keys).
    checks_run.append("protected_location_path")
    if target_path and _is_banned(target_path):
        return _decision(
            allowed=False, requires_approval=False,
            boundary_type="protected_location",
            boundary_reason=("Target path matches a hard-boundary protected location "
                             "(banking/crypto/passwords/keys); access is never allowed "
                             "on this path."),
            risk_level=RISK_CRITICAL,
            safe_alternative="Operate only on non-protected files inside the approved workspace.",
            display=display, audit_metadata=meta)

    # 2) Workspace scope (out-of-scope reads/writes are a hard boundary).
    checks_run.append("workspace_scope")
    if workspace_scope_required and path_in_scope is False:
        return _decision(
            allowed=False, requires_approval=False,
            boundary_type="out_of_scope_access",
            boundary_reason=("Target is outside the approved workspace root; "
                             "out-of-scope access is blocked."),
            risk_level=RISK_HIGH,
            safe_alternative="Use a path inside the approved workspace root.",
            display=display, audit_metadata=meta)

    cls: Optional[str] = None
    if command is not None:
        cls = classify_command(command)
        meta["command_classification"] = cls

        # 3a) Pipe-to-shell (named specifically; classifier also blocks it).
        checks_run.append("pipe_to_shell")
        if _PIPE_TO_SHELL_RE.search(command):
            return _decision(
                allowed=False, requires_approval=False,
                boundary_type="pipe_to_shell",
                boundary_reason="Piping downloaded/streamed content into a shell is never allowed.",
                risk_level=RISK_CRITICAL,
                safe_alternative=("Download to a workspace file first, inspect it, then run an "
                                  "approved build/test command."),
                display=display, audit_metadata=meta)

        # 3b) Unknown executables.
        checks_run.append("unknown_executable")
        if _is_unknown_executable(command):
            return _decision(
                allowed=False, requires_approval=False,
                boundary_type="unknown_executable",
                boundary_reason="Running unknown executable files is a hard boundary and is blocked.",
                risk_level=RISK_CRITICAL,
                safe_alternative=("Use a known interpreter/build tool (python3, node, npm, pytest) "
                                  "on source files inside the workspace."),
                display=display, audit_metadata=meta)

        # 3c) Destructive / privileged / global / chained commands.
        checks_run.append("destructive_command")
        if cls == "dangerous":
            return _decision(
                allowed=False, requires_approval=False,
                boundary_type="destructive_or_privileged_command",
                boundary_reason=("Command is destructive, privileged, global, or uses shell "
                                 "chaining/redirection; it is blocked by safety policy."),
                risk_level=RISK_CRITICAL,
                safe_alternative=("Run ONE simple read-only or build/test command (no &&, ;, |, >, "
                                  "sudo, rm, global installs) inside the approved workspace."),
                display=display, audit_metadata=meta)

    # 4) Hard-boundary TEXT rules. Always scanned on the action description;
    #    scanned on the command only when the command is not already classified
    #    as a known-safe form (safe/build/install), so benign commands like
    #    `npm install buy-button` are not topic-flagged.
    checks_run.append("hard_boundary_text_rules")
    scan_command = command if (cls not in ("safe", "build", "install")) else None
    text_result = detect_hard_boundaries(text=scan_command, action=action_description)
    meta["hard_boundary_rules_checked"] = text_result["rules_checked_count"]
    if text_result["detected"]:
        first = text_result["detected"][0]
        meta["hard_boundaries_detected"] = [d["key"] for d in text_result["detected"]]
        return _decision(
            allowed=False, requires_approval=True,
            boundary_type=first["key"],
            boundary_reason=(f"Hard boundary detected: {first['title']}. The action is paused "
                             "for Richard's decision (not abandoned)."),
            risk_level=RISK_CRITICAL,
            safe_alternative="Continue safe parallel work while this action waits for approval.",
            display=display, audit_metadata=meta)

    # 5) High-confidence secret material (keys/tokens/credentials) in the input.
    checks_run.append("secret_material")
    payload_text = None
    if payload:
        try:
            import json as _json
            payload_text = _json.dumps(payload)
        except Exception:  # noqa: BLE001
            payload_text = str(payload)
    if _contains_secret_material(command, content, action_description, payload_text):
        return _decision(
            allowed=False, requires_approval=True,
            boundary_type="secret_material",
            boundary_reason=("Input contains secret material (key/token/credential). Handling "
                             "secrets requires Richard's approval; the value is redacted "
                             "everywhere it is recorded."),
            risk_level=RISK_HIGH,
            safe_alternative=("Reference the secret by name and let Richard supply it through "
                              "the boundary input flow instead of embedding the raw value."),
            display=display, audit_metadata=meta)

    # 6) Residual command gating: risky commands and policy-gated build/install.
    if command is not None:
        checks_run.append("command_approval_gate")
        if cls == "risky":
            return _decision(
                allowed=False, requires_approval=True,
                boundary_type="approval_required_command",
                boundary_reason=("Command is not in the approved safe/build/install command "
                                 "policy and requires approval before execution."),
                risk_level=RISK_MEDIUM,
                safe_alternative=("Use an approved read-only/build/test command, or request "
                                  "approval for exactly this command."),
                display=display, audit_metadata=meta)
        if cls == "build" and not allow_build:
            return _decision(
                allowed=False, requires_approval=True,
                boundary_type="build_requires_approval",
                boundary_reason="Build/test execution requires approval in this context.",
                risk_level=RISK_MEDIUM,
                safe_alternative="Request approval, or run a read-only inspection command.",
                display=display, audit_metadata=meta)
        if cls == "install" and not allow_install:
            return _decision(
                allowed=False, requires_approval=True,
                boundary_type="install_requires_approval",
                boundary_reason="Package install requires approval in this context.",
                risk_level=RISK_MEDIUM,
                safe_alternative="Request approval for this exact install command.",
                display=display, audit_metadata=meta)

    return _decision(
        allowed=True, requires_approval=False,
        boundary_type=None, boundary_reason=None,
        risk_level=RISK_LOW, safe_alternative=None,
        display=display, audit_metadata=meta)
