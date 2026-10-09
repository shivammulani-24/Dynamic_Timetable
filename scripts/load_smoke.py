"""Concurrency smoke test against a running API seeded with demo data (development only).

It checks correctness under concurrent use (no 5xx, consistent answers per user); it is NOT a
capacity benchmark and its numbers must not be quoted as supported user counts.

    python scripts/load_smoke.py [base_url] [threads] [requests_per_thread]
"""
from __future__ import annotations

import statistics
import sys
import threading
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
THREADS = int(sys.argv[2]) if len(sys.argv) > 2 else 24
PER = int(sys.argv[3]) if len(sys.argv) > 3 else 15
USERS = ["alice", "bob", "chitra", "dev", "kkd", "avn", "pjb", "rhs", "principal", "admin"]
QUERIES = ["What is my next class?", "Show my timetable for this week", "Find all DBMS classes", "Is room 508 free now?",
           "Which professors teach SE-A?", "Do I have any classes left today?"]

tokens = {}
for u in USERS:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={"email": f"{u}@demo.college.edu", "password": "Demo@12345"}, timeout=20)
    r.raise_for_status()
    tokens[u] = r.json()["access_token"]

lat: list[float] = []
codes: dict[int, int] = {}
answers: dict[tuple[str, str], set] = {}
lock = threading.Lock()


def work(i: int) -> None:
    user = USERS[i % len(USERS)]
    h = {"Authorization": f"Bearer {tokens[user]}"}
    with httpx.Client(base_url=BASE, headers=h, timeout=30) as c:
        for k in range(PER):
            q = QUERIES[(i + k) % len(QUERIES)]
            t = time.perf_counter()
            if k % 5 == 4:
                r = c.get("/api/v1/dashboard", params={"domain": "INSTITUTIONAL"})
                key = None
            else:
                r = c.post("/api/v1/search", json={"query": q, "domain": "INSTITUTIONAL"})
                key = (user, q)
            dt = (time.perf_counter() - t) * 1000
            with lock:
                lat.append(dt)
                codes[r.status_code] = codes.get(r.status_code, 0) + 1
                if key and r.status_code < 500:
                    j = r.json()
                    stable = tuple(x.get("entry_id") or str({k: v for k, v in x.items() if k not in ("time", "date")}) for x in j["results"])
                    answers.setdefault(key, set()).add((j["status"], stable))


start = time.perf_counter()
ts = [threading.Thread(target=work, args=(i,)) for i in range(THREADS)]
[t.start() for t in ts]
[t.join() for t in ts]
wall = time.perf_counter() - start
lat.sort()
inconsistent = {k: v for k, v in answers.items() if len(v) > 1}
print(f"requests={len(lat)} threads={THREADS} wall={wall:.1f}s throughput={len(lat) / wall:.1f} req/s")
print(f"latency ms: p50={statistics.median(lat):.0f} p95={lat[int(len(lat) * 0.95) - 1]:.0f} max={lat[-1]:.0f}")
print(f"status codes: {codes}")
print(f"same question by same user gave different answers: {len(inconsistent)}")
sys.exit(1 if any(c >= 500 for c in codes) or inconsistent else 0)
