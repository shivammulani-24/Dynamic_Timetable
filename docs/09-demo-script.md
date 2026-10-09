# 10-minute demo script

Setup: `scripts/dev.sh seed`, API + worker running, app open on a phone/emulator. Password for all
demo users: `Demo@12345`.

1. **Student (alice@demo.college.edu)** — Home shows *Right now* / *Next* with a countdown; point out
   that the next class is her lab group's (A1), not A2's. Open **Timetable**: week strip, timeline,
   *Unverified* / *Tentative* tags. Tap a class → details with raw source text and page.
2. **Ask tab** — "Find all DBMS classes" → results. "Am I free at 2?" → AM/PM question → choose
   2:00 PM → date question → Today → answer. "Is room 702-B free at 12:30 pm today?" → *Cannot
   confirm* because the source's noon row label is inconsistent. "Compare my personal and college
   timetable" → clearly not supported.
3. **Domain separation** — switch to **Personal**: answers now come from her own upload (teal accent,
   timetable name shown). Log in as **bob** → Personal → no primary → upload prompt; nothing falls
   back to the college timetable.
4. **No batch yet (newbie)** — "What is my next class?" → *setup required* explanation.
5. **HOD (kkd)** — Home shows his teaching, free periods and the conflicts banner → Conflicts screen
   (POSSIBLE vs CONFIRMED). Quick action **Floor activity** → floor 5.
6. **Admin (admin)** — System stats. **Upload official timetable** → choose the synthetic PDF (or
   the real one) → watch *Uploaded → Extracting → Needs review* → validation summary. Open it →
   extraction summary, sections (Tentative), **Review & correct**: verify the 12:15 entry after
   checking the raw label; the change is audited. **Activate as official timetable** → confirm →
   users get a notification.
7. **Admin tools** — Rooms (floor needed for free-room search), Aliases, Institution settings
   (week start, lunch, working hours), Users (roles, suspend), Academic promotion (preview →
   confirm; history kept), Audit log (shows the activation, correction and any access-denied events).
8. Close with the architecture slide: same engine powers the dashboard and the chat; no arbitrary
   SQL; strict domain isolation; uncertainty is shown, never hidden.
