# -----------------------------------------------------------------------------
# EXPERIENCIAS EXPY FEST - GESTOR DE FILAS - app.py 
# -----------------------------------------------------------------------------
# NOTA IMPORTANTISIMA: ¡Esto funciona, no modificar mucho!
# Si vas a modificar alguna de estas partes, hacer copia de seguridad primero.
#
# ADAPTADO PARA RAILWAY: Este código ya está listo para subir a Railway.
# Usa PostgreSQL automáticamente en Railway (por la variable DATABASE_URL).
# En entorno local usa SQLite para pruebas (event_attractions.db).
# -----------------------------------------------------------------------------

import os
import time
from datetime import date, datetime, timedelta, timezone
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

# --- Configuración de la Aplicación ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'una-clave-secreta-muy-segura-dev')

DATABASE_URL = os.environ.get('DATABASE_URL')
USE_POSTGRES = DATABASE_URL is not None

VOLUNTEER_STATUSES = ('activo', 'descanso', 'comiendo', 'salida')

# --- Funciones de la Base de Datos ---
# NOTA: Esto funciona, no modificar mucho. Esta sección gestiona la compatibilidad
# entre SQLite (uso local) y PostgreSQL (uso en Railway).

pg_pool = None
if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    from psycopg2 import pool
    try:
        pg_pool = psycopg2.pool.ThreadedConnectionPool(1, 20, DATABASE_URL, sslmode='require')
    except Exception as e:
        print(f"Error initializing connection pool: {e}")

def get_db_connection():
    """Crea una conexión a la base de datos (PostgreSQL o SQLite)."""
    try:
        if USE_POSTGRES:
            if pg_pool:
                return pg_pool.getconn()
            else:
                import psycopg2
                return psycopg2.connect(DATABASE_URL, sslmode='require')
        else:
            import sqlite3
            conn = sqlite3.connect('event_attractions.db')
            conn.row_factory = sqlite3.Row
            return conn
    except Exception as e:
        print(f"Error de base de datos: {e}")
        raise

def release_db_connection(conn):
    if USE_POSTGRES and pg_pool and conn:
        pg_pool.putconn(conn)
    elif conn:
        conn.close()

def execute_query(conn, query, params=None):
    """Ejecuta una query compatible con ambas bases de datos."""
    if USE_POSTGRES:
        import psycopg2.extras
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        query = query.replace('?', '%s')
    else:
        cursor = conn.cursor()
        
    if params:
        cursor.execute(query, params)
    else:
        cursor.execute(query)
    return cursor

def sql_date(column):
    """Expresión SQL para extraer la fecha restando 3 horas (UTC-3)."""
    if USE_POSTGRES:
        return f"DATE({column} - INTERVAL '3 hours')"
    return f"date({column}, '-3 hours')"

def sql_hour(column):
    """Expresión SQL para extraer la hora (0-23) restando 3 horas (UTC-3)."""
    if USE_POSTGRES:
        return f"EXTRACT(HOUR FROM ({column} - INTERVAL '3 hours'))::INTEGER"
    return f"CAST(strftime('%H', {column}, '-3 hours') AS INTEGER)"

def format_utc_to_local_time(dt_obj_or_str):
    """Convierte un timestamp UTC a hora local de Argentina (UTC-3) formato HH:MM."""
    if not dt_obj_or_str:
        return ""
    if isinstance(dt_obj_or_str, str):
        try:
            # Eliminar microsegundos si existen y parsear
            clean_str = dt_obj_or_str.split('.')[0]
            dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return str(dt_obj_or_str)
    else:
        dt = dt_obj_or_str
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
            
    local_dt = dt - timedelta(hours=3)
    return local_dt.strftime("%H:%M")

def init_db():
    """Inicializa la base de datos y crea las tablas si no existen."""
    # NOTA: Si vas a modificar las tablas o su estructura, hacer copia de seguridad primero
    # para evitar pérdida de datos en el historial.
    conn = get_db_connection()
    cursor = conn.cursor()

    if USE_POSTGRES:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attractions (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                duration_minutes INTEGER DEFAULT 5
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS queue (
                id SERIAL PRIMARY KEY,
                attraction_id INTEGER NOT NULL,
                person_name TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (attraction_id) REFERENCES attractions (id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance_history (
                id SERIAL PRIMARY KEY,
                attraction_id INTEGER NOT NULL,
                person_name TEXT NOT NULL,
                attended_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (attraction_id) REFERENCES attractions (id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS queue_join_history (
                id SERIAL PRIMARY KEY,
                attraction_id INTEGER NOT NULL,
                person_name TEXT NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (attraction_id) REFERENCES attractions (id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS volunteers (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                attraction_id INTEGER,
                status TEXT DEFAULT 'activo',
                check_in TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (attraction_id) REFERENCES attractions (id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sos_alerts (
                id SERIAL PRIMARY KEY,
                attraction_id INTEGER NOT NULL,
                volunteer_name TEXT NOT NULL,
                message TEXT,
                status TEXT DEFAULT 'pendiente',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (attraction_id) REFERENCES attractions (id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id SERIAL PRIMARY KEY,
                attraction_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'pendiente',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (attraction_id) REFERENCES attractions (id)
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_queue_attraction ON queue (attraction_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_attraction ON attendance_history (attraction_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_join_attraction ON queue_join_history (attraction_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_volunteers_attraction ON volunteers (attraction_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sos_status ON sos_alerts (status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_announcement_status ON announcements (status)")
        print("Base de datos PostgreSQL inicializada [OK]")
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                duration_minutes INTEGER DEFAULT 5
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attraction_id INTEGER NOT NULL,
                person_name TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (attraction_id) REFERENCES attractions (id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attraction_id INTEGER NOT NULL,
                person_name TEXT NOT NULL,
                attended_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (attraction_id) REFERENCES attractions (id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS queue_join_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attraction_id INTEGER NOT NULL,
                person_name TEXT NOT NULL,
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (attraction_id) REFERENCES attractions (id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS volunteers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                attraction_id INTEGER,
                status TEXT DEFAULT 'activo',
                check_in DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (attraction_id) REFERENCES attractions (id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sos_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attraction_id INTEGER NOT NULL,
                volunteer_name TEXT NOT NULL,
                message TEXT,
                status TEXT DEFAULT 'pendiente',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (attraction_id) REFERENCES attractions (id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attraction_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'pendiente',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (attraction_id) REFERENCES attractions (id)
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_queue_attraction ON queue (attraction_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_attraction ON attendance_history (attraction_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_join_attraction ON queue_join_history (attraction_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_volunteers_attraction ON volunteers (attraction_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sos_status ON sos_alerts (status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_announcement_status ON announcements (status)")
        print("Base de datos SQLite inicializada [OK]")

    conn.commit()
    release_db_connection(conn)


# --- Rutas de la Aplicación ---
# NOTA: Estas rutas devuelven las páginas web (HTML).
# Esto funciona, no modificar mucho la lógica principal para no romper la web.

@app.route('/')
def index():
    """Página principal: experiencias, filas y alertas SOS pendientes."""
    conn = get_db_connection()
    query = """
        SELECT
            a.id,
            a.name,
            a.description,
            a.duration_minutes,
            COUNT(q.id) as queue_count,
            (COUNT(q.id) * a.duration_minutes) as estimated_wait_minutes
        FROM
            attractions a
        LEFT JOIN
            queue q ON a.id = q.attraction_id
        GROUP BY
            a.id, a.name, a.description, a.duration_minutes
        ORDER BY
            a.name;
    """
    cursor = execute_query(conn, query)
    attractions = cursor.fetchall()

    cursor = execute_query(conn, """
        SELECT s.*, a.name as attraction_name
        FROM sos_alerts s
        JOIN attractions a ON s.attraction_id = a.id
        WHERE s.status = 'pendiente'
        ORDER BY s.created_at DESC
    """)
    alerts_raw = cursor.fetchall()
    pending_alerts = []
    for s in alerts_raw:
        item = dict(s)
        item['created_at'] = format_utc_to_local_time(item['created_at'])
        pending_alerts.append(item)

    cursor = execute_query(conn, """
        SELECT ann.*, a.name as attraction_name
        FROM announcements ann
        JOIN attractions a ON ann.attraction_id = a.id
        WHERE ann.status = 'pendiente'
        ORDER BY ann.created_at DESC
    """)
    announcements_raw = cursor.fetchall()
    pending_announcements = []
    for s in announcements_raw:
        item = dict(s)
        item['created_at'] = format_utc_to_local_time(item['created_at'])
        pending_announcements.append(item)

    release_db_connection(conn)
    return render_template('index.html', attractions=attractions, pending_alerts=pending_alerts, pending_announcements=pending_announcements)

@app.route('/attraction/<int:attraction_id>')
def attraction_detail(attraction_id):
    """Página de detalle: información de la experiencia, fila y voluntarixs."""
    conn = get_db_connection()

    cursor = execute_query(conn, 'SELECT * FROM attractions WHERE id = ?', (attraction_id,))
    attraction = cursor.fetchone()

    cursor = execute_query(conn, 'SELECT * FROM queue WHERE attraction_id = ? ORDER BY timestamp', (attraction_id,))
    queue = cursor.fetchall()

    cursor = execute_query(conn, """
        SELECT * FROM volunteers
        WHERE attraction_id = ?
        ORDER BY name
    """, (attraction_id,))
    volunteers = cursor.fetchall()

    cursor = execute_query(conn, 'SELECT * FROM volunteers ORDER BY name')
    all_volunteers = cursor.fetchall()

    release_db_connection(conn)

    if attraction is None:
        return "Experiencia no encontrada", 404

    return render_template('attraction.html',
        attraction=attraction, queue=queue, volunteers=volunteers, all_volunteers=all_volunteers)

@app.route('/add_attraction', methods=['POST'])
def add_attraction():
    """Procesa el formulario para añadir una nueva experiencia."""
    name = request.form['name']
    description = request.form['description']
    duration_minutes = int(request.form.get('duration_minutes', 5))

    if name:
        conn = get_db_connection()
        try:
            execute_query(conn,
                'INSERT INTO attractions (name, description, duration_minutes) VALUES (?, ?, ?)',
                (name, description, duration_minutes))
            conn.commit()
            flash(f'Experiencia "{name}" creada exitosamente (duración: {duration_minutes} min)', 'success')
        except Exception as e:
            if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
                flash(f'Error: El nombre de la experiencia "{name}" ya existe.', 'error')
            else:
                flash(f'Error al crear la experiencia: {str(e)}', 'error')
        finally:
            release_db_connection(conn)

    return redirect(url_for('index'))

@app.route('/add_to_queue/<int:attraction_id>', methods=['POST'])
def add_to_queue(attraction_id):
    """Añade una persona a la fila y registra el ingreso en el historial."""
    person_name = request.form.get('person_name', '').strip()

    if not person_name:
        flash('El nombre no puede estar vacío', 'error')
        return redirect(url_for('attraction_detail', attraction_id=attraction_id))

    if len(person_name) < 2:
        flash('El nombre debe tener al menos 2 caracteres', 'error')
        return redirect(url_for('attraction_detail', attraction_id=attraction_id))

    conn = get_db_connection()

    cursor = execute_query(conn, 'SELECT name, duration_minutes FROM attractions WHERE id = ?', (attraction_id,))
    attraction = cursor.fetchone()

    if not attraction:
        release_db_connection(conn)
        flash('Experiencia no encontrada', 'error')
        return redirect(url_for('index'))

    cursor = execute_query(conn, 'SELECT COUNT(*) as count FROM queue WHERE attraction_id = ?', (attraction_id,))
    queue_count = cursor.fetchone()['count']

    execute_query(conn, 'INSERT INTO queue (attraction_id, person_name) VALUES (?, ?)', (attraction_id, person_name))
    execute_query(conn,
        'INSERT INTO queue_join_history (attraction_id, person_name) VALUES (?, ?)',
        (attraction_id, person_name))
    conn.commit()
    release_db_connection(conn)

    new_queue_count = queue_count + 1
    estimated_wait = new_queue_count * (attraction['duration_minutes'] or 5)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept') == 'application/json':
        return jsonify({
            'success': True,
            'message': f'{person_name} añadido a la fila. Tiempo estimado: {estimated_wait} minutos',
            'queue_count': new_queue_count,
            'estimated_wait': estimated_wait
        })

    flash(f'{person_name} añadido a la fila. Tiempo estimado: {estimated_wait} minutos', 'success')
    return redirect(url_for('attraction_detail', attraction_id=attraction_id))

@app.route('/next_person/<int:queue_id>', methods=['POST'])
def next_person(queue_id):
    """Registra asistencia histórica y elimina a la persona de la fila."""
    conn = get_db_connection()

    cursor = execute_query(conn,
        'SELECT attraction_id, person_name FROM queue WHERE id = ?', (queue_id,))
    queue_item = cursor.fetchone()

    if queue_item:
        attraction_id = queue_item['attraction_id']
        person_name = queue_item['person_name']
        execute_query(conn,
            'INSERT INTO attendance_history (attraction_id, person_name) VALUES (?, ?)',
            (attraction_id, person_name))
        execute_query(conn, 'DELETE FROM queue WHERE id = ?', (queue_id,))
        conn.commit()
        release_db_connection(conn)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept') == 'application/json':
            return jsonify({'success': True, 'message': f'{person_name} atendido y registrado en asistencia'})

        flash('Persona procesada y registrada en asistencia', 'success')
        return redirect(url_for('attraction_detail', attraction_id=attraction_id))

    release_db_connection(conn)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': False, 'error': 'Persona no encontrada'}), 404

    return redirect(url_for('index'))

@app.route('/metrics')
def metrics():
    """Dashboard: filas en vivo, saturación, métricas por día y totales del evento."""
    selected_day = request.args.get('day', 'today')
    today = (datetime.now(timezone.utc) - timedelta(hours=3)).date().isoformat()
    conn = get_db_connection()

    date_att_raw = sql_date('attended_at')
    hour_att_raw = sql_hour('attended_at')
    date_join_raw = sql_date('joined_at')
    hour_join_raw = sql_hour('joined_at')
    date_att_ah = sql_date('ah.attended_at')
    date_join_qjh = sql_date('qjh.joined_at')

    # Días con actividad registrada
    cursor = execute_query(conn, f"""
        SELECT day FROM (
            SELECT DISTINCT {date_att_raw} as day FROM attendance_history
            UNION
            SELECT DISTINCT {date_join_raw} as day FROM queue_join_history
        ) ORDER BY day DESC
    """)
    event_days = [str(row['day']) for row in cursor.fetchall() if row['day']]

    # Filtro de fecha según selección
    if selected_day == 'all':
        day_filter_att = None
        day_filter_join = None
        period_label = 'Todo el evento'
    elif selected_day == 'today':
        day_filter_att = today
        day_filter_join = today
        period_label = f'Hoy ({today})'
    else:
        day_filter_att = selected_day
        day_filter_join = selected_day
        period_label = selected_day

    # --- EN VIVO: saturación actual de filas (orden descendente) ---
    cursor = execute_query(conn, """
        SELECT a.id, a.name, a.duration_minutes,
               COUNT(q.id) as queue_count,
               (COUNT(q.id) * a.duration_minutes) as estimated_wait
        FROM attractions a
        LEFT JOIN queue q ON a.id = q.attraction_id
        GROUP BY a.id, a.name, a.duration_minutes
        ORDER BY queue_count DESC, a.name
    """)
    live_saturation = cursor.fetchall()

    # --- Totales del período seleccionado ---
    if day_filter_att:
        cursor = execute_query(conn, f"""
            SELECT COUNT(*) as total FROM attendance_history WHERE {date_att_raw} = ?
        """, (day_filter_att,))
        total_attended = cursor.fetchone()['total']
        cursor = execute_query(conn, f"""
            SELECT COUNT(*) as total FROM queue_join_history WHERE {date_join_raw} = ?
        """, (day_filter_join,))
        total_queue_joins = cursor.fetchone()['total']
        att_day_clause = f"AND {date_att_ah} = ?"
        join_day_clause = f"AND {date_join_qjh} = ?"
        att_params = (day_filter_att,)
        join_params = (day_filter_join,)
        hour_att_clause = f"WHERE {date_att_raw} = ?"
        hour_join_clause = f"WHERE {date_join_raw} = ?"
    else:
        cursor = execute_query(conn, "SELECT COUNT(*) as total FROM attendance_history")
        total_attended = cursor.fetchone()['total']
        cursor = execute_query(conn, "SELECT COUNT(*) as total FROM queue_join_history")
        total_queue_joins = cursor.fetchone()['total']
        att_day_clause = ""
        join_day_clause = ""
        att_params = ()
        join_params = ()
        hour_att_clause = ""
        hour_join_clause = ""

    # Por experiencia en el período
    cursor = execute_query(conn, f"""
        SELECT a.id, a.name, COUNT(ah.id) as attended
        FROM attractions a
        LEFT JOIN attendance_history ah ON a.id = ah.attraction_id {att_day_clause}
        GROUP BY a.id, a.name
        ORDER BY attended DESC, a.name
    """, att_params)
    attendance_by_attraction = cursor.fetchall()

    cursor = execute_query(conn, f"""
        SELECT a.id, a.name, COUNT(qjh.id) as joined
        FROM attractions a
        LEFT JOIN queue_join_history qjh ON a.id = qjh.attraction_id {join_day_clause}
        GROUP BY a.id, a.name
        ORDER BY joined DESC, a.name
    """, join_params)
    queue_by_attraction = {row['id']: row['joined'] for row in cursor.fetchall()}

    # Ranking histórico total del evento (siempre todos los días)
    cursor = execute_query(conn, """
        SELECT a.name, COUNT(ah.id) as total_attended
        FROM attractions a
        LEFT JOIN attendance_history ah ON a.id = ah.attraction_id
        GROUP BY a.id, a.name
        ORDER BY total_attended DESC, a.name
    """)
    event_ranking = cursor.fetchall()

    # Por hora en el período
    if hour_att_clause:
        cursor = execute_query(conn, f"""
            SELECT {hour_att_raw} as hour_slot, COUNT(*) as count
            FROM attendance_history {hour_att_clause}
            GROUP BY {hour_att_raw} ORDER BY hour_slot
        """, (day_filter_att,))
    else:
        cursor = execute_query(conn, f"""
            SELECT {hour_att_raw} as hour_slot, COUNT(*) as count
            FROM attendance_history
            GROUP BY {hour_att_raw} ORDER BY hour_slot
        """)
    attendance_by_hour = cursor.fetchall()

    if hour_join_clause:
        cursor = execute_query(conn, f"""
            SELECT {hour_join_raw} as hour_slot, COUNT(*) as count
            FROM queue_join_history {hour_join_clause}
            GROUP BY {hour_join_raw} ORDER BY hour_slot
        """, (day_filter_join,))
    else:
        cursor = execute_query(conn, f"""
            SELECT {hour_join_raw} as hour_slot, COUNT(*) as count
            FROM queue_join_history
            GROUP BY {hour_join_raw} ORDER BY hour_slot
        """)
    queue_by_hour = cursor.fetchall()

    active_hours = len(attendance_by_hour) or 1
    avg_per_hour = round(total_attended / active_hours, 1) if total_attended else 0

    # Desglose por día y experiencia (solo cuando se ve todo el evento)
    daily_by_experience = []
    if selected_day == 'all':
        cursor = execute_query(conn, f"""
            SELECT {date_att_raw} as day, a.name, COUNT(*) as count
            FROM attendance_history ah
            JOIN attractions a ON ah.attraction_id = a.id
            GROUP BY {date_att_raw}, a.name
            ORDER BY day DESC, count DESC
        """)
        daily_by_experience = cursor.fetchall()

    # Totales globales del evento (siempre visibles)
    cursor = execute_query(conn, "SELECT COUNT(*) as total FROM attendance_history")
    event_total_attended = cursor.fetchone()['total']
    cursor = execute_query(conn, "SELECT COUNT(*) as total FROM queue_join_history")
    event_total_joins = cursor.fetchone()['total']
    cursor = execute_query(conn, f"""
        SELECT COUNT(DISTINCT {hour_att_raw}) as hours FROM attendance_history
    """)
    event_active_hours = cursor.fetchone()['hours'] or 1
    event_avg_per_hour = round(event_total_attended / event_active_hours, 1) if event_total_attended else 0

    release_db_connection(conn)

    return render_template('metrics.html',
        today=today,
        selected_day=selected_day,
        period_label=period_label,
        event_days=event_days,
        live_saturation=live_saturation,
        attendance_by_attraction=attendance_by_attraction,
        queue_by_attraction=queue_by_attraction,
        event_ranking=event_ranking,
        attendance_by_hour=attendance_by_hour,
        queue_by_hour=queue_by_hour,
        total_attended=total_attended,
        total_queue_joins=total_queue_joins,
        avg_per_hour=avg_per_hour,
        daily_by_experience=daily_by_experience,
        event_total_attended=event_total_attended,
        event_total_joins=event_total_joins,
        event_avg_per_hour=event_avg_per_hour)

@app.route('/volunteers', methods=['GET', 'POST'])
def volunteers():
    """Gestión de voluntarixs: registro de nombres y listado general."""
    conn = get_db_connection()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()

        if name:
            execute_query(conn,
                'INSERT INTO volunteers (name) VALUES (?)',
                (name,))
            conn.commit()
            flash(f'Voluntarix "{name}" registrado. Asígnalo desde la experiencia correspondiente.', 'success')
        else:
            flash('El nombre del voluntarix no puede estar vacío', 'error')

    cursor = execute_query(conn, """
        SELECT v.*, a.name as attraction_name
        FROM volunteers v
        LEFT JOIN attractions a ON v.attraction_id = a.id
        ORDER BY v.name
    """)
    volunteer_list = cursor.fetchall()

    cursor = execute_query(conn, 'SELECT id, name FROM attractions ORDER BY name')
    attractions = cursor.fetchall()
    release_db_connection(conn)

    return render_template('volunteers.html',
        volunteers=volunteer_list,
        attractions=attractions,
        statuses=VOLUNTEER_STATUSES)

@app.route('/volunteers/update_status/<int:volunteer_id>', methods=['POST'])
def update_volunteer_status(volunteer_id):
    """Cambia el estado de un voluntarix y actualiza su hora de ingreso."""
    status = request.form.get('status', 'activo')
    if status not in VOLUNTEER_STATUSES:
        flash('Estado no válido', 'error')
        return redirect(url_for('volunteers'))

    conn = get_db_connection()
    execute_query(conn,
        "UPDATE volunteers SET status = ?, check_in = CURRENT_TIMESTAMP WHERE id = ?",
        (status, volunteer_id))
    conn.commit()
    release_db_connection(conn)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True, 'volunteer_id': volunteer_id, 'status': status})

    flash(f'Estado actualizado a "{status}"', 'success')
    return redirect(url_for('volunteers'))

@app.route('/volunteers/assign/<int:volunteer_id>', methods=['POST'])
def assign_volunteer(volunteer_id):
    """Asigna o reasigna un voluntarix a una atracción."""
    attraction_id = request.form.get('attraction_id')
    attraction_id = int(attraction_id) if attraction_id else None
    return_to = request.form.get('return_to')

    conn = get_db_connection()
    execute_query(conn,
        'UPDATE volunteers SET attraction_id = ? WHERE id = ?',
        (attraction_id, volunteer_id))
    conn.commit()
    release_db_connection(conn)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True, 'volunteer_id': volunteer_id, 'attraction_id': attraction_id})

    flash('Asignación actualizada', 'success')
    if return_to == 'attraction' and attraction_id:
        return redirect(url_for('attraction_detail', attraction_id=attraction_id))
    return redirect(url_for('volunteers'))

@app.route('/attraction/<int:attraction_id>/assign_volunteer', methods=['POST'])
def assign_volunteer_to_attraction(attraction_id):
    """Asigna un voluntarix pre-cargado a esta experiencia."""
    volunteer_id = request.form.get('volunteer_id')
    if not volunteer_id:
        flash('Selecciona un voluntarix', 'error')
        return redirect(url_for('attraction_detail', attraction_id=attraction_id))

    conn = get_db_connection()
    execute_query(conn,
        'UPDATE volunteers SET attraction_id = ? WHERE id = ?',
        (attraction_id, int(volunteer_id)))
    conn.commit()
    release_db_connection(conn)

    flash('Voluntarix asignado a esta experiencia', 'success')
    return redirect(url_for('attraction_detail', attraction_id=attraction_id))

@app.route('/attraction/<int:attraction_id>/unassign_volunteer/<int:volunteer_id>', methods=['POST'])
def unassign_volunteer_from_attraction(attraction_id, volunteer_id):
    """Quita un voluntarix de esta experiencia."""
    conn = get_db_connection()
    execute_query(conn,
        'UPDATE volunteers SET attraction_id = NULL WHERE id = ? AND attraction_id = ?',
        (volunteer_id, attraction_id))
    conn.commit()
    release_db_connection(conn)

    flash('Voluntarix desasignado', 'success')
    return redirect(url_for('attraction_detail', attraction_id=attraction_id))

@app.route('/sos/create/<int:attraction_id>', methods=['POST'])
def create_sos_alert(attraction_id):
    """Crea una alerta SOS de un voluntarix hacia supervisores."""
    volunteer_name = request.form.get('volunteer_name', '').strip()
    message = request.form.get('message', '').strip()

    if not volunteer_name:
        flash('Debes indicar tu nombre', 'error')
        return redirect(url_for('attraction_detail', attraction_id=attraction_id))

    if not message:
        message = 'Solicita ayuda urgente'

    conn = get_db_connection()
    execute_query(conn,
        'INSERT INTO sos_alerts (attraction_id, volunteer_name, message) VALUES (?, ?, ?)',
        (attraction_id, volunteer_name, message))
    conn.commit()
    release_db_connection(conn)

    flash('Alerta enviada al supervisor. Te contactarán pronto.', 'success')
    return redirect(url_for('attraction_detail', attraction_id=attraction_id))

@app.route('/sos/resolve/<int:alert_id>', methods=['POST'])
def resolve_sos_alert(alert_id):
    """Marca una alerta SOS como resuelta."""
    conn = get_db_connection()
    execute_query(conn,
        "UPDATE sos_alerts SET status = 'resuelta' WHERE id = ?",
        (alert_id,))
    conn.commit()
    release_db_connection(conn)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True, 'alert_id': alert_id, 'message': 'Alerta resuelta'})

    flash('Alerta marcada como resuelta', 'success')
    return redirect(url_for('index'))

@app.route('/announcement/create/<int:attraction_id>', methods=['POST'])
def create_announcement(attraction_id):
    """Crea un anuncio de una atracción."""
    message = request.form.get('message', '').strip()

    if not message:
        message = '¡Atracción libre!'

    conn = get_db_connection()
    execute_query(conn,
        'INSERT INTO announcements (attraction_id, message) VALUES (?, ?)',
        (attraction_id, message))
    conn.commit()
    release_db_connection(conn)

    flash('Anuncio publicado.', 'success')
    return redirect(url_for('attraction_detail', attraction_id=attraction_id))

@app.route('/announcement/resolve/<int:announcement_id>', methods=['POST'])
def resolve_announcement(announcement_id):
    """Marca un anuncio como resuelto."""
    conn = get_db_connection()
    execute_query(conn,
        "UPDATE announcements SET status = 'resuelta' WHERE id = ?",
        (announcement_id,))
    conn.commit()
    release_db_connection(conn)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True, 'announcement_id': announcement_id, 'message': 'Anuncio quitado'})

    flash('Anuncio quitado', 'success')
    return redirect(url_for('index'))

@app.route('/edit_attraction/<int:attraction_id>', methods=['GET', 'POST'])
def edit_attraction(attraction_id):
    """Página para editar una experiencia existente."""
    conn = get_db_connection()
    cursor = execute_query(conn, 'SELECT * FROM attractions WHERE id = ?', (attraction_id,))
    attraction = cursor.fetchone()

    if attraction is None:
        release_db_connection(conn)
        return "Experiencia no encontrada", 404

    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        duration_minutes = int(request.form.get('duration_minutes', 5))

        if name:
            try:
                execute_query(conn,
                    'UPDATE attractions SET name = ?, description = ?, duration_minutes = ? WHERE id = ?',
                    (name, description, duration_minutes, attraction_id))
                conn.commit()
                release_db_connection(conn)
                flash(f'Experiencia "{name}" actualizada exitosamente (duración: {duration_minutes} min)', 'success')
                return redirect(url_for('index'))
            except Exception as e:
                if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
                    flash(f'Error: El nombre de la experiencia "{name}" ya existe.', 'error')
                else:
                    flash(f'Error: {str(e)}', 'error')
                release_db_connection(conn)
                return render_template('edit_attraction.html', attraction=attraction)

    release_db_connection(conn)
    return render_template('edit_attraction.html', attraction=attraction)

@app.route('/delete_attraction/<int:attraction_id>', methods=['POST'])
def delete_attraction(attraction_id):
    """Elimina una experiencia y todos sus datos relacionados."""
    conn = get_db_connection()

    cursor = execute_query(conn, 'SELECT * FROM attractions WHERE id = ?', (attraction_id,))
    attraction = cursor.fetchone()

    if attraction is None:
        release_db_connection(conn)
        flash('Experiencia no encontrada', 'error')
        return redirect(url_for('index'))

    execute_query(conn, 'DELETE FROM queue WHERE attraction_id = ?', (attraction_id,))
    execute_query(conn, 'DELETE FROM attendance_history WHERE attraction_id = ?', (attraction_id,))
    execute_query(conn, 'DELETE FROM queue_join_history WHERE attraction_id = ?', (attraction_id,))
    execute_query(conn, 'DELETE FROM sos_alerts WHERE attraction_id = ?', (attraction_id,))
    execute_query(conn, 'DELETE FROM announcements WHERE attraction_id = ?', (attraction_id,))
    execute_query(conn, 'UPDATE volunteers SET attraction_id = NULL WHERE attraction_id = ?', (attraction_id,))
    execute_query(conn, 'DELETE FROM attractions WHERE id = ?', (attraction_id,))
    conn.commit()
    release_db_connection(conn)

    flash('Experiencia eliminada exitosamente', 'success')
    return redirect(url_for('index'))

@app.route('/clear_queue/<int:attraction_id>', methods=['POST'])
def clear_queue(attraction_id):
    """Vacía completamente la fila de una experiencia."""
    conn = get_db_connection()

    cursor = execute_query(conn, 'SELECT * FROM attractions WHERE id = ?', (attraction_id,))
    attraction = cursor.fetchone()

    if attraction is None:
        release_db_connection(conn)
        flash('Experiencia no encontrada', 'error')
        return redirect(url_for('index'))

    execute_query(conn, 'DELETE FROM queue WHERE attraction_id = ?', (attraction_id,))
    conn.commit()
    release_db_connection(conn)

    flash('Fila vaciada exitosamente', 'success')
    return redirect(url_for('attraction_detail', attraction_id=attraction_id))


# --- Rutas API para Live Refresh y Asincronía ---
# NOTA: Si vas a modificar hacer copia de seguridad de javascript en base.html antes.
# Estas rutas devuelven JSON y son llamadas en segundo plano (AJAX) 
# para actualizar los contadores en tiempo real (Live Sync). ¡No modificar mucho!

api_status_cache = {'time': 0, 'data': None}

@app.route('/api/status')
def api_status():
    """Retorna estado en vivo de todas las atracciones y alertas pendientes."""
    if time.time() - api_status_cache['time'] < 2.5:
        return jsonify(api_status_cache['data'])

    conn = get_db_connection()
    query = """
        SELECT
            a.id,
            a.name,
            a.description,
            a.duration_minutes,
            COUNT(q.id) as queue_count,
            (COUNT(q.id) * a.duration_minutes) as estimated_wait_minutes
        FROM
            attractions a
        LEFT JOIN
            queue q ON a.id = q.attraction_id
        GROUP BY
            a.id, a.name, a.description, a.duration_minutes
        ORDER BY
            a.name;
    """
    cursor = execute_query(conn, query)
    attractions = [dict(row) for row in cursor.fetchall()]

    cursor = execute_query(conn, """
        SELECT s.id, s.attraction_id, s.volunteer_name, s.message, s.created_at, a.name as attraction_name
        FROM sos_alerts s
        JOIN attractions a ON s.attraction_id = a.id
        WHERE s.status = 'pendiente'
        ORDER BY s.created_at DESC
    """)
    alerts_raw = cursor.fetchall()
    pending_alerts = []
    for s in alerts_raw:
        item = dict(s)
        item['created_at'] = format_utc_to_local_time(item['created_at'])
        pending_alerts.append(item)

    cursor = execute_query(conn, """
        SELECT ann.id, ann.attraction_id, ann.message, ann.created_at, a.name as attraction_name
        FROM announcements ann
        JOIN attractions a ON ann.attraction_id = a.id
        WHERE ann.status = 'pendiente'
        ORDER BY ann.created_at DESC
    """)
    announcements_raw = cursor.fetchall()
    pending_announcements = []
    for s in announcements_raw:
        item = dict(s)
        item['created_at'] = format_utc_to_local_time(item['created_at'])
        pending_announcements.append(item)

    total_queue_count = sum(a['queue_count'] for a in attractions)
    release_db_connection(conn)

    response_data = {
        'attractions': attractions,
        'pending_alerts': pending_alerts,
        'pending_announcements': pending_announcements,
        'total_queue_count': total_queue_count,
        'total_attractions': len(attractions)
    }
    api_status_cache['time'] = time.time()
    api_status_cache['data'] = response_data
    return jsonify(response_data)

@app.route('/api/attraction/<int:attraction_id>')
def api_attraction_detail(attraction_id):
    """Retorna la fila en vivo y voluntarixs de una atracción específica."""
    conn = get_db_connection()
    cursor = execute_query(conn, 'SELECT * FROM attractions WHERE id = ?', (attraction_id,))
    attraction_row = cursor.fetchone()

    if not attraction_row:
        release_db_connection(conn)
        return jsonify({'error': 'No encontrada'}), 404

    attraction = dict(attraction_row)

    cursor = execute_query(conn, 'SELECT id, person_name, timestamp FROM queue WHERE attraction_id = ? ORDER BY timestamp', (attraction_id,))
    queue = []
    for q in cursor.fetchall():
        item = dict(q)
        item['timestamp'] = str(item['timestamp'])
        queue.append(item)

    cursor = execute_query(conn, 'SELECT id, name, status FROM volunteers WHERE attraction_id = ? ORDER BY name', (attraction_id,))
    volunteers = [dict(v) for v in cursor.fetchall()]

    release_db_connection(conn)

    duration = attraction.get('duration_minutes') or 5
    queue_count = len(queue)
    estimated_wait = queue_count * duration

    return jsonify({
        'attraction': attraction,
        'queue': queue,
        'queue_count': queue_count,
        'estimated_wait_minutes': estimated_wait,
        'volunteers': volunteers
    })

@app.route('/api/volunteers')
def api_volunteers():
    """Retorna lista de voluntarixs con su estado y asignación actual."""
    conn = get_db_connection()
    cursor = execute_query(conn, """
        SELECT v.id, v.name, v.status, v.check_in, v.attraction_id, a.name as attraction_name
        FROM volunteers v
        LEFT JOIN attractions a ON v.attraction_id = a.id
        ORDER BY v.name
    """)
    volunteers = []
    for v in cursor.fetchall():
        item = dict(v)
        item['check_in'] = str(item['check_in'])
        volunteers.append(item)
    release_db_connection(conn)

    active_count = sum(1 for v in volunteers if v.get('status') == 'activo')
    break_count = sum(1 for v in volunteers if v.get('status') in ('descanso', 'comiendo'))

    return jsonify({
        'volunteers': volunteers,
        'total': len(volunteers),
        'active_count': active_count,
        'break_count': break_count
    })


init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
