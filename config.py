# config.py

class Config:
    SECRET_KEY = '0d8af58430b02ca6a291d3bb8180eb40d28285723a2e3dd9' # Ganti dengan kunci yang lebih aman
    
    # Konfigurasi Koneksi Redis
    REDIS_HOST = '127.0.0.1'
    REDIS_PORT = 6379
    REDIS_DB = 0  
    
    # Prefix Kunci Redis (Untuk menjaga keteraturan data)
    KEY_PREFIX_USER = 'user'
    KEY_PREFIX_RUN = 'run'
    KEY_NEXT_USER_ID = 'next_user_id'
    KEY_NEXT_RUN_ID = 'next_run_id'
