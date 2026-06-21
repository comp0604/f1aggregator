from flask import Flask, render_template, jsonify
import sqlite3
import os
import urllib.request
import json
import ssl
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()  
app = Flask(__name__)

OPENF1_PODIUM_CACHE = {}

def get_db_connection():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    conn = sqlite3.connect(os.path.join(base_dir, 'f1_news.db'))
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
    if "audi" in c_id or "sauber" in name: return "#c41130"
    if "rb" in c_id or "racingbulls" in name: return "#002fa7"
    return "#555555"

def get_flag_url(country_name):
    name = (country_name or "").lower().strip()
    mapping = {
        "australia": "au", "bahrain": "bh", "saudi arabia": "sa", "japan": "jp", "china": "cn",
        "usa": "us", "monaco": "mc", "spain": "es", "canada": "ca", "austria": "at", 
        "uk": "gb", "great britain": "gb", "hungary": "hu", "belgium": "be", "netherlands": "nl", 
        "italy": "it", "azerbaijan": "az", "singapore": "sg", "mexico": "mx", "brazil": "br"
    }
    return f"https://flagcdn.com/w1280/{mapping.get(name, 'un')}.png"

def fetch_json_safely(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'LecLovF1/1.0'})
        with urllib.request.urlopen(req, timeout=3, context=ssl._create_unverified_context()) as res:
            return json.loads(res.read().decode('utf-8'))
    except:
        return {}

def fetch_openf1_fallback(locality, race_date):
    try:
        year = race_date.split("-")[0] if race_date else "2026"
        sessions = fetch_json_safely(f"https://api.openf1.org/v1/sessions?year={year}&session_name=Race")
        if not isinstance(sessions, list): return None
        
        loc_mapping = {"monte-carlo": "monaco", "montmeló": "barcelona", "marina bay": "singapore"}
        mapped_loc = loc_mapping.get(locality.lower(), locality.lower())
        matched = next((s for s in sessions if mapped_loc in s.get("location", "").lower() or s.get("date_start", "").startswith(race_date)), None)
        if not matched: return None
        
        s_key = matched["session_key"]
        results = fetch_json_safely(f"https://api.openf1.org/v1/session_result?session_key={s_key}")
        drivers = fetch_json_safely(f"https://api.openf1.org/v1/drivers?session_key={s_key}")
        
        valid = [(r.get("position") or r.get("position_current"), r) for r in results if r.get("position") or r.get("position_current")]
        podium = []
        for pos, r in sorted([v for v in valid if 1 <= v[0] <= 3], key=lambda x: x[0]):
            
            # 🔥 [오타 수정 완료] dr for dr in drivers 로 올바르게 매칭되도록 수정!
            d = next((dr for dr in drivers if dr.get("driver_number") == r.get("driver_number")), {})
            
            podium.append({
                "position": str(pos), "familyName": d.get("last_name") or "Driver",
                "constructorId": (d.get("team_name") or "").lower().replace(" ", ""),
                "constructorName": d.get("team_name") or "Unknown",
                "wiki_title": (d.get("full_name") or "").replace(" ", "_")
            })
        return podium if podium else None
    except:
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
    
    if not races: return jsonify({"error": "API 오류", "races": []})
    
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
            p_data = OPENF1_PODIUM_CACHE[r_num]
            if p_data:
                w_name = p_data[0].get("familyName", "")
                t_color = get_team_color(p_data[0].get("constructorId"), p_data[0].get("constructorName"))
                w_wiki = p_data[0].get("wiki_title", "")

        payload.append({
            "idx": idx, "round": r_num, "raceName": race.get("raceName", "GP"),
            "locality": race.get("Circuit", {}).get("Location", {}).get("locality", ""),
            "date": c_date, "is_past": is_past, "is_next": (idx == next_idx),
            "winner_name": w_name, "team_color": t_color, "winner_wiki": w_wiki,
            "flag_url": get_flag_url(race.get("Circuit", {}).get("Location", {}).get("country", "")),
            "circuit_wiki_title": race.get("Circuit", {}).get("url", "").split('/wiki/')[-1],
            "circuit_name": race.get("Circuit", {}).get("circuitName", "")
        })
    return jsonify({"next_race_idx": next_idx, "races": payload})

@app.route('/api/race-podium/<round_num>')
def api_race_podium(round_num):
    if round_num in OPENF1_PODIUM_CACHE: return jsonify(OPENF1_PODIUM_CACHE[round_num])
        
    raw_res = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/current/{round_num}/results.json")
    r_races = raw_res.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    
    if r_races:
        podium = [{
            "position": p.get("position"), "familyName": p.get("Driver", {}).get("familyName", ""),
            "constructorId": p.get("Constructor", {}).get("constructorId", ""), "constructorName": p.get("Constructor", {}).get("name", ""),
            "wiki_title": p.get("Driver", {}).get("url", "").split('/wiki/')[-1]
        } for p in r_races[0].get("Results", [])[:3]]
        OPENF1_PODIUM_CACHE[round_num] = podium
        return jsonify(podium)
    else:
        raw_cal = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current.json")
        races = raw_cal.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        race = next((r for r in races if r.get("round") == round_num), None)
        if race:
            op = fetch_openf1_fallback(race.get("Circuit", {}).get("Location", {}).get("locality", ""), race.get("date", ""))
            if op: 
                OPENF1_PODIUM_CACHE[round_num] = op
                return jsonify(op)
    return jsonify([])

@app.route('/api/wiki-meta/<page_title>')
def api_wiki_meta(page_title):
    data = fetch_json_safely(f"https://en.wikipedia.org/api/rest_v1/page/summary/{page_title}")
    return jsonify({"extract": data.get("extract", "정보 없음"), "image": data.get("originalimage", {}).get("source") or data.get("thumbnail", {}).get("source") or ""})

if __name__ == '__main__':
    app.run(debug=True, port=5001)