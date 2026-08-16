import re

with open('db.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Add threading import if missing
if 'import threading' not in code:
    code = 'import threading\n' + code

# 1. FirestoreCache
fs_init = '''    def __init__(self):
        self.db = None
        self.creds = Config.get_firebase_credentials()
        self.connection_error = None
        self._connected = False'''
fs_init_new = '''    def __init__(self):
        self.db = None
        self.creds = Config.get_firebase_credentials()
        self.connection_error = None
        self._connected = False
        self._lock = threading.Lock()'''
code = code.replace(fs_init, fs_init_new)

fs_ens = '''    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
        if not self.creds:'''
fs_ens_new = '''    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
        with self._lock:
            if self._connected or self.connection_error:
                return
            if not self.creds:'''
code = code.replace(fs_ens, fs_ens_new)

# 2. GoogleSheetsCache
gs_init = '''    def __init__(self):
        self.client = None
        self.sheet = None
        self.specs_sheet = None
        self.spreadsheet_id = Config.GOOGLE_SHEETS_SPREADSHEET_ID
        self.creds = Config.get_google_sheets_credentials()
        self.connection_error = None
        self._connected = False'''
gs_init_new = '''    def __init__(self):
        self.client = None
        self.sheet = None
        self.specs_sheet = None
        self.spreadsheet_id = Config.GOOGLE_SHEETS_SPREADSHEET_ID
        self.creds = Config.get_google_sheets_credentials()
        self.connection_error = None
        self._connected = False
        self._lock = threading.Lock()'''
code = code.replace(gs_init, gs_init_new)

gs_ens = '''    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
        if not self.spreadsheet_id or not self.creds:'''
gs_ens_new = '''    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
        with self._lock:
            if self._connected or self.connection_error:
                return
            if not self.spreadsheet_id or not self.creds:'''
code = code.replace(gs_ens, gs_ens_new)

# 3. GoogleDriveManager
gd_init = '''    def __init__(self, firestore_cache=None):
        self.service = None
        self.creds = Config.get_google_sheets_credentials()
        self.connection_error = None
        self.firestore = firestore_cache
        self.oauth_connected = False
        self.oauth_email = None
        self._connected = False'''
gd_init_new = '''    def __init__(self, firestore_cache=None):
        self.service = None
        self.creds = Config.get_google_sheets_credentials()
        self.connection_error = None
        self.firestore = firestore_cache
        self.oauth_connected = False
        self.oauth_email = None
        self._connected = False
        self._lock = threading.Lock()'''
code = code.replace(gd_init, gd_init_new)

gd_ens = '''    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
            
        # 1. Firestore에서 OAuth 토큰 로드 시도'''
gd_ens_new = '''    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
        with self._lock:
            if self._connected or self.connection_error:
                return
                
            # 1. Firestore에서 OAuth 토큰 로드 시도'''
code = code.replace(gd_ens, gd_ens_new)

# Fix empty list returns
kw_ret = '''        if self.redis:
            val = self.redis.get("car_news_keywords")
            if val:
                return json.loads(val)'''
kw_ret_new = '''        if self.redis:
            val = self.redis.get("car_news_keywords")
            if val:
                return json.loads(val)
        return []'''
code = code.replace(kw_ret, kw_ret_new)

yt_ret = '''        if self.redis:
            val = self.redis.get("car_news_youtube_urls")
            if val:
                return json.loads(val)'''
yt_ret_new = '''        if self.redis:
            val = self.redis.get("car_news_youtube_urls")
            if val:
                return json.loads(val)
        return []'''
code = code.replace(yt_ret, yt_ret_new)

with open('db.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("db.py updated.")
