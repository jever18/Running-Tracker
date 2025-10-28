# models.py
import json
import time
from database import redis_client

class RunTrackerModel:
    
    # --- UTILITY METHODS ---

    @staticmethod
    def get_next_id(key: str) -> int:
        """Mengambil ID unik berikutnya (misal: user_id, run_id)."""
        return redis_client.incr(f"global:{key}_counter")

    @staticmethod
    def _decode_redis_data(data: dict) -> dict:
        """Helper untuk mendekode kunci dan nilai dari bytes ke string, menangani None."""
        if not data:
            return {}
        
        decoded = {}
        for k, v in data.items():
            # Pastikan kunci di-decode
            key_str = k.decode('utf-8') if isinstance(k, bytes) else k
            
            # Pastikan nilai di-decode jika berupa bytes
            value_str = v.decode('utf-8') if isinstance(v, bytes) else v
            
            decoded[key_str] = value_str
        return decoded

    # --- USER MANAGEMENT ---

    @staticmethod
    def create_new_user(username: str, email: str, password_hash: str) -> int or None:
        """Mendaftarkan pengguna baru jika email belum terdaftar."""
        
        # Cek apakah email sudah terdaftar (Redis HGET mengembalikan bytes atau None)
        if redis_client.hget("emails", email):
            return None 
        
        user_id = RunTrackerModel.get_next_id("user")
        user_key = f"user:{user_id}"
        
        user_data = {
            "user_id": user_id,
            "username": username,
            "email": email,
            "password_hash": password_hash,
            "join_date": time.time(),
        }
        
        pipe = redis_client.pipeline()
        pipe.hset("emails", email, user_id)
        pipe.hmset(user_key, user_data)
        pipe.zadd("leaderboard:total_distance", {user_key: 0})
        pipe.execute()
        
        return user_id

    @staticmethod
    def get_user_data(user_id: int) -> dict or None:
        """Mengambil data pengguna berdasarkan ID."""
        user_key = f"user:{user_id}"
        user_data = redis_client.hgetall(user_key)
        
        if user_data:
            return RunTrackerModel._decode_redis_data(user_data)
        return None

    # --- RUN LOGGING ---

    @staticmethod
    def log_new_run(user_id: int, duration_sec: int, distance_km: float, average_pace: float, route_data: list) -> int or None:
        """Mencatat sesi lari baru dan memperbarui Leaderboard."""
        
        if not RunTrackerModel.get_user_data(user_id):
            return None
        
        run_id = RunTrackerModel.get_next_id("run")
        run_key = f"run:{run_id}"
        
        run_data = {
            "run_id": run_id,
            "user_id": user_id,
            "start_time": time.time(),
            "duration_sec": duration_sec,
            "distance_km": distance_km,
            "average_pace": average_pace,
            "route_data": json.dumps(route_data) 
        }
        
        pipe = redis_client.pipeline()
        pipe.hmset(run_key, run_data)
        pipe.lpush(f"user:{user_id}:runs", run_id)
        
        user_key = f"user:{user_id}"
        pipe.zincrby("leaderboard:total_distance", distance_km, user_key)
        
        pipe.execute()
        
        return run_id

    # --- LEADERBOARD & RIWAYAT ---

    @staticmethod
    def get_global_leaderboard(limit: int = 10) -> list:
        """Mengambil Leaderboard global berdasarkan total jarak."""
        
        leaderboard_data = redis_client.zrevrange("leaderboard:total_distance", 0, limit - 1, withscores=True)
        
        result = []
        for user_key_bytes, total_distance in leaderboard_data:
            # PENTING: Decode user_key_bytes yang merupakan kunci ZSET
            user_key = user_key_bytes.decode('utf-8') if isinstance(user_key_bytes, bytes) else user_key_bytes
            user_id = user_key.split(':')[-1]
            
            username_bytes = redis_client.hget(user_key, "username")
            
            # PENTING: Handle username jika None atau bytes/string
            username = username_bytes.decode('utf-8') if isinstance(username_bytes, bytes) else username_bytes or "Unknown"
            
            result.append({
                "user_id": int(user_id),
                "username": username,
                "total_distance_km": float(total_distance)
            })
        return result

    @staticmethod
    def get_user_runs(user_id: int, limit: int = 5) -> list:
        """Mengambil riwayat sesi lari terbaru milik pengguna."""
        
        run_ids_bytes = redis_client.lrange(f"user:{user_id}:runs", 0, limit - 1)
        
        runs_detail = []
        for run_id_bytes in run_ids_bytes:
            run_id = int(run_id_bytes.decode('utf-8') if isinstance(run_id_bytes, bytes) else run_id_bytes)
            
            # Ambil data: menggunakan HMGET mengembalikan list of bytes/None
            run_data_bytes = redis_client.hmget(f"run:{run_id}", 
                                          "run_id", "distance_km", "duration_sec", "average_pace")
            
            # PENTING: Pastikan semua nilai yang diambil ada dan di-decode dengan benar
            run_id_val = run_data_bytes[0].decode('utf-8') if run_data_bytes[0] and isinstance(run_data_bytes[0], bytes) else run_data_bytes[0] or None
            distance_val = run_data_bytes[1].decode('utf-8') if run_data_bytes[1] and isinstance(run_data_bytes[1], bytes) else run_data_bytes[1] or '0.0'
            duration_val = run_data_bytes[2].decode('utf-8') if run_data_bytes[2] and isinstance(run_data_bytes[2], bytes) else run_data_bytes[2] or '0'
            pace_val = run_data_bytes[3].decode('utf-8') if run_data_bytes[3] and isinstance(run_data_bytes[3], bytes) else run_data_bytes[3] or '0.0'
            
            if run_id_val:
                runs_detail.append({
                    "run_id": int(run_id_val),
                    "distance_km": float(distance_val),
                    "duration_sec": int(duration_val),
                    "average_pace": float(pace_val)
                })
                
        return runs_detail

    # --- DETAIL LARI DENGAN PETA ---
    
    @staticmethod
    def get_run_detail(run_id: int):
        """Mengambil detail sesi lari tunggal, termasuk route_data yang di-parse."""
        run_key = f"run:{run_id}"
        run_data_bytes = redis_client.hgetall(run_key)
        
        if not run_data_bytes:
            return None

        # Gunakan helper untuk decoding yang aman
        decoded_data = RunTrackerModel._decode_redis_data(run_data_bytes)
        
        route_data = []
        if 'route_data' in decoded_data and decoded_data['route_data']:
            try:
                route_data = json.loads(decoded_data['route_data'])
            except json.JSONDecodeError:
                route_data = [] 

        run_detail = {
            'run_id': int(decoded_data.get('run_id')),
            'user_id': int(decoded_data.get('user_id')),
            'start_time': decoded_data.get('start_time'),
            'duration_sec': int(decoded_data.get('duration_sec', 0)),
            'distance_km': float(decoded_data.get('distance_km', 0.0)),
            'average_pace': float(decoded_data.get('average_pace', 0.0)),
            'route_data': route_data, 
        }
        
        return run_detail
