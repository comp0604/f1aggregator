from flask import Flask, render_template, jsonify, request
import sqlite3
import os
import urllib.request
import json
import ssl
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()  

app = Flask(__name__)

# 💾 인메모리 캐시 (외부 API 제한 완벽 우회용)
OPENF1_PODIUM_CACHE = {}
STANDINGS_CACHE = {"data": None, "updated_at": None}

def get_db_connection():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, 'f1_news.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def get_team_color(constructor_id, constructor_name):
    c_id = (constructor_id or "").lower().replace(" ", "").replace("_", "").replace("-", "")
    name = (constructor_name or "").lower().replace(" ", "").replace("_", "").replace("-", "")
    if "ferrari" in c_id or "ferrari" in name: return "#cc0000"
    if "mclaren" in c_id or "mclaren" in name: return "#ff8700"
    if "redbull" in c_id or "redbull" in name: return "#061043"
    if "mercedes" in c_id or "mercedes" in name: return "#00a19c"
    if "aston" in c_id or "aston" in name: return "#006f62"
    if "alpine" in c_id or "alpine" in name: return "#0090ff"
    if "williams" in c_id or "williams" in name: return "#005aff"
    if "haas" in c_id or "haas" in name: return "#787878"
    if "audi" in c_id or "audi" in name or "sauber" in c_id or "sauber" in name: return "#c41130"
    if "cadillac" in c_id or "cadillac" in name or "andretti" in c_id or "andretti" in name: return "#243345"
    if "rb" in c_id or "rb" in name or "racingbulls" in c_id or "racingbulls" in name: return "#002fa7"
    return "#555555"

def get_flag_url(country_name):
    name = (country_name or "").lower().strip()
    mapping = {
        "australia": "au", "bahrain": "bh", "saudi arabia": "sa", "japan": "jp", "china": "cn",
        "usa": "us", "united states": "us", "monaco": "mc", "spain": "es", "canada": "ca",
        "austria": "at", "uk": "gb", "united kingdom": "gb", "great britain": "gb", "hungary": "hu",
        "belgium": "be", "netherlands": "nl", "italy": "it", "azerbaijan": "az", "singapore": "sg",
        "mexico": "mx", "brazil": "br", "qatar": "qa", "uae": "ae", "united arab emirates": "ae"
    }
    return f"https://flagcdn.com/w1280/{mapping.get(name, 'un')}.png"

def fetch_json_safely(url):
    try:
        ssl_context = ssl._create_unverified_context()
        req = urllib.request.Request(url, headers={'User-Agent': 'LecLovF1/1.0 Python/3.x'})
        with urllib.request.urlopen(req, timeout=5, context=ssl_context) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"⚠️ API 요청 실패 ({url}): {e}")
        return {}

def fetch_openf1_fallback(locality, race_date):
    try:
        year = race_date.split("-")[0] if race_date else "2026"
        sessions = fetch_json_safely(f"https://api.openf1.org/v1/sessions?year={year}&session_name=Race")
        if not isinstance(sessions, list) or not sessions: return None
        
        loc_mapping = {"monte-carlo": "monaco", "montmeló": "barcelona", "marina bay": "singapore"}
        mapped_loc = loc_mapping.get(locality.lower(), locality.lower())
        matched = next((s for s in sessions if mapped_loc in s.get("location", "").lower() or s.get("date_start", "").startswith(race_date)), None)
        if not matched: return None
        
        s_key = matched["session_key"]
        results = fetch_json_safely(f"https://api.openf1.org/v1/session_result?session_key={s_key}")
        drivers = fetch_json_safely(f"https://api.openf1.org/v1/drivers?session_key={s_key}")
        if not isinstance(results, list) or not isinstance(drivers, list): return None
        
        valid = []
        for r in results:
            pos = r.get("position") or r.get("position_current")
            if pos and 1 <= pos <= 3: valid.append((pos, r))
            
        podium = []
        for pos, r in sorted(valid, key=lambda x: x[0]):
            d = next((dr for d in drivers if dr.get("driver_number") == r.get("driver_number")), {})
            podium.append({
                "position": str(pos), "familyName": d.get("last_name") or "Driver",
                "constructorId": (d.get("team_name") or "").lower().replace(" ", ""),
                "constructorName": d.get("team_name") or "Unknown",
                "wiki_title": (d.get("full_name") or "").replace(" ", "_")
            })
        return podium
    except Exception as e:
        print(f"🚨 OpenF1 Fallback Error: {e}")
        return None

@app.route('/')
def index():
    conn = get_db_connection()
    articles = conn.execute('SELECT title, link, summary_ko, image_url, published_at FROM articles ORDER BY published_at DESC LIMIT 10').fetchall()
    conn.close()
    return render_template('index.html', articles=articles)

@app.route('/calendar')
def calendar_page(): return render_template('calendar.html')

@app.route('/standings')
def standings_page(): return render_template('standings.html')

@app.route('/api/calendar-list')
def api_calendar_list():
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    raw_cal = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current.json")
    races = raw_cal.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    
    if not races: return jsonify({"error": "데이터 공급 지연", "races": []})
    
    raw_res = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current/results.json?limit=1000")
    res_races = raw_res.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    res_map = {r.get("round"): r.get("Results", []) for r in res_races}
    
    next_idx = next((i for i, r in enumerate(races) if r.get("date", "") >= today_str), len(races) - 1)
    payload = []
    
    for idx, race in enumerate(races):
        r_num = race.get("round")
        c_date = race.get("date", "")
        is_past = (c_date < today_str or r_num in res_map)
        w_name, t_color, w_wiki = "", "#1a1c1e", ""
        
        podium = res_map.get(r_num, [])
        if podium:
            w_name = podium[0].get("Driver", {}).get("familyName", "")
            t_color = get_team_color(podium[0].get("Constructor", {}).get("constructorId"), podium[0].get("Constructor", {}).get("name"))
            w_wiki = podium[0].get("Driver", {}).get("url", "").split('/wiki/')[-1]
        elif is_past and r_num in OPENF1_PODIUM_CACHE:
            p_data = OPENF1_PODIUM_CACHE[r_num].get("podium", [])
            if p_data:
                w_name = p_data[0].get("familyName", "")
                t_color = get_team_color(p_data[0].get("constructorId"), p_data[0].get("constructorName"))
                w_wiki = p_data[0].get("wiki_title", "")

        payload.append({
            "idx": idx, "round": r_num, "raceName": race.get("raceName", "GP"),
            "locality": race.get("Circuit", {}).get("Location", {}).get("locality", ""),
            "country": race.get("Circuit", {}).get("Location", {}).get("country", ""),
            "date": c_date, "is_past": is_past, "is_next": (idx == next_idx),
            "winner_name": w_name, "team_color": t_color, "winner_wiki": w_wiki,
            "flag_url": get_flag_url(race.get("Circuit", {}).get("Location", {}).get("country", "")),
            "circuit_wiki_title": race.get("Circuit", {}).get("url", "").split('/wiki/')[-1],
            "circuit_name": race.get("Circuit", {}).get("circuitName", "")
        })
    return jsonify({"next_race_idx": next_idx, "races": payload})

@app.route('/api/race-podium/<round_num>')
def api_race_podium(round_num):
    if round_num in OPENF1_PODIUM_CACHE and "pole" in OPENF1_PODIUM_CACHE[round_num]:
        return jsonify(OPENF1_PODIUM_CACHE[round_num])
        
    payload = {"podium": [], "pole": "", "fastest_lap": "", "sprint_winner": ""}
    raw_res = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/current/{round_num}/results.json")
    r_races = raw_res.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    
    if r_races:
        results = r_races[0].get("Results", [])
        payload["podium"] = [{
            "position": p.get("position"), "familyName": p.get("Driver", {}).get("familyName", ""),
            "constructorId": p.get("Constructor", {}).get("constructorId", ""), "constructorName": p.get("Constructor", {}).get("name", ""),
            "wiki_title": p.get("Driver", {}).get("url", "").split('/wiki/')[-1]
        } for p in results[:3]]
        
        pole = next((r for r in results if r.get("grid") == "1"), None)
        fl = next((r for r in results if r.get("FastestLap", {}).get("rank") == "1"), None)
        if pole: payload["pole"] = pole["Driver"]["familyName"]
        if fl: payload["fastest_lap"] = fl["Driver"]["familyName"]
    else:
        raw_cal = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current.json")
        races = raw_cal.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        race = next((r for r in races if r.get("round") == round_num), None)
        if race:
            op = fetch_openf1_fallback(race.get("Circuit", {}).get("Location", {}).get("locality", ""), race.get("date", ""))
            if op: payload["podium"] = op

    raw_sprint = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/current/{round_num}/sprint.json")
    s_races = raw_sprint.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    if s_races and s_races[0].get("SprintResults"):
        payload["sprint_winner"] = s_races[0]["SprintResults"][0]["Driver"]["familyName"]

    OPENF1_PODIUM_CACHE[round_num] = payload
    return jsonify(payload)

@app.route('/api/race-sessions/<round_num>')
def api_race_sessions(round_num):
    season = request.args.get('season', 'current')
    payload = {"schedule": {}, "qualifying": [], "sprint": [], "race": []}
    
    raw_cal = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/{season}.json")
    races = raw_cal.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    race = next((r for r in races if r.get("round") == round_num), None)
    
    if race:
        payload["schedule"] = {
            "fp1": race.get("FirstPractice", {}).get("date", "-"), "fp2": race.get("SecondPractice", {}).get("date", "-"),
            "fp3": race.get("ThirdPractice", {}).get("date", "-"), "qualifying": race.get("Qualifying", {}).get("date", "-"),
            "sprint": race.get("Sprint", {}).get("date", "-"), "race": race.get("date", "-")
        }
    
    raw_q = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/{season}/{round_num}/qualifying.json")
    q_races = raw_q.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    if q_races and q_races[0].get("QualifyingResults"):
        payload["qualifying"] = [{
            "position": q.get("position"), "driver": f"{q['Driver']['givenName']} {q['Driver']['familyName']}",
            "constructor": q["Constructor"]["name"], "time": q.get("Q3") or q.get("Q2") or q.get("Q1") or "-"
        } for q in q_races[0]["QualifyingResults"][:5]]

    raw_s = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/{season}/{round_num}/sprint.json")
    s_races = raw_s.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    if s_races and s_races[0].get("SprintResults"):
        payload["sprint"] = [{
            "position": s.get("position"), "driver": f"{s['Driver']['givenName']} {s['Driver']['familyName']}",
            "constructor": s["Constructor"]["name"], "points": s.get("points", "0")
        } for s in s_races[0]["SprintResults"][:5]]

    raw_r = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/{season}/{round_num}/results.json")
    r_races = raw_r.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    if r_races and r_races[0].get("Results"):
        payload["race"] = [{
            "position": r.get("position"), "driver": f"{r['Driver']['givenName']} {r['Driver']['familyName']}",
            "constructor": r["Constructor"]["name"], "points": r.get("points", "0")
        } for r in r_races[0]["Results"][:5]]

    return jsonify(payload)

@app.route('/api/standings-data')
def api_standings_data():
    raw_d = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current/driverStandings.json")
    raw_c = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current/constructorStandings.json")
    raw_res = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current/results.json?limit=1000")
    
    d_list = raw_d.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [{}])[0].get("DriverStandings", [])
    c_list = raw_c.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [{}])[0].get("ConstructorStandings", [])
    
    p_drivers, p_constructors = {}, {}
    if raw_res and "MRData" in raw_res:
        races = raw_res.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        for r in races:
            for res in r.get("Results", []):
                if int(res.get("position", 99)) <= 3:
                    d_id = res.get("Driver", {}).get("driverId")
                    c_id = res.get("Constructor", {}).get("constructorId")
                    if d_id: p_drivers[d_id] = p_drivers.get(d_id, 0) + 1
                    if c_id: p_constructors[c_id] = p_constructors.get(c_id, 0) + 1

    return jsonify({"drivers": d_list, "constructors": c_list, "podiums": {"drivers": p_drivers, "constructors": p_constructors}})

@app.route('/api/wiki-meta/<page_title>')
def api_wiki_meta(page_title):
    data = fetch_json_safely(f"https://en.wikipedia.org/api/rest_v1/page/summary/{page_title}")
    return jsonify({
        "extract": data.get("extract", "정보가 없습니다."),
        "image": data.get("originalimage", {}).get("source") or data.get("thumbnail", {}).get("source") or ""
    })

if __name__ == '__main__':
    app.run(debug=True, port=5001)