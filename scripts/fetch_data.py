import csv
import datetime
import io
import json
import os
import sys
import urllib.request

LEAGUE_DIVS = {
    "eng.1": "E0",
    "esp.1": "SP1",
    "ita.1": "I1",
    "ger.1": "D1",
    "fra.1": "F1",
}

SEASONS_TO_TRY = ["2627", "2526", "2425"]
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"


def fetch_csv_rows(url: str) -> list:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/csv,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        raw = resp.read().decode("utf-8-sig", errors="replace")
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


def fetch_upcoming_fixtures() -> dict:
    by_div = {v: [] for v in LEAGUE_DIVS.values()}
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


def main() -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    upcoming_by_div = fetch_upcoming_fixtures()

    output = {
        "updatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "football-data.co.uk",
        "leagues": {},
        "referees": [],
    }

    ref_agg = {}
    total_matches = 0

    for league_key, div_code in LEAGUE_DIVS.items():
        season, completed_rows = fetch_league_completed(div_code)
        market_line = 4.5 if league_key in ("esp.1", "ita.1") else 4.0

        # Aggregate real referee yellow card & foul stats from full season
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

        # 1. Upcoming fixtures first
        for idx, r in enumerate(upcoming_by_div.get(div_code, [])[:20]):
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

    # Save aggregated referee stats
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
        print("[ERROR] No matches fetched from football-data.co.uk!")
        sys.exit(1)

    os.makedirs("data", exist_ok=True)
    with open("data/matches.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[SUCCESS] Wrote {total_matches} matches and {len(output['referees'])} referees to data/matches.json")


if __name__ == "__main__":
    main()
