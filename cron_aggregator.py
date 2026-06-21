import os
import re
import sqlite3
import feedparser
from datetime import datetime, timezone
from deep_translator import GoogleTranslator # 0달러 구글 번역 라이브러리 도입

from dotenv import load_dotenv

load_dotenv()

CLEANR = re.compile('<.*?>')

def clean_html(raw_html):
    if not raw_html:
        return ""
    return re.sub(CLEANR, '', raw_html).strip()

def init_db():
    conn = sqlite3.connect('f1_news.db')
    cursor = conn.cursor()
    
    # 테이블 생성 규칙 유지
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, 
        title TEXT, 
        link TEXT UNIQUE, 
        summary_ko TEXT, 
        image_url TEXT,
        published_at DATETIME DEFAULT CURRENT_TIMESTAMP)
    ''')
    
    cursor.execute("DELETE FROM articles") 
    conn.commit()
    return conn

def translate_title_ko(raw_title):
    """
    구글 번역 프리 트랜스레이터를 이용해 영어 헤드라인을 한국어로 번역합니다.
    """
    try:
        translated = GoogleTranslator(source='en', target='ko').translate(raw_title)
        return translated
    except Exception as e:
        print(f"❌ 구글 번역 오류 발생: {e}")
        return raw_title # 오류 발생 시 원문 제목 유지

def run_f1_aggregator():
    F1_RSS_URL = [
        "https://www.formula1.com/en/latest/all.xml",
        "https://www.fia.com/rss/news/championships/f1-world-championship-1200.xml",
    ]

    trends_score = {}
    important_entries = []

    import urllib.request
    import ssl

    print("🏎️ 해외 F1 실시간 뉴스 수집 및 구글 번역 파이프라인 시작...")
    
    all_entries = []
    ssl_context = ssl._create_unverified_context()
    
    for url in F1_RSS_URL:
        try:
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            )
            with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
                rss_data = response.read()
            
            feed = feedparser.parse(rss_data)
            if feed.entries:
                all_entries.extend(feed.entries)
                print(f"✅ 수집 성공: {url.split('/')[2]} ({len(feed.entries)}개 기사)")
                
        except Exception as e:
            print(f"❌ RSS 피드 연결 실패 ({url}): {e}")
    
    if not all_entries:
        print("❌ 뉴스를 가져오지 못했거나 최신 뉴스가 없습니다.")
        return

    print(f"\n✨ 성공! 총 {len(all_entries)}개의 최신 뉴스를 가져왔습니다.\n")
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
        "podium": {"keywords": ["podium", "top 3"], "display": "Podium", "score": 200},
        "champion": {"keywords": ["champion", "championship"], "display": "Champion", "score": 50},
        "pole": {"keywords": ["pole"], "display": "Pole", "score": 150},
        "penalty": {"keywords": ["penalty"], "max_score": 80, "keywords": ["penalty"], "display": "Penalty", "score": 80},
        "retirement": {"keywords": ["retirement"], "display": "Retirement", "score": 50},
        "positive": {"keywords": ["positive", "improvement", "progress", "boost", "best", "revival", "success", "upgrade"], "display": "Positive", "score": 20},
        "worst": {"keywords": ["worst", "decline", "regression", "reliability", "concerns"], "display": "Worst", "score": 20}
    }

    for entry in all_entries:
        title = entry.title
        title_lower = title.lower()
        link = entry.link
        summary_raw = clean_html(entry.get('summary', title))
        
        matched_keys = set()
        total_article_score = 0

        image_url = ""
        if 'media_content' in entry and entry.media_content:
            image_url = entry.media_content[0]['url']
        elif 'enclosures' in entry and entry.enclosures:
            image_url = entry.enclosures[0]['href']

        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            pub_time = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        else:
            pub_time = now_utc 
            
        days_old = max(0, (now_utc - pub_time).days)
        time_penalty = days_old * 50
        if time_penalty > 0:
            total_article_score -= time_penalty

        for driver_key, info in f1_drivers.items():
            if any(re.search(r'\b' + re.escape(kw) + r'\b', title_lower) for kw in info["keywords"]):
                score_to_add = driver_base + info["bonus"]
                trends_score[driver_key] = trends_score.get(driver_key, 0) + score_to_add
                total_article_score += score_to_add
                matched_keys.add(driver_key)

        for team, bonus in constructor_bonus.items():
            if re.search(r'\b' + re.escape(team) + r'\b', title_lower):
                score_to_add = constructor_base + bonus
                trends_score[team] = trends_score.get(team, 0) + score_to_add
                total_article_score += score_to_add
                matched_keys.add(team)

        for status_key, info in status_keywords.items():
            if any(re.search(r'\b' + re.escape(kw) + r'\b', title_lower) for kw in info["keywords"]):
                score_to_add = info["score"]
                trends_score[status_key] = trends_score.get(status_key, 0) + score_to_add
                total_article_score += score_to_add
                matched_keys.add(status_key)

        important_entries.append({
            "title": title,
            "link": link,
            "summary_raw": summary_raw,
            "score": total_article_score,
            "matched_keys": matched_keys,
            "image_url": image_url
        })

    important_entries.sort(key=lambda x: x['score'], reverse=True)
    
    filtered_entries = []
    has_win_article = False
    seen_pole_drivers = set()
    seen_keyword_sets = []
    
    for article in important_entries:
        keys = article['matched_keys']
        if 'win' in keys:
            if has_win_article: continue
            has_win_article = True
        if 'pole' in keys:
            drivers_in_article = [k for k in keys if k in f1_drivers]
            if any(driver in seen_pole_drivers for driver in drivers_in_article): continue
            for driver in drivers_in_article: seen_pole_drivers.add(driver)
                
        is_redundant_general = False
        for seen_keys in seen_keyword_sets:
            overlap = keys.intersection(seen_keys)
            overlap_filtered = {k for k in overlap if k != 'positive' and k != 'worst'}
            if len(overlap_filtered) >= 4:
                is_redundant_general = True
                break
        if is_redundant_general: continue
            
        filtered_entries.append(article)
        seen_keyword_sets.append(keys)

    top_10_entries = filtered_entries[:10]

    conn = init_db()
    saved_count = 0

    print(f"\n🔄 최종 통과된 상위 {len(top_10_entries)}개 기사 단순 구글 번역 시작...")
    try:
        cursor = conn.cursor()
        for article in top_10_entries:
            cursor.execute("SELECT 1 FROM articles WHERE link = ?", (article['link'],))
            if cursor.fetchone() is not None:
                continue 

            print(f"📰 구글 번역 중: {article['title']}")
            
            # GPT 요약 기능 삭제 -> 헤드라인 구글 번역 매핑
            title_ko = translate_title_ko(article['title'])
            summary_ko = "" # 요약문은 빈 문자열로 처리

            try:
                cursor.execute(
                    "INSERT INTO articles (title, link, summary_ko, image_url) VALUES (?, ?, ?, ?)",
                    (title_ko, article['link'], summary_ko, article['image_url'])
                )
                conn.commit() 
                saved_count += 1
            except sqlite3.IntegrityError:
                conn.rollback()
            except Exception as e:
                conn.rollback()
                print(f"❌ DB 저장 중 오류 발생: {e}")
    finally:
        conn.close() 
        
    print(f"\n✨ 파이프라인 완료! 총 {saved_count}개의 기사가 구글 번역되어 DB에 저장되었습니다.")

if __name__ == "__main__":
    run_f1_aggregator()