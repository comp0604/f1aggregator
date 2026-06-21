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

# 💾 2차 소스(OpenF1) 데이터 구멍 메우기용 서버 메모리 캐시
OPENF1_PODIUM_CACHE = {}

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

# 💥 OpenF1 2차 피드 정밀 타격 함수 (API 간 지역명 불일치 및 예외 처리 완벽 방어)
# 💥 OpenF1 2차 피드 정밀 타격 함수 (API 간 지역명 불일치 및 위키피디아 대소문자 완벽 방어)
def fetch_openf1_fallback(locality, race_date):
    try:
        year = race_date.split("-")[0] if race_date else "2026"
        sessions = fetch_json_safely(f"https://api.openf1.org/v1/sessions?year={year}&session_name=Race")
        if not sessions: return None
        
        loc_mapping = {
            "monte-carlo": "monaco",
            "montmeló": "barcelona",
            "marina bay": "singapore",
            "abu dhabi": "yas island",
            "são paulo": "sao paulo",
            "mexico city": "mexico city"
        }
        mapped_loc = loc_mapping.get(locality.lower(), locality.lower())
        
        matched = next((s for s in sessions if mapped_loc in s.get("location", "").lower() or s.get("date_start", "").startswith(race_date)), None)
        if not matched: return None
        session_key = matched["session_key"]
        
        results = fetch_json_safely(f"https://api.openf1.org/v1/session_result?session_key={session_key}")
        drivers = fetch_json_safely(f"https://api.openf1.org/v1/drivers?session_key={session_key}")
        if not results or not drivers: return None
        
        valid_results = []
        for r in results:
            pos = r.get("position")
            if pos is None: pos = r.get("position_current")
            if pos is not None and 1 <= pos <= 3:
                valid_results.append((pos, r))
                
        # 🔥 위키피디아 URL 규칙 예외 사전 (특수문자 및 이름 표기법 보정)
        wiki_exceptions = {
            "Sergio_Perez": "Sergio_Pérez",
            "Nico_Hulkenberg": "Nico_Hülkenberg",
            "Carlos_Sainz": "Carlos_Sainz_Jr.",
            "Zhou_Guanyu": "Guanyu_Zhou",
            "Alexander_Albon": "Alex_Albon",
            "Nyck_De_Vries": "Nyck_de_Vries"
        }
                
        podium = []
        sorted_res = sorted(valid_results, key=lambda x: x[0])
        for pos, r in sorted_res:
            d_info = next((d for d in drivers if d.get("driver_number") == r.get("driver_number")), {})
            
            raw_name = d_info.get("full_name") or "Unknown"
            base_wiki_title = "_".join([w.capitalize() for w in raw_name.split()])
            wiki_title = wiki_exceptions.get(base_wiki_title, base_wiki_title)
            
            team_name = d_info.get("team_name") or "Unknown"
            
            podium.append({
                "position": str(pos),
                "familyName": d_info.get("last_name") or "Driver",
                "constructorId": team_name.lower().replace(" ", ""),
                "constructorName": team_name,
                "wiki_title": wiki_title
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
    results_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current/results.json?limit=1000")
    if not calendar_data: return jsonify({"error": "1차 소스 통신 실패"}), 500
    
    races = calendar_data["MRData"]["RaceTable"]["Races"]
    results_map = {r["round"]: r["Results"] for r in results_data["MRData"]["RaceTable"]["Races"]} if results_data else {}
    next_race_idx = next((i for i, r in enumerate(races) if r["date"] >= today_str), len(races) - 1)
    
    list_payload = []
    for idx, race in enumerate(races):
        r_num = race["round"]
        c_date = race["date"]
        is_past = (c_date < today_str or r_num in results_map)
        
        winner_name, team_color, winner_wiki = "", "#1a1c1e", ""
        
        podium = results_map.get(r_num)
        if podium:
            w1 = podium[0]
            winner_name = w1["Driver"]["familyName"]
            team_color = get_team_color(w1["Constructor"]["constructorId"], w1["Constructor"]["name"])
            winner_wiki = w1["Driver"]["url"].split('/wiki/')[-1]
        elif is_past:
            if r_num not in OPENF1_PODIUM_CACHE:
                print(f"🚨 [구멍 발견] Round {r_num} ({race['Circuit']['Location']['locality']}) 결과를 OpenF1에서 수집합니다.")
                op_podium = fetch_openf1_fallback(race["Circuit"]["Location"]["locality"], race["date"])
                if op_podium:
                    OPENF1_PODIUM_CACHE[r_num] = op_podium
            
            if r_num in OPENF1_PODIUM_CACHE:
                w1 = next((p for p in OPENF1_PODIUM_CACHE[r_num] if p["position"] == "1"), None)
                if w1:
                    winner_name = w1["familyName"]
                    team_color = get_team_color(w1["constructorId"], w1["constructorName"])
                    winner_wiki = w1["wiki_title"]

        list_payload.append({
            "idx": idx, "round": r_num, "raceName": race["raceName"], "locality": race["Circuit"]["Location"]["locality"],
            "date": c_date, "is_past": is_past, "is_next": (idx == next_race_idx),
            "winner_name": winner_name, "team_color": team_color, "winner_wiki": winner_wiki,
            "flag_url": get_flag_url(race["Circuit"]["Location"]["country"]),
            "circuit_wiki_title": race["Circuit"]["url"].split('/wiki/')[-1],
            "circuit_name": race["Circuit"]["circuitName"]
        })

    return jsonify({"next_race_idx": next_race_idx, "races": list_payload})

@app.route('/api/race-podium/<round_num>')
def api_race_podium(round_num):
    if round_num in OPENF1_PODIUM_CACHE:
        return jsonify(OPENF1_PODIUM_CACHE[round_num])
        
    results_data = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/current/{round_num}/results.json")
    if results_data and results_data["MRData"]["RaceTable"]["Races"]:
        podium_list = results_data["MRData"]["RaceTable"]["Races"][0]["Results"][:3]
        payload = [{
            "position": p["position"], "familyName": p["Driver"]["familyName"],
            "constructorId": p["Constructor"]["constructorId"], "constructorName": p["Constructor"]["name"],
            "wiki_title": p["Driver"]["url"].split('/wiki/')[-1]
        } for p in podium_list]
        
        OPENF1_PODIUM_CACHE[round_num] = payload
        return jsonify(payload)
    
    calendar_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current.json")
    if calendar_data:
        race = next((r for r in calendar_data["MRData"]["RaceTable"]["Races"] if r["round"] == round_num), None)
        if race:
            op_podium = fetch_openf1_fallback(race["Circuit"]["Location"]["locality"], race["date"])
            if op_podium:
                OPENF1_PODIUM_CACHE[round_num] = op_podium
                return jsonify(op_podium)
                
    return jsonify([])

@app.route('/api/wiki-meta/<page_title>')
def api_wiki_meta(page_title):
    fallback = {"extract": "요약 정보를 불러올 수 없습니다.", "image": ""}
    data = fetch_json_safely(f"https://en.wikipedia.org/api/rest_v1/page/summary/{page_title}")
    if not data: return jsonify(fallback)
    return jsonify({
        "extract": data.get("extract", "설명이 비어 있습니다."),
        "image": data.get("originalimage", {}).get("source") or data.get("thumbnail", {}).get("source") or ""
    })

if __name__ == '__main__':
    app.run(debug=True, port=5001)

# 🏛️ [라우트 4] 프랙티스 일정 및 스프린트/퀄리파잉/결승 결과를 일괄 수집하는 종합 세션 API
@app.route('/api/race-sessions/<round_num>')
def api_race_sessions(round_num):
    # 프론트엔드가 넘겨준 조건(current 또는 2025)을 바인딩합니다.
    season = request.args.get('season', 'current')
    
    payload = {
        "schedule": {},
        "qualifying": [],
        "sprint": [],
        "race": []
    }
    
    # 1. 주말 세션 공식 타임테이블/스케줄 수집 (프랙티스 포함)
    cal_data = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/{season}.json")
    if cal_data and "MRData" in cal_data:
        races = cal_data["MRData"]["RaceTable"]["Races"]
        race = next((r for r in races if r["round"] == round_num), None)
        if race:
            payload["schedule"] = {
                "fp1": race.get("FirstPractice", {}).get("date", "-"),
                "fp2": race.get("SecondPractice", {}).get("date", "-"),
                "fp3": race.get("ThirdPractice", {}).get("date", "-"),
                "qualifying": race.get("Qualifying", {}).get("date", "-"),
                "sprint": race.get("Sprint", {}).get("date", "-"),
                "race": race.get("date", "-")
            }
            
    # 2. 퀄리파잉 기록 수집 (Top 5)
    quali_data = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/{season}/{round_num}/qualifying.json")
    if quali_data and "MRData" in quali_data:
        r_table = quali_data["MRData"]["RaceTable"]["Races"]
        if r_table and "QualifyingResults" in r_table[0]:
            payload["qualifying"] = [{
                "position": q["position"],
                "driver": f"{q['Driver']['givenName']} {q['Driver']['familyName']}",
                "constructor": q["Constructor"]["name"],
                "time": q.get("Q3") or q.get("Q2") or q.get("Q1") or "-"
            } for q in r_table[0]["QualifyingResults"][:5]]
            
    # 3. 스프린트 결과 수집 (스프린트 주말인 경우 Top 5 수집)
    sprint_data = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/{season}/{round_num}/sprint.json")
    if sprint_data and "MRData" in sprint_data:
        r_table = sprint_data["MRData"]["RaceTable"]["Races"]
        if r_table and "SprintResults" in r_table[0]:
            payload["sprint"] = [{
                "position": s["position"],
                "driver": f"{s['Driver']['givenName']} {s['Driver']['familyName']}",
                "constructor": s["Constructor"]["name"],
                "points": s.get("points", "0")
            } for s in r_table[0]["SprintResults"][:5]]
            
    # 4. 결승 레이스 결과 수집 (Top 5)
    race_data = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/{season}/{round_num}/results.json")
    if race_data and "MRData" in race_data:
        r_table = race_data["MRData"]["RaceTable"]["Races"]
        if r_table and "Results" in r_table[0]:
            payload["race"] = [{
                "position": r["position"],
                "driver": f"{r['Driver']['givenName']} {r['Driver']['familyName']}",
                "constructor": r["Constructor"]["name"],
                "points": r.get("points", "0")
            } for r in r_table[0]["Results"][:5]]
            
    return jsonify(payload)