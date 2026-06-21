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

# ⚡ 서버사이드 가벼운 글로벌 메모리 캐시 세팅 (서버 부하 및 속도 저하 방지)
CALENDAR_CACHE = {
    "data": None,
    "updated_at": None
}

def get_db_connection():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, 'f1_news.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

# 🎨 2026 시즌 팀 컬러 매핑 유틸 함수 (서버 내부 처리)
def get_team_color(constructor_id, constructor_name):
    c_id = (constructor_id or "").toLowerCase().replace(" ", "").replace("_", "").replace("-", "")
    name = (constructor_name or "").toLowerCase().replace(" ", "").replace("_", "").replace("-", "")
    
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

# 🌍 국가별 Flag 배정 주소 변환 유틸
def get_flag_url(country_name):
    name = (country_name or "").lower().strip()
    mapping = {
        "australia": "au", "bahrain": "bh", "saudi arabia": "sa", "japan": "jp", "china": "cn",
        "usa": "us", "united states": "us", "monaco": "mc", "spain": "es", "canada": "ca",
        "austria": "at", "uk": "gb", "united kingdom": "gb", "great britain": "gb", "hungary": "hu",
        "belgium": "be", "netherlands": "nl", "italy": "it", "azerbaijan": "az", "singapore": "sg",
        "mexico": "mx", "brazil": "br", "qatar": "qa", "uae": "ae", "united arab emirates": "ae"
    }
    code = mapping.get(name, "un")
    return f"https://flagcdn.com/w1280/{code}.png"

# 🛡️ 안전한 서버사이드 HTTP Request 실행기 (위키피디아 차단 우회용 식별 헤더 포함)
def fetch_json_safely(url):
    try:
        ssl_context = ssl._create_unverified_context()
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'LecLovF1/1.0 (contact@example.com) Python-urllib/3.x',
                'Accept': 'application/json'
            }
        )
        with urllib.request.urlopen(req, timeout=8, context=ssl_context) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"❌ 외부 API 패치 실패 ({url}): {e}")
        return None

# 📸 위키피디아 프로필/사진 경로 정밀 파싱기
def get_wiki_data(wiki_url):
    fallback = {"extract": "요약 정보를 불러올 수 없습니다.", "image": ""}
    if not wiki_url: return fallback
    page_title = wiki_url.split('/wiki/')[-1]
    if not page_title: return fallback
    
    #  `page_title`로 올바르게 수정되었습니다.
    data = fetch_json_safely(f"https://en.wikipedia.org/api/rest_v1/page/summary/{page_title}")
    if not data: return fallback
    
    img_url = data.get("originalimage", {}).get("source") or data.get("thumbnail", {}).get("source") or ""
    return {
        "extract": data.get("extract", "상세 요약 설명이 비어 있습니다."),
        "image": img_url
    }

# 🔄 OpenF1 라이브 연동 자동 대체 서브 스레드 엔진 (백엔드 이식 버전)
def fetch_openf1_podium(locality, race_date):
    try:
        sessions = fetch_json_safely("https://api.openf1.org/v1/sessions?year=2026&session_name=Race")
        if not sessions: return None
        
        matched = next((s for s in sessions if locality.lower() in s.get("location", "").lower() or s.get("date_start", "").startswith(race_date)), None)
        if not matched: return None
        session_key = matched["session_key"]
        
        drivers = fetch_json_safely(f"https://api.openf1.org/v1/drivers?session_key={session_key}")
        positions = fetch_json_safely(f"https://api.openf1.org/v1/position?session_key={session_key}")
        if not drivers or not positions: return None
        
        latest_pos = {}
        for p in positions:
            d_num = p["driver_number"]
            if d_num not in latest_pos or p["date"] > latest_pos[d_num]["date"]:
                latest_pos[d_num] = p
                
        podium_list = sorted([p for p in latest_pos.values() if 1 <= p["position"] <= 3], key=lambda x: x["position"])
        if len(podium_list) < 3: return None
        
        result = []
        for p in podium_list:
            drv = next((d for d in drivers if d["driver_number"] == p["driver_number"]), {})
            wiki_name = (drv.get("full_name") or "").replace(" ", "_")
            result.append({
                "position": str(p["position"]),
                "Driver": {
                    "familyName": drv.get("last_name") or "Driver",
                    "url": f"https://en.wikipedia.org/wiki/{wiki_name}"
                },
                "Constructor": {
                    "constructorId": (drv.get("team_name") or "").lower().replace(" ", ""),
                    "name": drv.get("team_name") or "Unknown"
                }
            })
        return result
    except Exception as e:
        print(f"❌ OpenF1 백엔드 트랙 연동 오류: {e}")
        return None

@app.route('/')
def index():
    conn = get_db_connection()
    articles = conn.execute(
        'SELECT id, title, link, summary_ko, image_url, published_at FROM articles ORDER BY published_at DESC LIMIT 10'
    ).fetchall()
    conn.close()
    return render_template('index.html', articles=articles)

@app.route('/standings')
def standings():
    return render_template('standings.html')

@app.route('/calendar')
def calendar_page():
    return render_template('calendar.html')

# 💥 [신규 핵심] 정제된 캘린더 타임라인 일괄 패키징 백엔드 API 라우트
@app.route('/api/calendar-data')
def api_calendar_data():
    global CALENDAR_CACHE
    now = datetime.now()
    
    # 5분 동안은 기존 캐시 재활용 (불필요한 외부 차단 원천 방어 및 미친듯한 서핑 속도 보장)
    if CALENDAR_CACHE["data"] and CALENDAR_CACHE["updated_at"] and (now - CALENDAR_CACHE["updated_at"]).total_seconds() < 300:
        return jsonify(CALENDAR_CACHE["data"])
        
    calendar_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current.json")
    results_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current/results.json?limit=1000")
    
    if not calendar_data:
        return jsonify({"error": "Failed to source calendar base"}), 500
        
    races = calendar_data["MRData"]["RaceTable"]["Races"]
    results_list = results_data["MRData"]["RaceTable"]["Races"] if results_data else []
    
    results_map = {r["round"]: r["Results"] for r in results_list}
    today_str = now.strftime("%Y-%m-%d")
    
    processed_races = []
    next_race_idx = -1
    
    # 미래 가장 가까운 인덱스 선탐색
    for idx, race in enumerate(races):
        if race["date"] >= today_str and next_race_idx == -1:
            next_race_idx = idx
            
    if next_race_idx == -1 and races:
        next_race_idx = len(races) - 1

    for idx, race in enumerate(races):
        r_num = race["round"]
        locality = race["Circuit"]["Location"]["locality"]
        country = race["Circuit"]["Location"]["country"]
        c_date = race["date"]
        
        is_past = (c_date < today_str or r_num in results_map)
        is_next = (idx == next_race_idx)
        
        podium = results_map.get(r_num)
        
        # 🛡️ 백엔드 오토 바이패스 2차 피드 검증 발동
        if is_past and not podium:
            podium = fetch_openf1_openf1_podium = fetch_openf1_podium(locality, c_date)
            
        winner_name = ""
        team_color = "#1a1c1e"
        podium_payload = []
        
        if podium and len(podium) >= 3:
            w1 = next((p for p in podium if p["position"] == "1"), None)
            if w1:
                winner_name = w1["Driver"]["familyName"]
                team_color = get_team_color(w1["Constructor"]["constructorId"], w1["Constructor"]["name"])
                
            for p in podium:
                p_url = p["Driver"]["url"]
                wiki_meta = get_wiki_data(p_url) # 서버에서 유저 에이전트를 달고 안전하게 이미지 수집
                podium_payload.append({
                    "position": p["position"],
                    "familyName": p["Driver"]["familyName"],
                    "avatar": wiki_meta["image"]
                })
        
        circuit_wiki = get_wiki_data(race["Circuit"]["url"])
        flag_url = get_flag_url(country)
        
        processed_races.append({
            "idx": idx,
            "round": r_num,
            "raceName": race["raceName"],
            "locality": locality,
            "country": country,
            "date": c_date,
            "is_past": is_past,
            "is_next": is_next,
            "winner_name": winner_name,
            "team_color": team_color,
            "flag_url": flag_url,
            "circuit_name": race["Circuit"]["circuitName"],
            "circuit_map": circuit_wiki["image"],
            "circuit_extract": circuit_wiki["extract"],
            "podium": podium_payload
        })
        
    response_payload = {
        "next_race_idx": next_race_idx,
        "races": processed_races
    }
    
    # 캐시 갱신
    CALENDAR_CACHE["data"] = response_payload
    CALENDAR_CACHE["updated_at"] = now
    
    return jsonify(response_payload)

if __name__ == '__main__':
    app.run(debug=True, port=5001)