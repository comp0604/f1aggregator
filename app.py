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

# 💾 로컬 파일 영구 캐시 경로 설정
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'f1_cache.json')

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"calendar_list": None, "podiums": {}, "wiki": {}, "list_updated_at": None}

def save_cache(cache_data):
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ 캐시 파일 저장 실패: {e}")

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

def fetch_json_safely(url, timeout=3):
    try:
        ssl_context = ssl._create_unverified_context()
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'LecLovF1/1.0 (developer@leclovf1.com) Python/3.x'}
        )
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"⚠️ API 요청 실패/타임아웃 ({url}): {e}")
        return None

# 💥 OpenF1 백엔드 구동 트리거 (반복문 내부가 아니라 필요할 때 '단 한 번만' 실행)
def fetch_openf1_podium_live(locality, race_date):
    try:
        sessions = fetch_json_safely("https://api.openf1.org/v1/sessions?year=2026&session_name=Race", timeout=4)
        if not sessions: return None
        matched = next((s for s in sessions if locality.lower() in s.get("location", "").lower() or s.get("date_start", "").startswith(race_date)), None)
        if not matched: return None
        session_key = matched["session_key"]
        
        results = fetch_json_safely(f"https://api.openf1.org/v1/session_result?session_key={session_key}", timeout=4)
        drivers = fetch_json_safely(f"https://api.openf1.org/v1/drivers?session_key={session_key}", timeout=4)
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

# 🏛️ [속도 대혁명] 0.001초만에 반환하는 스크롤 리스트 API (반복문 내 외부 API 원천 차단)
@app.route('/api/calendar-list')
def api_calendar_list():
    cache = load_cache()
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    
    # 1. 10분 이내에 이미 로드한 적이 있다면 외부 요정 없이 즉시 로컬 파일 리턴
    if cache["calendar-list"] and cache["list_updated_at"]:
        time_diff = (now - datetime.strptime(cache["list_updated_at"], "%Y-%m-%d %H:%M:%S")).total_seconds()
        if time_diff < 600:
            return jsonify(cache["calendar-list"])
            
    # 2. 캐시가 만료되었을 때만 기본 메인 피드 1회 노크
    calendar_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current.json", timeout=3)
    results_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current/results.json?limit=1000", timeout=3)
    
    # 만약 Jolpi 네트워크 자체가 먹통이면 로컬에 저장되어 있던 기성 캐시 복원 (안전장치)
    if not calendar_data and cache["calendar-list"]:
        return jsonify(cache["calendar-list"])
    if not calendar_data:
        return jsonify({"error": "F1 Network Timeout"}), 500
        
    races = calendar_data["MRData"]["RaceTable"]["Races"]
    results_map = {r["round"]: r["Results"] for r in results_data["MRData"]["RaceTable"]["Races"]} if results_data else {}
    
    next_race_idx = next((i for i, r in enumerate(races) if r["date"] >= today_str), len(races) - 1)
    list_payload = []

    for idx, race in enumerate(races):
        r_num = race["round"]
        c_date = race["date"]
        is_past = (c_date < today_str or r_num in results_map)
        
        winner_name, team_color, winner_wiki = "", "#1a1c1e", ""
        
        # 💥 중요: 리스트를 그릴 때는 절대로 OpenF1을 호출하지 않음 (대기 원천 차단!)
        # 오직 이미 저장된 데이터나 Jolpi에 있는 정보만 매핑
        podium = results_map.get(r_num)
        if podium:
            w1 = podium[0]
            winner_name = w1["Driver"]["familyName"]
            team_color = get_team_color(w1["Constructor"]["constructorId"], w1["Constructor"]["name"])
            winner_wiki = w1["Driver"]["url"].split('/wiki/')[-1]
        elif is_past and r_num in cache["podiums"]:
            # 이전에 캐싱해둔 OpenF1 결과가 있다면 매핑
            op_pod = cache["podiums"][r_num]
            w1 = next((p for p in op_pod if p["position"] == "1"), None)
            if w1:
                winner_name = w1.get("familyName", "")
                team_color = get_team_color(w1.get("constructorId"), w1.get("constructorName"))
                winner_wiki = w1.get("wiki_title", "")

        list_payload.append({
            "idx": idx, "round": r_num, "raceName": race["raceName"], "locality": race["Circuit"]["Location"]["locality"],
            "date": c_date, "is_past": is_past, "is_next": (idx == next_race_idx),
            "winner_name": winner_name, "team_color": team_color, "winner_wiki": winner_wiki,
            "flag_url": get_flag_url(race["Circuit"]["Location"]["country"]),
            "circuit_wiki_title": race["Circuit"]["url"].split('/wiki/')[-1],
            "circuit_name": race["Circuit"]["circuitName"]
        })

    cache["calendar-list"] = {"next_race_idx": next_race_idx, "races": list_payload}
    cache["list_updated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
    save_cache(cache)
    
    return jsonify(cache["calendar-list"])

# 🏛️ [요청 분리] 카드를 클릭했을 때 "비어있다면 딱 한번만 2차 피드를 타격하는" 포디움 API
@app.route('/api/race-podium/<round_num>')
def api_race_podium(round_num):
    cache = load_cache()
    
    # 1. 이미 캐시에 저장된 결과가 있다면 즉시 반환 (API 호출 0회)
    if round_num in cache["podiums"]:
        return jsonify(cache["podiums"][round_num])
        
    # 2. 캐시에 없다면 먼저 Jolpi API 확인
    results_data = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/current/{round_num}/results.json", timeout=2)
    if results_data and results_data["MRData"]["RaceTable"]["Races"]:
        podium_list = results_data["MRData"]["RaceTable"]["Races"][0]["Results"][:3]
        payload = [{
            "position": p["position"], "familyName": p["Driver"]["familyName"],
            "wiki_title": p["Driver"]["url"].split('/wiki/')[-1]
        } for p in podium_list]
        
        cache["podiums"][round_num] = payload
        save_cache(cache)
        return jsonify(payload)
    
    # 3. 💥 진짜로 비어있을 때만 수동/자동 대처용 OpenF1 라이브 대체 엔진 기동 (최초 1회만)
    calendar_data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current.json", timeout=2)
    if calendar_data:
        race = next((r for r in calendar_data["MRData"]["RaceTable"]["Races"] if r["round"] == round_num), None)
        if race:
            print(f"🔄 [교차 검증 자동 트리거] {race['raceName']} 결과를 OpenF1에서 크롤링합니다.")
            op_podium = fetch_openf1_podium_live(race["Circuit"]["Location"]["locality"], race["date"])
            if op_podium:
                cache["podiums"][round_num] = op_podium
                
                # 메인 리스트 썸네일과 카드 컬러도 동시 업데이트 반영하기 위해 리스트 캐시 리셋 처리
                cache["list_updated_at"] = None 
                save_cache(cache)
                return jsonify(op_podium)
                
    return jsonify([])

# 🏛️ 위키피디아 요약 Proxy 엔드포인트 (로컬 파일 영구 저장 캐싱 결합)
@app.route('/api/wiki-meta/<page_title>')
def api_wiki_meta(page_title):
    cache = load_cache()
    if page_title in cache["wiki"]:
        return jsonify(cache["wiki"][page_title])
        
    fallback = {"extract": "요약 정보를 불러올 수 없습니다.", "image": ""}
    data = fetch_json_safely(f"https://en.wikipedia.org/api/rest_v1/page/summary/{page_title}", timeout=2)
    if not data: 
        return jsonify(fallback)
        
    payload = {
        "extract": data.get("extract", "설명이 비어 있습니다."),
        "image": data.get("originalimage", {}).get("source") or data.get("thumbnail", {}).get("source") or ""
    }
    cache["wiki"][page_title] = payload
    save_cache(cache)
    return jsonify(payload)

if __name__ == '__main__':
    app.run(debug=True, port=5001)