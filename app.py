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

def get_db_connection():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    conn = sqlite3.connect(os.path.join(base_dir, 'f1_news.db'))
    conn.row_factory = sqlite3.Row
    return conn

def fetch_json_safely(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5, context=ssl._create_unverified_context()) as res:
            return json.loads(res.read().decode('utf-8'))
    except: return {}

@app.route('/')
def index():
    conn = get_db_connection()
    articles = conn.execute('SELECT title, link, summary_ko, image_url, published_at FROM articles ORDER BY published_at DESC LIMIT 10').fetchall()
    conn.close()
    return render_template('index.html', articles=articles)

@app.route('/calendar')
def calendar_page(): return render_template('calendar.html')

@app.route('/standings')
def standings_page(): return render_template('standings.html')

# 독립된 API 복구 (서로 충돌하지 않음)
@app.route('/api/calendar-list')
def api_calendar_list():
    data = fetch_json_safely("https://api.jolpi.ca/ergast/f1/current.json")
    return jsonify(data)

@app.route('/api/driver-standings')
def api_drivers():
    return jsonify(fetch_json_safely("https://api.jolpi.ca/ergast/f1/current/driverStandings.json"))

@app.route('/api/constructor-standings')
def api_constructors():
    return jsonify(fetch_json_safely("https://api.jolpi.ca/ergast/f1/current/constructorStandings.json"))

@app.route('/api/wiki-meta/<page_title>')
def api_wiki_meta(page_title):
    data = fetch_json_safely(f"https://en.wikipedia.org/api/rest_v1/page/summary/{page_title}")
    return jsonify({"extract": data.get("extract", ""), "image": data.get("originalimage", {}).get("source") or data.get("thumbnail", {}).get("source") or ""})

if __name__ == '__main__':
    app.run(debug=True, port=5001)