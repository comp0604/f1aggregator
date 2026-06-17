import os
import re
import sqlite3
import feedparser
import json
from datetime import datetime, timezone
from openai import OpenAI, OpenAIError

from dotenv import load_dotenv

load_dotenv()

print("=" * 40)
print(f"현재 로드된 API 키 상태: {os.environ.get('OPENAI_API_KEY')}")
print("=" * 40)

# API 키 설정
API_KEY = os.environ.get("OPENAI_API_KEY", "your-actual-api-key")
client = OpenAI(api_key=API_KEY)

CLEANR = re.compile('<.*?>')

def clean_html(raw_html):
    if not raw_html:
        return ""
    return re.sub(CLEANR, '', raw_html).strip()

def init_db():
    conn = sqlite3.connect('f1_news.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, 
         title TEXT, 
         link TEXT UNIQUE, 
         summary_ko TEXT, 
         published_at DATETIME DEFAULT CURRENT_TIMESTAMP)
    ''')
    conn.commit()
    return conn

def get_f1_summary_ko(raw_title, raw_text):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={ "type": "json_object" }, 
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "너는 대한민국 최고의 모터스포츠(F1) 전문 기자야. "
                        "제공된 영어 뉴스 제목과 원문을 분석해서 자연스러운 한국어로 번역 및 요약해줘.\n\n"
                        "[요구사항]\n"
                        "1. title_ko: 영어 기사 제목을 국내 스포츠 기사 헤드라인처럼 시선을 끌고 자연스럽게 번역해.\n"
                        "2. summary_ko: 원문 내용을 핵심만 골라 읽기 편한 '한국어 2문장'으로 요약해.\n"
                        "3. 어투: '~다', '~했다' 형식의 깔끔하고 전문적인 스포츠 기사 문체를 사용해.\n\n"
                        "[F1 번역 사전 및 교정 지침]\n"
                        "- Maiden win -> 첫 우승 / 데뷔 첫 승\n"
                        "- Banished his demons -> 징크스를 극복하다 / 슬럼프를 탈출하다 (직역 금지)\n"
                        "- Middle finger -> 통쾌한 반격 / 일침 (직역 금지)\n"
                        "- Class act -> 품격 있는 태도 / 훌륭한 스포츠맨십\n"
                        "- Chassis -> 섀시\n"
                        "- Pole / Pole position -> 폴 포지션\n"
                        "- Retirement / Retires -> 리타이어\n"
                        "- Scuderia -> 스쿠데리아 페라리 (자연스럽게)\n"
                        "- Virtual Safety Car (VSC) -> 가상 세이프티카(VSC)\n\n"
                        "반드시 아래 JSON 형식으로만 응답해:\n"
                        "{\n"
                        "  \"title_ko\": \"한국어 헤드라인\",\n"
                        "  \"summary_ko\": \"첫 번째 문장.\\n두 번째 문장.\"\n"
                        "}"
                    )
                },
                {"role": "user", "content": f"Title: {raw_title}\n\nContent: {raw_text}"}
            ],
            temperature=0.4
        )
        
        result = json.loads(response.choices[0].message.content)
        return result.get("title_ko", raw_title), result.get("summary_ko", "요약을 생성할 수 없습니다.")
        
    except OpenAIError as e:
        print(f"❌ OpenAI API 오류 발생: {e}")
        return raw_title, "API 오류로 인해 요약을 생성할 수 없습니다."
    except Exception as e:
        print(f"❌ AI 요약 중 알 수 없는 오류 발생: {e}")
        return raw_title, "요약을 생성할 수 없습니다."

def run_f1_aggregator():
    F1_RSS_URL = "https://www.motorsport.com/rss/f1/news/"
    trends_score = {}
    important_entries = []

    import urllib.request
    import ssl

    print("🏎️ 해외 F1 실시간 뉴스 수집 중...")
    
    req = urllib.request.Request(
        F1_RSS_URL, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    )
    
    ssl_context = ssl._create_unverified_context()
    
    try:
        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
            rss_data = response.read()
        feed = feedparser.parse(rss_data)
    except Exception as e:
        print(f"❌ RSS 피드를 연결하는 중 오류가 발생했습니다: {e}")
        return
    
    if not feed.entries:
        if hasattr(feed, 'bozo_exception'):
            print(f"🔍 파싱 에러 상세 내용: {feed.bozo_exception}")
        print("❌ 뉴스를 가져오지 못했거나 최신 뉴스가 없습니다.")
        return

    print(f"성공! 총 {len(feed.entries)}개의 최신 뉴스를 가져왔습니다.\n")
    print("-" * 50)

    now_utc = datetime.now(timezone.utc)

    driver_base = 50
    constructor_base = 20

    f1_drivers = {
        "hamilton": {"keywords": ["hamilton", "lewis"], "display": "Hamilton", "bonus": 50},
        "leclerc": {"keywords": ["leclerc", "charles"], "display": "Leclerc", "bonus": 50},
        "norris": {"keywords": ["norris", "lando"], "display": "Norris", "bonus": 40},
        "piastri": {"keywords": ["piastri", "oscar"], "display": "Piastri", "bonus": 30},
        "verstappen": {"keywords": ["verstappen", "max"], "display": "Verstappen", "bonus": 50},
        "hadjar": {"keywords": ["hadjar", "isack"], "display": "Hadjar", "bonus": 0},
        "russell": {"keywords": ["russell", "george", "jeorge"], "display": "Russell", "bonus": 40},
        "antonelli": {"keywords": ["antonelli", "kimi"], "display": "Antonelli", "bonus": 40},
        "gasly": {"keywords": ["gasly", "pierre"], "display": "Gasly", "bonus": 0},
        "colapinto": {"keywords": ["colapinto", "franco"], "display": "Colapinto", "bonus": 0},
        "lawson": {"keywords": ["lawson", "liam"], "display": "Lawson", "bonus": 0},
        "lindblad": {"keywords": ["lindblad", "arvid"], "display": "Lindblad", "bonus": 0},
        "ocon": {"keywords": ["ocon", "esteban"], "display": "Ocon", "bonus": 0},
        "sainz": {"keywords": ["sainz", "carlos"], "display": "Sainz", "bonus": 10},
        "albon": {"keywords": ["albon", "alexander", "alex"], "display": "Albon", "bonus": 0},
        "hulkenberg": {"keywords": ["hulkenberg", "nico"], "display": "Hulkenberg", "bonus": 0},
        "bortoleto": {"keywords": ["bortoleto", "gabriel"], "display": "Bortoleto", "bonus": 0},
        "alonso": {"keywords": ["alonso", "fernando"], "display": "Alonso", "bonus": 20},
        "perez": {"keywords": ["perez", "sergio"], "display": "Perez", "bonus": 10},
        "bottas": {"keywords": ["bottas", "valtteri"], "display": "Bottas", "bonus": 10}
    }

    constructor_bonus = {
        "ferrari": 20, "mclaren": 20, "red bull": 20, "mercedes": 20, 
        "alpine": 0, "racing bulls": 0, "williams": 0, "audi": 0, 
        "aston martin": 0, "cadillac": 10
    }

    status_keywords = {
        "win": {"keywords": ["win", "triumph", "victory"], "display": "Win", "score": 300},
        "champion": {"keywords": ["champion", "championship"], "display": "Champion", "score": 50},
        "pole": {"keywords": ["pole"], "display": "Pole", "score": 150},
        "penalty": {"keywords": ["penalty"], "display": "Penalty", "score": 80},
        "retirement": {"keywords": ["retirement"], "display": "Retirement", "score": 50},
        "positive": {"keywords": ["positive", "improvement", "progress", "boost", "best", "revival", "success", "upgrade"], "display": "Positive", "score": 20},
        "worst": {"keywords": ["worst", "decline", "regression", "reliability", "concerns"], "display": "Worst", "score": 20}
    }

    for entry in feed.entries:
        title = entry.title
        title_lower = title.lower()
        link = entry.link
        summary_raw = clean_html(entry.get('summary', title))
        
        detected = []
        matched_keys = set() # 중복 검사를 위해 감지된 고유 키워드를 저장하는 집합
        total_article_score = 0

        # 시간 페널티 계산
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            pub_time = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        else:
            pub_time = now_utc 
            
        days_old = max(0, (now_utc - pub_time).days)
        time_penalty = days_old * 50
        
        if time_penalty > 0:
            total_article_score -= time_penalty
            detected.append(f"⏳시간감점(-{time_penalty}점/{days_old}일)")

        for driver_key, info in f1_drivers.items():
            if any(re.search(r'\b' + re.escape(kw) + r'\b', title_lower) for kw in info["keywords"]):
                score_to_add = driver_base + info["bonus"]
                trends_score[driver_key] = trends_score.get(driver_key, 0) + score_to_add
                total_article_score += score_to_add
                detected.append(f"{info['display']}(+{score_to_add}점)")
                matched_keys.add(driver_key)

        for team, bonus in constructor_bonus.items():
            if re.search(r'\b' + re.escape(team) + r'\b', title_lower):
                score_to_add = constructor_base + bonus
                trends_score[team] = trends_score.get(team, 0) + score_to_add
                total_article_score += score_to_add
                team_display = team.title() if team != "red bull" else "Red Bull"
                detected.append(f"{team_display}(+{score_to_add}점)")
                matched_keys.add(team)

        for status_key, info in status_keywords.items():
            if any(re.search(r'\b' + re.escape(kw) + r'\b', title_lower) for kw in info["keywords"]):
                score_to_add = info["score"]
                trends_score[status_key] = trends_score.get(status_key, 0) + score_to_add
                total_article_score += score_to_add
                detected.append(f"{info['display']}(+{score_to_add}점)")
                matched_keys.add(status_key)

        important_entries.append({
            "title": title,
            "link": link,
            "summary_raw": summary_raw,
            "score": total_article_score,
            "matched_keys": matched_keys # 필터링을 위해 추가
        })

    # --- 🧹 스마트 중복 필터링 로직 ---
    # 먼저 점수가 높은 순으로 정렬합니다.
    important_entries.sort(key=lambda x: x['score'], reverse=True)
    
    filtered_entries = []
    has_win_article = False
    seen_pole_drivers = set()
    seen_keyword_sets = []
    
    print("\n🧹 중복 기사 필터링 진행 중...")
    for article in important_entries:
        keys = article['matched_keys']
        
        # 1. 우승(Win) 기사 도배 방지
        if 'win' in keys:
            if has_win_article:
                print(f"  [탈락] 우승 중복: {article['title']}")
                continue
            has_win_article = True
            
        # 2. 폴포지션(Pole) + 드라이버 조합 도배 방지
        if 'pole' in keys:
            drivers_in_article = [k for k in keys if k in f1_drivers]
            # 해당 기사에 등장한 드라이버 중 이미 폴포지션 기사로 등록된 드라이버가 있다면 탈락
            if any(driver in seen_pole_drivers for driver in drivers_in_article):
                print(f"  [탈락] 폴포지션+드라이버 중복: {article['title']}")
                continue
            for driver in drivers_in_article:
                seen_pole_drivers.add(driver)
                
        # 4 'positive' 키워드를 제외하고 중복 개수 4개 이상 제외
        is_redundant_general = False
        for seen_keys in seen_keyword_sets:
            overlap = keys.intersection(seen_keys)
            
            # 여기서 'positive'는 걸러내고 개수를 셉니다.
            overlap_filtered = {k for k in overlap if k != 'positive' and k != 'worst'}
            
            if len(overlap_filtered) >= 4:
                is_redundant_general = True
                overlap_str = ', '.join([k.upper() for k in overlap_filtered])
                print(f"  [탈락] 키워드 4개 이상 일치({overlap_str}): {article['title']}")
                break
                
        if is_redundant_general:
            continue
            
        # 모든 검사를 통과한 기사만 저장
        filtered_entries.append(article)
        seen_keyword_sets.append(keys)

    top_10_entries = filtered_entries[:10]
    # -------------------------------

    print("-" * 50)
    print("📊 [최종 트렌드 분석 결과 점수판]")
    for keyword, score in sorted(trends_score.items(), key=lambda x: x[1], reverse=True):
        print(f"• {keyword.upper()}: {score}점")

    conn = init_db()
    saved_count = 0

    print(f"\n🔄 2단계: 최종 통과된 상위 {len(top_10_entries)}개 기사 AI 2줄 요약 진행 중...")
    try:
        cursor = conn.cursor()
        for article in top_10_entries:
            cursor.execute("SELECT 1 FROM articles WHERE link = ?", (article['link'],))
            if cursor.fetchone() is not None:
                continue 

            print(f"📰 요약 중: {article['title']} (최종 점수: {article['score']})")
            
            title_ko, summary_ko = get_f1_summary_ko(article['title'], article['summary_raw'])

            try:
                cursor.execute(
                    "INSERT INTO articles (title, link, summary_ko) VALUES (?, ?, ?)",
                    (title_ko, article['link'], summary_ko)
                )
                conn.commit() 
                saved_count += 1
            except sqlite3.IntegrityError:
                conn.rollback()
                pass
            except Exception as e:
                conn.rollback()
                print(f"❌ DB 저장 중 오류 발생: {e}")
    finally:
        conn.close() 
        
    print(f"\n✨ 파이프라인 완료! 총 {saved_count}개의 새로운 기사가 요약되어 DB에 저장되었습니다.")

if __name__ == "__main__":
    run_f1_aggregator()