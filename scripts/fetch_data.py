import datetime
import json
import os
import urllib.request

LEAGUES = [
    "eng.1",
    "esp.1",
    "ita.1",
    "ger.1",
    "fra.1",
    "uefa.champions",
]

BASE_AVG = {
    "eng.1": 3.85,
    "esp.1": 4.55,
    "ita.1": 4.35,
    "ger.1": 3.80,
    "fra.1": 3.75,
    "uefa.champions": 4.16,
}


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Football-Yellow-Card-Analyzer/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_league(league_code: str, date_range: str) -> list:
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/"
        f"{league_code}/scoreboard?dates={date_range}"
    )
    data = fetch_json(url)
    events = data.get("events", [])
    matches = []

    for idx, ev in enumerate(events):
        comp = (ev.get("competitions") or [{}])[0]
        competitors = comp.get("competitors") or []
        home_obj = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0] if competitors else {})
        away_obj = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})

        status_type = ev.get("status", {}).get("type", {}).get("state", "pre")
        is_past = status_type == "post"
        is_live = status_type == "in"

        actual_yc = None
        details = comp.get("details") or []
        if is_past or is_live:
            ycs = [
                d for d in details
                if d.get("yellowCard") is True
                or "yellow" in (d.get("type", {}).get("text", "")).lower()
            ]
            actual_yc = len(ycs)

        officials = comp.get("officials") or []
        ref_name = officials[0].get("displayName", "") if officials else ""

        state_val = 0
        if is_past and home_obj.get("score") is not None and away_obj.get("score") is not None:
            try:
                diff = abs(int(home_obj["score"]) - int(away_obj["score"]))
                state_val = -2 if diff >= 3 else (-1 if diff == 2 else 1)
            except ValueError:
                state_val = 0

        date_iso = ev.get("date", "")
        date_display = date_iso[:16].replace("T", " ") if date_iso else "نامشخص"
        if is_live:
            clock = ev.get("status", {}).get("displayClock", "")
            date_display = f"زنده ({clock})"

        matches.append({
            "id": f"gh-{league_code}-{ev.get('id', idx)}",
            "home": home_obj.get("team", {}).get("displayName", "میزبان"),
            "away": away_obj.get("team", {}).get("displayName", "میهمان"),
            "date": date_display,
            "status": "past" if is_past else "upcoming",
            "isLive": is_live,
            "score": f"{home_obj.get('score', 0)} - {away_obj.get('score', 0)}" if (is_past or is_live) else "در پیش رو",
            "venue": comp.get("venue", {}).get("fullName", "ورزشگاه رسمی"),
            "referee": ref_name,
            "refAssignedByApi": bool(ref_name),
            "stateVal": state_val,
            "crowdVal": 6,
            "varVal": 5,
            "marketLine": 4.5 if league_code in ("esp.1", "ita.1") else 4.0,
            "actualYc": actual_yc,
            "source": "GitHub Actions (ESPN)",
        })

    return matches


def main() -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    start = (now - datetime.timedelta(days=14)).strftime("%Y%m%d")
    end = (now + datetime.timedelta(days=14)).strftime("%Y%m%d")
    date_range = f"{start}-{end}"

    output = {
        "updatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dateRange": date_range,
        "leagues": {},
    }

    for league in LEAGUES:
        try:
            output["leagues"][league] = parse_league(league, date_range)
            print(f"[OK] {league}: {len(output['leagues'][league])} matches")
        except Exception as exc:
            print(f"[WARN] {league} failed: {exc}")
            output["leagues"][league] = []

    os.makedirs("data", exist_ok=True)
    with open("data/matches.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
