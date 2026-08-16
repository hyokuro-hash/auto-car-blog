import threading

with open('db.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Add lock to GoogleSheetsCache
old1 = '''        self.connection_error = None
        self._connected = False

    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
        if not self.spreadsheet_id or not self.creds:'''
new1 = '''        self.connection_error = None
        self._connected = False
        self._lock = __import__("threading").Lock()

    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
        with self._lock:
            if self._connected or self.connection_error:
                return
            if not self.spreadsheet_id or not self.creds:'''
text = text.replace(old1, new1)

# Add lock to FirestoreCache
old2 = '''        self.connection_error = None
        self._connected = False

    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
        if not self.creds:'''
new2 = '''        self.connection_error = None
        self._connected = False
        self._lock = __import__("threading").Lock()

    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
        with self._lock:
            if self._connected or self.connection_error:
                return
            if not self.creds:'''
text = text.replace(old2, new2)

# Add lock to GoogleDriveManager
old3 = '''        self.oauth_email = None
        self._connected = False

    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
            
        # 1.'''
new3 = '''        self.oauth_email = None
        self._connected = False
        self._lock = __import__("threading").Lock()

    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
        with self._lock:
            if self._connected or self.connection_error:
                return
            
            # 1.'''
text = text.replace(old3, new3)

# Fix empty fallback
old4 = '''        if self.redis:
            val = self.redis.get("car_news_keywords")
            if val:
                return json.loads(val)'''
new4 = '''        if self.redis:
            val = self.redis.get("car_news_keywords")
            if val:
                return json.loads(val)
        return []'''
text = text.replace(old4, new4)

old5 = '''        if self.redis:
            val = self.redis.get("car_news_youtube_urls")
            if val:
                return json.loads(val)'''
new5 = '''        if self.redis:
            val = self.redis.get("car_news_youtube_urls")
            if val:
                return json.loads(val)
        return []'''
text = text.replace(old5, new5)

with open('db.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Done")
