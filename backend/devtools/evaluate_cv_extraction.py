"""Evaluate the local extractor with fictional files. No upload or dispatch."""
import asyncio
import argparse
import io
import json
import tempfile
import time
import uuid
from pathlib import Path

import pymupdf
from docx import Document

from talentforge.config import get_settings
from talentforge.cv_automation import ScreeningFailure, extract_profile
from talentforge.cv_text_extraction import extract_cv_text_sandboxed


FIELDS = ("name", "email", "phone", "skills", "education", "experience", "projects")


def truth(name=None, email=None, phone=None, skills=(), education=(), experience=(), projects=()):
    return {
        key: [value] if isinstance(value, str) else list(value or ())
        for key, value in zip(FIELDS, (name, email, phone, skills, education, experience, projects))
    }


def lines(expected):
    return [value for key in FIELDS[:3] for value in expected[key]] + [
        f"{key.capitalize()}: {', '.join(expected[key])}" for key in FIELDS[3:] if expected[key]
    ]


def page(rows, x=50):
    return [(x, 60 + 14 * index, line) for index, line in enumerate(rows)]


def pdf(pages):
    with pymupdf.open() as document:
        for rows in pages:
            sheet = document.new_page()
            for x, y, line in rows:
                sheet.insert_text((x, y), line, fontsize=10)
        return document.tobytes()


def docx(expected, header=False):
    document = Document()
    rows = lines(expected)
    if header:
        document.sections[0].header.paragraphs[0].text = "\n".join(rows[:3])
        rows = rows[3:]
        document.add_table(rows=1, cols=1).cell(0, 0).text = rows.pop()
    for line in rows:
        document.add_paragraph(line)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def fixtures():
    a = truth("Alex Fictional", "alex.fixture@example.com", "+1 202-555-0101", ["Go", "SQL"],
              ["BSc Computer Science"], ["Backend Engineer at Alder Observatory"], ["Telescope Scheduler"])
    b = truth(skills=["Rust", "Docker"], experience=["Systems Technician at Birch Studio"],
              projects=["Sensor Monitor"])
    c = truth("Casey Fictional", "casey.fixture@example.com", "+1 202-555-0102", ["Python", "PostgreSQL"],
              ["MSc Data Science"], ["Data Analyst at Cedar Workshop"], ["Inventory Dashboard"])
    d = truth("Drew Fictional", "drew.fixture@example.com", skills=["Java"], education=["BSc Software Engineering"],
              experience=["Software Engineer at Dune Lab"], projects=["Harbor Simulator"])
    header = truth("Harper Fictional", "harper.fixture@example.com", "+1 202-555-0103",
                   skills=["Go"], projects=["Fixture Scheduler"])
    ambiguous = truth(skills=["Go"])
    filler = page(["The fictional archive contains generic background notes without new professional facts."] * 45)
    return [
        ("single_column", "pdf", pdf([page(lines(a))]), a),
        ("missing_fields", "docx", docx(b), b),
        ("two_column", "pdf", pdf([page(lines(c)[3:], 315) + page(lines(c)[:3])]), c),
        ("long_tail", "pdf", pdf([page(lines(d)[:-1]), filler, filler, filler, page(lines(d)[-1:])]), d),
        ("header_table", "docx", docx(header, header=True), header),
        ("ambiguous", "pdf", pdf([page([
            "Name: Riley Fictional", "Name: Morgan Fictional", "riley.fixture@example.com",
            "morgan.fixture@example.com", "+1 202-555-0104", "+1 202-555-0105", "Skills: Go",
        ])]), ambiguous),
    ]


def normalize(value, field):
    if field == "phone":
        return "".join(char for char in value if char.isdigit())
    return " ".join(value.casefold().split())


async def main(case_filter=None):
    with tempfile.TemporaryDirectory(prefix="fictional-cv-eval-") as folder:
        get_settings().cv_upload_dir = Path(folder)
        for case, ext, data, expected in fixtures():
            if case_filter and case != case_filter:
                continue
            ref = uuid.uuid4().hex + "." + ext
            (Path(folder) / ref).write_bytes(data)
            started = time.monotonic()
            parsed = await asyncio.to_thread(extract_cv_text_sandboxed, ref)
            parser_seconds = time.monotonic() - started
            text = parsed.text or ""
            raw_hits = {
                key: sum(normalize(value, key) in normalize(text, key) for value in expected[key])
                for key in FIELDS
            }
            layout = {}
            if case == "two_column":
                with pymupdf.open(stream=data, filetype="pdf") as document:
                    sorted_text = document[0].get_text("text", sort=True)
                layout = {
                    "stored_order_identity_first": text.strip().startswith(expected["name"][0]),
                    "coordinate_order_identity_first": sorted_text.strip().startswith(expected["name"][0]),
                    "coordinate_order_intact_facts": sum(
                        normalize(value, key) in normalize(sorted_text, key)
                        for key in FIELDS for value in expected[key]
                    ),
                    "coordinate_order_separate_name_line": expected["name"][0] in [
                        line.strip() for line in sorted_text.splitlines()
                    ],
                }
            print(json.dumps(dict(case=case, parser=parsed.extraction_status, parser_seconds=round(parser_seconds, 2),
                                  raw_hits=raw_hits, layout=layout)), flush=True)
            started = time.monotonic()
            try:
                profile = (await extract_profile(text)).model_dump()
            except ScreeningFailure as error:
                print(json.dumps(dict(case=case, model_error=str(error),
                                      model_seconds=round(time.monotonic() - started, 2))), flush=True)
                continue
            scores = {}
            for key in FIELDS:
                values = profile.get(key)
                values = values if isinstance(values, list) else [values] if values else []
                actual = {normalize(value, key) for value in values}
                wanted = {normalize(value, key) for value in expected[key]}
                scores[key] = dict(tp=len(actual & wanted), fp=len(actual - wanted),
                                   fn=len(wanted - actual), exact=actual == wanted)
            print(json.dumps(dict(case=case, model_seconds=round(time.monotonic() - started, 2),
                                  scores=scores, profile=profile)), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("single_column", "missing_fields", "two_column",
                                          "long_tail", "header_table", "ambiguous"))
    asyncio.run(main(parser.parse_args().case))
