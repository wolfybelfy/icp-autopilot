# -*- coding: utf-8 -*-
"""
ICP smart-play core — VERBATIM COPY (do not diverge) of the canonical logic.

PROVENANCE: copied unchanged from
  ../pipeline/build_icp_reports.py   (the canonical company-level generator)
Specifically these symbols and their line numbers at time of copy:
  ICP_INDUSTRY_KW   build_icp_reports.py:64-71
  norm_domain       build_icp_reports.py:74-78
  min_employees     build_icp_reports.py:80-88
  emp_band          build_icp_reports.py:90-105
  li_url            build_icp_reports.py:117-120
  industry_is_icp   build_icp_reports.py:122-125
  zi_industry_all   build_icp_reports.py:127-138
  zi_funding        build_icp_reports.py:140-147
  coalesce          build_icp_reports.py:149-152
  REASON_*          build_icp_reports.py:276-278
  icp_eval          build_icp_reports.py:280-296

WHY A COPY (not an import): the parent CLAUDE.md forbids editing the original
generators, and they are top-level scripts that run argparse + load files at import
time (not importable as a clean module). Copying the pure functions keeps this
subsystem standalone while guaranteeing identical ICP semantics. If the canonical
logic ever changes, re-sync this file — it must stay byte-identical in behaviour.

ICP RULE:  industry-ICP AND (employees >= 1000 OR funding Series A-F+).
SMART-PLAY: the industry test scans EVERY classification a company carries
(all ZoomInfo doziIndustry tops+subs, Warmly industry+subIndustry), not just the
primary — so TCS/Accenture/HPE/Amazon qualify via a non-primary tech class.
Product type is NEVER inferred from a company name.
"""
import re

EMD = "—"  # em dash (U+2014), matches the v2 report wording

# Tech-industry keywords matched against EVERY industry classification a company carries.
ICP_INDUSTRY_KW = [
    "software", "saas", "security", "cyber", "network", "cloud", "computer",
    "information technology", "it service", "it services", "it consulting",
    "internet software", "internet & services", "internet services",
    "semiconductor", "technology hardware", "hardware", "telecommunication",
    "developer", "data infrastructure", "analytics software", "platform",
    "custom software", "it & services", "information services",
]


def norm_domain(s):
    if not s:
        return ""
    s = str(s).strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = s.split("/")[0]
    s = re.sub(r"^www\.", "", s)
    return s.strip(". ")


def min_employees(range_str=None, count=None):
    if isinstance(count, (int, float)) and count:
        return int(count)
    if not range_str:
        return None
    s = str(range_str).lower().replace(",", "")
    s = re.sub(r"(\d+(?:\.\d+)?)\s*k", lambda m: str(int(float(m.group(1)) * 1000)), s)
    nums = [int(float(x)) for x in re.findall(r"\d+", s)]
    if not nums:
        return None
    if "over" in s or "+" in s or "more" in s:
        return max(nums)
    return min(nums)


def emp_band(range_str=None, count=None):
    m = min_employees(range_str, count)
    if m is None:
        return ""
    if m < 11:     return "1-10"
    if m < 20:     return "11+"
    if m < 50:     return "20+"
    if m < 100:    return "50+"
    if m < 200:    return "100+"
    if m < 250:    return "200+"
    if m < 500:    return "250+"
    if m < 1000:   return "500+"
    if m < 5000:   return "1k+"
    if m < 10000:  return "5k+"
    if m < 50000:  return "10k+"
    if m < 100000: return "50k+"
    return "100k+"


def li_url(handle):
    if not handle:
        return ""
    handle = str(handle).strip()
    return handle if handle.startswith("http") else "https://www.linkedin.com/" + handle.lstrip("/")


def industry_is_icp(industry_texts):
    """industry_texts: iterable of industry/sub-industry strings (the smart-play scans ALL)."""
    blob = " ".join(t for t in industry_texts if t).lower()
    return bool(blob.strip()) and any(kw in blob for kw in ICP_INDUSTRY_KW)


def zi_industry_all(rec):
    """Return (primary_display, [all classification strings tops+subs, name+displayName])."""
    di = [d for d in (rec.get("doziIndustry") or []) if isinstance(d, dict)]
    prim = next((d.get("displayName") for d in di
                 if d.get("isPrimary") and "." not in (d.get("name") or "")), "")
    if not prim:
        prim = next((d.get("displayName") for d in di if d.get("isPrimary")), "")
    allc = []
    for d in di:
        for k in (d.get("displayName"), d.get("name")):
            if k:
                allc.append(k)
    return prim, allc


def zi_funding(rec):
    f = rec.get("funding") or []
    rounds = [r.get("round", "") for r in f if isinstance(r, dict)]
    # Series A through F+ (any letter A-F)
    has_round = any(re.search(r"series\s*[a-f]\b", (r or "").lower()) for r in rounds)
    recent_round = f[0].get("round", "") if f else ""
    recent_amt = f[0].get("amountIn000s", "") if f else ""
    return has_round, recent_round, recent_amt


def coalesce(*vals):
    for v in vals:
        if v not in (None, ""):
            return v
    return ""


# v2 reason wording (em-dash U+2014) — aligned to the canonical reports.
REASON_RED    = "Industry & Size/Funding not ICP"
REASON_ORANGE = f"Right Size/Funding {EMD} Wrong Industry"
REASON_YELLOW = f"Right Industry {EMD} Emp/Funding Below Threshold"


def icp_eval(ind_all, emp_min, has_round, recent_round):
    ind = industry_is_icp(ind_all)
    size = (emp_min or 0) >= 1000
    fund = bool(has_round)
    is_icp = ind and (size or fund)
    if size:
        qual = "Emp 1k+"
    elif fund:
        qual = f"Funding {recent_round}" if recent_round else "Funding Series A-F+"
    else:
        qual = ""
    if is_icp:
        reason = ""
    elif ind and not (size or fund):
        reason = REASON_YELLOW
    elif (size or fund) and not ind:
        reason = REASON_ORANGE
    else:
        reason = REASON_RED
    return ind, size, fund, is_icp, qual, reason

# Re-copied unchanged into ICP-Autopilot 2026-07-20.
