from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import sqlite3
import json
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'секретный-ключ-поменяйте-на-свой'  # Обязательно смените!

DATABASE = 'taxi_data.db'

# ---------- НАСТРОЙКА FLASK-LOGIN ----------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите для доступа'

class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, username, password_hash FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return User(row['id'], row['username'], row['password_hash'])
    return None

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    # --- Существующие таблицы ---
    c.execute('''CREATE TABLE IF NOT EXISTS expenses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  hall TEXT, date TEXT,
                  people_count INTEGER DEFAULT 0,
                  taxi1 REAL DEFAULT 0, taxi2 REAL DEFAULT 0, taxi3 REAL DEFAULT 0,
                  taxi_total REAL DEFAULT 0, avg_taxi REAL DEFAULT 0,
                  prolong REAL DEFAULT 0, extra_clean REAL DEFAULT 0,
                  total_day REAL DEFAULT 0,
                  UNIQUE(hall, date))''')
    c.execute('''CREATE TABLE IF NOT EXISTS transfers
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  from_hall TEXT, to_hall TEXT, item_name TEXT,
                  photo_url TEXT, transfer_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS halls (name TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS admin_settings
                 (key TEXT PRIMARY KEY, value TEXT)''')

    # --- НОВЫЕ ТАБЛИЦЫ: пользователи и журнал действий ---
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS activity_log
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  username TEXT,
                  action TEXT,
                  target TEXT,
                  details TEXT,
                  timestamp TEXT)''')

    # --- Добавляем колонку garbage, если её ещё нет ---
    c.execute("PRAGMA table_info(expenses)")
    columns = [col[1] for col in c.fetchall()]
    if 'garbage' not in columns:
        c.execute("ALTER TABLE expenses ADD COLUMN garbage REAL DEFAULT 0")
        print("Добавлена колонка garbage в таблицу expenses")

    # --- Создаём первого пользователя, если нет ни одного ---
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        admin_hash = generate_password_hash('admin')   # пароль: admin
        c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ('admin', admin_hash))
        print("Создан пользователь admin с паролем admin")

    # --- Начальные залы, если пусто ---
    c.execute("SELECT COUNT(*) FROM halls")
    if c.fetchone()[0] == 0:
        default_halls = ['B1', 'B3', 'B4', 'B5', 'B7']
        for h in default_halls:
            c.execute("INSERT INTO halls (name) VALUES (?)", (h,))

    conn.commit()
    conn.close()

init_db()

# ---------- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ЛОГИРОВАНИЯ ----------
def log_action(action, target, details=''):
    """Сохраняет действие в activity_log"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO activity_log (user_id, username, action, target, details, timestamp)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (current_user.id, current_user.username, action, target, details, datetime.now().isoformat()))
    conn.commit()
    conn.close()

# ------------------- СТРАНИЦЫ -------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,))
        row = c.fetchone()
        conn.close()
        if row and check_password_hash(row['password_hash'], password):
            user = User(row['id'], row['username'], row['password_hash'])
            login_user(user)
            log_action('LOGIN', f'user {username}', 'Вход в систему')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('Неверное имя пользователя или пароль')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    log_action('LOGOUT', f'user {current_user.username}', 'Выход из системы')
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/transfers')
@login_required
def transfers_page():
    return render_template('transfers.html')

# ------------------- API РАСХОДЫ -------------------
@app.route('/api/save_expense', methods=['POST'])
@login_required
def save_expense():
    data = request.json
    conn = get_db()
    c = conn.cursor()
    taxi_total = float(data['taxi1']) + float(data['taxi2']) + float(data['taxi3'])
    people = int(data['people']) if int(data['people']) > 0 else 1
    avg_taxi = taxi_total / people
    garbage = float(data.get('garbage', 0))
    total_day = taxi_total + garbage + float(data['prolong']) + float(data['extra_clean'])

    c.execute('''INSERT OR REPLACE INTO expenses
                 (hall, date, people_count, taxi1, taxi2, taxi3, taxi_total, avg_taxi, garbage, prolong, extra_clean, total_day)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (data['hall'], data['date'], people,
               float(data['taxi1']), float(data['taxi2']), float(data['taxi3']),
               taxi_total, avg_taxi, garbage, float(data['prolong']), float(data['extra_clean']), total_day))
    conn.commit()
    conn.close()

    log_action('SAVE_EXPENSE', f"{data['hall']} {data['date']}", f"Сумма {total_day} руб.")
    return jsonify({'status': 'ok', 'total_day': total_day})

@app.route('/api/get_expenses/<hall>')
@login_required
def get_expenses(hall):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT date, total_day FROM expenses WHERE hall=?", (hall,))
    rows = c.fetchall()
    conn.close()
    return jsonify({row['date']: row['total_day'] for row in rows})

@app.route('/api/get_expense_details/<hall>/<date>')
@login_required
def get_expense_details(hall, date):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT people_count, taxi1, taxi2, taxi3, garbage, prolong, extra_clean FROM expenses WHERE hall=? AND date=?", (hall, date))
    row = c.fetchone()
    conn.close()
    if row:
        return jsonify({
            'people': row[0],
            'taxi1': row[1],
            'taxi2': row[2],
            'taxi3': row[3],
            'garbage': row[4] if len(row) > 4 else 0,
            'prolong': row[5] if len(row) > 5 else 0,
            'extra_clean': row[6] if len(row) > 6 else 0
        })
    else:
        return jsonify(None)

@app.route('/api/delete_expense', methods=['POST'])
@login_required
def delete_expense():
    data = request.json
    hall = data['hall']
    date = data['date']
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM expenses WHERE hall=? AND date=?", (hall, date))
    conn.commit()
    conn.close()
    log_action('DELETE_EXPENSE', f"{hall} {date}", 'Удалён расход')
    return jsonify({'status': 'ok'})

@app.route('/api/get_monthly_details/<hall>/<int:year>/<int:month>')
@login_required
def get_monthly_details(hall, year, month):
    """Возвращает детализацию по дням за указанный месяц: дата, сумма такси, доп. оплата, итого"""
    conn = get_db()
    c = conn.cursor()
    start_date = f"{year}-{month:02d}-01"
    if month == 12:
        end_date = f"{year}-12-31"
    else:
        end_date = f"{year}-{month+1:02d}-01"
    c.execute('''
        SELECT date, taxi_total, (garbage + prolong + extra_clean) as extra, total_day
        FROM expenses
        WHERE hall = ? AND date >= ? AND date < ?
        ORDER BY date
    ''', (hall, start_date, end_date))
    rows = c.fetchall()
    conn.close()
    details = []
    for row in rows:
        details.append({
            'date': row['date'],
            'taxi_total': row['taxi_total'] or 0,
            'extra': row['extra'] or 0,
            'total_day': row['total_day'] or 0
        })
    return jsonify(details)

@app.route('/api/get_all_totals')
@login_required
def get_all_totals():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name FROM halls")
    halls = [row['name'] for row in c.fetchall()]
    result = {}
    for hall in halls:
        c.execute("SELECT SUM(total_day) FROM expenses WHERE hall=?", (hall,))
        result[hall] = c.fetchone()[0] or 0
    conn.close()
    return jsonify(result)

# ------------------- API ПЕРЕВОЗКИ -------------------
@app.route('/api/save_transfer', methods=['POST'])
@login_required
def save_transfer():
    data = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO transfers (from_hall, to_hall, item_name, photo_url, transfer_date)
                 VALUES (?, ?, ?, ?, ?)''',
              (data['from_hall'], data['to_hall'], data['item_name'], data.get('photo_url', ''), data['transfer_date']))
    conn.commit()
    conn.close()
    log_action('SAVE_TRANSFER', f"{data['from_hall']}→{data['to_hall']}", data['item_name'])
    return jsonify({'status': 'ok', 'id': c.lastrowid})

@app.route('/api/get_transfers')
@login_required
def get_transfers():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, from_hall, to_hall, item_name, photo_url, transfer_date FROM transfers ORDER BY transfer_date DESC")
    rows = c.fetchall()
    transfers = [dict(row) for row in rows]
    conn.close()
    return jsonify(transfers)

@app.route('/api/delete_transfer', methods=['POST'])
@login_required
def delete_transfer():
    data = request.json
    transfer_id = data['id']
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM transfers WHERE id=?", (transfer_id,))
    conn.commit()
    conn.close()
    log_action('DELETE_TRANSFER', f"id {transfer_id}", 'Удалена перевозка')
    return jsonify({'status': 'ok'})

@app.route('/api/clear_transfers', methods=['POST'])
@login_required
def clear_transfers():
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM transfers")
    conn.commit()
    conn.close()
    log_action('CLEAR_TRANSFERS', 'all', 'Очищены все перевозки')
    return jsonify({'status': 'ok'})

# ------------------- API ЗАЛЫ -------------------
@app.route('/api/get_halls')
@login_required
def get_halls():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name FROM halls ORDER BY name")
    rows = c.fetchall()
    halls = [row['name'] for row in rows]
    conn.close()
    return jsonify(halls)

@app.route('/api/add_hall', methods=['POST'])
@login_required
def add_hall():
    data = request.json
    name = data['name']
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO halls (name) VALUES (?)", (name,))
        conn.commit()
        log_action('ADD_HALL', name, 'Добавлен новый зал')
        return jsonify({'status': 'ok'})
    except sqlite3.IntegrityError:
        return jsonify({'status': 'error', 'message': 'Зал уже существует'}), 400
    finally:
        conn.close()

@app.route('/api/rename_hall', methods=['POST'])
@login_required
def rename_hall():
    data = request.json
    old_name = data['old_name']
    new_name = data['new_name']
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE halls SET name=? WHERE name=?", (new_name, old_name))
    c.execute("UPDATE expenses SET hall=? WHERE hall=?", (new_name, old_name))
    c.execute("UPDATE transfers SET from_hall=? WHERE from_hall=?", (new_name, old_name))
    c.execute("UPDATE transfers SET to_hall=? WHERE to_hall=?", (new_name, old_name))
    conn.commit()
    conn.close()
    log_action('RENAME_HALL', f"{old_name}→{new_name}", 'Переименован зал')
    return jsonify({'status': 'ok'})

@app.route('/api/delete_hall', methods=['POST'])
@login_required
def delete_hall():
    data = request.json
    name = data['name']
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM expenses WHERE hall=?", (name,))
    c.execute("DELETE FROM halls WHERE name=?", (name,))
    conn.commit()
    conn.close()
    log_action('DELETE_HALL', name, 'Удалён зал со всеми расходами')
    return jsonify({'status': 'ok'})

# ------------------- АНАЛИТИКА -------------------
@app.route('/api/monthly_summary/<hall>/<int:year>')
@login_required
def monthly_summary(hall, year):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT strftime('%m', date) as month, SUM(total_day) as total
        FROM expenses
        WHERE hall = ? AND strftime('%Y', date) = ?
        GROUP BY month
        ORDER BY month
    ''', (hall, str(year)))
    rows = c.fetchall()
    conn.close()
    result = {}
    for row in rows:
        month_num = int(row['month'])
        result[month_num] = row['total'] or 0
    full_result = {m: result.get(m, 0) for m in range(1, 13)}
    return jsonify(full_result)

# ------------------- СИСТЕМНЫЕ -------------------
@app.route('/api/clear_all_data', methods=['POST'])
@login_required
def clear_all_data():
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM expenses")
    c.execute("DELETE FROM transfers")
    conn.commit()
    conn.close()
    log_action('CLEAR_ALL_DATA', 'all', 'Очищены все расходы и перевозки (залы остались)')
    return jsonify({'status': 'ok'})

@app.route('/api/export_all_data')
@login_required
def export_all_data():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name FROM halls")
    halls = [row['name'] for row in c.fetchall()]
    expenses = {}
    for hall in halls:
        c.execute("SELECT date, total_day FROM expenses WHERE hall=?", (hall,))
        expenses[hall] = {row['date']: row['total_day'] for row in c.fetchall()}
    c.execute("SELECT id, from_hall, to_hall, item_name, photo_url, transfer_date FROM transfers")
    transfers = [dict(row) for row in c.fetchall()]
    conn.close()
    export = {
        'halls': halls,
        'expenses': expenses,
        'transfers': transfers,
        'export_date': datetime.now().isoformat()
    }
    log_action('EXPORT_DATA', 'all', 'Экспорт всех данных')
    return jsonify(export)
