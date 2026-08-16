import re

with open('db.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Refactor GoogleSheetsCache
sheets_target = '''    def _init_connection(self):
        if not self.spreadsheet_id or not self.creds:
            self.connection_error = f"Spreadsheet ID exists: {bool(self.spreadsheet_id)}, Credentials exist: {bool(self.creds)}"
            return
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            credentials = Credentials.from_service_account_info(self.creds, scopes=scopes)
            self.client = gspread.authorize(credentials)
            self.spreadsheet = self.client.open_by_key(self.spreadsheet_id)
            
            # 중복 체크용 캐시 시트 로드
            try:
                self.sheet = self.spreadsheet.get_worksheet(0)
            except Exception:
                self.sheet = self.spreadsheet.add_worksheet(title="Cache", rows="100", cols="10")
            
            # 차량 제원용 시트 로드
            try:
                self.specs_sheet = self.spreadsheet.worksheet("VehicleSpecs")
            except Exception:
                self.specs_sheet = self.spreadsheet.add_worksheet(title="VehicleSpecs", rows="100", cols="10")
        except Exception as e:
            self.connection_error = str(e)
            print(f"[GoogleSheets] 연결 실패: {e}")
            self.client = None

    @property
    def is_available(self) -> bool:
        return self.client is not None'''

sheets_repl = '''    def _init_connection(self):
        self._connected = False
        if not self.spreadsheet_id or not self.creds:
            self.connection_error = f"Spreadsheet ID exists: {bool(self.spreadsheet_id)}, Credentials exist: {bool(self.creds)}"
            return

    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            credentials = Credentials.from_service_account_info(self.creds, scopes=scopes)
            self.client = gspread.authorize(credentials)
            self.spreadsheet = self.client.open_by_key(self.spreadsheet_id)
            
            # 중복 체크용 캐시 시트 로드
            try:
                self.sheet = self.spreadsheet.get_worksheet(0)
            except Exception:
                self.sheet = self.spreadsheet.add_worksheet(title="Cache", rows="100", cols="10")
            
            # 차량 제원용 시트 로드
            try:
                self.specs_sheet = self.spreadsheet.worksheet("VehicleSpecs")
            except Exception:
                self.specs_sheet = self.spreadsheet.add_worksheet(title="VehicleSpecs", rows="100", cols="10")
            self._connected = True
        except Exception as e:
            self.connection_error = str(e)
            print(f"[GoogleSheets] 연결 실패: {e}")
            self.client = None

    @property
    def is_available(self) -> bool:
        self._ensure_connected()
        return self.client is not None'''

code = code.replace(sheets_target, sheets_repl)

# Refactor GoogleDriveManager
drive_target = '''    def _init_connection(self):
        # 1. Firestore에서 OAuth 토큰 로드 시도
        refresh_token = None
        if self.firestore and self.firestore.is_available:
            try:
                doc = self.firestore.db.collection("settings").document("google_oauth").get()
                if doc.exists:
                    data = doc.to_dict()
                    refresh_token = data.get("refresh_token")
                    self.oauth_email = data.get("email")
            except Exception as e:
                print(f"[GoogleDrive] Firestore OAuth 로드 실패: {e}")

        # 2. 토큰이 있고 Client ID/Secret이 있다면 OAuth2.0 연결 (20TB 드라이브 활용)
        if refresh_token and Config.GOOGLE_CLIENT_ID and Config.GOOGLE_CLIENT_SECRET:
            try:
                from googleapiclient.discovery import build
                from google.oauth2.credentials import Credentials
                scopes = ["https://www.googleapis.com/auth/drive"]
                credentials = Credentials(
                    token=None,
                    refresh_token=refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=Config.GOOGLE_CLIENT_ID,
                    client_secret=Config.GOOGLE_CLIENT_SECRET,
                    scopes=scopes
                )
                self.service = build('drive', 'v3', credentials=credentials)
                self.oauth_connected = True
                print(f"[GoogleDrive] OAuth 연결 성공 ({self.oauth_email})")
                return
            except Exception as e:
                self.connection_error = f"OAuth 연결 실패: {e}"
                print(f"[GoogleDrive] {self.connection_error}")
                self.oauth_connected = False

        # 3. OAuth 실패 시, 서비스 계정(기존 방식)으로 Fallback
        if not self.creds:
            self.connection_error = "Credentials missing"
            return
        try:
            from googleapiclient.discovery import build
            from google.oauth2.service_account import Credentials
            scopes = ["https://www.googleapis.com/auth/drive"]
            credentials = Credentials.from_service_account_info(self.creds, scopes=scopes)
            self.service = build('drive', 'v3', credentials=credentials)
            self.oauth_connected = False
            print("[GoogleDrive] 서비스 계정으로 연결 성공 (Fallback)")
        except Exception as e:
            self.connection_error = str(e)
            print(f"[GoogleDrive] Fallback 연결 실패: {e}")
            self.service = None

    @property
    def is_available(self) -> bool:
        return self.service is not None'''

drive_repl = '''    def _init_connection(self):
        self._connected = False

    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
            
        # 1. Firestore에서 OAuth 토큰 로드 시도
        refresh_token = None
        if self.firestore and self.firestore.is_available:
            try:
                doc = self.firestore.db.collection("settings").document("google_oauth").get()
                if doc.exists:
                    data = doc.to_dict()
                    refresh_token = data.get("refresh_token")
                    self.oauth_email = data.get("email")
            except Exception as e:
                print(f"[GoogleDrive] Firestore OAuth 로드 실패: {e}")

        # 2. 토큰이 있고 Client ID/Secret이 있다면 OAuth2.0 연결 (20TB 드라이브 활용)
        if refresh_token and Config.GOOGLE_CLIENT_ID and Config.GOOGLE_CLIENT_SECRET:
            try:
                from googleapiclient.discovery import build
                from google.oauth2.credentials import Credentials
                scopes = ["https://www.googleapis.com/auth/drive"]
                credentials = Credentials(
                    token=None,
                    refresh_token=refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=Config.GOOGLE_CLIENT_ID,
                    client_secret=Config.GOOGLE_CLIENT_SECRET,
                    scopes=scopes
                )
                self.service = build('drive', 'v3', credentials=credentials)
                self.oauth_connected = True
                self._connected = True
                print(f"[GoogleDrive] OAuth 연결 성공 ({self.oauth_email})")
                return
            except Exception as e:
                self.connection_error = f"OAuth 연결 실패: {e}"
                print(f"[GoogleDrive] {self.connection_error}")
                self.oauth_connected = False

        # 3. OAuth 실패 시, 서비스 계정(기존 방식)으로 Fallback
        if not self.creds:
            self.connection_error = "Credentials missing"
            return
        try:
            from googleapiclient.discovery import build
            from google.oauth2.service_account import Credentials
            scopes = ["https://www.googleapis.com/auth/drive"]
            credentials = Credentials.from_service_account_info(self.creds, scopes=scopes)
            self.service = build('drive', 'v3', credentials=credentials)
            self.oauth_connected = False
            self._connected = True
            print("[GoogleDrive] 서비스 계정으로 연결 성공 (Fallback)")
        except Exception as e:
            self.connection_error = str(e)
            print(f"[GoogleDrive] Fallback 연결 실패: {e}")
            self.service = None

    @property
    def is_available(self) -> bool:
        self._ensure_connected()
        return self.service is not None'''

code = code.replace(drive_target, drive_repl)

with open('db.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("db.py updated successfully.")
