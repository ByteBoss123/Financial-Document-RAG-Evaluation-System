"""
edgar_ingest.py

Fetches real SEC filings from the official EDGAR API (data.sec.gov, www.sec.gov)
and extracts clean text sections for indexing.

This module is the data layer of FinDocQA: it does NOT use any third-party
scraping service. It calls SEC's own public REST endpoints directly, which is
the legitimate, ToS-compliant way to pull filing data programmatically.

SEC requires a descriptive User-Agent header on every request (their fair-use
policy) -- set EDGAR_USER_AGENT in your environment before running, e.g.:

    export EDGAR_USER_AGENT="Amarnath Ganta aganta@gmu.edu FinDocQA research project"
"""

import os
import re
import time
import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("findocqa.ingest")

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:0>10}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{filename}"

DEFAULT_USER_AGENT = os.environ.get(
    "EDGAR_USER_AGENT",
    "FinDocQA research project contact@example.com",  # replace via env var before running
)

HEADERS = {"User-Agent": DEFAULT_USER_AGENT}

# A handful of well-known financial-sector CIKs (Central Index Key) to make
# this easy to demo without the user needing to look anything up themselves.
KNOWN_CIKS = {
    "BGC": "1094831",      # BGC Group, Inc.
    "JPM": "19617",        # JPMorgan Chase & Co.
    "GS": "886982",        # Goldman Sachs Group
    "MS": "895421",        # Morgan Stanley
    "ICE": "1571949",      # Intercontinental Exchange
}


@dataclass
class FilingSection:
    company: str
    cik: str
    form_type: str
    filed_date: str
    fiscal_period_end: Optional[str]
    section_name: str
    text: str
    source_url: str

    def to_dict(self):
        return asdict(self)


def _get(url: str, **kwargs) -> requests.Response:
    """GET with SEC's required rate limit (max ~10 req/sec) and retry."""
    for attempt in range(3):
        resp = requests.get(url, headers=HEADERS, timeout=20, **kwargs)
        if resp.status_code == 200:
            time.sleep(0.15)  # stay well under SEC's rate limit
            return resp
        if resp.status_code == 429:
            wait = 2 ** attempt
            logger.warning(f"Rate limited by SEC, backing off {wait}s")
            time.sleep(wait)
            continue
        resp.raise_for_status()
    raise RuntimeError(f"Failed to fetch {url} after retries")


def get_recent_filings(cik: str, form_type: str = "10-K", limit: int = 1) -> list[dict]:
    """
    Look up a company's recent filings of a given form type using SEC's
    official submissions API (data.sec.gov).
    """
    url = SEC_SUBMISSIONS_URL.format(cik=cik)
    resp = _get(url)
    data = resp.json()

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])

    results = []
    for i, form in enumerate(forms):
        if form == form_type:
            results.append({
                "company": data.get("name"),
                "cik": cik,
                "form_type": form,
                "accession_number": accession_numbers[i],
                "primary_document": primary_docs[i],
                "filed_date": filing_dates[i],
                "report_date": report_dates[i] if i < len(report_dates) else None,
            })
            if len(results) >= limit:
                break
    return results


def fetch_filing_html(cik: str, accession_number: str, primary_document: str) -> str:
    """Download the raw HTML of a filing's primary document directly from SEC."""
    accession_nodash = accession_number.replace("-", "")
    url = SEC_ARCHIVES_BASE.format(
        cik=cik.lstrip("0"), accession_nodash=accession_nodash, filename=primary_document
    )
    resp = _get(url)
    return resp.text, url


# Section headers we care about for a financial-QA use case. Real 10-Ks vary
# in exact wording, so we match loosely and take everything until the next
# "ITEM " heading.
SECTION_PATTERNS = {
    "risk_factors": r"item\s*1a\.?\s*risk\s*factors",
    "business": r"item\s*1\.?\s*business",
    "mdna": r"item\s*7\.?\s*management.?s\s*discussion",
    "market_risk": r"item\s*7a\.?\s*quantitative\s*and\s*qualitative",
}


def extract_sections(html: str) -> dict[str, str]:
    """
    Parse a 10-K/10-Q HTML doc and pull out the major narrative sections by
    locating ITEM headings. This is intentionally simple (regex over visible
    text) rather than depending on consistent HTML structure, since EDGAR
    filings have no standardized markup across filers.
    """
    soup = BeautifulSoup(html, "lxml")
    # Strip tables' inner whitespace noise but keep them as text blocks --
    # MD&A and Risk Factors are prose, so this is fine for those sections.
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    # Build a list of (start_index, section_key) for every heading we find,
    # in document order, then slice between consecutive matches.
    lower = text.lower()
    matches = []
    for key, pattern in SECTION_PATTERNS.items():
        for m in re.finditer(pattern, lower):
            matches.append((m.start(), key))
    matches.sort()

    sections = {}
    for idx, (start, key) in enumerate(matches):
        end = matches[idx + 1][0] if idx + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        # Keep the longest match per section key (heading sometimes repeats
        # in the table of contents with no real content following it)
        if key not in sections or len(chunk) > len(sections[key]):
            sections[key] = chunk
    return sections


def ingest_company(ticker: str, form_type: str = "10-K", out_dir: str = "data") -> list[FilingSection]:
    """
    End-to-end: resolve ticker -> CIK -> most recent filing -> download ->
    extract sections -> save as JSON records ready for indexing.
    """
    cik = KNOWN_CIKS.get(ticker.upper())
    if cik is None:
        raise ValueError(
            f"Unknown ticker {ticker}. Add its CIK to KNOWN_CIKS, or look it up "
            f"at https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={ticker}"
        )

    filings = get_recent_filings(cik, form_type=form_type, limit=1)
    if not filings:
        raise RuntimeError(f"No {form_type} filings found for {ticker}")

    filing = filings[0]
    html, source_url = fetch_filing_html(cik, filing["accession_number"], filing["primary_document"])
    sections = extract_sections(html)

    records = []
    for section_name, section_text in sections.items():
        if len(section_text) < 200:
            continue  # skip near-empty matches (likely a TOC reference, not real content)
        records.append(FilingSection(
            company=filing["company"],
            cik=cik,
            form_type=form_type,
            filed_date=filing["filed_date"],
            fiscal_period_end=filing.get("report_date"),
            section_name=section_name,
            text=section_text,
            source_url=source_url,
        ))

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    out_file = out_path / f"{ticker.upper()}_{form_type.replace('/', '')}_{filing['filed_date']}.json"
    with open(out_file, "w") as f:
        json.dump([r.to_dict() for r in records], f, indent=2)

    logger.info(f"Ingested {len(records)} sections for {ticker} -> {out_file}")
    return records


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    tickers = sys.argv[1:] if len(sys.argv) > 1 else list(KNOWN_CIKS.keys())
    for t in tickers:
        try:
            ingest_company(t)
        except Exception as e:
            logger.error(f"Failed to ingest {t}: {e}")
