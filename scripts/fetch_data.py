import csv
import datetime
import io
import json
import os
import sys
import urllib.request

LEAGUE_CONFIG = {
    "eng.1": {"div": "E0", "of": "en.1", "line": 4.0},
    "esp.1": {"div": "SP1", "of": "es.1", "line": 4.5},
    "ita.1": {"div": "I1", "of": "it.1", "line": 4.5},
    "ger.1": {"div": "D1", "of": "de.1", "line": 4.0},
    "fra.1": {"div": "F1", "of": "fr.1", "line": 4.0},
    "uefa.champions": {"div": None, "of": "uefa.cl", "line": 4.5},
}

SEASONS_FDUK = ["2627", "2526", "2425"]
SEASONS_OF = ["2026-27", "2025-26"]
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
    if not div_code:
        return "", []
    for season in SEASONS_FDUK:
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
    by_div = {cfg["div"]: [] for cfg in LEAGUE_CONFIG.values() if cfg["div"]}
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


def fetch_from_openfootball(league_key: str, of_code: str, market_line: float):
    """Returns (upcoming_list, past_list) from openfootball/football.json."""
    today_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    for season in SEASONS_OF:
        url = f"https://raw.githubusercontent.com/openfootball/football.json/master/{season}/{of_code}.json"
        try:
            data = json.loads(http_get_text(url))
            raw_matches = data.get("matches") or []
            upcoming = []
            past = []
            for idx, m in enumerate(raw_matches):
                dt = (m.get("date") or "").strip()
                score = m.get("score") or {}
                ft = score.get("ft")
                home = (m.get("team1") or "").strip()
                away = (m.get("team2") or "").strip()
                if not home or not away:
                    continue
                t = (m.get("time") or "").strip()
                dt_label = f"{dt} {t}".strip() or "نامشخص"
                round_name = (m.get("round") or "مسابقه رسمی").strip()

                if isinstance(ft, list) and len(ft) == 2:
                    h_sc, a_sc = safe_int(ft[0], 0), safe_int(ft[1], 0)
                    diff = abs(h_sc - a_sc)
                    state_val = -2 if diff >= 3 else (-1 if diff == 2 else 1)
                    past.append({
                        "id": f"of-past-{league_key}-{idx}",
                        "home": home,
                        "away": away,
                        "date": dt_label,
                        "status": "past",
                        "isLive": False,
                        "score": f"{h_sc} - {a_sc}",
                        "venue": round_name,
                        "referee": "",
                        "refAssignedByApi": False,
                        "stateVal": state_val,
                        "crowdVal": 6,
                        "varVal": 5,
                        "marketLine": market_line,
                        "actualYc": None,
                        "source": f"OpenFootball ({season})",
                    })
                elif not dt or dt >= today_iso:
                    if len(upcoming) < 15:
                        upcoming.append({
                            "id": f"of-up-{league_key}-{idx}",
                            "home": home,
                            "away": away,
                            "date": dt_label,
                            "status": "upcoming",
                            "isLive": False,
                            "score": "در پیش رو",
                            "venue": round_name,
                            "referee": "",
                            "refAssignedByApi": False,
                            "stateVal": 0,
                            "crowdVal": 6,
                            "varVal": 5,
                            "marketLine": market_line,
                            "actualYc": None,
                            "source": f"OpenFootball ({season})",
                        })
            if upcoming or past:
                print(f"[OK] OpenFootball {of_code} ({season}): {len(upcoming)} upcoming, {len(past)} past")
                return upcoming, list(reversed(past[-20:]))
        except Exception as exc:
            print(f"[INFO] OpenFootball {of_code} ({season}) skipped: {exc}")
    return [], []


def fetch_from_espn_window(league_key: str, market_line: float, days_back: int = 0, days_ahead: int = 14):
    """Fetches matches day-by-day from ESPN on GitHub Actions server."""
    now = datetime.datetime.now(datetime.timezone.utc)
    seen = set()
    upcoming = []
    past = []
    for offset in range(-days_back, days_ahead + 1):
        day_str = (now + datetime.timedelta(days=offset)).strftime("%Y%m%d")
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_key}/scoreboard?dates={day_str}"
        try:
            data = json.loads(http_get_text(url))
            for ev in data.get("events", []):
                ev_id = str(ev.get("id", ""))
                if not ev_id or ev_id in seen:
                    continue
                seen.add(ev_id)
                st = ev.get("status", {}).get("type", {}).get("state", "pre")
                is_past = st == "post"
                is_live = st == "in"
                comp = (ev.get("competitions") or [{}])[0]
                competitors = comp.get("competitors") or []
                home_obj = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0] if competitors else {})
                away_obj = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})
                officials = comp.get("officials") or []
                ref_name = officials[0].get("displayName", "") if officials else ""
                date_iso = ev.get("date", "")
                date_label = date_iso[:16].replace("T", " ") if date_iso else day_str
                if is_live:
                    date_label = f"زنده ({ev.get('status', {}).get('displayClock', '')})"

                actual_yc = None
                if (is_past or is_live) and isinstance(comp.get("details"), list):
                    actual_yc = sum(
                        1 for d in comp["details"]
                        if d.get("yellowCard") is True or "yellow" in (d.get("type", {}).get("text", "")).lower()
                    )

                h_sc = safe_int(home_obj.get("score"), 0)
                a_sc = safe_int(away_obj.get("score"), 0)
                diff = abs(h_sc - a_sc)
                state_val = (-2 if diff >= 3 else (-1 if diff == 2 else 1)) if is_past else 0

                item = {
                    "id": f"espn-{league_key}-{ev_id}",
                    "home": home_obj.get("team", {}).get("displayName", "میزبان"),
                    "away": away_obj.get("team", {}).get("displayName", "میهمان"),
                    "date": date_label,
                    "status": "past" if is_past else "upcoming",
                    "isLive": is_live,
                    "score": f"{h_sc} - {a_sc}" if (is_past or is_live) else "در پیش رو",
                    "venue": comp.get("venue", {}).get("fullName", "ورزشگاه رسمی"),
                    "referee": ref_name,
                    "refAssignedByApi": bool(ref_name),
                    "stateVal": state_val,
                    "crowdVal": 7 if league_key == "uefa.champions" else 6,
                    "varVal": 6 if league_key == "uefa.champions" else 5,
                    "marketLine": market_line,
                    "actualYc": actual_yc,
                    "source": "ESPN (Server)",
                }
                if is_past:
                    past.append(item)
                else:
                    upcoming.append(item)
        except Exception:
            continue
    print(f"[OK] ESPN {league_key}: {len(upcoming)} upcoming, {len(past)} past")
    return upcoming[:15], list(reversed(past))[:20]


def main() -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    upcoming_by_div = fetch_upcoming_from_fduk()

    output = {
        "updatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "football-data.co.uk + OpenFootball + ESPN",
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

        of_up, of_past = fetch_from_openfootball(league_key, cfg["of"], market_line)
        matches = []

        # 1. Upcoming matches
        fduk_up = upcoming_by_div.get(div_code, [])[:20] if div_code else []
        if len(fduk_up) >= 5:
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
        elif len(of_up) >= 5:
            matches.extend(of_up)
        else:
            espn_up, espn_past_extra = fetch_from_espn_window(
                league_key, market_line,
                days_back=14 if not completed_rows else 0,
                days_ahead=14,
            )
            matches.extend(espn_up if len(espn_up) >= len(of_up) else of_up)
            if not completed_rows and not of_past and espn_past_extra:
                of_past = espn_past_extra

        # 2. Completed matches (football-data.co.uk preferred for real HY+AY yellow cards & referee)
        if completed_rows:
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
        elif of_past:
            matches.extend(of_past)

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
