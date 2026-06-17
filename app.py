from flask import Flask, render_template
import sqlite3
import os

from dotenv import load_dotenv
load_dotenv()  # .env 파일 로드

app = Flask(__name__)

def get_db_connection():
    # 현재 실행 중인 app.py 파일의 절대 경로를 기준으로 DB 위치 지정
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, 'f1_news.db')
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    conn = get_db_connection()
    # 최신 뉴스 10개 가져오기
    articles = conn.execute(
        'SELECT id, title, link, summary_ko, image_url, published_at FROM articles ORDER BY published_at DESC LIMIT 10'
    ).fetchall()
    conn.close()
    return render_template('index.html', articles=articles)

@app.route('/article/<int:article_id>')
def article_detail(article_id):
    conn = get_db_connection()
    article = conn.execute('SELECT * FROM articles WHERE id = ?', (article_id,)).fetchone()
    conn.close()
    return render_template('detail.html', article=article)

@app.route('/standings')
def standings():
    # 자바스크립트 처리 방식으로 전환되어 DB 조회 없이 템플릿만 렌더링
    return render_template('standings.html')

@app.route('/calendar')
def calendar():
    # 자바스크립트 처리 방식으로 전환되어 DB 조회 없이 템플릿만 렌더링
    return render_template('calendar.html')

if __name__ == '__main__':
    app.run(debug=True, port=5000)