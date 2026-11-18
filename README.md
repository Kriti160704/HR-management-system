# TalentSift - HR Resume Screener
1. Install Python 3.9+
2. `pip install -r requirements.txt`
3. `python app.py`  (or double-click run.bat on Windows / `bash run.sh` on Mac/Linux)
4. Open http://localhost:5000

Use: enter job title + description -> upload up to 1,000 PDF/DOCX/TXT resumes (or a whole folder) -> "Find relevant resumes".
Adjust the threshold slider to change who is shortlisted. Export the ranking with "Download CSV".
The chatbot (bottom-right) only answers questions about the resumes and job description; anything else gets a polite refusal.
Note: scanned image-only PDFs have no text and are skipped.
