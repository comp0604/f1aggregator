from flask import Flask, render_template
import sqlite3
import os  # <-- 1. 상단에 os 라이브러리를 추가합니다.

from dotenv import load_dotenv
load_dotenv()  # 프로젝트 폴더 내의 .env 파일을 읽어옵니다.

app = Flask(__name__)

def get_db_connection():
    # <-- 2. 현재 실행 중인 app.py 파일의 절대 경로를 기준으로 db 위치를 찾습니다.
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, 'f1_news.db')
    
    conn = sqlite3.connect(db_path) # <-- 3. db_path로 연결합니다.
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    conn = get_db_connection()
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

if __name__ == '__main__':
    app.run(debug=True, port=5000)