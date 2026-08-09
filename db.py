import os
import json
import hashlib
from datetime import datetime
from config import Config

# 로컬 캐시 파일 정의
LOCAL_CACHE_FILE = "cache.json"
LOCAL_TASKS_FILE = "tasks.json"
LOCAL_KEYWORDS_FILE = "keywords.json"
LOCAL_SCHEDULE_FILE = "schedule.json"
LOCAL_YOUTUBE_FILE = "youtube_urls.json"

def _hash_url(url: str) -> str:
    """URL의 MD5 해시값을 생성합니다."""
    return hashlib.md5(url.strip().encode("utf-8")).hexdigest()

# --- 헬퍼 함수: 로컬 파일 입출력 ---
def _load_json_file(filepath: str, default_val) -> dict:
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[db.py] {filepath} 로드 오류: {e}")
    return default_val

def _save_json_file(filepath: str, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[db.py] {filepath} 저장 오류: {e}")


class LocalCache:
    """Google Sheets나 Firebase 설정이 없을 때 사용하는 로컬 JSON 캐시 폴백"""
    def __init__(self):
        pass

    def is_duplicate(self, url: str) -> bool:
        data = _load_json_file(LOCAL_CACHE_FILE, {})
        url_hash = _hash_url(url)
        return url_hash in data

    def mark_as_collected(self, url: str, title: str):
        data = _load_json_file(LOCAL_CACHE_FILE, {})
        url_hash = _hash_url(url)
        if url_hash not in data:
            data[url_hash] = {
                "url": url,
                "title": title,
                "collected_at": datetime.now().isoformat(),
                "published": False,
                "tistory_url": "",
                "wordpress_url": ""
            }
            _save_json_file(LOCAL_CACHE_FILE, data)

    def mark_as_published(self, url: str, platform: str, post_url: str):
        data = _load_json_file(LOCAL_CACHE_FILE, {})
        url_hash = _hash_url(url)
        if url_hash in data:
            data[url_hash]["published"] = True
            if platform.lower() == "tistory":
                data[url_hash]["tistory_url"] = post_url
            elif platform.lower() == "wordpress":
                data[url_hash]["wordpress_url"] = post_url
            data[url_hash]["published_at"] = datetime.now().isoformat()
            _save_json_file(LOCAL_CACHE_FILE, data)


class GoogleSheetsCache:
    """Google Sheets API 기반 중복 제거 캐시 및 SpecsDB 통합 관리"""
    def __init__(self):
        self.client = None
        self.sheet = None
        self.specs_sheet = None
        self.spreadsheet_id = Config.GOOGLE_SHEETS_SPREADSHEET_ID
        self.creds = Config.get_google_sheets_credentials()
        self.connection_error = None
        self._init_connection()

    def _init_connection(self):
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
            
            headers = ["URL Hash", "URL", "Title", "Collected At", "Published", "Tistory URL", "WordPress URL", "Published At"]
            first_row = self.sheet.row_values(1)
            if not first_row or first_row[0] != "URL Hash":
                self.sheet.insert_row(headers, 1)

            # SpecsDB 시트 연결 (없으면 자동 생성)
            try:
                self.specs_sheet = self.spreadsheet.worksheet("SpecsDB")
            except Exception:
                self.specs_sheet = self.spreadsheet.add_worksheet(title="SpecsDB", rows="1000", cols="8")
                
            specs_headers = ["키워드", "공식모델명", "가격정보", "출력토크", "배터리제원", "장단점", "시장평가", "갱신일자"]
            first_row_specs = self.specs_sheet.row_values(1)
            if not first_row_specs or first_row_specs[0] != "키워드":
                self.specs_sheet.insert_row(specs_headers, 1)

            print("[GoogleSheets] 연동 성공 (SpecsDB 활성화 완료).")
        except Exception as e:
            self.connection_error = str(e)
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
            cell = self.sheet.find(url_hash, in_column=1)
            return cell is not None
        except Exception:
            return False

    def mark_as_collected(self, url: str, title: str):
        if not self.is_available:
            return
        try:
            url_hash = _hash_url(url)
            row = [url_hash, url, title, datetime.now().isoformat(), "FALSE", "", "", ""]
            self.sheet.append_row(row)
        except Exception as e:
            print(f"[GoogleSheets] 수집 기록 실패: {e}")

    def get_specs(self, keyword: str) -> dict | None:
        """SpecsDB 시트에서 키워드에 해당하는 제원 데이터를 조회합니다."""
        if not self.is_available or self.specs_sheet is None:
            return None
        try:
            records = self.specs_sheet.get_all_records()
            normalized_kw = keyword.replace(" ", "").lower()
            for r in records:
                if str(r.get("키워드", "")).replace(" ", "").lower() == normalized_kw:
                    return r
            return None
        except Exception as e:
            print(f"[GoogleSheets] SpecsDB 스펙 조회 실패 ({keyword}): {e}")
            return None

    def save_specs(self, keyword: str, specs_dict: dict):
        """새로 생성된 제원 데이터를 SpecsDB 시트에 캐싱합니다."""
        if not self.is_available or self.specs_sheet is None:
            return
        try:
            normalized_kw = keyword.replace(" ", "").lower()
            cell = None
            try:
                cell = self.specs_sheet.find(keyword, in_column=1)
                if not cell:
                    cells = self.specs_sheet.findall(keyword)
                    for c in cells:
                        if c.col == 1:
                            cell = c
                            break
            except Exception:
                cell = None

            row_data = [
                keyword,
                specs_dict.get("공식모델명", specs_dict.get("model_name", "")),
                specs_dict.get("가격정보", specs_dict.get("price_info", "")),
                specs_dict.get("출력토크", specs_dict.get("performance", "")),
                specs_dict.get("배터리제원", specs_dict.get("battery", specs_dict.get("specs", ""))),
                specs_dict.get("장단점", specs_dict.get("pros_cons", "")),
                specs_dict.get("시장평가", specs_dict.get("market_review", specs_dict.get("review", ""))),
                datetime.now().isoformat()
            ]

            if cell:
                row_idx = cell.row
                self.specs_sheet.update(range_name=f"A{row_idx}:H{row_idx}", values=[row_data])
                print(f"[GoogleSheets] SpecsDB 업데이트 성공: {keyword} (행 {row_idx})")
            else:
                self.specs_sheet.append_row(row_data)
                print(f"[GoogleSheets] SpecsDB 신규 추가 성공: {keyword}")
        except Exception as e:
            print(f"[GoogleSheets] SpecsDB 저장 실패 ({keyword}): {e}")

    def mark_as_published(self, url: str, platform: str, post_url: str):
        if not self.is_available:
            return
        try:
            url_hash = _hash_url(url)
            cell = self.sheet.find(url_hash, in_column=1)
            if cell:
                row_num = cell.row
                self.sheet.update_cell(row_num, 5, "TRUE")
                self.sheet.update_cell(row_num, 8, datetime.now().isoformat())
                if platform.lower() == "tistory":
                    self.sheet.update_cell(row_num, 6, post_url)
                elif platform.lower() == "wordpress":
                    self.sheet.update_cell(row_num, 7, post_url)
        except Exception as e:
            print(f"[GoogleSheets] 발행 상태 업데이트 실패: {e}")


class FirestoreCache:
    """Firebase Firestore 기반 중복 제거 캐시"""
    def __init__(self):
        self.db = None
        self.creds = Config.get_firebase_credentials()
        self.connection_error = None
        self._init_connection()

    def _init_connection(self):
        if not self.creds:
            self.connection_error = "Credentials missing"
            return
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
            try:
                firebase_admin.get_app()
            except ValueError:
                cred = credentials.Certificate(self.creds)
                firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            print("[Firestore] 연동 성공.")
        except Exception as e:
            self.connection_error = str(e)
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
            return doc_ref.get().exists
        except Exception:
            return False

    def mark_as_collected(self, url: str, title: str):
        if not self.is_available:
            return
        try:
            url_hash = _hash_url(url)
            self.db.collection("car_news_cache").document(url_hash).set({
                "url": url,
                "title": title,
                "collected_at": datetime.now().isoformat(),
                "published": False,
                "tistory_url": "",
                "wordpress_url": ""
            })
        except Exception as e:
            print(f"[Firestore] 수집 기록 실패: {e}")

    def mark_as_published(self, url: str, platform: str, post_url: str):
        if not self.is_available:
            return
        try:
            url_hash = _hash_url(url)
            doc_ref = self.db.collection("car_news_cache").document(url_hash)
            update_data = {"published": True, "published_at": datetime.now().isoformat()}
            if platform.lower() == "tistory":
                update_data["tistory_url"] = post_url
            elif platform.lower() == "wordpress":
                update_data["wordpress_url"] = post_url
            doc_ref.update(update_data)
        except Exception as e:
            print(f"[Firestore] 발행 상태 업데이트 실패: {e}")


# --- 글로벌 DB 캐시 및 대시보드 데이터 제어 통합 클래스 ---
class DatabaseCache:
    def __init__(self):
        self.firestore = FirestoreCache()
        self.sheets = GoogleSheetsCache()
        self.drive = GoogleDriveManager(self.firestore)
        self.local = LocalCache()

    # --- 중복 제거 및 수집 상태 관리 (기존 유지) ---
    def is_duplicate(self, url: str) -> bool:
        if self.firestore.is_available:
            return self.firestore.is_duplicate(url)
        if self.sheets.is_available:
            return self.sheets.is_duplicate(url)
        return self.local.is_duplicate(url)

    def mark_as_collected(self, url: str, title: str):
        if self.firestore.is_available:
            self.firestore.mark_as_collected(url, title)
        if self.sheets.is_available:
            self.sheets.mark_as_collected(url, title)
        self.local.mark_as_collected(url, title)

    def mark_as_published(self, url: str, platform: str, post_url: str):
        if self.firestore.is_available:
            self.firestore.mark_as_published(url, platform, post_url)
        if self.sheets.is_available:
            self.sheets.mark_as_published(url, platform, post_url)
        self.local.mark_as_published(url, platform, post_url)

    # --- 1. 실시간 작업 상태(Task Status) 모니터링 기능 추가 ---
    def update_task_status(self, task_id: str, status: str, progress: int, title: str = "", original_url: str = "", platform_results: dict = None):
        """작업의 진행 단계와 완료 결과를 업데이트합니다."""
        task_data = {
            "task_id": task_id,
            "status": status,  # 수집중, AI작성중, 발행대기, 발행완료, 실패
            "progress": progress,  # 0 ~ 100
            "title": title,
            "original_url": original_url,
            "platform_results": platform_results or {},
            "updated_at": datetime.now().isoformat()
        }

        # Firestore 우선 기록 - merge=True 로 항상 upsert (중복 도큐먼트 생성 방지)
        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_tasks").document(task_id).set(task_data, merge=True)
                return
            except Exception as e:
                print(f"[db.py] Firestore Task 업데이트 실패: {e}")

        # 로컬 폴백 - task_id 키 기준 upsert
        tasks = _load_json_file(LOCAL_TASKS_FILE, {})
        if task_id not in tasks:
            tasks[task_id] = {}
        tasks[task_id].update(task_data)
        _save_json_file(LOCAL_TASKS_FILE, tasks)

    def get_active_tasks(self) -> list:
        """대시보드 상태판에 노출할 최근 작업 목록을 조회합니다."""
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_tasks").order_by("updated_at", direction="DESCENDING").limit(20).get()
                return [doc.to_dict() for doc in docs]
            except Exception as e:
                print(f"[db.py] Firestore Tasks 조회 실패: {e}")

        tasks = _load_json_file(LOCAL_TASKS_FILE, {})
        # task_id 기준 중복 제거: 동일 task_id 는 이미 dict 키로 유일하므로 최신 updated_at 순 정렬만
        sorted_tasks = sorted(tasks.values(), key=lambda x: x.get("updated_at", ""), reverse=True)
        return sorted_tasks[:20]

    def cleanup_old_tasks(self, keep_recent: int = 10):
        """로컬 tasks.json 및 Firestore에서 오래된 테스트/완료 작업 레코드를 정리합니다."""
        # 로컬 정리
        tasks = _load_json_file(LOCAL_TASKS_FILE, {})
        if tasks:
            sorted_items = sorted(
                tasks.items(),
                key=lambda x: x[1].get("updated_at", ""),
                reverse=True
            )
            # 최근 N 개만 남기고 나머지 삭제
            tasks = dict(sorted_items[:keep_recent])
            _save_json_file(LOCAL_TASKS_FILE, tasks)
            print(f"[db.py] 로컬 tasks.json 정리 완료: {len(tasks)}개 유지")

        # Firestore 정리 (최근 keep_recent 이후 항목 삭제)
        if self.firestore.is_available:
            try:
                all_docs = self.firestore.db.collection("car_news_tasks").order_by(
                    "updated_at", direction="DESCENDING"
                ).get()
                to_delete = list(all_docs)[keep_recent:]
                for doc in to_delete:
                    doc.reference.delete()
                print(f"[db.py] Firestore 오래된 작업 {len(to_delete)}개 삭제 완료")
            except Exception as e:
                print(f"[db.py] Firestore 정리 실패: {e}")

    # --- 2. 수집 키워드 및 카테고리 관리 기능 추가 ---
    def get_keywords(self) -> list:
        """대시보드 및 봇이 정기 수집용으로 참조할 키워드와 카테고리 목록을 반환합니다."""
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_keywords").get()
                return [doc.to_dict() for doc in docs]
            except Exception as e:
                print(f"[db.py] Firestore Keywords 조회 실패: {e}")

        # 로컬 기본값 폴백
        default_keywords = [
            {"keyword": "Toyota GR86", "category": "뉴스"},
            {"keyword": "IONIQ 5 N", "category": "뉴스"},
            {"keyword": "EV9", "category": "뉴스"}
        ]
        return _load_json_file(LOCAL_KEYWORDS_FILE, default_keywords)

    def add_keyword(self, keyword: str, category: str):
        """수집 키워드를 새로 추가합니다."""
        kw_data = {"keyword": keyword, "category": category, "created_at": datetime.now().isoformat()}
        
        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_keywords").document(keyword).set(kw_data)
                return
            except Exception as e:
                print(f"[db.py] Firestore Keyword 추가 실패: {e}")

        keywords = self.get_keywords()
        # 중복 방지
        if not any(k["keyword"] == keyword for k in keywords):
            keywords.append(kw_data)
            _save_json_file(LOCAL_KEYWORDS_FILE, keywords)

    def delete_keyword(self, keyword: str):
        """수집 키워드를 삭제합니다."""
        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_keywords").document(keyword).delete()
                return
            except Exception as e:
                print(f"[db.py] Firestore Keyword 삭제 실패: {e}")

        keywords = self.get_keywords()
        keywords = [k for k in keywords if k["keyword"] != keyword]
        _save_json_file(LOCAL_KEYWORDS_FILE, keywords)

    # --- 3. 정기 수집 스케줄러 및 도메인 상태 제어 추가 ---
    def get_schedule_settings(self) -> dict:
        """자동 정기 수집 및 도메인 관련 설정 정보를 반환합니다."""
        if self.firestore.is_available:
            try:
                doc = self.firestore.db.collection("car_news_settings").document("schedule").get()
                if doc.exists:
                    res = doc.to_dict()
                    if "run_times" not in res:
                        res["run_times"] = ["08:00"]
                    if "blog_domain" not in res:
                        res["blog_domain"] = "automotive"
                    return res
            except Exception as e:
                print(f"[db.py] Firestore Settings 조회 실패: {e}")

        default_settings = {
            "active": True,
            "interval_hours": 24,
            "run_times": ["08:00"],
            "blog_domain": "automotive",
            "updated_at": datetime.now().isoformat()
        }
        res = _load_json_file(LOCAL_SCHEDULE_FILE, default_settings)
        if "run_times" not in res:
            res["run_times"] = ["08:00"]
        if "blog_domain" not in res:
            res["blog_domain"] = "automotive"
        return res

    def update_schedule_settings(self, active: bool, interval_hours: int, run_times: list = None, blog_domain: str = "automotive"):
        """대시보드에서 스케줄 온/오프, 주기, 상세 예약 시간대 및 블로그 도메인을 저장합니다."""
        if run_times is None:
            run_times = ["08:00"]
        settings_data = {
            "active": active,
            "interval_hours": int(interval_hours),
            "run_times": run_times,
            "blog_domain": blog_domain,
            "updated_at": datetime.now().isoformat()
        }

        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_settings").document("schedule").set(settings_data)
                return
            except Exception as e:
                print(f"[db.py] Firestore Settings 업데이트 실패: {e}")

        _save_json_file(LOCAL_SCHEDULE_FILE, settings_data)

    # --- 4. 유튜브 수집 링크 제어판 데이터 관리 ---
    def get_youtube_urls(self) -> list:
        """대시보드에 등록된 수집 대상 유튜브 URL 목록을 반환합니다."""
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_youtube_urls").get()
                return [doc.to_dict() for doc in docs]
            except Exception as e:
                print(f"[db.py] Firestore YouTube URLs 조회 실패: {e}")
        
        return _load_json_file(LOCAL_YOUTUBE_FILE, [])

    def add_youtube_url(self, url: str, title: str = ""):
        """유튜브 URL을 목록에 추가합니다."""
        import hashlib
        url_hash = hashlib.md5(url.strip().encode("utf-8")).hexdigest()
        yt_data = {
            "url": url,
            "title": title or url,
            "created_at": datetime.now().isoformat()
        }

        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_youtube_urls").document(url_hash).set(yt_data)
                return
            except Exception as e:
                print(f"[db.py] Firestore YouTube URL 추가 실패: {e}")

        urls = self.get_youtube_urls()
        if not any(u["url"] == url for u in urls):
            urls.append(yt_data)
            _save_json_file(LOCAL_YOUTUBE_FILE, urls)

    def delete_youtube_url(self, url: str):
        """특정 유튜브 URL을 목록에서 삭제합니다."""
        import hashlib
        url_hash = hashlib.md5(url.strip().encode("utf-8")).hexdigest()

        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_youtube_urls").document(url_hash).delete()
                return
            except Exception as e:
                print(f"[db.py] Firestore YouTube URL 삭제 실패: {e}")

        urls = self.get_youtube_urls()
        urls = [u for u in urls if u["url"] != url]
        _save_json_file(LOCAL_YOUTUBE_FILE, urls)

    def clear_youtube_urls(self):
        """모든 유튜브 URL 목록을 비웁니다."""
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_youtube_urls").get()
                for doc in docs:
                    doc.reference.delete()
                return
            except Exception as e:
                print(f"[db.py] Firestore YouTube URLs 비우기 실패: {e}")

class GoogleDriveManager:
    """Google Drive API 연동 고화질 이미지 검색 매니저"""
    def __init__(self, firestore_cache=None):
        self.service = None
        self.creds = Config.get_google_sheets_credentials()
        self.connection_error = None
        self.firestore = firestore_cache
        self.oauth_connected = False
        self.oauth_email = None
        self._init_connection()

    def _init_connection(self):
        # 1. Firestore에서 OAuth 리프레시 토큰 로드 시도
        refresh_token = None
        if self.firestore and self.firestore.is_available:
            try:
                doc = self.firestore.db.collection("settings").document("google_oauth").get()
                if doc.exists:
                    data = doc.to_dict()
                    refresh_token = data.get("refresh_token")
                    self.oauth_email = data.get("email")
            except Exception as e:
                print(f"[GoogleDrive] Firestore OAuth 로드 중 에러: {e}")

        # 2. 리프레시 토큰 및 Client ID/Secret이 존재한다면 OAuth2.0 연동 진행 (20TB 등 개인 계정 활용)
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
                self.service = build("drive", "v3", credentials=credentials)
                self.oauth_connected = True
                print(f"[GoogleDrive] OAuth2.0 사용자 계정 연동 성공. (이메일: {self.oauth_email})")
                return
            except Exception as e:
                print(f"[GoogleDrive] OAuth2.0 연동 실패 (서비스 계정으로 폴백 진행): {e}")
                self.connection_error = f"OAuth initialization error: {str(e)}"
                self.oauth_connected = False

        # 3. OAuth가 연동되지 않았거나 오류 발생 시 서비스 계정 크레덴셜로 연결 진행 (폴백)
        if not self.creds:
            self.connection_error = "Credentials missing"
            return
        try:
            from googleapiclient.discovery import build
            from google.oauth2.service_account import Credentials as ServiceAccountCredentials
            scopes = ["https://www.googleapis.com/auth/drive"]
            credentials = ServiceAccountCredentials.from_service_account_info(self.creds, scopes=scopes)
            self.service = build("drive", "v3", credentials=credentials)
            print(f"[GoogleDrive] 서비스 계정 연동 성공. (이메일: {self.creds.get('client_email', '알수없음')})")
        except Exception as e:
            print(f"[GoogleDrive] 연결 실패: {e}")
            self.service = None
            self.connection_error = f"Service account connection error: {str(e)}"

    @property
    def is_available(self) -> bool:
        return self.service is not None

    def get_drive_images(self, keyword: str) -> dict | None:
        """
        Google Drive 내 'Blog_Assets/{keyword}' 및 하위 'images' 폴더를 찾아
        내부 이미지 파일들의 직접 렌더링 URL(lh3.googleusercontent.com/d/ID)을 검색 매핑합니다.
        """
        if not self.is_available:
            return None

        try:
            # 1. 'Blog_Assets' 메인 폴더 ID 찾기
            query = "name = 'Blog_Assets' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            items = results.get('files', [])
            if not items:
                print("[GoogleDrive] 'Blog_Assets' 메인 폴더를 드라이브에서 찾을 수 없습니다.")
                return None
            blog_assets_id = items[0]['id']

            # 2. 'Blog_Assets' 아래에 있는 '{keyword}' 하위 폴더 ID 찾기
            query = f"name = '{keyword}' and '{blog_assets_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            kw_folders = results.get('files', [])
            if not kw_folders:
                print(f"[GoogleDrive] '{keyword}' 폴더를 Blog_Assets 하위에서 찾을 수 없습니다.")
                return None
            folder_id = kw_folders[0]['id']

            # 3. '{keyword}' 폴더 아래의 'images' 하위 폴더 ID 찾기
            query = f"name = 'images' and '{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            img_folders = results.get('files', [])
            
            # 폴더 구조 하위 호환성 유지: 'images' 폴더가 존재하면 사용하고, 없으면 키워드 폴더 자체를 검색 대상으로 지정
            search_target_folder_id = img_folders[0]['id'] if img_folders else folder_id

            # 4. 대상 폴더 내 이미지 파일 목록 리스트업
            query = f"'{search_target_folder_id}' in parents and trashed = false and mimeType startswith 'image/'"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name, webContentLink)').execute()
            files = results.get('files', [])
            if not files:
                print(f"[GoogleDrive] 대상 폴더에 이미지 파일이 없습니다.")
                return None

            # 파일 정렬 및 매핑
            ext_img = None
            int_img = None
            specs_img = None
            driving_img = None

            remaining_files = []
            for f in files:
                name_lower = f['name'].lower()
                fid = f['id']
                direct_url = f"https://lh3.googleusercontent.com/d/{fid}"
                
                if any(x in name_lower for x in ['ext', 'outer']):
                    ext_img = direct_url
                elif any(x in name_lower for x in ['int', 'inner', 'detail']):
                    int_img = direct_url
                elif any(x in name_lower for x in ['spec', 'table', 'data']):
                    specs_img = direct_url
                elif any(x in name_lower for x in ['driv', 'run', 'road', 'benchmark']):
                    driving_img = direct_url
                else:
                    remaining_files.append(direct_url)

            # 매핑 빈 슬롯은 순서대로 채워넣기
            slot_images = [ext_img, int_img, specs_img, driving_img]
            for i in range(4):
                if slot_images[i] is None and remaining_files:
                    slot_images[i] = remaining_files.pop(0)

            # 남는 이미지 마저 다 매핑하기 (Fallback 플레이스홀더 대체용)
            mapped = {
                "ext": slot_images[0] or "https://placehold.co/800x450/eeeeee/333333?text=Drive+Exterior",
                "int": slot_images[1] or "https://placehold.co/800x450/eeeeee/333333?text=Drive+Interior",
                "specs": slot_images[2] or "https://placehold.co/800x450/eeeeee/333333?text=Drive+Specs",
                "driving": slot_images[3] or "https://placehold.co/800x450/eeeeee/333333?text=Drive+Driving"
            }
            print(f"[GoogleDrive] {keyword} 이미지 매핑 성공: {mapped}")
            return mapped

        except Exception as e:
            self.connection_error = str(e)
            print(f"[GoogleDrive] 이미지 조회 중 에러: {e}")
            return None

    def upload_images_to_drive(self, keyword: str, image_urls: list) -> dict | None:
        """
        Google Drive 내 'Blog_Assets' 폴더 하위에 '{keyword}/images' 폴더를 새로 만들고
        수집/검증된 웹 이미지 목록을 다운로드하여 해당 폴더에 자동으로 업로드(캐싱)합니다.
        """
        if not self.is_available or not image_urls:
            return None

        try:
            import requests
            import io
            from googleapiclient.http import MediaIoBaseUpload

            # 1. 'Blog_Assets' 메인 폴더 ID 찾기
            query = "name = 'Blog_Assets' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            items = results.get('files', [])
            if not items:
                self.connection_error = "Blog_Assets main folder not found"
                print("[GoogleDrive] 'Blog_Assets' 메인 폴더가 없어 업로드를 중단합니다.")
                return None
            blog_assets_id = items[0]['id']

            # 2. '{keyword}' 폴더 존재 여부 확인 및 생성
            query = f"name = '{keyword}' and '{blog_assets_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            kw_folders = results.get('files', [])
            if kw_folders:
                folder_id = kw_folders[0]['id']
            else:
                folder_metadata = {
                    'name': keyword,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [blog_assets_id]
                }
                folder = self.service.files().create(body=folder_metadata, fields='id').execute()
                folder_id = folder.get('id')
                print(f"[GoogleDrive] '{keyword}' 폴더 생성 완료 (ID: {folder_id})")

            # 3. '{keyword}/images' 하위 폴더 존재 여부 확인 및 생성
            query = f"name = 'images' and '{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            img_folders = results.get('files', [])
            if img_folders:
                images_folder_id = img_folders[0]['id']
            else:
                images_folder_metadata = {
                    'name': 'images',
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [folder_id]
                }
                img_folder = self.service.files().create(body=images_folder_metadata, fields='id').execute()
                images_folder_id = img_folder.get('id')
                print(f"[GoogleDrive] 'images' 하위 폴더 생성 완료 (ID: {images_folder_id})")

            # 4. 이미지 업로드 루프 (최대 4개)
            uploaded_urls = []
            slot_names = ["1_exterior.jpg", "2_interior.jpg", "3_specs.jpg", "4_driving.jpg"]
            
            for idx, url in enumerate(image_urls[:4]):
                try:
                    # 이미지 다운로드
                    resp = requests.get(url, timeout=10)
                    if resp.status_code != 200:
                        print(f"[GoogleDrive] 이미지 다운로드 실패 ({resp.status_code}): {url}")
                        continue
                    
                    content_type = resp.headers.get('Content-Type', 'image/jpeg')
                    filename = slot_names[idx]
                    
                    file_metadata = {
                        'name': filename,
                        'parents': [images_folder_id]
                    }
                    # resumable=False로 설정하여 소용량 파일 인메모리 업로드 신뢰성 보장
                    media = MediaIoBaseUpload(io.BytesIO(resp.content), mimetype=content_type, resumable=False)
                    uploaded_file = self.service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                    
                    fid = uploaded_file.get('id')
                    direct_url = f"https://lh3.googleusercontent.com/d/{fid}"
                    uploaded_urls.append(direct_url)
                    print(f"[GoogleDrive] 이미지 업로드 성공: {filename} (ID: {fid})")
                except Exception as upload_err:
                    print(f"[GoogleDrive] 개별 이미지 업로드 실패 ({url}): {upload_err}")
                    self.connection_error = f"Individual upload error: {str(upload_err)}"

            if uploaded_urls:
                mapped = {
                    "ext": uploaded_urls[0] if len(uploaded_urls) > 0 else "https://placehold.co/800x450/eeeeee/333333?text=Drive+Exterior",
                    "int": uploaded_urls[1] if len(uploaded_urls) > 1 else "https://placehold.co/800x450/eeeeee/333333?text=Drive+Interior",
                    "specs": uploaded_urls[2] if len(uploaded_urls) > 2 else "https://placehold.co/800x450/eeeeee/333333?text=Drive+Specs",
                    "driving": uploaded_urls[3] if len(uploaded_urls) > 3 else "https://placehold.co/800x450/eeeeee/333333?text=Drive+Driving"
                }
                print(f"[GoogleDrive] {keyword} 업로드 매핑 성공: {mapped}")
                return mapped
            return None
        except Exception as e:
            self.connection_error = f"Upload core error: {str(e)}"
            print(f"[GoogleDrive] 자동 폴더 생성/업로드 중 에러: {e}")
            return None


db_cache = DatabaseCache()

