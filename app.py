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

# ⚡ 글로벌 메모리 캐시 (1차 + 2차 피드를 완벽히 가공한 최종 완성본 저장소)
FULL_CALENDAR_CACHE = {"data": None, "updated_at": None}

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
    except:
        return None

def fetch_openf1_podium_direct(locality, race_date):
    try:
        sessions = fetch_json_safely("https://api.openf1.org/v1/sessions?year=2026&session_name=Race")
        if not sessions: return None
        matched = next((s for s in sessions if locality.lower() in s.get("location", "").lower() or s.get("date_start", "").startswith(race_date)), None)
        if (!matched): return None
        session_key = matched["session_key"]
        
        results = fetch_json_safely(f"https://api.openf1.org/v1/session_result?session_key={session_key}")
        drivers = fetch_json_safely(f"https://api.openf1.org/v1/drivers?session_key={session_key}")
        if not results or not drivers: return None
        
        podium = []
        sorted_res = sorted([r for r in results if 1 <= r.get("position", 99) <= 3], key=lambda x: x["position"])
        for r in sorted_res:
            d_info = next((d for d in drivers if d.get("driver_number") == r.get("driver_number")), {})
            podium.append({
                "position": str(r["position"]),
                "familyName": d_info.get("last_name") or "Driver",
                "constructorId": d_info.get("team_name", "").lower().replace(" ", ""),
                "constructorName": d_info.get("team_name") or "Unknown",
                "wiki_title": (d_info.get("full_name") or "").replace(" ", "_")
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

# 🏛️ [대개조 API] 1차+2차 데이터 및 이미지까지 완벽히 조립 후 프론트에 던지는 마스터 엔드포인트
@app.route('/api/calendar-master')
def api_calendar_master():
    global FULL_CALENDAR_CACHE
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    
    # 캐시 유효 시 외부 요청 0회, 응답 속도 0.001초 보장
    if FULL_CALENDAR_CACHE["data"] and (now - FULL_CALENDAR_CACHE["updated_at"]).total_seconds() < 600:
        return jsonify(FULL_CALENDAR_CACHE["data"])
        
    calendar_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current.json")
    results_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current/results.json?limit=1000")
    if not calendar_data: return jsonify({"error": "1차 소스 피드 다운"}), 500
    
    races = calendar_data["MRData"]["RaceTable"]["Races"]
    results_map = {r["round"]: r["Results"] for r in results_data["MRData"]["RaceTable"]["Races"]} if results_data else {}
    next_race_idx = next((i for i, r in enumerate(races) if r["date"] >= today_str), len(races) - 1)
    
    master_payload = []
    for idx, race in enumerate(races):
        r_num = race["round"]
        c_date = race["date"]
        locality = race["Circuit"]["Location"]["locality"]
        is_past = (c_date < today_str or r_num in results_map)
        
        winner_name, team_color, winner_wiki = "", "#1a1c1e", ""
        final_podium = []
        
        # 1. 포디움 조립 분기 (1차 우선 -> 없으면 2차 자동 대체)
        jolpi_podium = results_map.get(r_num)
        if jolpi_podium:
            for p in jolpi_podium[:3]:
                final_podium.append({
                    "position": p["position"],
                    "familyName": p["Driver"]["familyName"],
                    "wiki_title": p["Driver"]["url"].split('/wiki/')[-1]
                })
        elif is_past:
            # 💥 구멍 발견 시 백엔드에서 미리 OpenF1 동기식 결합 유도
            op_pod = fetch_openf1_podium_direct(locality, c_date)
            if op_pod:
                final_podium = op_pod

        # 2. 메인 화면용 우승자 정보 가공
        if final_podium:
            w1 = next((p for p in final_podium if p["position"] == "1"), None)
            if w1:
                winner_name = w1["familyName"]
                winner_wiki = w1["wiki_title"]
                # OpenF1 구조 혹은 Jolpi 구조에 맞춰 팀 컬러 세팅
                c_id = w1.get("constructorId") or w1.get("Constructor", {}).get("constructorId", "")
                c_name = w1.get("constructorName") or w1.get("Constructor", {}).get("name", "")
                team_color = get_team_color(c_id, c_name)

        master_payload.append({
            "idx": idx, "round": r_num, "raceName": race["raceName"], "locality": locality,
            "country": race["Circuit"]["Location"]["country"], "date": c_date, "is_past": is_past,
            "is_next": (idx == next_race_idx), "winner_name": winner_name, "team_color": team_color,
            "winner_wiki": winner_wiki, "flag_url": get_flag_url(race["Circuit"]["Location"]["country"]),
            "circuit_wiki_title": race["Circuit"]["url"].split('/wiki/')[-1],
            "circuit_name": race["Circuit"]["circuitName"],
            "podium": final_podium
        })

    FULL_CALENDAR_CACHE = {"data": {"next_race_idx": next_race_idx, "races": master_payload}, "updated_at": now}
    return jsonify(FULL_CALENDAR_CACHE["data"])

# 프론트가 이미지와 텍스트를 실시간 레이지 플로우할 프록시는 독립 유지
@app.route('/api/wiki-meta/<page_title>')
def api_wiki_meta(page_title):
    data = fetch_json_safely(f"https://en.wikipedia.org/api/rest_v1/page/summary/{page_title}")
    if not data: return jsonify({"extract": "정보 없음", "image": ""})
    return jsonify({
        "extract": data.get("extract", "설명이 비어 있습니다."),
        "image": data.get("originalimage", {}).get("source") or data.get("thumbnail", {}).get("source") or ""
    })

if __name__ == '__main__':
    app.run(debug=True, port=5001)