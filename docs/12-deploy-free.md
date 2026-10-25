# Free online demo (Render) — no Expo Go, one link for iPhone, Android and laptop

This puts the whole system online for free: the server, the database and the app (as a web app).
Anyone with the link can open it in Safari/Chrome, and "Add to Home Screen" gives an app icon.

It is meant for a **demo**. Free-tier limits (Render, 2026):

| Limit | What it means for you |
|---|---|
| Sleeps after 15 min without visitors | The first visit after a quiet period takes about **1 minute** to load. Open the link a minute before you demo. |
| Free database expires **30 days** after creation (deleted after a further 14 days) | Re-create it before then (step 6) — the demo data reloads by itself. |
| 750 free hours per month | Enough for one always-available service. |
| Uploaded original files are not kept across restarts | Extracted timetables (in the database) stay; only "Reprocess" of an old upload needs the file again. |
| No `.xls` / `.doc` (old Office formats) | PDF, `.xlsx`, `.docx`, `.csv` and photos work. |

## 1. Create a Render account (free)

Go to **https://render.com** → **Get Started** → **Sign up with GitHub** (use the account that owns
`shivammulani-24/Dynamic_Timetable`). No card is needed for the free tier.

## 2. Create the service from the blueprint

1. In the Render dashboard: **New +** → **Blueprint**.
2. Connect GitHub if asked, and pick **Dynamic_Timetable**.
3. Branch: choose **`claude/wizardly-fermi-fuvc05`** (or `main` if you renamed it).
4. Render reads `render.yaml` and shows: a database **timetable-db** and a web service **dynamic-timetable**, both *Free*.
5. It asks for **DEMO_PASSWORD**: type a password only you know (10+ characters, e.g. `Spit#Demo2026`).
   Every demo account uses it. Do **not** use `Demo@12345` — the server refuses the published one.
6. Click **Apply**.

The first build takes about **10–15 minutes** (it builds the web app and installs OCR). Watch
**dynamic-timetable → Logs**; it is ready when you see `Application startup complete`.

## 3. Open it

Your link is shown at the top of the service page, e.g. **`https://dynamic-timetable.onrender.com`**
(Render adds a suffix if the name is taken).

* **Laptop:** open the link.
* **iPhone:** open it in **Safari** → Share → **Add to Home Screen**.
* **Android:** open it in **Chrome** → ⋮ → **Add to Home screen** / **Install app**.

Log in with the same accounts as on your laptop, but with **your DEMO_PASSWORD**:
`admin@demo.college.edu`, `principal@…`, `snd@…` (HOD), any faculty code (`kkd@…`), and students
`student.se.a1@…` … `student.te.b4@…`, `student.be.c@…`, `student.mtech@…`.

## 4. Updating the demo

Every `git push` to that branch redeploys automatically (about 5–10 minutes). Your data is kept:
the demo data is only loaded into an **empty** database.

## 5. Things to know

* **Forgot password:** there is no email on the free demo. The Admin opens *Admin → Users → the person →
  Issue new access code* and gives them the code; they use *Activate account* to set a new password.
* **New accounts:** the Admin creates them (*Admin → Register student or staff*); the activation code is
  shown to the Admin once, to hand over in person.
* **Security:** the demo runs in production mode — strong secret key, no reset codes in responses or logs,
  the published development password is rejected. Still, it is a demo: use demo data only.

## 6. When the free database expires (every 30 days)

Render emails you before it expires. Then: **timetable-db** → *Delete*, and in the dashboard
**Blueprints → your blueprint → Manual sync**. A new free database is created and the demo data loads
again on the next start. (Anything changed in the old database is lost.)

## 7. Later: real students

Before real students use it, the college should pay for (or otherwise provide) hosting that does not sleep
or expire, then:

1. remove `ALLOW_DEMO_SEED` / `DEMO_PASSWORD` (no demo accounts),
2. create the first Admin (see `docs/07-deployment.md`),
3. configure email (SMTP variables) so activation and reset codes are emailed,
4. load the real master data and timetable through the Admin screens,
5. optionally build the installable Android/iPhone apps with EAS (`mobile/eas.json`).
