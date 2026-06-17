from flask import Flask, render_template
import sqlite3
import os

from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

def get_db_connection():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, 'f1_news.db')
    conn = sqlite3.connect(db_path)
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

# 🔥 [수정] 기존의 conn.execute('SELECT * FROM standings...') 코드를 싹 지웁니다!
@app.route('/standings')
def standings():
    return render_template('standings.html')

# 🔥 [수정] 캘린더도 마찬가지로 데이터베이스를 거치지 않고 화면만 열어줍니다.
@app.route('/calendar')
def calendar():
    return render_template('calendar.html')

if __name__ == '__main__':
    app.run(debug=True, port=5000)