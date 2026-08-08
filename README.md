# Course Copilot — Quickstart

## Setup
```bash
cd course-copilot
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...    # Windows: set ANTHROPIC_API_KEY=sk-ant-...
```

## Step 1: extract a syllabus
```bash
python scripts/extract_syllabus.py path/to/syllabus.pdf cs101 --course-name "Intro to CS"
```

This will:
1. Read the PDF/TXT/MD file
2. Send the raw text to Claude (Sonnet) with instructions to extract ONLY what's in the document
3. Validate the result against the syllabus.json schema
4. Write `courses/cs101/syllabus.json` (asking for confirmation first if the file already exists)

If extraction fails validation, nothing is written — you'll see the raw model output
and the specific validation errors so you can tell whether it's a prompt problem or
a messy source document.

## Test checklist before moving to Step 2 (ask.py)
- [ ] Run on a real syllabus PDF from one of your actual courses
- [ ] Check `courses/<id>/syllabus.json` by eye: are dates right? any hallucinated entries?
- [ ] Try a syllabus with an unusual format (table-based dates, no explicit weights) and see how it fails
- [ ] Confirm re-running without `--force` prompts before overwriting
