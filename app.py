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

# 💾 2차 소스(OpenF1) 데이터 구멍 메우기용 서버 메모리 캐시
OPENF1_PODIUM_CACHE = {}

def get_db_connection():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, 'f1_news.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

# 🎨 2026 규정 반영 11개 팀 컬러 매핑
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

# 💥 OpenF1 2차 피드 정밀 타격 함수 (구멍 난 라운드 요청 시에만 딱 1번 기동)
def fetch_openf1_fallback(locality, race_date):
    try:
        sessions = fetch_json_safely("https://api.openf1.org/v1/sessions?year=2026&session_name=Race")
        if not sessions: return None
        
        matched = next((s for s in sessions if locality.lower() in s.get("location", "").lower() or s.get("date_start", "").startswith(race_date)), None)
        if not matched: return None
        session_key = matched["session_key"]
        
        results = fetch_json_safely(f"https://api.openf1.org/v1/session_result?session_key={session_key}")
        drivers = fetch_json_safely(f"https://api.openf1.org/v1/drivers?session_key={session_key}")
        if not results or not drivers: return None
        
        podium = []
        sorted_res = sorted([r for r in results if 1 <= r.get("position", 99) <= 3], key=lambda x: x["position"])
        for r in sorted_res:
            d_info = next((d for d in drivers if d.get("driver_number") == r.get("driver_number")), {})
            wiki_title = (d_info.get("full_name") or "").replace(" ", "_")
            podium.append({
                "position": str(r["position"]),
                "familyName": d_info.get("last_name") or "Driver",
                "constructorId": d_info.get("team_name", "").lower().replace(" ", ""),
                "constructorName": d_info.get("team_name") or "Unknown",
                "wiki_title": wiki_title
            })
        return podium
    except:
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

# 🏛️ [라우트 1] 1차 소스 조회 및 구멍 난 과거 경기는 2차 소스로 즉시 대체하는 API
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
            # 1차 소스에 구멍이 났고 과거 경기라면 리스트 구성 단계에서 바로 2차 소스 가동
            if r_num not in OPENF1_PODIUM_CACHE:
                print(f"🚨 [리스트 로드 중 구멍 발견] Round {r_num} 결과를 OpenF1에서 자동 대체 수집합니다.")
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

# 🏛️ [라우트 2] 클릭 시 실행되며, 1차 소스에 구멍이 났을 때만 2차 소스로 자동 대처하는 포디움 API
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
            print(f"🚨 [1차 구멍 발견] {race['raceName']} 결과를 OpenF1에서 자동 대체 수집합니다.")
            op_podium = fetch_openf1_fallback(race["Circuit"]["Location"]["locality"], race["date"])
            if op_podium:
                OPENF1_PODIUM_CACHE[round_num] = op_podium
                return jsonify(op_podium)
                
    return jsonify([])

# 🏛️ [라우트 3] 위키피디아 403 차단 우회용 프록시 API
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