#!/usr/bin/env python3
"""Bulk article quality fixer for Home Organization Ideas."""

from __future__ import annotations
import argparse, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = ROOT / 'content' / 'posts'
REPORT_PATH = ROOT / 'reports' / 'article-fix-report.md'

FAQ_PATTERNS = [
    (re.compile(r'How should I start organizing (.+?) ideas\\?', re.I), r'What should I do first when organizing \\1?'),
    (re.compile(r'What are the best ways to organize (.+?) ideas\\?', re.I), r'How do I organize \\1?'),
    (re.compile(r'What is the best way to organize (.+?) ideas\\?', re.I), r'How do I organize \\1?'),
    (re.compile(r'What are some organizing (.+?) ideas\\?', re.I), r'What are some practical ways to organize \\1?'),
    (re.compile(r'How can I organize (.+?) ideas\\?', re.I), r'How can I organize \\1?'),
]
REPEATED_WORD = re.compile(r'\\b([A-Za-z][A-Za-z\'-]*)\\s+\\1\\b', re.I)
MEASUREMENT = re.compile(r'\\b\\d+(?:\\.\\d+)?\\s*(?:×|x|X|by)\\s*\\d+(?:\\.\\d+)?\\s*(?:ft|feet|foot|sq\\s*ft|square feet)?\\b', re.I)
H2 = re.compile(r'^##\\s+(.+?)\\s*$', re.M)
IMAGE = re.compile(r'!\\[([^\\]]*)\\]\\(([^)]+)\\)')
STOPWORDS = {'the','a','an','and','or','to','for','of','in','on','with','your','you','is','are','how','what','can','do','ideas','best','ways','way','organize','organization','organizing','small'}

def tokens(text):
    return {w for w in re.findall(r'[a-z0-9]+', text.lower()) if w not in STOPWORDS and len(w) > 2}

def h2_similarity(a, b):
    aa, bb = tokens(a), tokens(b)
    return len(aa & bb) / len(aa | bb) if aa and bb else 0.0

def fix_deterministic(text):
    changes = []
    for pattern, replacement in FAQ_PATTERNS:
        text, n = pattern.subn(replacement, text)
        if n: changes.append(f'FAQ wording: {n}')
    text, n = REPEATED_WORD.subn(lambda m: m.group(1), text)
    if n: changes.append(f'repeated words: {n}')
    return text, changes

def inspect_article(path, apply):
    original = path.read_text(encoding='utf-8')
    fixed, changes = fix_deterministic(original)
    h2s = H2.findall(fixed)
    duplicate_h2s = []
    for i, left in enumerate(h2s):
        for right in h2s[i+1:]:
            score = h2_similarity(left, right)
            if score >= 0.65: duplicate_h2s.append((left, right, score))
    measurements = sorted(set(MEASUREMENT.findall(fixed)))
    measurement_flag = len(measurements) >= 2
    image_flags = []
    for alt, src in IMAGE.findall(fixed):
        if not alt.strip(): image_flags.append(f'empty alt: {src}')
        else: image_flags.append(f'review alt vs image: {alt[:100]} -> {src}')
    if apply and fixed != original: path.write_text(fixed, encoding='utf-8')
    return {'file': path.name, 'fixed': changes, 'h2': duplicate_h2s, 'measurements': measurements, 'measurement_flag': measurement_flag, 'images': image_flags}

def build_report(rows):
    lines = ['# Bulk Article Fix Report','',f'- Articles scanned: **{len(rows)}**',f'- Articles changed automatically: **{sum(bool(r["fixed"]) for r in rows)}**','- H2 duplicates: **review only**','- Alt/image mismatch: **review only**','- Conflicting measurements: **review only**','', '| # | Article | Issues | Fixed | Needs Review |','|---:|---|---|---|---|']
    for i, r in enumerate(rows, 1):
        issues=[]; review=[]
        if r['h2']: issues.append(f'H2 similarity x{len(r["h2"])}'); review.append('H2')
        if r['measurement_flag']: issues.append(f'measurements x{len(r["measurements"])}'); review.append('measurements')
        if r['images']: issues.append(f'images x{len(r["images"])}'); review.append('alt/image')
        if r['fixed']: issues.extend(r['fixed'])
        lines.append(f'| {i} | {r["file"]} | {"; ".join(issues) or "-"} | {"Yes" if r["fixed"] else "No"} | {"; ".join(review) or "No"} |')
    lines += ['', '## Human-review details', '']
    for r in rows:
        if not (r['h2'] or r['measurement_flag'] or r['images']): continue
        lines.append(f'### {r["file"]}')
        for a,b,score in r['h2']: lines.append(f'- H2 similarity {score:.2f}: {a} <-> {b}')
        if r['measurement_flag']: lines.append('- Measurements: ' + ', '.join(r['measurements']))
        for item in r['images']: lines.append(f'- {item}')
        lines.append('')
    return '\n'.join(lines)+'\n'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='report only; do not modify posts')
    args=parser.parse_args()
    paths=sorted(p for p in POSTS_DIR.glob('*.md') if p.is_file())
    rows=[inspect_article(p, apply=not args.check) for p in paths]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(build_report(rows), encoding='utf-8')
    print(f'Scanned {len(rows)} articles')
    print(f'Automatic fixes: {sum(len(r["fixed"]) for r in rows)}')
    print(f'Articles needing human review: {sum(bool(r["h2"] or r["measurement_flag"] or r["images"]) for r in rows)}')
    print(f'Report: {REPORT_PATH}')

if __name__ == '__main__': raise SystemExit(main())