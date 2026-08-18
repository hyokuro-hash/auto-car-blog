from typing import Optional, Union
import os
import json
import time
import hashlib
from datetime import datetime, timezone, timedelta
KST = timezone(timedelta(hours=9))
from config import Config
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type


# 로컬 캐시 파일 정의
LOCAL_CACHE_FILE = "cache.json"
LOCAL_TASKS_FILE = "tasks.json"
LOCAL_KEYWORDS_FILE = "keywords.json"
LOCAL_SCHEDULE_FILE = "schedule.json"
LOCAL_YOUTUBE_FILE = "youtube_urls.json"
LOCAL_PROMPT_SETTINGS_FILE = "prompt_settings.json"

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


class UpstashRedisCache:
    """Vercel Serverless 호환 Upstash Redis 기반 캐시"""
    def __init__(self):
        self.url = Config.UPSTASH_REDIS_REST_URL
        self.token = Config.UPSTASH_REDIS_REST_TOKEN
        self.is_available = bool(self.url and self.token)
        if self.is_available:
            try:
                from upstash_redis import Redis
                self.client = Redis(url=self.url, token=self.token)
            except Exception as e:
                print(f"[Upstash] 초기화 오류: {e}")
                self.is_available = False
        else:
            self.client = None

    def get_data(self, key: str, default_val=None):
        if not self.is_available:
            return default_val
        try:
            val = self.client.get(key)
            if val is None:
                return default_val
            if isinstance(val, str):
                import json
                try:
                    return json.loads(val)
                except:
                    return val
            return val
        except Exception as e:
            print(f"[Upstash] {key} 로드 오류: {e}")
            return default_val

    def set_data(self, key: str, data):
        if not self.is_available:
            return
        try:
            import json
            if not isinstance(data, str):
                data = json.dumps(data, ensure_ascii=False)
            self.client.set(key, data)
        except Exception as e:
            print(f"[Upstash] {key} 저장 오류: {e}")

class LocalCache:
    """로컬 파일 대신 Upstash Redis를 사용하여 중복 제거 캐시(cache.json 대체) 관리"""
    def __init__(self):
        self.redis = UpstashRedisCache()

    def is_duplicate(self, url: str) -> bool:
        data = self.redis.get_data("local_cache", {})
        url_hash = _hash_url(url)
        return url_hash in data

    def mark_as_collected(self, url: str, title: str):
        data = self.redis.get_data("local_cache", {})
        url_hash = _hash_url(url)
        if url_hash not in data:
            data[url_hash] = {
                "url": url,
                "title": title,
                "collected_at": datetime.now(KST).isoformat(),
                "published": False,
                "tistory_url": "",
                "wordpress_url": ""
            }
            self.redis.set_data("local_cache", data)

    def delete_collected_history(self, url: str):
        try:
            data = self.redis.get_data("local_cache", {})
            url_hash = _hash_url(url)
            if url_hash in data:
                del data[url_hash]
                self.redis.set_data("local_cache", data)
                print(f"[LocalCache/Redis] 수집 기록에서 URL 해시 {url_hash} 삭제 성공")
        except Exception as e:
            print(f"[LocalCache/Redis] 수집 기록에서 URL {url} 삭제 실패: {e}")

    def mark_as_published(self, url: str, platform: str, post_url: str):
        data = self.redis.get_data("local_cache", {})
        url_hash = _hash_url(url)
        if url_hash in data:
            data[url_hash]["published"] = True
            if platform.lower() == "tistory":
                data[url_hash]["tistory_url"] = post_url
            elif platform.lower() == "wordpress":
                data[url_hash]["wordpress_url"] = post_url
            data[url_hash]["published_at"] = datetime.now(KST).isoformat()
            self.redis.set_data("local_cache", data)

    def get_past_published_titles(self, keyword: str) -> list[str]:
        data = self.redis.get_data("local_cache", {})
        # keyword 단어들이 포함된 제목들을 찾아 최근 순으로 정렬하여 리턴 (최대 15개)
        kw_parts = keyword.lower().split()
        matched_titles = []
        
        # 날짜순 정렬을 위한 리스트화
        items = list(data.values())
        items.sort(key=lambda x: x.get("collected_at", ""), reverse=True)
        
        for item in items:
            # published 여부에 상관없이 수집했던 기사라면 피하도록 함
            title = item.get("title", "")
            title_lower = title.lower()
            if any(part in title_lower for part in kw_parts):
                matched_titles.append(title)
                if len(matched_titles) >= 15:
                    break
        return matched_titles


class GoogleSheetsCache:
    """Google Sheets API 기반 중복 제거 캐시 및 SpecsDB 통합 관리"""
    def __init__(self):
        self.client = None
        self.sheet = None
        self.specs_sheet = None
        self.spreadsheet_id = Config.GOOGLE_SHEETS_SPREADSHEET_ID
        self.creds = Config.get_google_sheets_credentials()
        self.connection_error = None
        self._connected = False
        self._lock = __import__("threading").Lock()

    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
        with self._lock:
            if self._connected or self.connection_error:
                return
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

                self._connected = True
                print("[GoogleSheets] 연동 성공 (SpecsDB 활성화 완료).")
            except Exception as e:
                self.connection_error = str(e)
                print(f"[GoogleSheets] 연결 실패: {e}")
                self.client = None

    @property
    def is_available(self) -> bool:
        self._ensure_connected()
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
            row = [url_hash, url, title, datetime.now(KST).isoformat(), "FALSE", "", "", ""]
            self.sheet.append_row(row)
        except Exception as e:
            print(f"[GoogleSheets] 수집 기록 실패: {e}")

    def delete_collected_history(self, url: str):
        """수집 기록 시트에서 특정 URL의 수집 기록(행)을 삭제합니다."""
        if not self.is_available:
            return
        try:
            url_hash = _hash_url(url)
            cell = self.sheet.find(url_hash, in_column=1)
            if cell:
                row_num = cell.row
                self.sheet.delete_rows(row_num)
                print(f"[GoogleSheets] 수집 기록에서 URL 해시 {url_hash} 삭제 성공 (행 {row_num})")
        except Exception as e:
            print(f"[GoogleSheets] 수집 기록에서 URL {url} 삭제 실패: {e}")

    def get_specs(self, keyword: str) -> Optional[dict]:
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
                datetime.now(KST).isoformat()
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
                self.sheet.update_cell(row_num, 8, datetime.now(KST).isoformat())
                if platform.lower() == "tistory":
                    self.sheet.update_cell(row_num, 6, post_url)
                elif platform.lower() == "wordpress":
                    self.sheet.update_cell(row_num, 7, post_url)
        except Exception as e:
            print(f"[GoogleSheets] 발행 상태 업데이트 실패: {e}")

    def delete_specs(self, keyword: str):
        """SpecsDB 시트에서 키워드에 해당하는 제원 데이터를 찾아 삭제(행 제거)합니다."""
        if not self.is_available or self.specs_sheet is None:
            return
        try:
            cell = self.specs_sheet.find(keyword, in_column=1)
            if cell:
                row_idx = cell.row
                self.specs_sheet.delete_rows(row_idx)
                print(f"[GoogleSheets] SpecsDB 키워드 {keyword} 제원 삭제 성공 (행 {row_idx})")
        except Exception as e:
            print(f"[GoogleSheets] SpecsDB 키워드 {keyword} 제원 삭제 실패: {e}")


class FirestoreCache:
    """Firebase Firestore 기반 중복 제거 캐시"""
    def __init__(self):
        self.db = None
        self.creds = Config.get_firebase_credentials()
        self.connection_error = None
        self._connected = False
        self._lock = __import__("threading").Lock()

    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
        with self._lock:
            if self._connected or self.connection_error:
                return
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
                self._connected = True
                print("[Firestore] 연동 성공.")
            except Exception as e:
                self.connection_error = str(e)
                print(f"[Firestore] 연결 실패: {e}")
                self.db = None

    @property
    def is_available(self) -> bool:
        self._ensure_connected()
        return self.db is not None

    def is_duplicate(self, url: str) -> bool:
        if not self.is_available:
            return False
        try:
            url_hash = _hash_url(url)
            doc_ref = self.db.collection("car_news_cache").document(url_hash)
            return doc_ref.get(timeout=3.0).exists
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
                "collected_at": datetime.now(KST).isoformat(),
                "published": False,
                "tistory_url": "",
                "wordpress_url": ""
            }, timeout=3.0)
        except Exception as e:
            print(f"[Firestore] 수집 기록 실패: {e}")

    def delete_collected_history(self, url: str):
        if not self.is_available:
            return
        try:
            url_hash = _hash_url(url)
            self.db.collection("car_news_cache").document(url_hash).delete(timeout=3.0)
            print(f"[Firestore] 수집 기록에서 URL 해시 {url_hash} 삭제 성공")
        except Exception as e:
            print(f"[Firestore] 수집 기록에서 URL {url} 삭제 실패: {e}")

    def mark_as_published(self, url: str, platform: str, post_url: str):
        if not self.is_available:
            return
        try:
            url_hash = _hash_url(url)
            doc_ref = self.db.collection("car_news_cache").document(url_hash)
            update_data = {"published": True, "published_at": datetime.now(KST).isoformat()}
            if platform.lower() == "tistory":
                update_data["tistory_url"] = post_url
            elif platform.lower() == "wordpress":
                update_data["wordpress_url"] = post_url
            doc_ref.update(update_data, timeout=3.0)
        except Exception as e:
            print(f"[Firestore] 발행 상태 업데이트 실패: {e}")


# --- 글로벌 DB 캐시 및 대시보드 데이터 제어 통합 클래스 ---
class DatabaseCache:
    def __init__(self):
        self.firestore = FirestoreCache()
        self.sheets = GoogleSheetsCache()
        self.drive = GoogleDriveManager(self.firestore)
        self.local = LocalCache()
        self.redis = self.local.redis
        self._tasks_cache = None
        self._tasks_cache_time = 0

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

    def delete_collected_history(self, url: str):
        """수집 기록(중복 방지 캐시)에서 특정 URL을 소거합니다."""
        if self.firestore.is_available:
            self.firestore.delete_collected_history(url)
        if self.sheets.is_available:
            self.sheets.delete_collected_history(url)
        self.local.delete_collected_history(url)
        
    # --- 임시 데이터 저장 (Stage 1 등) ---
    def set_temp_data(self, key: str, data):
        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_temp").document(key).set({"data": data}, merge=True, timeout=3.0)
                return
            except Exception as e:
                print(f"[db.py] Firestore temp_data 저장 에러: {e}")
        
        if self.redis.is_available:
            self.redis.set_data(key, data)
            return
            
        # Local JSON Fallback
        import os
        TEMP_CACHE_FILE = "temp_cache.json"
        local_data = _load_json_file(TEMP_CACHE_FILE, {})
        local_data[key] = data
        _save_json_file(TEMP_CACHE_FILE, local_data)
        
    def get_temp_data(self, key: str, default_val=None):
        if self.firestore.is_available:
            try:
                doc = self.firestore.db.collection("car_news_temp").document(key).get(timeout=3.0)
                if doc.exists:
                    return doc.to_dict().get("data", default_val)
            except Exception as e:
                print(f"[db.py] Firestore temp_data 로드 에러: {e}")
                
        if self.redis.is_available:
            return self.redis.get_data(key, default_val)
            
        # Local JSON Fallback
        TEMP_CACHE_FILE = "temp_cache.json"
        local_data = _load_json_file(TEMP_CACHE_FILE, {})
        return local_data.get(key, default_val)

    # --- 1. 실시간 작업 상태(Task Status) 모니터링 기능 추가 ---
    def update_task_status(self, task_id: str, status: str, progress: int, title: str = "", original_url: str = "", platform_results: dict = None, keyword: str = ""):
        """작업의 진행 단계와 완료 결과를 업데이트합니다."""
        task_data = {
            "task_id": task_id,
            "status": status,  # 수집중, AI작성중, 발행대기, 발행완료, 실패
            "progress": progress,  # 0 ~ 100
            "title": title,
            "original_url": original_url,
            "platform_results": platform_results or {},
            "updated_at": datetime.now(KST).isoformat()
        }
        if keyword:
            task_data["keyword"] = keyword

        # 캐시 무효화 (UI 깜빡임 현상 방지)
        self._tasks_cache = None

        # Firestore 우선 기록 - merge=True 로 항상 upsert (중복 도큐먼트 생성 방지)
        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_tasks").document(task_id).set(task_data, merge=True, timeout=3.0)
                return
            except Exception as e:
                print(f"[db.py] Firestore Task 업데이트 실패: {e}")

        # 로컬 폴백 - task_id 키 기준 upsert
        tasks = self.redis.get_data("tasks", {})
        if task_id not in tasks:
            tasks[task_id] = {}
        tasks[task_id].update(task_data)
        self.redis.set_data("tasks", tasks)

    def get_active_tasks(self) -> list:
        """대시보드 상태판에 노출할 최근 작업 목록을 조회합니다."""
        import time
        now = time.time()
        
        def _clean_zombies(task_list):
            cleaned = []
            for t in task_list:
                status = t.get("status", "")
                if status in ["수집중", "1차 수집중", "키워드 도출중", "2차 수집중", "AI작성중", "발행중"]:
                    updated_at_str = t.get("updated_at")
                    if updated_at_str:
                        try:
                            up_time = datetime.fromisoformat(updated_at_str)
                            if (datetime.now(KST) - up_time).total_seconds() > 330:
                                t["status"] = "실패"
                                t["title"] = "서버 강제 종료됨 (타임아웃)"
                                t["progress"] = 0
                                # 비동기/동기 제약 없이 딕셔너리로 바로 덮어씀. DB도 같이 업데이트
                                self.update_task_status(t["task_id"], "실패", 0, title="서버 강제 종료됨 (타임아웃)", keyword=t.get("keyword", ""))
                        except Exception:
                            pass
                cleaned.append(t)
            return cleaned

        if self.firestore.is_available:
            # Serverless 환경에서 인메모리 캐시가 길면 노드가 다를 때 작업이 사라져보이는 현상 발생
            if self._tasks_cache is not None and now - self._tasks_cache_time < 1.5:
                return self._tasks_cache
                
            try:
                docs = self.firestore.db.collection("car_news_tasks").order_by("updated_at", direction="DESCENDING").limit(20).get(timeout=2.0, retry=None)
                raw_tasks = [doc.to_dict() for doc in docs]
                self._tasks_cache = _clean_zombies(raw_tasks)
                self._tasks_cache_time = now
                return self._tasks_cache
            except Exception as e:
                print(f"[db.py] Firestore get_active_tasks 실패: {e}")
                print(f"[db.py] Firestore Tasks 조회 실패: {e}")

        tasks = {}
        if self.redis and self.redis.is_available:
            tasks = self.redis.get_data("tasks", {})
        
        if not tasks:
            tasks = _load_json_file(LOCAL_TASKS_FILE, {})
            
        # task_id 기준 중복 제거: 동일 task_id 는 이미 dict 키로 유일하므로 최신 updated_at 순 정렬만
        sorted_tasks = sorted(tasks.values(), key=lambda x: x.get("updated_at", ""), reverse=True)[:20]
        return _clean_zombies(sorted_tasks)

    def cleanup_old_tasks(self, keep_recent: int = 10):
        """로컬 tasks.json 및 Firestore에서 오래된 테스트/완료 작업 레코드를 정리합니다."""
        # 로컬 정리
        tasks = self.redis.get_data("tasks", {})
        if tasks:
            sorted_items = sorted(
                tasks.items(),
                key=lambda x: x[1].get("updated_at", ""),
                reverse=True
            )
            # 최근 N 개만 남기고 나머지 삭제
            tasks = dict(sorted_items[:keep_recent])
            self.redis.set_data("tasks", tasks)
            print(f"[db.py] 로컬 tasks.json 정리 완료: {len(tasks)}개 유지")

        # Firestore 정리 (최근 keep_recent 이후 항목 삭제)
        if self.firestore.is_available:
            try:
                all_docs = self.firestore.db.collection("car_news_tasks").order_by(
                    "updated_at", direction="DESCENDING"
                ).get()
                to_delete = list(all_docs)[keep_recent:]
                for doc in to_delete:
                    doc.reference.delete(timeout=3.0)
                print(f"[db.py] Firestore 오래된 작업 {len(to_delete)}개 삭제 완료")
            except Exception as e:
                print(f"[db.py] Firestore 정리 실패: {e}")

    def delete_task(self, task_id: str) -> bool:
        """특정 작업을 삭제하고 연관된 구글 드라이브 내 작업 이미지 폴더 및 구글 시트 수집 기록(URL)을 연쇄 소거합니다."""
        # 1. 삭제 전 작업에 등록된 정보(키워드, 원본기사 URL) 조회
        keyword = ""
        original_url = ""
        if self.firestore.is_available:
            try:
                task_doc = self.firestore.db.collection("car_news_tasks").document(task_id).get(timeout=2.0, retry=None)
                if task_doc.exists:
                    data = task_doc.to_dict()
                    keyword = data.get("keyword", "")
                    original_url = data.get("original_url", "")
            except Exception as e:
                print(f"[db.py] delete_task 전 Firestore에서 정보 조회 실패: {e}")
        
        if not keyword:
            try:
                tasks = self.redis.get_data("tasks", {})
                if task_id in tasks:
                    keyword = tasks[task_id].get("keyword", "")
                    original_url = tasks[task_id].get("original_url", "")
            except Exception as e:
                print(f"[db.py] delete_task 전 로컬에서 정보 조회 실패: {e}")

        # 2. 작업 삭제
        deleted = False
        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_tasks").document(task_id).delete(timeout=3.0)
                deleted = True
            except Exception as e:
                print(f"[db.py] Firestore Task 삭제 실패: {e}")
        try:
            tasks = self.redis.get_data("tasks", {})
            if task_id in tasks:
                del tasks[task_id]
                self.redis.set_data("tasks", tasks)
                deleted = True
        except Exception as e:
            print(f"[db.py] 로컬 Task 삭제 실패: {e}")

        # 3. 작업 관련 구글 생태계 리소스만 조준 소거
        if deleted:
            # (1) 수집 역사 기록(중복 차단 캐시)에서 이 작업의 원본 URL을 삭제하여 재수집이 가능하도록 설정
            if original_url:
                print(f"[db.py] 수집 기록에서 URL 해제 시도: {original_url}")
                self.delete_collected_history(original_url)
                
            # (2) 구글 드라이브 내 이 작업(task_id) 전용 폴더만 안전하게 영구 삭제 (다른 작업 영향 없음)
            if keyword and self.drive.is_available:
                print(f"[db.py] 구글 드라이브에서 '{keyword}' 하위의 작업 에셋 폴더 '{task_id}' 삭제를 시도합니다.")
                self.drive.delete_drive_folder(keyword, task_id)
                
            # 즉각적인 UI 반영을 위해 인메모리 캐시 무효화
            self._tasks_cache = None
            self._tasks_cache_time = 0

        return deleted

    # --- 2. 수집 키워드 및 카테고리 관리 기능 추가 ---
    def get_keywords(self) -> list:
        """대시보드 및 봇이 정기 수집용으로 참조할 키워드와 카테고리 목록을 반환합니다."""
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_keywords").get(timeout=2.0, retry=None)
                kw_list = [doc.to_dict() for doc in docs]
                if self.redis:
                    self.redis.set_data("keywords", kw_list)
                return kw_list
            except Exception as e:
                print(f"[db.py] Firestore Keywords 조회 실패: {e}")

        # 로컬 파일 폴백
        local_kws = _load_json_file(LOCAL_KEYWORDS_FILE, None)
        if local_kws is not None:
            return local_kws

        # 로컬 기본값 폴백
        default_keywords = [
            {"keyword": "Toyota GR86", "category": "뉴스"},
            {"keyword": "IONIQ 5 N", "category": "뉴스"},
            {"keyword": "EV9", "category": "뉴스"}
        ]
        if self.redis and self.redis.is_available:
            return self.redis.get_data("keywords", default_keywords)
        return default_keywords

    def add_keyword(self, keyword: str):
        """수집 키워드를 새로 추가합니다."""
        kw_data = {"keyword": keyword, "created_at": datetime.now(KST).isoformat()}
        
        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_keywords").document(keyword).set(kw_data, timeout=3.0)
            except Exception as e:
                print(f"[db.py] Firestore Keyword 추가 실패: {e}")

        keywords = self.get_keywords()
        # 중복 방지
        if not any(k["keyword"] == keyword for k in keywords):
            keywords.append(kw_data)
            self.redis.set_data("keywords", keywords)

    def delete_keyword(self, keyword: str):
        """수집 키워드를 삭제합니다."""
        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_keywords").document(keyword).delete(timeout=3.0)
            except Exception as e:
                print(f"[db.py] Firestore Keyword 삭제 실패: {e}")

        keywords = self.get_keywords()
        keywords = [k for k in keywords if k["keyword"] != keyword]
        self.redis.set_data("keywords", keywords)

    # --- 3. 정기 수집 스케줄러 및 도메인 상태 제어 추가 ---
    def get_schedule_settings(self) -> dict:
        """자동 정기 수집 및 도메인 관련 설정 정보를 반환합니다."""
        if self.firestore.is_available:
            try:
                doc = self.firestore.db.collection("car_news_settings").document("schedule").get(timeout=2.0, retry=None)
                if doc.exists:
                    res = doc.to_dict()
                    if "run_times" not in res:
                        res["run_times"] = ["08:00"]
                    if "blog_domain" not in res:
                        res["blog_domain"] = "universal"
                    return res
            except Exception as e:
                print(f"[db.py] Firestore Settings 조회 실패: {e}")

        default_settings = {
            "active": True,
            "interval_hours": 24,
            "run_times": ["08:00"],
            "blog_domain": "universal",
            "updated_at": datetime.now(KST).isoformat()
        }
        res = self.redis.get_data("schedule", default_settings)
        if "run_times" not in res:
            res["run_times"] = ["08:00"]
        if "blog_domain" not in res:
            res["blog_domain"] = "universal"
        return res

    def update_schedule_settings(self, active: bool, interval_hours: int, run_times: list = None, blog_domain: str = "universal"):
        """대시보드에서 스케줄 온/오프, 주기, 상세 예약 시간대 및 블로그 도메인을 저장합니다."""
        if run_times is None:
            run_times = ["08:00"]
        settings_data = {
            "active": active,
            "interval_hours": int(interval_hours),
            "run_times": run_times,
            "blog_domain": blog_domain,
            "updated_at": datetime.now(KST).isoformat()
        }

        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_settings").document("schedule").set(settings_data, timeout=3.0)
                return
            except Exception as e:
                print(f"[db.py] Firestore Settings 업데이트 실패: {e}")

        _save_json_file(LOCAL_SCHEDULE_FILE, settings_data)

    def get_prompt_settings(self) -> dict:
        """대시보드에서 설정한 커스텀 프롬프트 설정을 반환합니다."""
        if self.redis:
            val = self.redis.get_data("car_news_prompt_settings", None)
            if val is not None:
                return val

        if self.firestore.is_available:
            try:
                doc = self.firestore.db.collection("car_news_settings").document("prompt_settings").get(timeout=3.0)
                if doc.exists:
                    settings_data = doc.to_dict()
                    if self.redis:
                        self.redis.set_data("car_news_prompt_settings", settings_data)
                    return settings_data
            except Exception as e:
                print(f"[db.py] Firestore Prompt Settings 조회 실패: {e}")
        
        return _load_json_file(LOCAL_PROMPT_SETTINGS_FILE, {})

    def update_prompt_settings(self, settings_data: dict):
        """커스텀 프롬프트 설정을 저장합니다."""
        settings_data["updated_at"] = datetime.now(KST).isoformat()
        
        if self.redis:
            self.redis.set_data("car_news_prompt_settings", settings_data)
            
        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_settings").document("prompt_settings").set(settings_data, timeout=3.0)
                return
            except Exception as e:
                print(f"[db.py] Firestore Prompt Settings 업데이트 실패: {e}")

        _save_json_file(LOCAL_PROMPT_SETTINGS_FILE, settings_data)

    # --- 4. 유튜브 수집 링크 제어판 데이터 관리 ---
    def get_youtube_urls(self) -> list:
        """대시보드에 등록된 수집 대상 유튜브 URL 목록을 반환합니다."""
        if self.redis:
            val = self.redis.get_data("car_news_youtube_urls", None)
            if val is not None:
                return val

        yt_list = []
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_youtube_urls").get(timeout=3.0)
                yt_list = [doc.to_dict() for doc in docs]
                if self.redis:
                    self.redis.set_data("car_news_youtube_urls", yt_list)
                return yt_list
            except Exception as e:
                print(f"[db.py] Firestore YouTube URLs 조회 실패 (Timeout 등): {e}")
        
        return _load_json_file(LOCAL_YOUTUBE_FILE, [])

    def add_youtube_url(self, url: str, title: str = ""):
        """유튜브 URL을 목록에 추가합니다."""
        import hashlib
        url_hash = hashlib.md5(url.strip().encode("utf-8")).hexdigest()
        yt_data = {
            "url": url,
            "title": title or url,
            "created_at": datetime.now(KST).isoformat()
        }

        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_youtube_urls").document(url_hash).set(yt_data, timeout=3.0)
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
                self.firestore.db.collection("car_news_youtube_urls").document(url_hash).delete(timeout=3.0)
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
                docs = self.firestore.db.collection("car_news_youtube_urls").get(timeout=3.0)
                for doc in docs:
                    doc.reference.delete(timeout=3.0)
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
        self._connected = False
        self._lock = __import__("threading").Lock()

    def _ensure_connected(self):
        if self._connected or self.connection_error:
            return
        with self._lock:
            if self._connected or self.connection_error:
                return
            # 1. Firestore에서 OAuth 리프레시 토큰 로드 시도
            refresh_token = None
            if self.firestore and self.firestore.is_available:
                try:
                    doc = self.firestore.db.collection("settings").document("google_oauth").get(timeout=3.0)
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
                    self._connected = True
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
                self._connected = True
                print(f"[GoogleDrive] 서비스 계정 연동 성공. (이메일: {self.creds.get('client_email', '알수없음')})")
            except Exception as e:
                print(f"[GoogleDrive] 연결 실패: {e}")
                self.service = None
                self.connection_error = f"Service account connection error: {str(e)}"

    @property
    def is_available(self) -> bool:
        self._ensure_connected()
        return self.service is not None

    def get_drive_images(self, keyword: str) -> dict | None:
        """
        Google Drive 내 'Blog_Assets/{keyword}' 및 하위 'images' 폴더를 찾아
        내부 이미지 파일들의 직접 렌더링 URL(lh3.googleusercontent.com/d/ID)을 검색 매핑합니다.
        """
        if not self.is_available:
            return None

        try:
            query = "name = 'Blog_Assets' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            items = results.get('files', [])
            if not items:
                return None
            blog_assets_id = items[0]['id']

            query = f"name = '{keyword}' and '{blog_assets_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            kw_folders = results.get('files', [])
            if not kw_folders:
                return None
            folder_id = kw_folders[0]['id']

            query = f"name = 'images' and '{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            img_folders = results.get('files', [])
            
            search_target_folder_id = img_folders[0]['id'] if img_folders else folder_id

            query = f"'{search_target_folder_id}' in parents and trashed = false and mimeType startswith 'image/'"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name, webContentLink)').execute()
            files = results.get('files', [])
            if not files:
                return None

            flat_mapped = {}
            nested_mapped = {"naver": {}, "tistory": {}, "wordpress": {}}
            
            is_nested = False

            for f in files:
                name_lower = f['name'].lower()
                fid = f['id']
                direct_url = f"https://lh3.googleusercontent.com/d/{fid}"
                
                matched_slot = None
                if any(x in name_lower for x in ['ext', 'outer', '외관']):
                    matched_slot = "ext"
                elif any(x in name_lower for x in ['int', 'inner', 'detail', '내장']):
                    matched_slot = "int"
                elif any(x in name_lower for x in ['spec', 'table', 'data', '제원']):
                    matched_slot = "specs"
                elif any(x in name_lower for x in ['driv', 'run', 'road', 'benchmark', '주행']):
                    matched_slot = "driving"
                else:
                    matched_slot = "ext" # fallback
                    
                matched_platform = None
                if "naver" in name_lower:
                    matched_platform = "naver"
                elif "tistory" in name_lower:
                    matched_platform = "tistory"
                elif "wordpress" in name_lower:
                    matched_platform = "wordpress"
                    
                if matched_platform:
                    is_nested = True
                    nested_mapped[matched_platform][matched_slot] = direct_url
                else:
                    flat_mapped[matched_slot] = direct_url
                    
            if is_nested:
                return nested_mapped
            else:
                return {
                    "ext": flat_mapped.get("ext"),
                    "int": flat_mapped.get("int"),
                    "specs": flat_mapped.get("specs"),
                    "driving": flat_mapped.get("driving")
                }

        except Exception as e:
            self.connection_error = str(e)
            print(f"[GoogleDrive] 이미지 조회 중 에러: {e}")
            return None

    @retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(5))
    def upload_images_to_drive(self, keyword: str, image_urls: Union[list, dict], task_id: str = "", domain: str = "universal") -> Optional[dict]:
        """수집된 이미지 URL들을 다운로드 받아 구글 드라이브 지정 폴더에 업로드합니다."""
        if not self.is_available:
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
                folder = self.service.files().create(body={'name': 'Blog_Assets', 'mimeType': 'application/vnd.google-apps.folder'}, fields='id').execute()
                blog_assets_id = folder.get('id')
            else:
                blog_assets_id = items[0]['id']

            # 2. '{keyword}' 폴더 존재 여부 확인 및 생성
            query = f"name = '{keyword}' and '{blog_assets_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            kw_folders = results.get('files', [])
            if kw_folders:
                folder_id = kw_folders[0]['id']
            else:
                folder = self.service.files().create(body={'name': keyword, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [blog_assets_id]}, fields='id').execute()
                folder_id = folder.get('id')
            
            parent_for_images = folder_id
            if task_id:
                query = f"name = '{task_id}' and '{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
                results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
                task_folders = results.get('files', [])
                if task_folders:
                    parent_for_images = task_folders[0]['id']
                else:
                    task_folder_obj = self.service.files().create(body={'name': task_id, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [folder_id]}, fields='id').execute()
                    parent_for_images = task_folder_obj.get('id')

            query = f"name = 'images' and '{parent_for_images}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            img_folders = results.get('files', [])
            if img_folders:
                images_folder_id = img_folders[0]['id']
            else:
                img_folder = self.service.files().create(body={'name': 'images', 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_for_images]}, fields='id').execute()
                images_folder_id = img_folder.get('id')

            # 4. 이미지 업로드 루프
            mapping_items = {}
            is_nested = False
            
            if isinstance(image_urls, list):
                for idx, url in enumerate(image_urls):
                    mapping_items[f"slot_{idx}"] = url
            elif isinstance(image_urls, dict):
                is_nested = any(isinstance(v, dict) for v in image_urls.values())
                mapping_items = image_urls

            uploaded_urls = {}
            slot_names = {"ext": "외관", "int": "내장", "specs": "제원", "driving": "주행"}

            def _upload_single(slot, url, p_name=""):
                if isinstance(url, dict):
                    url = url.get("url")
                if not url or "placehold.co" in url or not str(url).startswith("http"):
                    return None
                
                try:
                    base_filename = slot_names.get(slot, f"{slot}.jpg")
                    filename = f"{p_name}_{base_filename}" if p_name else base_filename
                    
                    check_query = f"name = '{filename}' and '{images_folder_id}' in parents and trashed = false"
                    check_results = self.service.files().list(q=check_query, spaces='drive', fields='files(id)').execute()
                    existing_files = check_results.get('files', [])

                    if existing_files:
                        fid = existing_files[0]['id']
                        return f"https://lh3.googleusercontent.com/d/{fid}"
                    
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                    resp = requests.get(url, headers=headers, timeout=10)
                    if resp.status_code == 200:
                        content_type = resp.headers.get('Content-Type', 'image/jpeg')
                        file_metadata = {'name': filename, 'parents': [images_folder_id]}
                        media = MediaIoBaseUpload(io.BytesIO(resp.content), mimetype=content_type, resumable=False)
                        uploaded_file = self.service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                        fid = uploaded_file.get('id')
                        
                        self.service.permissions().create(
                            fileId=fid,
                            body={'type': 'anyone', 'role': 'reader'},
                            fields='id'
                        ).execute()
                        
                        return f"https://lh3.googleusercontent.com/d/{fid}"
                except Exception as upload_err:
                    print(f"[GoogleDrive] 개별 이미지 업로드 실패 ({url}): {upload_err}")
                return None

            if is_nested:
                for platform_name, platform_slots in mapping_items.items():
                    if not isinstance(platform_slots, dict):
                        continue
                    uploaded_urls[platform_name] = {}
                    for slot, url in platform_slots.items():
                        res_url = _upload_single(slot, url, platform_name)
                        if res_url:
                            uploaded_urls[platform_name][slot] = res_url
                return uploaded_urls
            else:
                for slot in mapping_items.keys():
                    res_url = _upload_single(slot, mapping_items.get(slot))
                    if res_url:
                        uploaded_urls[slot] = res_url
                
                if uploaded_urls:
                    mapped = {
                        "ext": uploaded_urls.get("ext") or mapping_items.get("ext", "https://placehold.co/800x450/eeeeee/333333?text=Drive+Exterior"),
                        "int": uploaded_urls.get("int") or mapping_items.get("int", "https://placehold.co/800x450/eeeeee/333333?text=Drive+Interior"),
                        "specs": uploaded_urls.get("specs") or mapping_items.get("specs", "https://placehold.co/800x450/eeeeee/333333?text=Drive+Specs"),
                        "driving": uploaded_urls.get("driving") or mapping_items.get("driving", "https://placehold.co/800x450/eeeeee/333333?text=Drive+Driving")
                    }
                    return mapped
                return None

        except Exception as e:
            self.connection_error = f"Upload core error: {str(e)}"
            print(f"[GoogleDrive] 자동 폴더 생성/업로드 중 에러: {e}")
            return None


    def delete_drive_folder(self, keyword: str, task_id: str = "") -> bool:
        """구글 드라이브 내 Blog_Assets/keyword 하위의 task_id 폴더(또는 전체 keyword 폴더)를 완전히 삭제합니다."""
        if not self.is_available:
            return False
        try:
            # 1. 'Blog_Assets' 메인 폴더 ID 찾기
            query = "name = 'Blog_Assets' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id)').execute()
            items = results.get('files', [])
            if not items:
                print("[GoogleDrive] 'Blog_Assets' 메인 폴더가 없습니다.")
                return False
            blog_assets_id = items[0]['id']

            # 2. 'Blog_Assets' 하위에 있는 '{keyword}' 폴더 ID 찾기
            query = f"name = '{keyword}' and '{blog_assets_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id)').execute()
            kw_folders = results.get('files', [])
            if not kw_folders:
                print(f"[GoogleDrive] '{keyword}' 폴더를 찾을 수 없습니다.")
                return False
            keyword_folder_id = kw_folders[0]['id']
            
            # 3. 만약 task_id가 제공되었다면 keyword/task_id 폴더만 삭제
            target_id = keyword_folder_id
            target_desc = f"'{keyword}' 전체 폴더"
            
            if task_id:
                query = f"name = '{task_id}' and '{keyword_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
                results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
                task_folders = results.get('files', [])
                if task_folders:
                    target_id = task_folders[0]['id']
                    target_desc = f"'{keyword}' 하위의 작업 폴더 '{task_id}'"
                else:
                    print(f"[GoogleDrive] 작업 폴더 '{task_id}'를 찾을 수 없습니다. 삭제를 중단합니다.")
                    return False
            
            # 4. 폴더 삭제
            self.service.files().delete(fileId=target_id).execute()
            print(f"[GoogleDrive] {target_desc} 삭제 성공 (ID: {target_id})")
            return True
        except Exception as e:
            print(f"[GoogleDrive] 폴더 삭제 실패 (KW: {keyword}, Task: {task_id}): {e}")
            return False


db_cache = DatabaseCache()

