"""Ground profile values in the normalized CV text, without changing account identity."""
import re
import unicodedata
from hashlib import sha256
from pydantic import EmailStr, TypeAdapter, ValidationError


def skill_fingerprint(value):
    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    return sha256(normalized.encode()).hexdigest()


_TEXT_SECTIONS = {
    "skills": "skills", "technical skills": "skills", "technologies": "skills",
    "technology stack": "skills", "tools": "skills", "programming languages": "skills",
    "education": "education", "qualifications": "education",
    "experience": "experience", "work experience": "experience",
    "professional experience": "experience", "projects": "projects",
    "certifications": "certifications", "certificates": "certifications",
}


def deterministic_profile(text):
    """Copy bounded, explicitly labelled source entries into the existing profile shape."""
    profile = {field: [] for field in _PROFESSIONAL_FIELDS}
    profile.update(name=None, email=None, phone=None, summary=None)
    sources = []
    section = None
    continued = None
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip().lstrip("•*- ").strip()
        if not line:
            section = None
            continued = None
            continue
        label, separator, value = line.partition(":")
        if continued and not separator and not raw_line.lstrip().startswith(("•", "-", "*")):
            prior = profile["skills"][-1]
            if len(prior) + len(line) + 1 <= 400:
                profile["skills"][-1] = prior + " " + line
                sources[-1]["end_line"] = line_number
                continued = line.endswith(",")
                continue
        continued = None
        explicit = _TEXT_SECTIONS.get(label.strip().casefold())
        if explicit and (not separator or not value.strip()):
            section = explicit
            continue
        if separator:
            section = None
        field = explicit or section
        entry = value.strip() if separator else line
        if field and entry and len(entry) <= 400 and len(profile[field]) < 20 and entry not in profile[field]:
            profile[field].append(entry)
            sources.append({"id": len(sources), "field": field, "line": line_number})
            continued = field == "skills" and entry.endswith(",")
    profile["source_evidence"] = {"origin": "deterministic_text", "sources": sources}
    return profile


_EMAIL = re.compile(r"(?<![\w.+@-])[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+(?![\w@-])")
_EMAIL_TYPE = TypeAdapter(EmailStr)
_PHONE = re.compile(
    r"(?<![\w+])(?:\+(?=[1-9])|(?:phone|mobile|tel(?:ephone)?|contact number)[ \t]*:[ \t]*)"
    r"(?P<number>\+?\(?\d[\d(). \t-]{6,30}\d)(?![\w]|[(). \t-]*\d)",
    re.IGNORECASE,
)
_LABEL_NAME = re.compile(r"^[ \t]*(?:full[ \t]+)?name:[ \t]*(.+?)[ \t]*$", re.I | re.M)
_PROFESSIONAL_FIELDS = ("skills", "education", "experience", "projects",
                        "certifications", "languages", "other_information")


def _name_shaped(value):
    words = value.split()
    return 2 <= len(words) <= 5 and all(
        word[0].isupper() and word.replace("-", "").replace("'", "").replace("’", "").isalpha()
        for word in words
    )


def _identity(candidates, proposed):
    distinct = {value.casefold() for value, _ in candidates}
    if len(distinct) == 1:
        status, value = "verified", candidates[0][0]
    elif distinct:
        status, value = "ambiguous", None
    else:
        status, value = ("unsupported" if proposed else "missing"), None
    return value, {
        "status": status, "candidate_count": len(distinct),
        "spans": [span for _, span in candidates[:8]],
        "model_value_omitted": proposed is not None and (
            value is None or value.casefold() != str(proposed).casefold()
        ),
    }


def ground_profile(source, profile):
    emails = []
    for match in _EMAIL.finditer(source):
        try:
            value = _EMAIL_TYPE.validate_python(match[0])
        except ValidationError:
            continue
        emails.append((value, match.span()))

    phones = []
    for match in _PHONE.finditer(source):
        raw = match["number"]
        international = match[0].startswith("+") or raw.startswith("+")
        digits = re.sub(r"[^0-9]", "", raw)
        if len(digits) <= 15 and (
            (international and len(digits) >= 8 and digits[0] != "0")
            or (not international and len(digits) >= 9)
        ):
            span = match.span() if match[0].startswith("+") else match.span("number")
            phones.append((("+" if international else "") + digits, span))

    names = [(match[1], match.span(1)) for match in _LABEL_NAME.finditer(source)
             if _name_shaped(match[1])]
    if not names:
        for address, (start, _) in emails:
            end = source.rfind("\n", 0, start)
            begin = source.rfind("\n", 0, end) + 1 if end >= 0 else 0
            line = source[begin:end] if end >= 0 else ""
            value = line.strip()
            if _name_shaped(value) and value.split()[0].casefold() in re.split(
                r"[._+-]", address.split("@", 1)[0].casefold()
            ):
                offset = begin + len(line) - len(line.lstrip())
                names.append((value, (offset, offset + len(value))))
    if not names:
        first = re.search(r"[^\s][^\n]*", source)
        if first and profile["name"] and first[0].strip() == profile["name"] and _name_shaped(profile["name"]):
            names.append((profile["name"], (first.start(), first.start() + len(profile["name"]))))

    evidence = {}
    for key, candidates in (("name", names), ("email", emails), ("phone", phones)):
        profile[key], evidence[key] = _identity(candidates, profile[key])
    identity_spans = [span for _, span in names + emails + phones]

    for key in _PROFESSIONAL_FIELDS:
        values, spans = [], []
        rejected = set()
        for value in profile[key]:
            words = value.split()
            if words:
                pattern = r"(?<!\w)" + r"\s+".join(map(re.escape, words)) + r"(?!\w)"
                match = next((
                    occurrence for occurrence in re.finditer(pattern, source, re.IGNORECASE)
                    if not any(
                        occurrence.start() < end and start < occurrence.end()
                        for start, end in identity_spans
                    )
                ), None)
                if match:
                    values.append(" ".join(words))
                    spans.append(match.span())
                    continue
            if key == "skills":
                for part in re.split(r"[,;|•:]", value):
                    part = part.strip().rstrip(".")
                    if part and len(part) <= 200:
                        rejected.add(skill_fingerprint(part))
        omitted = len(profile[key]) - len(values)
        profile[key] = values
        evidence[key] = {
            "status": "verified" if values else ("unsupported" if omitted else "missing"),
            "spans": spans, "omitted_count": omitted,
        }
        if key == "skills":
            evidence[key]["rejected_skill_fingerprints"] = sorted(rejected)
    evidence["summary"] = {"status": "unverified_summary" if profile["summary"] else "missing"}
    return profile, evidence
