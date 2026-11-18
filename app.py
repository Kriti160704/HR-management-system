"""HR Resume Screener - Flask backend. Run: python app.py  ->  http://localhost:5000"""
import io, re, csv, math, os, hashlib
from collections import Counter
from flask import Flask, request, jsonify, send_from_directory, Response

app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1 GB per request

STATE = {"resumes": [], "title": "", "jd": "", "threshold": 40, "analyzed": False, "keywords": []}

STOP = set("""a an the and or of to in for with on at by from as is are was were be been this that these those it its you your we our
will can should must have has had not but if than then so such into over under about per etc using use used within across including able
strong good excellent knowledge experience years year work working role candidate candidates responsibilities requirements required preferred
plus job description team company looking skills skill ability who what when where how all any more most other some very also may might
well new one two three etc eg ie need needs building build looking them their they he she his her us per while during through between both each""".split())

TOKEN = re.compile(r"[a-z][a-z0-9+#]*(?:[.\-][a-z0-9+#]+)*")
def tokenize(t): return TOKEN.findall(t.lower())

# ---------- resume reading ----------
def extract_text(name, data):
    ext = name.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    if ext == "docx":
        import docx
        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts += [c.text for c in row.cells]
        return "\n".join(parts)
    if ext in ("txt", "md", "text"):
        return data.decode("utf-8", errors="ignore")
    raise ValueError("Unsupported file type (use PDF, DOCX or TXT)")

def parse_resume(fname, text):
    lines = [l.strip() for l in text.splitlines() if l.strip()][:10]
    name = os.path.splitext(os.path.basename(fname))[0].replace("_", " ").replace("-", " ").title()
    for l in lines:
        if 2 <= len(l.split()) <= 4 and re.fullmatch(r"[A-Za-z .'\-]+", l) and not re.search(r"resume|curriculum|vitae|\bcv\b", l, re.I):
            name = l.title() if l.isupper() else l
            break
    email = (re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text) or [""])[0]
    phone = (re.search(r"(?:\+?\d[\d\s\-()]{8,}\d)", text) or [""])[0].strip()
    yrs = [int(x) for x in re.findall(r"(\d{1,2})\+?\s*(?:years|yrs|year)", text.lower()) if int(x) <= 40]
    toks = [t for t in tokenize(text)]
    return {"file": fname, "name": name, "email": email, "phone": phone,
            "years": max(yrs) if yrs else 0, "tf": Counter(toks), "score": 0, "matched": [], "missing": []}

# ---------- scoring ----------
def analyze():
    jd = [t for t in tokenize(STATE["jd"] + " " + STATE["title"]) if t not in STOP and len(t) > 1]
    kw = [k for k, _ in Counter(jd).most_common(45)]
    STATE["keywords"] = kw
    R = STATE["resumes"]; N = len(R) + 1
    df = Counter()
    for r in R: df.update(r["tf"].keys())
    idf = lambda t: math.log((N + 1) / (df.get(t, 0) + 1)) + 1
    jtf = Counter(jd)
    for r in R:
        have = [k for k in kw if k in r["tf"]]
        cover = len(have) / len(kw) if kw else 0
        norm = math.sqrt(sum((c * idf(t)) ** 2 for t, c in r["tf"].items())) or 1
        jn = math.sqrt(sum((c * idf(t)) ** 2 for t, c in jtf.items())) or 1
        cos = sum(jtf[t] * idf(t) * r["tf"].get(t, 0) * idf(t) for t in jtf) / (norm * jn)
        r["score"] = round(100 * (0.7 * cover + 0.3 * min(1, cos * 2.5)), 1)
        r["matched"] = have
        r["missing"] = [k for k in kw if k not in r["tf"]][:8]
    R.sort(key=lambda r: -r["score"])
    STATE["analyzed"] = True

is_match = lambda r: STATE["analyzed"] and r["score"] >= STATE["threshold"]

def public(r, i):
    return {"rank": i + 1, "name": r["name"], "file": r["file"], "email": r["email"], "phone": r["phone"],
            "years": r["years"], "score": r["score"], "matched": r["matched"][:12], "missing": r["missing"],
            "shortlisted": is_match(r)}

# ---------- chatbot (domain restricted) ----------
DECLINE = ("Sorry, I can't give an answer to that question. I can only help with questions about the uploaded "
           "resumes and the job description - for example: \"How many resumes match the job description?\"")
DOMAIN = re.compile(r"resume|\bcvs?\b|student|candidate|applicant|profile|job|\bjd\b|description|shortlist|match|relevant|qualif|"
                    r"hire|hiring|screen|score|rank|uploaded|experience|skill|recruit|fit\b|suitable|eligible|required|keyword|people|person")
POS = re.compile(r"match|shortlist|relevant|qualif|suitable|eligible|\bfit\b|selected|good for|pass")
NEG = re.compile(r"not match|unmatch|mismatch|reject|irrelevant|not relevant|not shortlist|not qualif|not suitable|don'?t match|do not match|doesn'?t match|unsuitable")
CHAT_STOP = set("""how many what which who whom whose is are was were the a an of in to for with have has had do does did there their they them
student students resume resumes cv cvs candidate candidates applicant applicants person people profile profiles match matches matching matched
shortlisted shortlist relevant qualified suitable eligible fit selected not job description jd total number count list show give me name names
top best highest lowest rank ranked average score scores experience experienced years year more than less over under above below at least minimum
maximum uploaded all any and or can you please tell about know knows skill skills good strong this that it i my our we us on at by from as be
been will would should could display find get see whose does having possess possesses expertise expert familiar working work worked""".split())

CUSTOM = [
  (r"most experienced|highest experience|longest experience",
   lambda R: f"Most experienced: {max(R, key=lambda r: r['years'])['name']} ({max(r['years'] for r in R)} years)."),
  (r"average experience|avg experience",
   lambda R: f"Average experience is {round(sum(r['years'] for r in R)/len(R), 1)} years."),
  (r"(no|without|missing) email",
   lambda R: f"{sum(1 for r in R if not r['email'])} resumes have no email address."),
  (r"(no|without|missing) (phone|contact)",
   lambda R: f"{sum(1 for r in R if not r['phone'])} resumes have no phone number."),
]
def chat(q):
    ql = q.lower().strip()
    R = STATE["resumes"]
    if re.fullmatch(r"(hi|hello|hey|help|good (morning|afternoon|evening))\W*", ql) or "what can you" in ql:
        return ("Hi! I'm your HR assistant. Ask me things like:\n- How many resumes are uploaded?\n- How many students match the job description?\n"
                "- Show the top 5 candidates\n- Who knows Python?\n- Candidates with more than 3 years experience\n- What are the key skills in the job description?")
    toks = tokenize(ql)
    vocab = set().union(*(r["tf"].keys() for r in R)) if R else set()
    skills = [t for t in toks if t not in CHAT_STOP and t in vocab and not t.isdigit()]
    named = [r for r in R if len(r["name"]) > 3 and (r["name"].lower() in ql or
             (re.search(r"about|detail|profile|tell|score|email|phone|contact|who is", ql) and
              any(len(p) > 3 and p in toks for p in r["name"].lower().split())))]
    skill_ctx = re.search(r"know|skill|have|has|with|experience|expert|familiar|worked|using", ql)
    if not (DOMAIN.search(ql) or named or (skills and skill_ctx)):
        return DECLINE
    if not R:
        return "No resumes have been uploaded yet. Please upload resumes and click Analyze first."
    if re.search(r"(required|key|needed|important).*(skill|keyword)|jd keyword|skills.*(in|from|of).*(job|jd)|keywords", ql):
        if not STATE["keywords"]: return "Please paste a job description and click Analyze first."
        return "Key skills/keywords in the job description:\n" + ", ".join(STATE["keywords"][:25])
    if named:
        r = named[0]
        return (f"{r['name']} - score {r['score']}% ({'Shortlisted' if is_match(r) else 'Not shortlisted'})\n"
                f"Email: {r['email'] or 'n/a'} | Phone: {r['phone'] or 'n/a'} | Experience: {r['years']} yrs\n"
                f"Matched: {', '.join(r['matched'][:10]) or '-'}\nMissing: {', '.join(r['missing'][:8]) or '-'}")
    wants_match = bool(POS.search(ql) or NEG.search(ql))
    if wants_match and not STATE["analyzed"]:
        return "Please paste the job description and click Analyze first, then I can tell you who matches."
    pool = list(R)
    flag = None
    if NEG.search(ql): flag = False
    elif POS.search(ql): flag = True
    if flag is not None: pool = [r for r in pool if is_match(r) == flag]
    for s in skills: pool = [r for r in pool if s in r["tf"]]
    m = re.search(r"(more than|over|above|at least|minimum|min|greater than)\s*(\d+)", ql)
    n = re.search(r"(less than|under|below|at most|maximum|max)\s*(\d+)", ql)
    if m: pool = [r for r in pool if r["years"] >= int(m.group(2)) and (r["years"] > int(m.group(2)) or "least" in m.group(1) or "min" in m.group(1))]
    if n: pool = [r for r in pool if r["years"] <= int(n.group(2))]
    label = ("matching " if flag is True else "non-matching " if flag is False else "") + "resumes"
    if skills: label += " with " + ", ".join(skills)
    if m or n: label += f" ({(m or n).group(1)} {(m or n).group(2)} yrs experience)"
    if re.search(r"average|avg|mean", ql) and re.search(r"score|match", ql):
        return f"The average match score across {len(R)} resumes is {round(sum(r['score'] for r in R)/len(R),1)}%." if STATE["analyzed"] else "Please click Analyze first."
    top = re.search(r"\b(top|best|highest|strongest|ranked|rank)\b", ql)
    if top:
        k = int((re.search(r"top\s*(\d+)", ql) or re.search(r"(\d+)", ql) or [0, 5])[1]) if re.search(r"\d+", ql) and not (m or n) else 5
        k = max(1, min(k, 25)) if not re.search(r"best|highest", ql) or re.search(r"top|\d", ql) else 1
        rows = pool[:k]
        return f"Top {len(rows)} {label}:\n" + "\n".join(f"{i+1}. {r['name']} - {r['score']}%" for i, r in enumerate(rows)) if rows else f"No {label} found."
    if re.search(r"how many|count|number of|total", ql):
        if not wants_match and not skills and not (m or n):
            return f"{len(R)} resumes have been uploaded."
        return f"{len(pool)} of {len(R)} {label}."
    if re.search(r"\b(list|show|who|which|name|names|give|display|find)\b", ql) or skills or m or n or flag is not None:
        if not pool: return f"No {label} found."
        out = "\n".join(f"{i+1}. {r['name']} - {r['score']}%" for i, r in enumerate(pool[:15]))
        return f"{len(pool)} {label}:\n{out}" + (f"\n...and {len(pool)-15} more (see the table)." if len(pool) > 15 else "")
    return (f"Summary: {len(R)} resumes uploaded"
            + (f", {sum(is_match(r) for r in R)} shortlisted at {STATE['threshold']}% threshold." if STATE["analyzed"] else ". Click Analyze to score them."))

# ---------- routes ----------
@app.route("/")
def home(): return send_from_directory("static", "index.html")

@app.post("/api/upload")
def upload():
    ok, dups, errors = 0, 0, []
    seen = {r["hash"] for r in STATE["resumes"]}
    for f in request.files.getlist("files"):
        try:
            data = f.read(); h = hashlib.md5(data).hexdigest()
            if h in seen: dups += 1; continue   # identical file already uploaded
            text = extract_text(f.filename, data)
            if not text.strip(): raise ValueError("No readable text (scanned PDF?)")
            r = parse_resume(f.filename, text); r["hash"] = h
            STATE["resumes"].append(r); seen.add(h); ok += 1
        except Exception as e:
            errors.append(f"{f.filename}: {e}")
    STATE["analyzed"] = False
    return jsonify(added=ok, dups=dups, errors=errors, total=len(STATE["resumes"]))

@app.post("/api/analyze")
def run_analyze():
    d = request.get_json(force=True)
    STATE.update(title=d.get("title", ""), jd=d.get("jd", ""), threshold=float(d.get("threshold", 40)))
    if not STATE["resumes"]: return jsonify(error="Upload resumes first."), 400
    if len(tokenize(STATE["jd"])) < 3: return jsonify(error="Please enter a job description."), 400
    analyze()
    return jsonify(results=[public(r, i) for i, r in enumerate(STATE["resumes"])], keywords=STATE["keywords"])

@app.post("/api/threshold")
def threshold():
    STATE["threshold"] = float(request.get_json(force=True).get("threshold", 40)); return jsonify(ok=True)

@app.post("/api/chat")
def chat_api(): return jsonify(answer=chat(request.get_json(force=True).get("message", "")))

@app.post("/api/reset")
def reset():
    STATE.update(resumes=[], analyzed=False, keywords=[]); return jsonify(ok=True)

@app.get("/api/export")
def export():
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["Rank", "Name", "File", "Email", "Phone", "Years", "Score %", "Status", "Matched skills"])
    for i, r in enumerate(STATE["resumes"]):
        w.writerow([i + 1, r["name"], r["file"], r["email"], r["phone"], r["years"], r["score"],
                    "Shortlisted" if is_match(r) else "Not shortlisted", "; ".join(r["matched"])])
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=shortlist.csv"})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
