# ESE demo guide: Group 86, Dynamic Timetable

This guide covers what to open, what to click and what to say, screen by screen. The main demo
takes about **10 minutes**. The questions examiners usually ask are at the end, with short answers.

---

## Part A: Before the demo (do this 30 minutes before)

| # | What | How |
|---|---|---|
| 1 | **Wake up the online demo** | Open your Render link (e.g. `https://dynamic-timetable.onrender.com`) on the laptop **5 minutes early**. The free server sleeps; the first load takes about 1 minute. Keep the tab open. |
| 2 | **Phone ready** | Open the same link in Safari/Chrome on your phone, or use the home-screen icon. Log in once to check that it works. |
| 3 | **Backup: run on the laptop** | If the internet fails, double-click `scripts\start-windows.bat` (after the one-time setup in `docs/11-run-on-phone.md`) and use `http://localhost:8081`. Password there: `Demo@12345`. |
| 4 | **Keep these open in tabs** | (1) the app as **student**, (2) the app as **Admin** in a *private/incognito* window (separate login), (3) the college timetable PDF `backend/tests/fixtures/reference/college_timetable.pdf`, (4) the GitHub repository page, (5) the report PDF. |
| 5 | **Screen** | Laptop brightness up, zoom the browser to 110–125 %, turn notifications off, phone on silent. |
| 6 | **Know the day** | Answers like "next class" depend on today's day and time. If the demo is on a weekend or after 6 pm, say so: *"It's after college hours, so it shows tomorrow's first class."* |

**Logins** (online demo: use **your DEMO_PASSWORD**; laptop: `Demo@12345`)

| Role | E-mail |
|---|---|
| Student, TE-B4 (our own lab group) | `student.te.b4@demo.college.edu` |
| Student, SE-A1 (shows a lab group) | `student.se.a1@demo.college.edu` |
| Professor | `kkd@demo.college.edu` (Dr. Kailas Devadkar) |
| HOD | `snd@demo.college.edu` |
| Principal | `principal@demo.college.edu` |
| Admin | `admin@demo.college.edu` |

**Roles in the group (3 members):**

| Part | Speaks | Drives the laptop | Shows on phone |
|---|---|---|---|
| 0–1 Opening, real PDF | **Shivam** | Harshvarddhan | Gurshaan |
| 2–3 Student home, timetable | **Harshvarddhan** (built the app) | Shivam | Gurshaan |
| 4 Ask in plain English, "not ChatGPT" | **Shivam** (built the query engine) | Harshvarddhan | Gurshaan |
| 5 HOD and conflicts | **Gurshaan** (built conflict detection) | Shivam | Harshvarddhan |
| 6 Admin upload and extraction | **Gurshaan** (built the extraction) | Harshvarddhan | n/a |
| 7–8 Archives, personal, promotion | **Harshvarddhan** | Gurshaan | n/a |
| 9 Closing, numbers, architecture | **Shivam** | n/a | n/a |

In Q&A, each person answers questions about their own module (see the report's Table 7.2):
**Shivam**: architecture, database, security, query engine, deployment. **Gurshaan**: PDF/OCR
extraction, conflicts, performance. **Harshvarddhan**: app screens, laptop/web version, testing,
report and poster.

---

## Part B: The demo, screen by screen

### 0. Opening (30 seconds, no screen yet; show the poster)

> **Say:** "Good morning. We are Group 86. Our project is *Dynamic Timetable*. Every semester the
> college publishes the timetable as a 10-page PDF. Students and teachers read it by hand every day:
> where is my next class, which lab is my batch in, is room 508 free. Clashes are found only when
> they happen. Our system reads that same PDF automatically and turns it into a smart app with
> separate views for students, professors, the HOD, the Principal and the Admin. You can also ask
> questions in plain English. It runs on Android, iPhone and laptop from one code base."

### 1. The problem: the real PDF (30 seconds)

**Do:** open `college_timetable.pdf` and zoom into one page with stacked labs (A1–A4) and the legend.

> **Say:** "This is the actual timetable we used, not sample data. Look at one cell: subject, teacher
> code, room, and four lab batches stacked inside it. The codes like KKD and DBMS are expanded in a
> legend at the bottom of each page. That is what makes it hard to read, for people and for
> software."

### 2. Login and student home (1 minute)

**Do:** log in as `student.te.b4`. Show **Home**.

> **Say:** "I'm logged in as a TE-B4 student. Home shows the class happening right now, the next
> class with a countdown, and my free periods. It knows my division *and* my lab batch, so it shows
> B4's labs, not B1's. The login is a college e-mail and password. Passwords are stored with
> Argon2id hashing, and the session uses short-lived JWT tokens."

**Phone person:** show the same screen on the phone: *"Same app on the phone, same code."*

### 3. Weekly timetable and class details (1 minute)

**Do:** tap **Timetable** and pick **Mon**, then tap one class.

> **Say:** "This is the weekly view, Monday. Each card shows time, subject, teacher, room and floor.
> When I tap a class I see where it came from: page number, the raw text exactly as written in the
> PDF, and its status *Verified*. We never hide where data came from."

**Optional (shows a special rule):** log in as `student.se.a1`, open Monday 9:00 *Co Curricular Course*
and say: *"LLC slots have no teacher or room in the PDF, so we show them without inventing one."*

### 4. Ask in plain English (2 minutes): the highlight

**Do:** tap **Ask** and type these one by one (they are all tested on our data):

| Type this | What happens | Say |
|---|---|---|
| `What is my next class?` | Next class with room and countdown | "Same answer as the Home card, because both use the same engine." |
| `Do I have classes after lunch on Wednesday?` | Lists classes from 1:15 | "TE lunch is 12:15–1:15 and SE lunch is 1:15–2:15. The system reads the lunch row of *each* year from the PDF, so it doesn't use one fixed time." |
| `Am I free at 2?` | **Asks: 2 AM or 2 PM?** then the date | "It asks instead of guessing. That's a design rule: no silent assumptions." |
| `Where is Prof. Devadkar on Monday at 10 am?` | Room 508, DBMS | "It says *scheduled* location. We don't track people, we only read the timetable." |
| `Which rooms are free at 11 am on Monday?` | List of free rooms | "Useful for extra lectures. A room is free if no class overlaps that time." |
| `Who teaches Software Engineering?` | All SE classes with teacher | |
| `How many labs do I have this week?` | **8 labs** with a per-day breakdown | "This isn't a stored question. The planner combines *count* + *labs* + *this week* into a query plan." |
| `Which day is my busiest?` | Day-wise list, **Wednesday** on top | "Same engine: *per day* + *most classes*. It also tells you which days have no classes." |
| `When is my last class on Friday?` | Last class and when you're done | "*last* + *Friday*. Try 'Which day do I finish earliest?' as well." |
| `Do I have classes before 11 am on Tuesday?` | Classes starting before 11 | "A *before* time window. A bare '11' would make it ask a.m. or p.m." |
| `When is lunch break on Monday?` / `When am I free on Thursday?` | Lunch 12:15–1:15 (TE) / free periods | "It reads *your* section's lunch row — SE gets 1:15–2:15." |
| `Who teaches software engineering?` / `Which floor is room 606-5?` | Teacher names / floor 6 | |
| `Any clashes?` | The 2 clashes | "Viewing is open to everyone — the timetable is public; only changes are Admin-only." |
| `Compare my personal and college timetable` | Politely refused | "Personal and college data are deliberately kept separate, so this is not allowed." |

> **Say (important, examiners like this):** "This is **not ChatGPT**. We don't send the question to
> an AI and we never build SQL from the user's text. A **compositional planner** splits the question
> into pieces (what to compute: list, count, first/last, total hours, per day; filters: me, batch,
> professor, room, subject, lab or lecture; when: a day, a date or this week; a time window; an order)
> and builds a **typed query plan**. The server adds your role scope and compiles the plan into
> parameterised SQL. So questions aren't limited to a fixed list, answers are always the same and
> correct, and SQL injection is impossible by design. Every answer even carries its plan, so we can
> show exactly how it was understood. We read
> research showing that LLM text-to-SQL can be tricked by prompt injection, which is why we chose
> this approach."

### 5. Professor, HOD and conflicts (1.5 minutes)

**Do:** log out and log in as `snd` (HOD). Show **Home** and tap **Review conflicts**.

> **Say:** "The HOD sees their own teaching and a conflict warning. The system checked every pair of
> classes and found **two real clashes printed in the official PDF**: Prof. Sushama Pande has two
> classes on Friday at 2:15, and room 603-2 is double-booked on Tuesday at 2:15. At first there
> were 542 raw overlaps, but most were intended, like four lab batches running at the same time or
> elective options. We taught the system to recognise those, so only the 2 genuine clashes remain.
> The committee can fix them *before* the semester starts."

(Optional: log in as `kkd` and ask `What is my schedule today?`. Ask on a weekday, because
on a weekend the answer is empty.)

### 6. Admin: upload a new timetable live (2 minutes)

**Do:** in the incognito window as `admin`: **Admin → Upload official timetable →** choose
`college_timetable.pdf` → **Upload & process**.

> **Say:** "When the committee releases a new timetable, the Admin just uploads it, as a PDF, Excel,
> Word file or even a photo. A background worker processes it so the app stays fast. Uploading
> **does not** change what students see. It goes into the archive first."

Wait for **Needs review** (about 10–60 s online), then open it:

> **Say:** "Here's the extraction summary: **453 classes, 452 verified automatically**. The one
> that isn't verified is an M.Tech class that has *no time printed* in the PDF, so we flag it
> instead of guessing. The Admin can open **Review & correct**, fix it, and every change is saved
> with the old value in an audit log. Only when the Admin presses **Activate** does it become the
> official timetable, and everyone gets a notification."

(You don't need to press Activate. If you do, it becomes the new official version, which is fine.)

### 7. Archives and personal timetable (45 seconds)

**Do:** as a student, open **Archives** and switch the top toggle **College ↔ Personal**.

> **Say:** "Every version of the timetable is kept, so we can always see which timetable was
> official on which date. Students can also upload their *personal* timetable, for example
> coaching classes. That data is private. Even the Admin can't open it; the server returns
> 'not found' to anyone else."

### 8. Year change: promotion (30 seconds)

**Do:** **Admin → Academic promotion**, show the preview.

> **Say:** "At the end of the year the Admin promotes students, for example SE to TE, in one step
> with a preview. History is kept, and the next login automatically shows the new year's timetable.
> The same student and the same account work across years."

### 9. Closing (30 seconds; show the architecture diagram from the report or poster)

> **Say:** "To summarise: one React Native app for Android, iPhone and laptop; a FastAPI back end;
> PostgreSQL; a background worker; an extraction pipeline with OCR; and a safe rule-based question
> engine. It is backed by **178 automated back-end tests, 20 app tests and end-to-end browser tests
> that all pass**. Measured search time is about **40–50 ms** for one user. With 4 server workers
> on a laptop it handled about **60 searches per second** with **zero wrong answers at 32
> simultaneous users**. It's deployed online for free. Next steps are a load test on real
> college servers, an installable store app and measuring extraction accuracy on hand-checked
> pages. Thank you."

---

## Part C: If something goes wrong

| Problem | What to do / say |
|---|---|
| Online link loads forever | "The free server was sleeping." Wait 60 s, or switch to the laptop backup (`start-windows.bat`). |
| "Next class" looks odd | It depends on today's time. Ask `What are my classes on Monday?` instead. |
| Upload takes long | Free server is slow; show the already-processed timetable in **Archives** instead. |
| Wrong password | Online uses your **DEMO_PASSWORD**, laptop uses `Demo@12345`. |
| Phone can't reach the laptop server | Use the online link on the phone, or the phone's hotspot. |

---

## Part D: Questions examiners usually ask (short answers)

| Question | Answer |
|---|---|
| **Is this ChatGPT / an AI model?** | No. It is a rule-based **compositional query planner**: the question becomes a typed plan (operation + filters + time) that the server compiles into parameterised SQL with your role scope. It is deterministic, reproducible and injection-safe, and it needs no paid API. |
| **Can a student see other batches?** | Yes. The official timetable is public, so anyone can ask about any batch, teacher, room or clash. "My" still means your own batch and lab group, personal timetables stay private, and only the Admin can change data. |
| **Are you limited to fixed questions?** | No longer. Earlier versions had 30 fixed question types; now pieces combine freely (count / first / last / busiest day / lab or lecture / before or after a time / this week). Specialised operations (free rooms, professor free time, archives) are reused where they need special logic. An LLM could be added later only to *suggest* a plan, never to touch the database. |
| **How do you read the PDF?** | PyMuPDF gives text with coordinates and ruled tables (it keeps merged 2-hour lab cells). We find the time row, day rows and sections, split stacked lab batches, expand the page's legend and validate everything. Scanned pages and photos go through Tesseract OCR. |
| **What if the PDF format changes?** | Each entry gets a status. Anything the parser isn't sure about becomes *Unverified* or *Incomplete* and goes to the Admin's review screen. The parser is versioned (`tt-grid-parser/1.2.0`) and has regression tests on the real PDF. |
| **Accuracy?** | On the real 10-page PDF, 452 of 453 classes were verified automatically, and the remaining one has no time in the PDF. Precision/recall against a hand-labelled sample is future work, and we say so honestly. |
| **How are clashes detected?** | Two classes overlap if `start1 < end2` and `start2 < end1` (start inclusive, end exclusive, so 9–10 and 10–11 don't clash). We group by professor, room and batch, and skip intended overlaps such as parallel lab batches and electives. |
| **Security?** | Argon2id passwords, 15-minute JWT access tokens plus rotating refresh tokens (reuse detection), roles loaded from the DB on every request, rate limiting, parameterised SQL only, IDOR protection (404 to non-owners) and an audit log. |
| **Concurrency: two admins activate at once?** | The settings row is locked with `SELECT … FOR UPDATE`, so the activations run one after the other. This is tested. Upload workers take jobs with `FOR UPDATE SKIP LOCKED`, so two workers never process the same file. |
| **DBMS concepts?** | Normalised schema (3NF), PK/FK, CHECK constraints, partial unique indexes (e.g. one open placement per student, one active academic year), composite indexes `(timetable_id, day_of_week, start_time)`, transactions. |
| **OS concepts?** | API processes plus a separate worker process, a job queue in Postgres, row locks for synchronisation, heartbeat and retry for crashed jobs. |
| **Networks?** | Client–server over HTTPS, JSON REST API, stateless servers, timeouts, retry for reads only, single-flight token refresh. |
| **Data structures / algorithms?** | Hash maps for legend and vocabulary lookup, sorting plus a sweep for overlaps, a queue for jobs, n-gram matching for entity names, interval logic for free time. |
| **How many users can it handle?** | Tested: 32 simultaneous users, 960 requests, 0 wrong answers, about 57 req/s on a 4-core laptop with 4 workers. That is a measured test, not a capacity promise; production needs a test on the real server. |
| **Cost?** | Rs. 0. Open-source stack and Render free tier for the demo. Real use would need about US$7–25/month of hosting. |
| **Year change, new timetable, student promoted?** | Admin promotion (preview, confirm, history kept), then upload and activate the new timetable. The student keeps the same account and the new batch's timetable appears automatically. |
| **Mid-semester timetable change?** | Upload the revised PDF, review it, then activate. Everyone is notified and the old version stays in Archives. |
| **Why not Google Calendar?** | Nobody can type 450 classes by hand every revision, and a calendar has no roles, no free-room search and no clash check. |
| **Who did what?** | Each member answers their own part (see the report's Section 7.8 contribution table). |

> If the guide gave you specific "scenario-based challenges", practise them with the matching rows
> above. Most scenarios (promotion, revised timetable, clash, wrong time, offline phone, two admins)
> are already handled and tested.

---

## Part E: How to open and build the report and poster

The submission folder is `report/86_Dynamic_Timetable_Monitoring_System/`:

```
86_Dynamic_Timetable_Monitoring_System/
├── 86_Dynamic_Timetable_Monitoring_System.tex   ← main file (compile this)
├── 86_Dynamic_Timetable_Monitoring_System.pdf   ← ready-made PDF
├── details.tex          ← names, UIDs, guide, HOD (EDIT THIS FIRST)
├── frontmatter/         ← cover, certificate, approval, declaration, acknowledgement, abstract
├── chapters/            ← ch01 … ch11
├── references.tex
├── figures/             ← SPIT logo, app screenshots
└── poster/              ← A3 poster (.pptx editable + .pdf)
```

### Step 1: Check your details (1 minute)
Names, UIDs, guide (Prof. Anant Nimkar) and HOD (Dr. Sudhir Dhage) are already filled in, in
`details.tex`. Change them there if anything is wrong: one edit updates every page.

### Step 2a: Compile on Overleaf (easiest, nothing to install)
1. Zip the folder `86_Dynamic_Timetable_Monitoring_System` (right-click → *Send to → Compressed folder*).
2. Go to **overleaf.com** → *New Project* → **Upload Project** → choose the zip.
3. Click **Menu** and set *Main document* = `86_Dynamic_Timetable_Monitoring_System.tex` and *Compiler* = **pdfLaTeX**.
4. Click **Recompile**. If the Table of Contents is empty, click Recompile once more.
5. **Download PDF** (the icon next to Recompile).

### Step 2b: Compile on your laptop (Windows)
1. Install **MiKTeX** (miktex.org). On first compile, allow it to install missing packages.
2. Open Command Prompt in the folder and run:
   ```
   pdflatex 86_Dynamic_Timetable_Monitoring_System.tex
   pdflatex 86_Dynamic_Timetable_Monitoring_System.tex
   pdflatex 86_Dynamic_Timetable_Monitoring_System.tex
   ```
   (It needs three runs so the contents, list of figures and references are filled in.) If you have
   `latexmk`, `latexmk -pdf 86_Dynamic_Timetable_Monitoring_System.tex` does it in one go.
3. Or use **TeXstudio**: open the `.tex` file → press **F5** (Build & View).

### Step 3: Poster (A3)
1. A ready A3 PDF is in `poster/86_Dynamic_Timetable_Poster_A3.pdf`. To edit, open
   `poster/86_Dynamic_Timetable_Poster.pptx` in **PowerPoint** (the department template, filled in for our
   project; it uses Bookman Old Style, which comes with Windows/Office).
2. Names and guide are already filled in; check the title box once.
3. **File → Export → PDF**, or print with *Paper size* = **A3** and *Scale to fit paper*. The
   slide has the same proportions as A3 (ISO paper), so nothing is cut off.
4. Don't change fonts or box formatting; the department note in the template asks for that.

### Step 4: Submit
* Folder or zip name: **`86_Dynamic_Timetable_Monitoring_System`**, the format *GroupNo_TitleOfTheProject*.
* Include the complete LaTeX source (the whole folder) and the compiled PDF.
* Plagiarism and AI-content reports: run them on **your institute's** tool on the final PDF.
  Read through the text and rewrite parts in your own words where needed, following the
  institute's policy on AI-assisted writing.
