from flask import Flask, render_template, jsonify, request
import sqlite3
import os
import urllib.request
import json
import ssl
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
 
from dotenv import load_dotenv
load_dotenv()  
 
app = Flask(__name__)
 
# 💾 2차 소스(OpenF1) 데이터 구멍 메우기용 서버 메모리 캐시
OPENF1_PODIUM_CACHE = {}
 
# 💾 /api/calendar-list 전체 응답 캐시 (외부 API가 느리거나 죽었을 때 매 요청마다 재호출 방지)
CALENDAR_LIST_CACHE = {"payload": None, "ts": 0}
CALENDAR_LIST_TTL_SECONDS = 300  # 5분: 캘린더는 자주 안 바뀌고, jolpi.ca 시간당 200req 제한도 있어 너무 짧으면 위험
 
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
 
# ⏱️ 예선(Qualifying) leader gap 계산용: "1:23.456" / "23.456" 형태의 랩타임 문자열을 초로 변환
def parse_lap_time_to_seconds(t):
    if not t or t == "-":
        return None
    try:
        if ":" in t:
            mins, secs = t.split(":")
            return int(mins) * 60 + float(secs)
        return float(t)
    except (ValueError, TypeError):
        return None
 
def format_gap_seconds(diff_seconds):
    if diff_seconds is None:
        return None
    return f"+{diff_seconds:.3f}"
 
def fetch_json_safely(url, timeout=7, retries=1, retry_delay=0.6):
    last_err = None
    for attempt in range(retries + 1):
        try:
            ssl_context = ssl._create_unverified_context()
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'LecLovF1/1.0 (contact@leclovf1.com) Python/3.x'}
            )
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            last_err = e
            if attempt < retries:
                # jolpi.ca는 백엔드 과부하 시 503을 자주 반환하는 것으로 알려져 있어 짧게 한 번 재시도
                time.sleep(retry_delay)
                continue
    print(f"⚠️ API 통신 지연/실패 ({url}): {last_err}")
    return None
 
# OpenF1 2차 피드 정밀 타격 함수
def fetch_openf1_fallback(locality, race_date):
    try:
        year = race_date.split("-")[0] if race_date else "2026"
        sessions = fetch_json_safely(f"https://api.openf1.org/v1/sessions?year={year}&session_name=Race")
        if not sessions: return None
        
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
        if not results or not drivers: return None
        
        valid_results = []
        for r in results:
            pos = r.get("position") or r.get("position_current")
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
    # 1) 짧은 TTL 캐시: 외부 API가 느리거나 죽어 있어도 매 새로고침마다 재호출하지 않음
    cached = CALENDAR_LIST_CACHE["payload"]
    if cached and (time.time() - CALENDAR_LIST_CACHE["ts"] < CALENDAR_LIST_TTL_SECONDS):
        return jsonify(cached)
 
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    with ThreadPoolExecutor(max_workers=2) as pre_executor:
        calendar_future = pre_executor.submit(fetch_json_safely, "https://api.jolpi.ca/ergast/f1/current.json")
        results_future = pre_executor.submit(fetch_json_safely, "https://api.jolpi.ca/ergast/f1/current/results.json?limit=1000")
        calendar_data = calendar_future.result()
        results_data = results_future.result()
    if not calendar_data:
        # 1차 소스 실패 시, 직전에 성공했던 캐시가 있다면 그거라도 내려준다 (프론트가 무한로딩에 빠지지 않도록)
        if cached:
            return jsonify(cached)
        return jsonify({"error": "1차 소스 통신 실패"}), 500
 
    races = calendar_data["MRData"]["RaceTable"]["Races"]
    results_map = {r["round"]: r["Results"] for r in results_data["MRData"]["RaceTable"]["Races"]} if results_data else {}
    next_race_idx = next((i for i, r in enumerate(races) if r["date"] >= today_str), len(races) - 1)
 
    # 2) jolpi 결과가 없는 과거 라운드만 모아서, OpenF1 fallback을 "순차"가 아니라 "병렬"로 호출
    #    (라운드가 여러 개 비어 있을 때 응답이 N배로 느려지는 게 체감 무한로딩의 핵심 원인)
    rounds_needing_fallback = []
    for race in races:
        r_num = race["round"]
        c_date = race["date"]
        is_past = (c_date < today_str or r_num in results_map)
        if is_past and r_num not in results_map and r_num not in OPENF1_PODIUM_CACHE:
            rounds_needing_fallback.append(race)
 
    if rounds_needing_fallback:
        with ThreadPoolExecutor(max_workers=min(8, len(rounds_needing_fallback))) as executor:
            future_map = {
                executor.submit(fetch_openf1_fallback, race["Circuit"]["Location"]["locality"], race["date"]): race["round"]
                for race in rounds_needing_fallback
            }
            for future in future_map:
                r_num = future_map[future]
                try:
                    op_podium = future.result(timeout=10)
                    if op_podium:
                        OPENF1_PODIUM_CACHE[r_num] = op_podium
                except Exception as e:
                    print(f"🚨 OpenF1 병렬 fallback 실패 (round {r_num}): {e}")
 
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
        elif is_past and r_num in OPENF1_PODIUM_CACHE:
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
 
    payload = {"next_race_idx": next_race_idx, "races": list_payload}
    CALENDAR_LIST_CACHE["payload"] = payload
    CALENDAR_LIST_CACHE["ts"] = time.time()
    return jsonify(payload)
 
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
 
# 🏛️ [통합 연동] 하단 세션 타임라인 분석용 신규 라우트 배치 완료
@app.route('/api/race-sessions/<round_num>')
def api_race_sessions(round_num):
    season = request.args.get('season', 'current')
    payload = {
        "schedule": {}, "qualifying": [], "sprint": [], "race": [],
        "qualifying_full": [], "sprint_full": [], "race_full": []
    }
    
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
            
    quali_data = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/{season}/{round_num}/qualifying.json")
    if quali_data and "MRData" in quali_data and quali_data["MRData"]["RaceTable"]["Races"]:
        r_table = quali_data["MRData"]["RaceTable"]["Races"]
        if "QualifyingResults" in r_table[0]:
            q_full = []
            leader_secs = None
            for q in r_table[0]["QualifyingResults"]:
                best_time = q.get("Q3") or q.get("Q2") or q.get("Q1") or "-"
                secs = parse_lap_time_to_seconds(best_time)
                if q["position"] == "1":
                    leader_secs = secs
                q_full.append({
                    "position": q["position"], "driver": f"{q['Driver']['givenName']} {q['Driver']['familyName']}",
                    "constructor": q["Constructor"]["name"], "time": best_time, "_secs": secs
                })
            for item in q_full:
                # 리더는 프론트에서 "LEADER"로 표시하므로 gap은 비워두고, 나머지는 대표 기록(Q1/Q2/Q3 중 최종) 기준 leader와의 차이를 계산
                if item["position"] == "1" or item["_secs"] is None or leader_secs is None:
                    item["gap"] = None
                else:
                    item["gap"] = format_gap_seconds(item["_secs"] - leader_secs)
                del item["_secs"]
            payload["qualifying_full"] = q_full
            payload["qualifying"] = q_full[:5]
 
    sprint_data = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/{season}/{round_num}/sprint.json")
    if sprint_data and "MRData" in sprint_data and sprint_data["MRData"]["RaceTable"]["Races"]:
        r_table = sprint_data["MRData"]["RaceTable"]["Races"]
        if "SprintResults" in r_table[0]:
            s_full = []
            for s in r_table[0]["SprintResults"]:
                if s["position"] == "1":
                    gap = None  # 프론트에서 "LEADER"로 표시
                elif s.get("Time", {}).get("time"):
                    gap = s["Time"]["time"]  # 동일 랩 완주: Ergast가 이미 "+5.073" 형태로 제공
                else:
                    gap = s.get("status")  # 랩 차이/리타이어 등: "+1 Lap", "Retired" 등
                s_full.append({
                    "position": s["position"], "driver": f"{s['Driver']['givenName']} {s['Driver']['familyName']}",
                    "constructor": s["Constructor"]["name"], "points": s.get("points", "0"), "gap": gap
                })
            payload["sprint_full"] = s_full
            payload["sprint"] = s_full[:5]
 
    race_data = fetch_json_safely(f"https://api.jolpi.ca/ergast/f1/{season}/{round_num}/results.json")
    if race_data and "MRData" in race_data and race_data["MRData"]["RaceTable"]["Races"]:
        r_table = race_data["MRData"]["RaceTable"]["Races"]
        if "Results" in r_table[0]:
            r_full = []
            for r in r_table[0]["Results"]:
                if r["position"] == "1":
                    gap = None  # 프론트에서 "LEADER"로 표시
                elif r.get("Time", {}).get("time"):
                    gap = r["Time"]["time"]  # 동일 랩 완주: Ergast가 이미 "+5.073" 형태로 제공
                else:
                    gap = r.get("status")  # 랩 차이/리타이어 등: "+1 Lap", "+2 Laps", "Retired" 등
                r_full.append({
                    "position": r["position"], "driver": f"{r['Driver']['givenName']} {r['Driver']['familyName']}",
                    "constructor": r["Constructor"]["name"], "points": r.get("points", "0"), "gap": gap
                })
            payload["race_full"] = r_full
            payload["race"] = r_full[:5]
            
    return jsonify(payload)
 
if __name__ == '__main__':
    app.run(debug=True, port=5001)