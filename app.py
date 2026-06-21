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

# 💾 서버 메모리 캐시 (API Rate Limit 완벽 방어용)
OPENF1_PODIUM_CACHE = {}
STANDINGS_CACHE = {"data": None}

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
    return "#1a1c1e"

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
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'LecLovF1/1.0 (contact@leclovf1.com) Python/3.x'}
        )
        with urllib.request.urlopen(req, timeout=4, context=ssl_context) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"⚠️ API 통신 지연/실패 ({url}): {e}")
        return None

def fetch_openf1_fallback(locality, race_date):
    try:
        year = race_date.split("-")[0] if race_date else "2026"
        sessions = fetch_json_safely(f"https://api.openf1.org/v1/sessions?year={year}&session_name=Race")
        if not isinstance(sessions, list): return None
        
        loc_mapping = {
            "monte-carlo": "monaco", "montmeló": "barcelona", "marina bay": "singapore",
            "abu dhabi": "yas island", "são paulo": "sao paulo", "mexico city": "mexico city"
        }
        mapped_loc = loc_mapping.get(locality.lower(), locality.lower())
        matched = next((s for s in sessions if mapped_loc in s.get("location", "").lower() or s.get("date_start", "").startswith(race_date)), None)
        if not matched: return None
        session_key = matched["session_key"]
        
        results = fetch_json_safely(f"https://api.openf1.org/v1/session_result?session_key={session_key}")
        drivers = fetch_json_safely(f"https://api.openf1.org/v1/drivers?session_key={session_key}")
        if not isinstance(results, list) or not isinstance(drivers, list): return None
        
        valid_results = []
        for r in results:
            pos = r.get("position") if r.get("position") is not None else r.get("position_current")
            if pos is not None and 1 <= pos <= 3:
                valid_results.append((pos, r))
                
        wiki_exceptions = {
            "Sergio_Perez": "Sergio_Pérez", "Nico_Hulkenberg": "Nico_Hülkenberg",
            "Carlos_Sainz": "Carlos_Sainz_Jr.", "Zhou_Guanyu": "Guanyu_Zhou",
            "Alexander_Albon": "Alex_Albon", "Nyck_De_Vries": "Nyck_de_Vries"
        }
                
        podium = []
        for pos, r in sorted(valid_results, key=lambda x: x[0]):
            d_info = next((d for d in drivers if d.get("driver_number") == r.get("driver_number")), {})
            raw_name = d_info.get("full_name") or "Unknown"
            base_title = "_".join([w.capitalize() for w in raw_name.split()])
            
            podium.append({
                "position": str(pos),
                "familyName": d_info.get("last_name") or "Driver",
                "constructorId": (d_info.get("team_name") or "Unknown").lower().replace(" ", ""),
                "constructorName": d_info.get("team_name") or "Unknown",
                "wiki_title": wiki_exceptions.get(base_title, base_title)
            })
        return podium if len(podium) > 0 else None
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
def calendar_page():
    return render_template('calendar.html')

@app.route('/standings')
def standings():
    return render_template('standings.html')

@app.route('/api/calendar-list')
def api_calendar_list():
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    
    calendar_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current.json")
    races = calendar_data.get("MRData", {}).get("RaceTable", {}).get("Races", []) if isinstance(calendar_data, dict) else []
    
    if not races:
        return jsonify({"error": "무료 API 서버(Jolpi) 응답 제한", "races": []})
        
    results_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current/results.json?limit=1000")
    results_races = results_data.get("MRData", {}).get("RaceTable", {}).get("Races", []) if isinstance(results_data, dict) else []
    results_map = {r.get("round"): r.get("Results", []) for r in results_races}
    
    next_race_idx = next((i for i, r in enumerate(races) if r.get("date", "") >= today_str), len(races) - 1)
    
    list_payload = []
    for idx, race in enumerate(races):
        r_num = race.get("round")
        c_date = race.get("date", "")
        is_past = (c_date < today_str or r_num in results_map)
        winner_name, team_color, winner_wiki = "", "#1a1c1e", ""
        
        podium = results_map.get(r_num, [])
        if podium and len(podium) > 0:
            w1 = podium[0]
            winner_name = w1.get("Driver", {}).get("familyName", "Unknown")
            team_color = get_team_color(w1.get("Constructor", {}).get("constructorId"), w1.get("Constructor", {}).get("name"))
            winner_wiki = w1.get("Driver", {}).get("url", "").split('/wiki/')[-1]
        elif is_past:
            if r_num not in OPENF1_PODIUM_CACHE:
                op_podium = fetch_openf1_fallback(race.get("Circuit", {}).get("Location", {}).get("locality", ""), c_date)
                if op_podium: OPENF1_PODIUM_CACHE[r_num] = {"podium": op_podium, "pole": "", "fastest_lap": "", "sprint_winner": ""}
            if r_num in OPENF1_PODIUM_CACHE:
                pod_data = OPENF1_PODIUM_CACHE[r_num].get("podium", [])
                w1 = next((p for p in pod_data if p.get("position") == "1"), None)
                if w1:
                    winner_name = w1.get("familyName", "Unknown")
                    team_color = get_team_color(w1.get("constructorId"), w1.get("constructorName"))
                    winner_wiki = w1.get("wiki_title", "")

        list_payload.append({
            "idx": idx, "round": r_num, "raceName": race.get("raceName", "GP"), 
            "locality": race.get("Circuit", {}).get("Location", {}).get("locality", ""),
            "date": c_date, "is_past": is_past, "is_next": (idx == next_race_idx),
            "winner_name": winner_name, "team_color": team_color, "winner_wiki": winner_wiki,
            "flag_url": get_flag_url(race.get("Circuit", {}).get("Location", {}).get("country", "")),
            "circuit_wiki_title": race.get("Circuit", {}).get("url", "").split('/wiki/')[-1],
            "circuit_name": race.get("Circuit", {}).get("circuitName", "")
        })
    return jsonify({"next_race_idx": next_race_idx, "races": list_payload})

@app.route('/api/race-podium/<round_num>')
def api_race_podium(round_num):
    if round_num in OPENF1_PODIUM_CACHE and "pole" in OPENF1_PODIUM_CACHE[round_num]:
        return jsonify(OPENF1_PODIUM_CACHE[round_num])
        
    payload = {"podium": [], "pole": "", "fastest_lap": "", "sprint_winner": ""}
    
    results_data = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/current/{round_num}/results.json")
    results_races = results_data.get("MRData", {}).get("RaceTable", {}).get("Races", []) if isinstance(results_data, dict) else []
    
    if results_races:
        race_info = results_races[0]
        podium_list = race_info.get("Results", [])[:3]
        payload["podium"] = [{
            "position": p.get("position"), "familyName": p.get("Driver", {}).get("familyName", "Unknown"),
            "constructorId": p.get("Constructor", {}).get("constructorId", ""), "constructorName": p.get("Constructor", {}).get("name", "Unknown"),
            "wiki_title": p.get("Driver", {}).get("url", "").split('/wiki/')[-1]
        } for p in podium_list]
        
        all_res = race_info.get("Results", [])
        pole_driver = next((r for r in all_res if r.get("grid") == "1"), None)
        fl_driver = next((r for r in all_res if r.get("FastestLap", {}).get("rank") == "1"), None)
        if pole_driver: payload["pole"] = pole_driver.get("Driver", {}).get("familyName", "")
        if fl_driver: payload["fastest_lap"] = fl_driver.get("Driver", {}).get("familyName", "")
    else:
        calendar_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current.json")
        cal_races = calendar_data.get("MRData", {}).get("RaceTable", {}).get("Races", []) if isinstance(calendar_data, dict) else []
        race = next((r for r in cal_races if r.get("round") == round_num), None)
        if race:
            op_podium = fetch_openf1_fallback(race.get("Circuit", {}).get("Location", {}).get("locality", ""), race.get("date", ""))
            if op_podium: payload["podium"] = op_podium

    sprint_data = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/current/{round_num}/sprint.json")
    sprint_races = sprint_data.get("MRData", {}).get("RaceTable", {}).get("Races", []) if isinstance(sprint_data, dict) else []
    if sprint_races and sprint_races[0].get("SprintResults"):
        payload["sprint_winner"] = sprint_races[0]["SprintResults"][0].get("Driver", {}).get("familyName", "")

    OPENF1_PODIUM_CACHE[round_num] = payload
    return jsonify(payload)

@app.route('/api/wiki-meta/<page_title>')
def api_wiki_meta(page_title):
    fallback = {"extract": "요약 정보를 불러올 수 없습니다.", "image": ""}
    data = fetch_json_safely(f"https://en.wikipedia.org/api/rest_v1/page/summary/{page_title}")
    if not data: return jsonify(fallback)
    return jsonify({
        "extract": data.get("extract", "설명이 비어 있습니다."),
        "image": data.get("originalimage", {}).get("source") or data.get("thumbnail", {}).get("source") or ""
    })

@app.route('/api/race-sessions/<round_num>')
def api_race_sessions(round_num):
    season = request.args.get('season', 'current')
    payload = {"schedule": {}, "qualifying": [], "sprint": [], "race": []}
    
    cal_data = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/{season}.json")
    cal_races = cal_data.get("MRData", {}).get("RaceTable", {}).get("Races", []) if isinstance(cal_data, dict) else []
    race = next((r for r in cal_races if r.get("round") == round_num), None)
    
    if race:
        payload["schedule"] = {
            "fp1": race.get("FirstPractice", {}).get("date", "-"),
            "fp2": race.get("SecondPractice", {}).get("date", "-"),
            "fp3": race.get("ThirdPractice", {}).get("date", "-"),
            "qualifying": race.get("Qualifying", {}).get("date", "-"),
            "sprint": race.get("Sprint", {}).get("date", "-"),
            "race": race.get("date", "-")
        }
            
    quali_data = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/{season}/{round_num}/qualifying.json")
    quali_races = quali_data.get("MRData", {}).get("RaceTable", {}).get("Races", []) if isinstance(quali_data, dict) else []
    if quali_races and quali_races[0].get("QualifyingResults"):
        payload["qualifying"] = [{
            "position": q.get("position"), "driver": f"{q.get('Driver',{}).get('givenName','')} {q.get('Driver',{}).get('familyName','')}",
            "constructor": q.get("Constructor",{}).get("name",""), "time": q.get("Q3") or q.get("Q2") or q.get("Q1") or "-"
        } for q in quali_races[0]["QualifyingResults"][:5]]
            
    sprint_data = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/{season}/{round_num}/sprint.json")
    sprint_races = sprint_data.get("MRData", {}).get("RaceTable", {}).get("Races", []) if isinstance(sprint_data, dict) else []
    if sprint_races and sprint_races[0].get("SprintResults"):
        payload["sprint"] = [{
            "position": s.get("position"), "driver": f"{s.get('Driver',{}).get('givenName','')} {s.get('Driver',{}).get('familyName','')}",
            "constructor": s.get("Constructor",{}).get("name",""), "points": s.get("points", "0")
        } for s in sprint_races[0]["SprintResults"][:5]]
            
    race_data = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/{season}/{round_num}/results.json")
    res_races = race_data.get("MRData", {}).get("RaceTable", {}).get("Races", []) if isinstance(race_data, dict) else []
    if res_races and res_races[0].get("Results"):
        payload["race"] = [{
            "position": r.get("position"), "driver": f"{r.get('Driver',{}).get('givenName','')} {r.get('Driver',{}).get('familyName','')}",
            "constructor": r.get("Constructor",{}).get("name",""), "points": r.get("points", "0")
        } for r in res_races[0]["Results"][:5]]
            
    return jsonify(payload)

# 🔥 [신규] 프론트엔드 연쇄 붕괴를 막기 위한 Standings 백엔드 단일 창구
@app.route('/api/standings-data')
def api_standings_data():
    if STANDINGS_CACHE["data"]:
        return jsonify(STANDINGS_CACHE["data"])
        
    drivers_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current/driverStandings.json")
    constructors_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current/constructorStandings.json")
    results_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current/results.json?limit=1000")
    
    if not drivers_data or not constructors_data:
        return jsonify({"error": "API 통신 장애"}), 500
        
    podium_map_drivers = {}
    podium_map_constructors = {}
    
    if results_data and isinstance(results_data, dict):
        races = results_data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        for race in races:
            for res in race.get("Results", []):
                try:
                    pos = int(res.get("position", 99))
                    if pos <= 3:
                        d_id = res.get("Driver", {}).get("driverId")
                        c_id = res.get("Constructor", {}).get("constructorId")
                        if d_id: podium_map_drivers[d_id] = podium_map_drivers.get(d_id, 0) + 1
                        if c_id: podium_map_constructors[c_id] = podium_map_constructors.get(c_id, 0) + 1
                except:
                    pass
                    
    d_list = drivers_data.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [{}])[0].get("DriverStandings", [])
    c_list = constructors_data.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [{}])[0].get("ConstructorStandings", [])
    
    payload = {
        "drivers": d_list,
        "constructors": c_list,
        "podiums": {
            "drivers": podium_map_drivers,
            "constructors": podium_map_constructors
        }
    }
    STANDINGS_CACHE["data"] = payload
    return jsonify(payload)

if __name__ == '__main__':
    app.run(debug=True, port=5001)