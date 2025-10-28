# database.py

import redis
from config import Config

# Inisialisasi koneksi Redis
# decode_responses=True agar hasil yang diterima dari Redis berupa string
redis_client = redis.Redis(
    host=Config.REDIS_HOST,
    port=Config.REDIS_PORT,
    db=Config.REDIS_DB,
    decode_responses=True
)

# Test koneksi ke Redis (Opsional, bisa dilakukan di app.py)
try:
    redis_client.ping()
    print("✅ Redis: Koneksi berhasil dari database.py!")
except Exception as e:
    print(f"❌ Redis: Gagal terhubung! Error: {e}")
