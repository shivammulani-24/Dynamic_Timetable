from __future__ import annotations

from app.worker import drain


def upload(client, headers, path, domain="PERSONAL", **form):
    with open(path, "rb") as fh:
        data = {"domain": domain, **{k: str(v) for k, v in form.items() if v is not None}}
        name = form.pop("filename", None) or path.rsplit("/", 1)[-1]
        return client.post("/api/v1/timetables/uploads", headers=headers, data=data, files={"file": (name, fh.read())})


def upload_and_process(client, headers, path, domain="PERSONAL", **form) -> dict:
    r = upload(client, headers, path, domain, **form)
    assert r.status_code == 201, r.text
    drain()
    got = client.get(f"/api/v1/timetables/{r.json()['timetable_id']}", params={"domain": domain}, headers=headers)
    assert got.status_code == 200, got.text
    return got.json()
