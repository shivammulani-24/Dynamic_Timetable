# Running and testing on your phone (with the college's real timetable)

This runs the backend on your laptop and the app on your Android phone or iPhone through **Expo Go**.
Total time the first time: about 30–45 minutes, mostly installs.

## 1. What you need

| On the laptop (Windows, macOS or Linux) | On the phone |
|---|---|
| Git, **Python 3.12+**, **PostgreSQL 16** (14+ works), **Node.js 22** (20+ works) | **Expo Go** from the Play Store / App Store |
| Optional: Tesseract (photos/scanned PDFs), LibreOffice (old `.xls`/`.doc`) | Same Wi-Fi network as the laptop |

> College Wi-Fi often blocks phone ↔ laptop traffic. If the app can't reach the server, turn on the
> **phone's hotspot** and connect the laptop to it, which is the most reliable option for testing.

## 2. Get the code

```bash
git clone https://github.com/shivammulani-24/Dynamic_Timetable.git
cd Dynamic_Timetable
git checkout claude/wizardly-fermi-fuvc05      # or main, once this branch is merged
```

## 3. Backend set-up (one time)

**macOS / Linux**

```bash
scripts/dev.sh setup        # venv + Python packages, DB user/databases, migrations, npm install
```

**Windows (PowerShell)**: run the same steps by hand:

```powershell
# in "SQL Shell (psql)" as postgres:
#   CREATE USER timetable WITH PASSWORD 'timetable_dev' CREATEDB;
#   CREATE DATABASE timetable OWNER timetable;  CREATE DATABASE timetable_test OWNER timetable;
cd backend
py -3.13 -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
copy .env.example .env
.venv\Scripts\alembic upgrade head
cd ..\mobile; npm ci
```

## 4. Load the college timetable (development data)

```bash
scripts/dev.sh seed-college          # Windows: cd backend; .venv\Scripts\python -m app.seed_college --reset
```

This **wipes the development database**, reads `backend/tests/fixtures/reference/college_timetable.pdf`
with the normal extraction pipeline, creates the batches, subjects, faculty and rooms that the PDF
names, uploads the PDF and activates it as the official timetable. Expected output:

```
Loaded …college_timetable.pdf: 453 classes (452 verified) — statuses {'VERIFIED': 452, 'INCOMPLETE': 1}
```

To load a newer timetable later: `scripts/dev.sh seed-college --pdf path/to/new.pdf`, or upload it in
the app as Admin (step 7).

## 5. Start the server (two terminals, keep both open)

```bash
scripts/dev.sh api         # Windows: cd backend; .venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000
scripts/dev.sh worker      # Windows: cd backend; .venv\Scripts\python -m app.worker
```

Check it from the **phone's browser**: `http://<laptop-IP>:8000/healthz` should show `{"status":"OK"}`.
Find the laptop IP with `ipconfig` (Windows, "IPv4 Address") or `ipconfig getifaddr en0` (macOS) /
`hostname -I` (Linux). If the phone can't open it: allow port 8000 in the laptop firewall (Windows
asks the first time; choose *Private networks*), or use the hotspot tip above.

## 6. Start the app

```bash
cd mobile
npx expo start
```

* **Android**: open Expo Go → *Scan QR code*.
* **iPhone**: open the Camera app and scan the QR code → it opens in Expo Go.

The app finds the server by itself (same IP as the QR code, port 8000). If it shows "Can't reach the
server", create `mobile/.env` with `EXPO_PUBLIC_API_URL=http://<laptop-IP>:8000` and restart
`npx expo start`. If the QR code won't load at all on your network, use `npx expo start --tunnel` for
the app bundle (the API must still be reachable, as in step 5).

## 7. What to test (password for every account: `Demo@12345`)

| Sign in as | Check |
|---|---|
| `student.se.a1@demo.college.edu` | **Home**: current/next class and countdown. **Timetable → Mon**: *Co Curricular Course* (LLC) shows no teacher/room; 12:15–1:15 *Data Structures* is a normal class. **Wed**: only the A1 labs, not A2/A3/A4. Tap a class for details. |
| same | **Ask**: "What is my next class?", "Do I have classes after lunch on Tuesday?" (SE lunch is 1:15–2:15, so it answers from 2:15), "Find all DBMS classes", "Am I free at 2?" (asks AM/PM), "Where is Prof. Devadkar now?" |
| `student.te.a1@…` | "Do I have classes after lunch?": TE lunch is 12:15–1:15, so it answers from 1:15 |
| `student.be.c@…` (or `.be.a`) | **Timetable → Tue**: the combined BE A–D electives (TSDA, Gen AI, XAI, DMBI…), shared by all BE divisions |
| `student.mtech@…` | M.Tech page (W.E.F. 07 Sept) |
| `student.newbie@…` | Any question → "not yet linked to a batch" (no invented class) |
| `kkd@…` (any faculty code works: `avn@`, `js@`, `aag@`…) | "What is my schedule today?", free periods |
| `snd@…` | HOD dashboard → **Review conflicts** → 2 conflicts (see §8) |
| `admin@…` | Admin hub: rooms (floors), courses, users, academic promotion, audit log. **Upload official timetable** → pick a PDF/Excel/Word/photo from the phone → wait for *Needs review* → open → **Review & correct** → **Activate** |
| student, Personal tab | Upload your own timetable (PDF/Excel/photo); it stays separate from the college one |

## 8. What the app reports about this PDF (these are in the document, not app errors)

* **Two real clashes** (Conflicts screen):
  * Friday 2:15–3:15: Prof. Sushama Pande (SP) has *LA* for SE-B in 609 (page 2) **and**
    *Data Sci. Lab C3* for SE-C in 606-4, written "(2.15 - 4.15 pm)" (page 3).
  * Tuesday 2:15–3:15: room **603-2** has BE *PE III-GenAI-A* (YP, 1:15–3:15, page 9) **and** TE-D *DC Lab D2*
    (PL, "02:15 PM-04:15 PM", page 8).
  Fix them in the next version of the PDF, or correct one entry in **Review & correct**.
* **One class without a time**: M.Tech *HSS (305)* on Friday sits in a row with no time label (page 10).
  It is kept as *Incomplete* (not shown in "now/next"). Admin → open the timetable → **Review & correct**
  → set its start/end time; after that every class is verified.
* **Room floors** were set from the room number (508 → floor 5, 002 → floor 0). Correct any that are
  wrong in Admin → Rooms (used by "free rooms on floor 6" questions).

## 9. Installing it like a normal app (optional, later)

Expo Go is for testing. To get an installable app:

1. `npm i -g eas-cli && eas login && eas init` (free Expo account).
2. Put the server's **https** address in `mobile/eas.json` → `preview.env.EXPO_PUBLIC_API_URL`
   (Android release builds refuse plain `http`; for laptop testing you can use a tunnel such as
   `cloudflared tunnel --url http://localhost:8000`, which gives a temporary https URL).
3. Android APK: `eas build --profile preview --platform android` → install the APK from the link.
4. iPhone: needs an Apple Developer account: `eas build --profile preview --platform ios`, then TestFlight.
5. Push notifications work only in these builds (not in Expo Go); set `EXPO_PUSH_ENABLED=true` on the server.

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| "Can't reach the server" | Phone browser → `http://<laptop-IP>:8000/healthz`. Firewall / hotspot / `EXPO_PUBLIC_API_URL` (step 6) |
| Expo Go says the project needs a newer/older SDK | Update Expo Go from the store. If it still doesn't match, use a development build (`eas build --profile development`) |
| Upload stays at *Queued* | The worker terminal (step 5) isn't running |
| Photo / scanned PDF fails | Install Tesseract; on Windows set `TESSERACT_CMD` in `backend/.env` |
| `.xls`/`.doc` fails | Install LibreOffice (or save as `.xlsx`/`.docx`) |
| Login says invalid credentials | Re-run step 4 (the seed resets the database) |
