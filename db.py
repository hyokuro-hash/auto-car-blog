import os
import json
import hashlib
from datetime import datetime
from config import Config

# 로컬 폴백용 캐시 파일 경로
LOCAL_CACHE_FILE = "cache.json"

def _hash_url(url: str) -> str:
    """URL의 MD5 해시값을 생성하여 키로 사용합니다."""
    return hashlib.md5(url.strip().encode("utf-8")).hexdigest()

class LocalCache:
    """Google Sheets나 Firebase 설정이 없을 때 사용하는 로컬 JSON 캐시 폴백"""
    def __init__(self, filepath=LOCAL_CACHE_FILE):
        self.filepath = filepath
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception as e:
                print(f"[LocalCache] 로드 오류: {e}, 캐시를 초기화합니다.")
                self.data = {}
        else:
            self.data = {}

    def _save(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[LocalCache] 저장 오류: {e}")

    def is_duplicate(self, url: str) -> bool:
        url_hash = _hash_url(url)
        return url_hash in self.data

    def mark_as_collected(self, url: str, title: str):
        url_hash = _hash_url(url)
        if url_hash not in self.data:
            self.data[url_hash] = {
                "url": url,
                "title": title,
                "collected_at": datetime.now().isoformat(),
                "published": False,
                "tistory_url": "",
                "wordpress_url": ""
            }
            self._save()

    def mark_as_published(self, url: str, platform: str, post_url: str):
        url_hash = _hash_url(url)
        if url_hash in self.data:
            self.data[url_hash]["published"] = True
            if platform.lower() == "tistory":
                self.data[url_hash]["tistory_url"] = post_url
            elif platform.lower() == "wordpress":
                self.data[url_hash]["wordpress_url"] = post_url
            self.data[url_hash]["published_at"] = datetime.now().isoformat()
            self._save()


class GoogleSheetsCache:
    """Google Sheets API 기반 중복 제거 캐시"""
    def __init__(self):
        self.client = None
        self.sheet = None
        self.spreadsheet_id = Config.GOOGLE_SHEETS_SPREADSHEET_ID
        self.creds = Config.get_google_sheets_credentials()
        self._init_connection()

    def _init_connection(self):
        if not self.spreadsheet_id or not self.creds:
            print("[GoogleSheets] 설정 정보(Spreadsheet ID 또는 Credentials)가 부족합니다.")
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
            
            # 첫 번째 워크시트 가져오거나 생성
            try:
                self.sheet = self.spreadsheet.get_worksheet(0)
            except Exception:
                self.sheet = self.spreadsheet.add_worksheet(title="Cache", rows="100", cols="10")
            
            # 헤더가 없으면 초기화
            headers = ["URL Hash", "URL", "Title", "Collected At", "Published", "Tistory URL", "WordPress URL", "Published At"]
            first_row = self.sheet.row_values(1)
            if not first_row or first_row[0] != "URL Hash":
                self.sheet.insert_row(headers, 1)
                print("[GoogleSheets] 시트 헤더를 초기화했습니다.")
            
            print("[GoogleSheets] 연동 성공.")
        except Exception as e:
            print(f"[GoogleSheets] 연결 실패: {e}")
            self.client = None

    @property
    def is_available(self) -> bool:
        return self.client is not None and self.sheet is not None

    def is_duplicate(self, url: str) -> bool:
        if not self.is_available:
            return False
        try:
            url_hash = _hash_url(url)
            # URL Hash 컬럼(1번째 열)에서 검색
            cell = self.sheet.find(url_hash, in_column=1)
            return cell is not None
        except Exception as e:
            print(f"[GoogleSheets] 중복 검사 오류: {e}")
            return False

    def mark_as_collected(self, url: str, title: str):
        if not self.is_available:
            return
        try:
            url_hash = _hash_url(url)
            row = [
                url_hash, 
                url, 
                title, 
                datetime.now().isoformat(), 
                "FALSE", 
                "", 
                "", 
                ""
            ]
            self.sheet.append_row(row)
        except Exception as e:
            print(f"[GoogleSheets] 수집 기록 작성 오류: {e}")

    def mark_as_published(self, url: str, platform: str, post_url: str):
        if not self.is_available:
            return
        try:
            url_hash = _hash_url(url)
            cell = self.sheet.find(url_hash, in_column=1)
            if cell:
                row_num = cell.row
                # Published 컬럼(5번째 열) 업데이트
                self.sheet.update_cell(row_num, 5, "TRUE")
                self.sheet.update_cell(row_num, 8, datetime.now().isoformat())
                
                if platform.lower() == "tistory":
                    self.sheet.update_cell(row_num, 6, post_url)
                elif platform.lower() == "wordpress":
                    self.sheet.update_cell(row_num, 7, post_url)
        except Exception as e:
            print(f"[GoogleSheets] 발행 상태 업데이트 오류: {e}")


class FirestoreCache:
    """Firebase Firestore 기반 중복 제거 캐시"""
    def __init__(self):
        self.db = None
        self.creds = Config.get_firebase_credentials()
        self._init_connection()

    def _init_connection(self):
        if not self.creds:
            print("[Firestore] Credentials 설정 정보가 없습니다.")
            return
        
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
            
            # 중복 초기화 방지
            try:
                app = firebase_admin.get_app()
            except ValueError:
                cred = credentials.Certificate(self.creds)
                app = firebase_admin.initialize_app(cred)
                
            self.db = firestore.client()
            print("[Firestore] 연동 성공.")
        except Exception as e:
            print(f"[Firestore] 연결 실패: {e}")
            self.db = None

    @property
    def is_available(self) -> bool:
        return self.db is not None

    def is_duplicate(self, url: str) -> bool:
        if not self.is_available:
            return False
        try:
            url_hash = _hash_url(url)
            doc_ref = self.db.collection("car_news_cache").document(url_hash)
            doc = doc_ref.get()
            return doc.exists
        except Exception as e:
            print(f"[Firestore] 중복 검사 오류: {e}")
            return False

    def mark_as_collected(self, url: str, title: str):
        if not self.is_available:
            return
        try:
            url_hash = _hash_url(url)
            doc_ref = self.db.collection("car_news_cache").document(url_hash)
            doc_ref.set({
                "url": url,
                "title": title,
                "collected_at": datetime.now().isoformat(),
                "published": False,
                "tistory_url": "",
                "wordpress_url": ""
            })
        except Exception as e:
            print(f"[Firestore] 수집 기록 작성 오류: {e}")

    def mark_as_published(self, url: str, platform: str, post_url: str):
        if not self.is_available:
            return
        try:
            url_hash = _hash_url(url)
            doc_ref = self.db.collection("car_news_cache").document(url_hash)
            update_data = {
                "published": True,
                "published_at": datetime.now().isoformat()
            }
            if platform.lower() == "tistory":
                update_data["tistory_url"] = post_url
            elif platform.lower() == "wordpress":
                update_data["wordpress_url"] = post_url
                
            doc_ref.update(update_data)
        except Exception as e:
            print(f"[Firestore] 발행 상태 업데이트 오류: {e}")


# --- 글로벌 DB 캐시 인스턴스 팩토리 ---
class DatabaseCache:
    def __init__(self):
        # 1. Firebase 연동 시도
        self.firestore = FirestoreCache()
        # 2. Google Sheets 연동 시도
        self.sheets = GoogleSheetsCache()
        # 3. 로컬 폴백
        self.local = LocalCache()

    def is_duplicate(self, url: str) -> bool:
        # 우선순위: Firestore -> Sheets -> Local
        if self.firestore.is_available:
            return self.firestore.is_duplicate(url)
        if self.sheets.is_available:
            return self.sheets.is_duplicate(url)
        return self.local.is_duplicate(url)

    def mark_as_collected(self, url: str, title: str):
        # 활성화된 모든 매체에 병렬 기록
        recorded = False
        if self.firestore.is_available:
            self.firestore.mark_as_collected(url, title)
            recorded = True
        if self.sheets.is_available:
            self.sheets.mark_as_collected(url, title)
            recorded = True
        
        # 클라우드 저장소가 하나도 동작하지 않을 시에만 혹은 기본적으로 로컬 백업
        self.local.mark_as_collected(url, title)

    def mark_as_published(self, url: str, platform: str, post_url: str):
        if self.firestore.is_available:
            self.firestore.mark_as_published(url, platform, post_url)
        if self.sheets.is_available:
            self.sheets.mark_as_published(url, platform, post_url)
        self.local.mark_as_published(url, platform, post_url)


db_cache = DatabaseCache()
