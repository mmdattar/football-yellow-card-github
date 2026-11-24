```python
import csv
import datetime
import io
import json
import os
import sys
import urllib.request

LEAGUE_CONFIG = {
    "eng.1": {"div": "E0", "tsdb": "4328", "line": 4.0},
    "esp.1": {"div": "SP1", "tsdb": "4335", "line": 4.5},
    "ita.1": {"div": "I1", "tsdb": "4332", "line": 4.5},
    "ger.1": {"div": "D1", "tsdb": "4331", "line": 4.0},
    "fra.1": {"div": "F1", "tsdb": "4334", "line": 4.0},
}

SEASONS_TO_TRY = ["2627", "2526", "2425"]
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"


def http_get_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json,text/csv,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8-sig", errors="replace")


def fetch_csv_rows(url: str) -> list:
    raw = http_get_text(url)
    reader = csv.DictReader(io.StringIO(raw))
    return [row for row in reader if row.get("HomeTeam") and row.get("AwayTeam")]


def safe_int(val, default=None):
    try:
        if val is None or str(val).strip() == "":
            return default
        return int(float(str(val).strip()))
    except ValueError:
        return default


def fetch_league_completed(div_code: str):
    for season in SEASONS_TO_TRY:
        url = f"https://www.football-data.co.uk/mmz4281/{season}/{div_code}.csv"
        try:
            rows = fetch_csv_rows(url)
            if rows:
                print(f"[OK] {div_code} season {season}: {len(rows)} completed matches")
                return season, rows
        except Exception as exc:
            print(f"[INFO] {div_code} season {season} skipped: {exc}")
    return "", []


def fetch_upcoming_from_fduk() -> dict:
    by_div = {cfg["div"]: [] for cfg in LEAGUE_CONFIG.values()}
    try:
        rows = fetch_csv_rows(FIXTURES_URL)
        for row in rows:
            div = (row.get("Div") or "").strip()
            if div in by_div:
                by_div[div].append(row)
        print(f"[OK] fixtures.csv loaded: {sum(len(v) for v in by_div.values())} upcoming matches")
    except Exception as exc:
        print(f"[WARN] fixtures.csv failed: {exc}")
    return by_div


def fetch_upcoming_from_tsdb(league_key: str, tsdb_id: str, market_line: float) -> list:
    url = f"https://www.thesportsdb.com/api/v1/json/3/eventsnextleague.php?id={tsdb_id}"
    upcoming = []
    try:
        data = json.loads(http_get_text(url))
        events = data.get("events") or []
        for idx, ev in enumerate(events[:15]):
            home = (ev.get("strHomeTeam") or "").strip()
            away = (ev.get("strAwayTeam") or "").strip()
            if not home or not away:
                continue
            date_s = (ev.get("dateEvent") or "").strip()
            time_s = (ev.get("strTime") or "").strip()[:5]
            dt_label = f"{date_s} {time_s}".strip() or "پیش رو"
            upcoming.append({
                "id": f"tsdb-up-{league_key}-{ev.get('idEvent', idx)}",
                "home": home,
                "away": away,
                "date": dt_label,
                "status": "upcoming",
                "isLive": False,
                "score": "در پیش رو",
                "venue": (ev.get("strVenue") or "ورزشگاه رسمی").strip(),
                "referee": "",
                "refAssignedByApi": False,
                "stateVal": 0,
                "crowdVal": 6,
                "varVal": 5,
                "marketLine": market_line,
                "actualYc": None,
                "source": "TheSportsDB (Upcoming)",
            })
        print(f"[OK] TheSportsDB upcoming {league_key}: {len(upcoming)} matches")
    except Exception as exc:
        print(f"[WARN] TheSportsDB upcoming {league_key} failed: {exc}")
    return upcoming


def fetch_upcoming_from_espn(league_key: str, market_line: float) -> list:
    """Fallback: fetches active/next matchweek from ESPN default scoreboard."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_key}/scoreboard"
    upcoming = []
    try:
        data = json.loads(http_get_text(url))
        for idx, ev in enumerate(data.get("events", [])):
            st = ev.get("status", {}).get("type", {}).get("state", "pre")
            if st == "post":
                continue
            comp = (ev.get("competitions") or [{}])[0]
            competitors = comp.get("competitors") or []
            home_obj = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0] if competitors else {})
            away_obj = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})
            officials = comp.get("officials") or []
            ref_name = officials[0].get("displayName", "") if officials else ""
            date_iso = ev.get("date", "")
            date_label = date_iso[:16].replace("T", " ") if date_iso else "پیش رو"
            is_live = st == "in"
            upcoming.append({
                "id": f"espn-up-{league_key}-{ev.get('id', idx)}",
                "home": home_obj.get("team", {}).get("displayName", "میزبان"),
                "away": away_obj.get("team", {}).get("displayName", "میهمان"),
                "date": date_label,
                "status": "upcoming",
                "isLive": is_live,
                "score": f"{home_obj.get('score', 0)} - {away_obj.get('score', 0)}" if is_live else "در پیش رو",
                "venue": comp.get("venue", {}).get("fullName", "ورزشگاه رسمی"),
                "referee": ref_name,
                "refAssignedByApi": bool(ref_name),
                "stateVal": 0,
                "crowdVal": 6,
                "varVal": 5,
                "marketLine": market_line,
                "actualYc": None,
                "source": "ESPN (Upcoming)",
            })
        print(f"[OK] ESPN default upcoming {league_key}: {len(upcoming)} matches")
    except Exception as exc:
        print(f"[WARN] ESPN default upcoming {league_key} failed: {exc}")
    return upcoming


def main() -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    upcoming_by_div = fetch_upcoming_from_fduk()

    output = {
        "updatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "football-data.co.uk + TheSportsDB",
        "leagues": {},
        "referees": [],
    }

    ref_agg = {}
    total_matches = 0

    for league_key, cfg in LEAGUE_CONFIG.items():
        div_code = cfg["div"]
        market_line = cfg["line"]
        season, completed_rows = fetch_league_completed(div_code)

        for r in completed_rows:
            ref = (r.get("Referee") or "").strip()
            hy = safe_int(r.get("HY"))
            ay = safe_int(r.get("AY"))
            hf = safe_int(r.get("HF"))
            af = safe_int(r.get("AF"))
            if ref and hy is not None and ay is not None:
                entry = ref_agg.setdefault(ref, {"matches": 0, "yc": 0, "fouls": 0, "fouls_n": 0})
                entry["matches"] += 1
                entry["yc"] += hy + ay
                if hf is not None and af is not None:
                    entry["fouls"] += hf + af
                    entry["fouls_n"] += 1

        matches = []

        # 1. Triple-fallback upcoming matches: football-data.co.uk -> TheSportsDB -> ESPN default
        fduk_up = upcoming_by_div.get(div_code, [])[:20]
        if fduk_up:
            for idx, r in enumerate(fduk_up):
                date_str = (r.get("Date") or "").strip()
                time_str = (r.get("Time") or "").strip()
                dt_label = f"{date_str} {time_str}".strip() or "پیش رو"
                matches.append({
                    "id": f"fduk-up-{league_key}-{idx}",
                    "home": r["HomeTeam"].strip(),
                    "away": r["AwayTeam"].strip(),
                    "date": dt_label,
                    "status": "upcoming",
                    "isLive": False,
                    "score": "در پیش رو",
                    "venue": "مسابقه رسمی لیگ",
                    "referee": (r.get("Referee") or "").strip(),
                    "refAssignedByApi": bool((r.get("Referee") or "").strip()),
                    "stateVal": 0,
                    "crowdVal": 6,
                    "varVal": 5,
                    "marketLine": market_line,
                    "actualYc": None,
                    "source": "football-data.co.uk (Upcoming)",
                })
        else:
            tsdb_up = fetch_upcoming_from_tsdb(league_key, cfg["tsdb"], market_line)
            if tsdb_up:
                matches.extend(tsdb_up)
            else:
                matches.extend(fetch_upcoming_from_espn(league_key, market_line))

        # 2. Most recent 20 completed matches (newest first)
        recent_completed = list(reversed(completed_rows[-20:]))
        for idx, r in enumerate(recent_completed):
            fthg = safe_int(r.get("FTHG"), 0)
            ftag = safe_int(r.get("FTAG"), 0)
            hy = safe_int(r.get("HY"))
            ay = safe_int(r.get("AY"))
            actual_yc = (hy + ay) if (hy is not None and ay is not None) else None
            ref = (r.get("Referee") or "").strip()
            diff = abs(fthg - ftag)
            state_val = -2 if diff >= 3 else (-1 if diff == 2 else 1)

            matches.append({
                "id": f"fduk-past-{league_key}-{idx}",
                "home": r["HomeTeam"].strip(),
                "away": r["AwayTeam"].strip(),
                "date": (r.get("Date") or "پایان‌یافته").strip(),
                "status": "past",
                "isLive": False,
                "score": f"{fthg} - {ftag}",
                "venue": f"فصل {season}" if season else "مسابقه لیگ",
                "referee": ref,
                "refAssignedByApi": bool(ref),
                "stateVal": state_val,
                "crowdVal": 6,
                "varVal": 5,
                "marketLine": market_line,
                "actualYc": actual_yc,
                "source": "football-data.co.uk",
            })

        output["leagues"][league_key] = matches
        total_matches += len(matches)

    for name, st in sorted(ref_agg.items(), key=lambda x: x[1]["matches"], reverse=True):
        m_cnt = st["matches"]
        output["referees"].append({
            "id": name.lower().replace(" ", "-"),
            "name": name,
            "matches": m_cnt,
            "yc": st["yc"],
            "ycpg": round(st["yc"] / m_cnt, 2),
            "foulsPg": round(st["fouls"] / st["fouls_n"], 2) if st["fouls_n"] > 0 else None,
        })

    if total_matches == 0:
        print("[ERROR] No matches fetched!")
        sys.exit(1)

    os.makedirs("data", exist_ok=True)
    with open("data/matches.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[SUCCESS] Wrote {total_matches} matches and {len(output['referees'])} referees to data/matches.json")


if __name__ == "__main__":
    main()
```
