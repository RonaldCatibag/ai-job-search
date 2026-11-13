#!/usr/bin/env python3
"""Discover remote infrastructure jobs on configured public employer boards.

Writes timestamped result metadata and caches raw responses OUTSIDE the repository.
Does not submit applications, score fit, or mark jobs applied. Feed candidates to
scrape_state.py candidates, inspect selected posting details, then use store.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BOARDS = (
    ("Canonical", "greenhouse", "canonical"),
    ("3Cloud", "greenhouse", "3cloud"),
    ("Career Team Enterprises", "greenhouse", "cteph"),
    ("Supabase", "ashby", "supabase"),
    ("Kraken", "ashby", "kraken.com"),
)
ROLE = re.compile(r"devops|devsecops|site reliability|\bsre\b|platform engineer", re.I)
ALLOWED = re.compile(r"worldwide|global|philippines|\bAPAC\b", re.I)


def fetch_json(url, cache_dir, refresh=False):
    key = hashlib.sha256(url.encode()).hexdigest()
    cached = cache_dir / (key + ".json")
    if cached.exists() and not refresh and time.time() - cached.stat().st_mtime < 3600:
        return json.loads(cached.read_text(encoding="utf-8")), "cache"
    request = urllib.request.Request(url, headers={"User-Agent": "LocalRemoteJobSearch/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read(10_000_001)
        if len(body) > 10_000_000:
            raise ValueError("employer response exceeds 10 MB")
        data = json.loads(body)
    temporary = cached.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(cached)
    return data, "live"


def select_jobs(company, provider, board, jobs, cutoff, include_older=False):
    candidates, excluded = [], []
    for job in jobs:
        title = job.get("title", "").strip()
        if not ROLE.search(title) or "manager" in title.lower() or company.lower() == "tookitaki":
            continue
        location = job.get("location", "")
        if isinstance(location, dict):
            location = location.get("name", "")
        url = job.get("jobUrl", job.get("absolute_url", ""))
        published = job.get("publishedAt")  # Greenhouse updated_at is NOT a posting date.
        reason = None
        if not url or not ALLOWED.search(location) or not re.search(r"remote|home[ -]based", location, re.I):
            reason = "Philippines/worldwide remote eligibility not established from location"
        if published:
            try:
                posted = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if posted.tzinfo is None:
                    posted = posted.replace(tzinfo=timezone.utc)
                if posted < cutoff and not include_older:
                    reason = "published outside requested freshness window"
            except ValueError:
                published = None
        row = dict(company=company, title=title, location=location, url=url,
                   employer_country=None, employer_country_status="unverified",
                   job_country="Philippines" if re.search(r"\bPhilippines\b", location, re.I) else None,
                   hiring_region=location,
                   posted_date=published[:10] if published else None,
                   deadline=None, portal="employer-careers", source="websearch",
                   discovery_method="public_employer_api", provider=provider,
                   board=board, job_id=job.get("id"),
                   eligibility="review" if "APAC" in location and not re.search(r"global|worldwide|philippines", location, re.I) else "location supports Philippines or worldwide; verify full posting",
                   salary_status="unverified", fetched_at=datetime.now(timezone.utc).isoformat())
        if reason:
            row["exclusion_reason"] = reason
            excluded.append(row)
        else:
            candidates.append(row)
    return candidates, excluded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path.home()/"local-ai/cache/job-search")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--max-age-days", type=int, default=14)
    parser.add_argument("--include-older", action="store_true", help="include older listings still on an employer board; flag for freshness review")
    args = parser.parse_args()
    if args.max_age_days < 1:
        parser.error("--max-age-days must be positive")
    cache = args.cache_dir.expanduser().resolve()
    if cache.is_relative_to(ROOT):
        parser.error("raw API cache must be outside the repository")
    cache.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.max_age_days)
    report = dict(checked_at=datetime.now(timezone.utc).isoformat(), candidates=[], excluded=[], sources=[], errors=[])
    for company, provider, board in BOARDS:
        url = ("https://boards-api.greenhouse.io/v1/boards/"+board+"/jobs" if provider == "greenhouse" else "https://api.ashbyhq.com/posting-api/job-board/"+board)
        try:
            data, mode = fetch_json(url, cache, args.refresh)
            selected, excluded = select_jobs(company, provider, board, data.get("jobs", []), cutoff, args.include_older)
            report["candidates"].extend(selected)
            report["excluded"].extend(excluded)
            report["sources"].append(dict(company=company, url=url, retrieval=mode))
        except Exception as error:
            report["errors"].append(dict(company=company, error=str(error)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    candidates_path = args.out.with_name(args.out.stem+"-candidates.json")
    candidates_path.write_text(json.dumps(report["candidates"], ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(candidates=len(report["candidates"]), excluded=len(report["excluded"]), errors=report["errors"], report=str(args.out), candidates_file=str(candidates_path))))
    return 1 if len(report["errors"]) == len(BOARDS) else 0


if __name__ == "__main__":
    raise SystemExit(main())
