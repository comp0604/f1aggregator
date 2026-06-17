from flask import Flask, render_template
import sqlite3

from dotenv import load_dotenv
load_dotenv()  # 프로젝트 폴더 내의 .env 파일을 읽어옵니다.

app = Flask(__name__)

def get_db_connection():
    conn = sqlite3.connect('f1_news.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    conn = get_db_connection()
    articles = conn.execute(
        'SELECT id, title, link, summary_ko, published_at FROM articles ORDER BY published_at DESC LIMIT 10'
    ).fetchall()
    conn.close()
    return render_template('index.html', articles=articles)

if __name__ == '__main__':
    app.run(debug=True, port=5000)