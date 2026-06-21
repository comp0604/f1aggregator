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

# ⚡ 글로벌 캐시 세팅
CALENDAR_CACHE = {"data": None, "updated_at": None}

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
            headers={'User-Agent': 'LecLovF1/1.0 (developer@leclovf1.com) Python/3.x'}
        )
        with urllib.request.urlopen(req, timeout=5, context=ssl_context) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"⚠️ API Timeout/Error ({url}): {e}")
        return None

# 💥 [초경량화] OpenF1 최종 결과 스펙만 타격하는 라이트 엔진
def fetch_openf1_podium_light(locality, race_date):
    try:
        sessions = fetch_json_safely("https://api.openf1.org/v1/sessions?year=2026&session_name=Race")
        if not sessions: return None
        matched = next((s for s in sessions if locality.lower() in s.get("location", "").lower() or s.get("date_start", "").startswith(race_date)), None)
        if not matched: return None
        session_key = matched["session_key"]
        
        # 💥 대용량 position 대신 최종 스탠딩 스냅샷(session_result) 엔드포인트만 매핑 조율
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

# 🏛️ [인덱스 1] 0.1초 만에 뼈대를 뿜어내는 가로 스크롤바 전용 경량화 API
@app.route('/api/calendar-list')
def api_calendar_list():
    global CALENDAR_CACHE
    now = datetime.now()
    if CALENDAR_CACHE["data"] and (now - CALENDAR_CACHE["updated_at"]).total_seconds() < 300:
        return jsonify(CALENDAR_CACHE["data"])
        
    calendar_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current.json")
    results_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current/results.json?limit=1000")
    if not calendar_data: return jsonify({"error": "Data failure"}), 500
    
    races = calendar_data["MRData"]["RaceTable"]["Races"]
    results_map = {r["round"]: r["Results"] for r in results_data["MRData"]["RaceTable"]["Races"]} if results_data else {}
    today_str = now.strftime("%Y-%m-%d")
    
    next_race_idx = next((i for i, r in enumerate(races) if r["date"] >= today_str), len(races) - 1)
    list_payload = []

    for idx, race in enumerate(races):
        r_num = race["round"]
        locality = race["Circuit"]["Location"]["locality"]
        c_date = race["date"]
        is_past = (c_date < today_str or r_num in results_map)
        
        winner_name, team_color, winner_wiki = "", "#1a1c1e", ""
        podium = results_map.get(r_num)
        
        if is_past and not podium:
            podium = fetch_openf1_podium_light(locality, c_date)
            if podium:
                w1 = next((p for p in podium if p["position"] == "1"), None)
                if w1:
                    winner_name = w1["familyName"]
                    team_color = get_team_color(w1["constructorId"], w1["constructorName"])
                    winner_wiki = w1["wiki_title"]
        elif podium:
            w1 = podium[0]
            winner_name = w1["Driver"]["familyName"]
            team_color = get_team_color(w1["Constructor"]["constructorId"], w1["Constructor"]["name"])
            winner_wiki = w1["Driver"]["url"].split('/wiki/')[-1]

        list_payload.append({
            "idx": idx, "round": r_num, "raceName": race["raceName"], "locality": locality,
            "date": c_date, "is_past": is_past, "is_next": (idx == next_race_idx),
            "winner_name": winner_name, "team_color": team_color, "winner_wiki": winner_wiki,
            "flag_url": get_flag_url(race["Circuit"]["Location"]["country"]),
            "circuit_wiki_title": race["Circuit"]["url"].split('/wiki/')[-1],
            "circuit_name": race["Circuit"]["circuitName"]
        })

    CALENDAR_CACHE = {"data": {"next_race_idx": next_race_idx, "races": list_payload}, "updated_at": now}
    return jsonify(CALENDAR_CACHE["data"])

# 🏛️ [인덱스 2] 특정 라운드 클릭 시 탑3 포디움 드라이버 구조만 떼어오는 서브 API
@app.route('/api/race-podium/<round_num>')
def api_race_podium(round_num):
    results_data = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/current/{round_num}/results.json")
    podium_list = []
    if results_data and results_data["MRData"]["RaceTable"]["Races"]:
        podium_list = results_data["MRData"]["RaceTable"]["Races"][0]["Results"][:3]
        return jsonify([{
            "position": p["position"], "familyName": p["Driver"]["familyName"],
            "wiki_title": p["Driver"]["url"].split('/wiki/')[-1]
        } for p in podium_list])
    
    # Ergast 누락 시 OpenF1 라이트 즉시 호출
    calendar_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current.json")
    if calendar_data:
        race = next((r for r in calendar_data["MRData"]["RaceTable"]["Races"] if r["round"] == round_num), None)
        if race:
            op_podium = fetch_openf1_podium_light(race["Circuit"]["Location"]["locality"], race["date"])
            if op_podium: return jsonify(op_podium)
            
    return jsonify([])

# 🏛️ [인덱스 3] 403 차단을 원천 차단하고 프론트엔드가 실시간 레이지 로딩해가는 위키 유틸 프록시
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