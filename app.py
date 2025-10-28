import os
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import redis
import time 

app = Flask(__name__)
# Ambil SECRET_KEY dari Environment Variable untuk keamanan
app.secret_key = os.environ.get('SECRET_KEY', 'default_secret_key_yang_sangat_panjang_dan_aman')


# --- 1. Konfigurasi Redis (Diperbaiki untuk Serverless Vercel) ---

REDIS_URL = os.environ.get('REDIS_URL')
redis_client_instance = None
REDIS_READY = False

def get_redis_client():
    """
    Mengembalikan instance klien Redis yang terhubung (Lazy Initialization).
    Mengutamakan koneksi via REDIS_URL (Vercel/Upstash) lalu fallback ke localhost (Lokal).
    """
    global redis_client_instance, REDIS_READY

    if REDIS_READY is True and redis_client_instance is not None:
        return redis_client_instance
    
    # 1. Coba koneksi ke Vercel/Eksternal via REDIS_URL
    if REDIS_URL and not REDIS_READY:
        try:
            redis_client_instance = redis.from_url(
                REDIS_URL,
                decode_responses=True, 
                socket_timeout=5,
                socket_connect_timeout=5
            )
            redis_client_instance.ping()
            REDIS_READY = True
            print("Redis: Koneksi berhasil diinisialisasi dan diuji via Vercel ENV!")
            return redis_client_instance
        except Exception as e:
            print(f"Redis ERROR: Gagal terhubung ke Redis via Vercel ENV! {e}")
            REDIS_READY = False
            # Lanjut ke fallback
    
    # 2. Fallback ke localhost untuk pengembangan lokal
    if not REDIS_READY:
        try:
            redis_client_instance = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)
            redis_client_instance.ping()
            REDIS_READY = True
            print("Redis: Koneksi lokal berhasil diuji!")
            return redis_client_instance
        except Exception as e:
            print(f"Redis ERROR: Gagal terhubung ke Redis lokal! {e}")
            REDIS_READY = False
            return None
    
    return None


# --- JINJA2 FILTERS (Pace dan Durasi) ---
def format_duration(seconds):
    """Mengkonversi total detik menjadi format jam:menit:detik."""
    if not seconds or not isinstance(seconds, (int, float)):
        return "0 detik"

    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if hours > 0:
        parts.append(f"{hours} jam")
    if minutes > 0 or hours > 0:
        parts.append(f"{minutes} menit")
    if secs > 0 or (hours == 0 and minutes == 0):
        parts.append(f"{secs} detik")

    return " ".join(parts)
                                                                              
def format_pace(pace_decimal):
    """Mengubah pace dari format desimal (e.g., 6.50) menjadi Menit:Detik."""
    if not pace_decimal or float(pace_decimal) <= 0:
        return "--"

    pace_float = float(pace_decimal)
    minutes = int(pace_float)
    seconds_decimal = pace_float - minutes
    seconds = round(seconds_decimal * 60)

    if seconds == 60:
        minutes += 1
        seconds = 0

    return f"{minutes}:{seconds:02d} min/km"
                                                                              
# DAFTARKAN FILTER KE APLIKASI FLASK
app.jinja_env.filters['format_duration'] = format_duration
app.jinja_env.filters['format_pace'] = format_pace


# --- 2. Model Data Tracking (Menggunakan Redis) ---
class RunTrackerModel:
    RUN_ID_COUNTER = 'run_id_counter'
    USER_ID_COUNTER = 'user_id_counter'
    USER_KEY = 'user:{}:details'
    USER_USERNAME_IDX = 'user:username:{}' 
    GLOBAL_LEADERBOARD = 'global_leaderboard'
    USER_RUNS = 'user:{}:runs'
    RUN_DETAIL = 'run:{}'

    @staticmethod
    def get_redis_conn():
        """Fungsi pembantu untuk mendapatkan koneksi Redis yang aktif."""
        return get_redis_client()

    @staticmethod
    def find_user_by_username(username):
        redis_conn = RunTrackerModel.get_redis_conn()
        if not redis_conn:
            return None
        
        user_id_bytes = redis_conn.get(RunTrackerModel.USER_USERNAME_IDX.format(username))
        if user_id_bytes:
            user_id = int(user_id_bytes)
            return RunTrackerModel.get_user_data(user_id)
        return None

    @staticmethod
    def register_user(username, password):
        redis_conn = RunTrackerModel.get_redis_conn()
        if not redis_conn:
            return None                                                       
        try:
            if RunTrackerModel.find_user_by_username(username):
                return 'duplicate'

            user_id = redis_conn.incr(RunTrackerModel.USER_ID_COUNTER)
            user_data = {
                'username': username,
                'password': password,
                'registered_at': datetime.now().isoformat(),
                'id': user_id
            }
            redis_conn.hset(RunTrackerModel.USER_KEY.format(user_id), mapping=user_data)
                                                                                          
            redis_conn.set(RunTrackerModel.USER_USERNAME_IDX.format(username), user_id)

            return user_id
        except Exception as e:
            print(f"Error registering user: {e}")
            return None                                                       
    
    @staticmethod
    def get_user_data(user_id):
        redis_conn = RunTrackerModel.get_redis_conn()
        if not redis_conn:
            return None

        data = redis_conn.hgetall(RunTrackerModel.USER_KEY.format(user_id))
        if data:
            user_data = dict(data)
            user_data['id'] = int(user_id)
            return user_data
        return None
               
    @staticmethod
    def add_run(user_id, duration_sec, distance_km, average_pace, route_data, total_steps):
        redis_conn = RunTrackerModel.get_redis_conn()
        if not redis_conn:
            return None

        try:
            run_id = redis_conn.incr(RunTrackerModel.RUN_ID_COUNTER)
            timestamp = datetime.now().isoformat()
                                                                                          
            run_data_raw = {
                'run_id': run_id,
                'user_id': user_id,
                'timestamp': timestamp,
                'duration_sec': int(duration_sec),
                'distance_km': float(distance_km),
                'average_pace': float(average_pace),
                'route_data': json.dumps(route_data),
                'total_steps': int(total_steps)
            }                                                                                                                                                           
            run_data_redis = {k: str(v) for k, v in run_data_raw.items()}
                                                                                          
            redis_conn.hset(RunTrackerModel.RUN_DETAIL.format(run_id), mapping=run_data_redis)

            redis_conn.lpush(RunTrackerModel.USER_RUNS.format(user_id), run_id)

            redis_conn.zadd(RunTrackerModel.GLOBAL_LEADERBOARD, {f"{user_id}:{run_id}": float(distance_km)})

            return run_id
        except Exception as e:
            print(f"Error saving run to Redis: {e}")
            return None
          
    @staticmethod
    def get_run_detail(run_id):
        redis_conn = RunTrackerModel.get_redis_conn()
        if not redis_conn:
            return None
                                                                                      
        try: 
            data = redis_conn.hgetall(RunTrackerModel.RUN_DETAIL.format(run_id))
            if not data:
                return None                                                   
            detail = dict(data)

            detail['run_id'] = int(detail['run_id'])
            detail['user_id'] = int(detail['user_id'])
            detail['duration_sec'] = int(detail['duration_sec'])
            detail['distance_km'] = float(detail['distance_km'])
            detail['average_pace'] = float(detail['average_pace'])
            detail['total_steps'] = int(detail.get('total_steps', 0))

            route_data_json_string = detail.get('route_data', '[]')
            detail['route_data'] = json.loads(route_data_json_string)

            return detail
        except Exception as e:
            print(f"Error retrieving run detail: {e}")
            return None
                 
    @staticmethod
    def get_user_runs(user_id):
        redis_conn = RunTrackerModel.get_redis_conn()
        if not redis_conn:
            return []
                                                                                      
        run_ids = redis_conn.lrange(RunTrackerModel.USER_RUNS.format(user_id), 0, -1)
        runs = []                                                                     
        for run_id_str in run_ids:
            try:
                run_id = int(run_id_str)
                run_detail = RunTrackerModel.get_run_detail(run_id)
                if run_detail:
                    runs.append(run_detail)
            except ValueError:
                print(f"Warning: Failed to convert run_id {run_id_str} to int.")
                                                                                      
        return runs


    @staticmethod
    def get_global_leaderboard(count=5):
        redis_conn = RunTrackerModel.get_redis_conn()
        if not redis_conn:
            return []

        try:
            leaderboard_raw = redis_conn.zrevrange(RunTrackerModel.GLOBAL_LEADERBOARD, 0, count - 1, withscores=True)
            leaderboard = []
                                                                                          
            for key_score, distance in leaderboard_raw:
                try:
                    key_score_str = key_score
                    user_id_str, run_id_str = key_score_str.split(':')
                    run_id = int(run_id_str)
                    user_id = int(user_id_str)

                    run_detail = RunTrackerModel.get_run_detail(run_id)
                    user_data = RunTrackerModel.get_user_data(user_id)
 
                    username = user_data.get('username', f"Runner {user_id}")
                                                                                                  
                    if run_detail:
                        leaderboard.append({
                            'run_id': run_id,
                            'username': username,
                            'distance': float(distance),
                            'average_pace': run_detail.get('average_pace', 0.0),
                            'timestamp': run_detail.get('timestamp')
                        })

                except Exception as e:
                    print(f"Error parsing leaderboard entry or getting detail: {e}")

            return leaderboard
        except Exception as e:
            print(f"Error retrieving leaderboard: {e}")
            return []
        
# --- 3. Routing Halaman Web (Autentikasi di sisi Klien) ---

def get_current_user_id():
    # Fungsi Dummy untuk simulasi sesi
    return 1
                                                                              
@app.route('/')
@app.route('/web')
@app.route('/web/dashboard')
def web_dashboard():
    user_id = get_current_user_id()
    user_data = RunTrackerModel.get_user_data(user_id)
    username = user_data.get('username') if user_data else 'Pelari'

    user_runs = RunTrackerModel.get_user_runs(user_id)

    leaderboard = RunTrackerModel.get_global_leaderboard(count=5)

    return render_template('dashboard.html',
        user_runs=user_runs,
        leaderboard=leaderboard,
        username=username
    )                                                                         
@app.route('/web/register')
def web_register():
    return render_template('register.html')

@app.route('/web/login')                                                      
def web_login():
    return render_template('login.html')
      
@app.route('/web/run/<int:run_id>')                                           
def web_run_detail(run_id):
    run_detail = RunTrackerModel.get_run_detail(run_id)

    if not run_detail:
        return render_template('base.html', content="Error: Sesi lari tidak ditemukan")
                                                                                  
    user_data = RunTrackerModel.get_user_data(run_detail['user_id'])
                                                                                  
    return render_template('run_detail.html', run=run_detail, username=user_data.get('username'))

@app.route('/web/start_run')
def web_start_run():
    user_id = get_current_user_id()
    user_data = RunTrackerModel.get_user_data(user_id)
    if not user_data:
        return render_template('base.html', content=f"Pengguna ID {user_id} tidak ditemukan")

    return render_template('start_run.html', user_id=user_id, username=user_data.get('username'))

# --- 4. API Endpoint ---                                                     
@app.route('/api/log_run', methods=['POST'])
def api_log_run():
    data = request.get_json()

    if not all(k in data for k in ['user_id', 'duration_sec', 'distance_km', 'route_data', 'total_steps']):
        return jsonify({"message": "Data tidak lengkap.", "success": False}), 400

    duration_sec = int(data['duration_sec'])
    distance_km = float(data['distance_km'])

    final_pace = 0.00
    if distance_km > 0 and duration_sec > 0:
        duration_min = duration_sec / 60
        calculated_pace = duration_min / distance_km
        final_pace = float(f"{calculated_pace:.2f}")
    elif distance_km == 0:
        final_pace = 0.00

    run_id = RunTrackerModel.add_run(
        data['user_id'],
        data['duration_sec'],
        data['distance_km'],
        final_pace,
        data['route_data'],
        data['total_steps']
    )

    if run_id:
        return jsonify({
            "message": "Sesi lari berhasil dicatat!",
            "run_id": run_id,
            "success": True
        })
    else:
        return jsonify({"message": "Gagal menyimpan ke database. Koneksi Redis mungkin gagal.", "success": False}), 500

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json()
                                                                                  
    if not all(k in data for k in ['username', 'password']):
        return jsonify({"message": "Username dan password dibutuhkan.", "success": False}), 400
    
    user_id = RunTrackerModel.register_user(data['username'], data['password'])
     
    if user_id == 'duplicate':
        return jsonify({"message": "Pendaftaran gagal: Username sudah terdaftar.", "success": False}), 409
                                                                                  
    if user_id:
        return jsonify({
            "message": f"Pendaftaran sukses! Selamat datang, {data['username']}.",
            "user_id": user_id,
            "success": True
        })
    else:
        return jsonify({"message": "Pendaftaran gagal karena masalah server (Koneksi Redis Gagal).", "success": False}), 500


# --- 5. Jalankan Aplikasi ---                                                
if __name__ == '__main__':
    # Jalankan aplikasi di lokal
    app.run(host='0.0.0.0', port=5000, debug=True)
