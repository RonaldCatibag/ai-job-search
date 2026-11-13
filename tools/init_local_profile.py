#!/usr/bin/env python3
"""Create missing local configuration from safe templates; never overwrite it."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    'CLAUDE.md': 'CLAUDE.md.example',
    '.claude/skills/job-application-assistant/01-candidate-profile.md': '01-candidate-profile.md.example',
    '.claude/skills/job-application-assistant/04-job-evaluation.md': '04-job-evaluation.md.example',
    '.claude/skills/job-scraper/search-queries.md': 'search-queries.md.example',
}

def initialize(root=ROOT):
    created = []
    for destination, template in PROFILES.items():
        target = root / destination
        source = root / 'templates/local-profile' / template
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open('x', encoding='utf-8') as stream:
                stream.write(source.read_text(encoding='utf-8'))
            created.append(destination)
        except FileExistsError:
            pass
    return created

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    for name in initialize():
        print('Created local configuration:', name)

if __name__ == '__main__':
    main()
