#!/usr/bin/env python3
"""Regenerate test/fixtures/docs/brief.pdf, the PDF twin of brief.html (needs PyMuPDF)."""
import os

import fitz  # PyMuPDF

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'docs', 'brief.pdf')

PAGES = [
    ('Project brief', [
        'This document stands in for a deliverable sent to a client.',
        'Its PDF twin opens first in the review, as pages, because the',
        'PDF is what the reader receives.',
        '',
        'Scope: three pages, one form and a price list. Every page is',
        'reviewed on a desktop and a phone before it goes out.',
    ]),
    ('Timeline', [
        'A first draft in week one, a reviewed draft in week two, and',
        'the handover once every open note is closed or answered.',
    ]),
]

doc = fitz.open()
for title, lines in PAGES:
    page = doc.new_page(width=595, height=842)      # A4 in points
    page.insert_text((72, 110), title, fontsize=28, fontname='helv')
    y = 160
    for line in lines:
        page.insert_text((72, y), line, fontsize=13, fontname='tiro')
        y += 22
doc.set_metadata({'title': 'Project brief', 'creator': 'review-page test fixtures'})
doc.save(OUT, garbage=4, deflate=True)
print(OUT)
