# -*- coding: utf-8 -*-
"""Person-level ICP (persona) gate.

Company fit lives in the FROZEN icp_core / icp_check. This module decides whether the
PERSON is a target buyer - which icp_core never did, so an engineer at a big tech company
slipped straight through to a draft (the 2026-07-21 Kyle Morrison case). Kept OUT of
icp_core so that file stays a verbatim copy.

Rule (2026-07-22, per operator). FIT if and only if the person is NOT in an excluded
role AND is one of:
  * Marketing family, Manager level or above - Marketing Manager, Head of Demand Gen,
    Content Manager, VP Marketing, CMO, Growth Lead, Product Marketing Manager, ...
  * Product management, Senior level or above  - Senior/Principal/Group/Lead PM,
    Director/VP of Product, CPO. Plain "Product Manager" and below do NOT qualify.
Everything else - engineers, IT, security, data eng, sales/brokers/realtors, risk,
customer service/support/success, finance, HR, legal, procurement, and too-junior
individual contributors (coordinator/specialist/associate/analyst/intern) - is not a
target, no matter how good the company is.
"""
import re

# Roles that ALWAYS disqualify, even if "marketing" also appears in the title.
_ALWAYS_EXCLUDE = [
    "engineer", "engineering", "developer", "devops", "sre", "site reliability",
    "architect", "programmer", "broker", "realtor", "real estate",
    "account executive", "account exec", "bdr", "sdr", "salesperson",
    "sales manager", "sales director", "sales rep", "sales lead", "sales associate",
    "head of sales", "vp sales", "vp of sales", "inside sales", "field sales",
]
# Roles that disqualify UNLESS the title is genuinely marketing (e.g. "marketing ops").
_SOFT_EXCLUDE = [
    "information technology", "it manager", "it support", "it director", "it lead",
    "sysadmin", "system administrator", "network", "helpdesk", "help desk",
    "security", "infosec", "cyber", "data engineer", "data scientist", "database",
    "ml engineer", "machine learning engineer",
    "risk", "compliance", "audit", "underwriting", "legal", "counsel", "attorney",
    "paralegal", "customer service", "customer support", "customer success",
    "technical support", "client service", "finance", "accounting", "accountant",
    "controller", "treasurer", "bookkeeper", "human resources", "recruiter",
    "recruiting", "talent acquisition", "people operations", "procurement",
    "purchasing", "supply chain", "warehouse", "logistics", "facilities",
    "receptionist", "nurse", "physician", "clinical", "pharmacist",
]
_MARKETING = [
    "marketing", "demand gen", "demand generation", "growth", "brand", "content",
    "abm", "account-based", "account based", "communications", "marcom", "comms",
    "advertising", "ads", "paid media", "paid social", "paid search", "campaign",
    "digital marketing", "performance marketing", "lifecycle", "field marketing",
    "product marketing", "seo", "sem", "go-to-market", "gtm", "cmo",
    "revenue marketing",
]
_PRODUCT = [
    "product manager", "product management", "product owner", "product lead",
    "head of product", "director of product", "vp product", "vp of product",
    "chief product", "cpo",
]
# Seniority signals.
_SENIOR_MGMT = {"c level exec", "vp level exec", "director", "board member",
                "senior manager"}
_MANAGER_MGMT = _SENIOR_MGMT | {"manager"}
_SENIOR_TITLE = ["chief", "cmo", "cro", "cgo", "cpo", "ceo", "founder", "co-founder",
                 "president", "vp", "vice president", "svp", "evp", "head of",
                 "director", "senior manager", "sr manager", "senior director"]
_MANAGER_TITLE = ["manager", "head of", "lead", "director", "vp", "vice president",
                  "chief", "founder", "president"]
_SENIOR_PRODUCT = ["senior", "sr ", "sr.", "principal", "staff", "group", "lead",
                   "head", "director", "vp", "vice president", "chief", "cpo"]
_JUNIOR = ["coordinator", "specialist", "associate", "analyst", "assistant", "intern",
           "trainee", "apprentice", "representative", "clerk", "junior", "entry level"]


def _compile(words):
    # word-boundary match so "sales" never fires on "salesforce", "engineer" never on
    # "reengineering", etc. Keywords may contain spaces, hyphens, dots.
    parts = [re.escape(w.strip()) for w in words if w.strip()]
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(parts) + r")(?![a-z0-9])", re.I)


_RX_ALWAYS = _compile(_ALWAYS_EXCLUDE)
_RX_SOFT = _compile(_SOFT_EXCLUDE)
_RX_MARKETING = _compile(_MARKETING)
_RX_PRODUCT = _compile(_PRODUCT)
_RX_SENIOR_TITLE = _compile(_SENIOR_TITLE)
_RX_MANAGER_TITLE = _compile(_MANAGER_TITLE)
_RX_SENIOR_PRODUCT = _compile(_SENIOR_PRODUCT)
_RX_JUNIOR = _compile(_JUNIOR)


def person_fit(person):
    """person: dict with any of title/jobTitle, job_function/jobFunction,
    management_level/managementLevel/seniority. Returns {"is_fit": bool, "reason": str}."""
    title = str(person.get("title") or person.get("jobTitle") or "")
    func = str(person.get("job_function") or person.get("jobFunction") or "")
    level = str(person.get("management_level") or person.get("managementLevel")
                or person.get("seniority") or "").lower()
    text = f"{title} {func}".strip().lower()
    if not text:
        return {"is_fit": False, "reason": "no_title"}

    is_marketing = bool(_RX_MARKETING.search(text))
    is_product = bool(_RX_PRODUCT.search(text))

    if _RX_ALWAYS.search(text):
        return {"is_fit": False, "reason": "excluded_role"}
    if _RX_SOFT.search(text) and not is_marketing:
        return {"is_fit": False, "reason": "excluded_role"}

    senior = (level in _SENIOR_MGMT) or bool(_RX_SENIOR_TITLE.search(text))
    junior = bool(_RX_JUNIOR.search(text)) and not senior
    manager_plus = (not junior) and (
        senior or (level in _MANAGER_MGMT) or bool(_RX_MANAGER_TITLE.search(text)))

    if is_marketing:
        if manager_plus:
            return {"is_fit": True, "reason": "marketing_manager+"}
        return {"is_fit": False, "reason": "marketing_below_manager"}
    if is_product:
        if (not junior) and bool(_RX_SENIOR_PRODUCT.search(text)):
            return {"is_fit": True, "reason": "product_senior+"}
        return {"is_fit": False, "reason": "product_below_senior"}
    return {"is_fit": False, "reason": "not_marketing_or_product"}
