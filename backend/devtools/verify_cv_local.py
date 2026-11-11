"""Explicit synthetic-only local Ollama check. Never contacts n8n or sends email."""
import asyncio
import json
import pathlib
import sys
import tempfile

import pymupdf

from talentforge.config import get_settings
from talentforge.cv_text_extraction import extract_cv_text_sandboxed
from talentforge.cv_automation import extract_profile


async def main():
    output=pathlib.Path(sys.argv[1]).resolve();output.mkdir(parents=True,exist_ok=True)
    settings=get_settings()
    assert not settings.cv_automation_enabled and not settings.n8n_auto_dispatch_enabled
    with tempfile.TemporaryDirectory(prefix='talentforge-synthetic-cv-') as tmp:
        settings.cv_upload_dir=pathlib.Path(tmp)
        name='a'*32+'.pdf'
        with pymupdf.open() as doc:
            page=doc.new_page()
            page.insert_text((72,72),'Alex Example\nalex@example.com\nSkills: Python, FastAPI, PostgreSQL\nEducation: BSc Computer Science, Example University, 2024\nExperience: Software Engineering Intern, Example Labs, 2024-2025\nProjects: Built a recruitment API using FastAPI and PostgreSQL\nLanguages: English\nCertification: Python Fundamentals\nSynthetic fictional CV for authorized testing only.')
            doc.save(pathlib.Path(tmp)/name)
        result=extract_cv_text_sandboxed(name)
        assert result.extraction_status=='success'
        profile=await extract_profile(result.text)
        assert profile.name and 'Alex' in profile.name and profile.email=='alex@example.com'
        assert any('python' in x.lower() for x in profile.skills)
        assert profile.education and profile.experience and profile.projects
        (output/'synthetic-cv.pdf').write_bytes((pathlib.Path(tmp)/name).read_bytes())
        (output/'synthetic-profile.json').write_text(profile.model_dump_json(indent=2))
        report={'sample':'generated fictional CV approved by user','pdf_extraction':'PASS','real_ollama':'PASS','model':'llama3.2:3b','strict_schema':'PASS','expected_factual_fields':'PASS','emails_sent':0,'n8n_calls':0}
        (output/'local-ollama-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))


if __name__=='__main__':asyncio.run(main())
