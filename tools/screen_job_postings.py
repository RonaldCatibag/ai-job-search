#!/usr/bin/env python3
"""Screen a CSV of job postings for remote DevOps/SRE/Platform fit. No applications are submitted."""
import argparse
import csv
import sys
from pathlib import Path

FLOOR = 40200
TARGET = 80400
STRETCH = 110000
ROLES = ('devops', 'site reliability', 'sre', 'platform engineer', 'platform engineering')
REMOTE = ('remote', 'fully remote', 'distributed')
COUNTRIES = ('philippines', 'philippine', 'worldwide', 'global', 'anywhere')
EXCLUDED_EMPLOYERS = ('tookitaki',)


def annual(value, period):
    try:
        amount = float(value.replace(',', '').replace('$', '').strip())
    except (ValueError, AttributeError):
        return None
    period = period.strip().lower()
    if period in ('year', 'yearly', 'annual', 'annually', 'per year', 'yr'):
        return amount
    if period in ('month', 'monthly', 'per month', 'mo'):
        return amount * 12
    if period in ('hour', 'hourly', 'per hour', 'hr'):
        return amount * 2080
    return None


def screen(row):
    title = row.get('title', '').strip()
    company = row.get('company', '').strip()
    if any(name in company.casefold() for name in EXCLUDED_EMPLOYERS):
        return 'SKIP', ['Excluded employer: current employer; keep job search confidential'], None
    workplace = row.get('workplace_type', '').lower()
    countries = row.get('eligible_countries', '').lower()
    reasons = []
    if not any(x in title.lower() for x in ROLES):
        return 'SKIP', ['Outside DevOps/SRE/Platform targets'], None
    if not any(x in workplace or x in title.lower() for x in REMOTE):
        return 'SKIP', ['Remote status is not confirmed'], None
    if countries and not any(x in countries for x in COUNTRIES):
        return 'SKIP', ['Hiring locations do not include Philippines/worldwide'], None
    if not countries:
        reasons.append('Verify remote hiring eligibility from the Philippines')
    if row.get('salary_currency', '').strip().upper() not in ('USD', 'US$', '$'):
        reasons.append('Salary currency is missing or not USD; convert before ranking')
        return 'REVIEW', reasons, None
    period = row.get('salary_period', '')
    low = annual(row.get('salary_min', ''), period)
    high = annual(row.get('salary_max', ''), period)
    if low is None and high is None:
        reasons.append('Salary undisclosed; verify it meets USD 40,200/year floor')
        return 'REVIEW', reasons, None
    top = high if high is not None else low
    bottom = low if low is not None else high
    if top < FLOOR:
        return 'SKIP', [f'Maximum USD {top:,.0f}/year is below USD 40,200 floor'], top
    if bottom < FLOOR:
        reasons.append('Range begins below floor; confirm likely offer can meet floor')
    if top >= STRETCH:
        reasons.append('Range reaches USD 110,000/year stretch target')
    elif top >= TARGET:
        reasons.append('Range reaches USD 80,400/year preferred target')
    else:
        reasons.append('Meets floor, below preferred target')
    if not row.get('skills', '').strip():
        reasons.append('Compare requirements against verified resume profile')
    review = any(x.lower().startswith(('verify', 'confirm', 'compare', 'salary currency')) for x in reasons)
    return ('REVIEW' if review else 'MATCH'), reasons, top


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv_file', type=Path, help='CSV export of job postings')
    args = parser.parse_args()
    try:
        with args.csv_file.open(newline='', encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
    except OSError as exc:
        print(f'Cannot read {args.csv_file}: {exc}', file=sys.stderr)
        return 2
    for row in rows:
        verdict, reasons, top = screen(row)
        salary = f' up to USD {top:,.0f}/year' if top is not None else ''
        print(f'[{verdict}] {row.get("title", "Untitled role")} - {row.get("company", "Unknown company")}{salary}')
        if row.get('url'):
            print(f'  {row["url"]}')
        for reason in reasons:
            print(f'  - {reason}')
    if not rows:
        print('No postings found.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
