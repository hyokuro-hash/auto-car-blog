with open('db.py', 'r', encoding='utf-8') as f:
    text = f.read()

old_get_kw = '''    def get_keywords(self) -> list:
        """대시보드 및 봇이 정기 수집용으로 참조할 키워드와 카테고리 목록을 반환합니다."""
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_keywords").get(timeout=3.0)
                kw_list = [doc.to_dict() for doc in docs]
                if self.redis:
                    self.redis.set_data("keywords", kw_list)
                return kw_list
            except Exception as e:
                print(f"[db.py] Firestore Keywords 조회 실패 (Timeout 등): {e}")

        # 기본 폴백
        default_keywords = [
            {"keyword": "Toyota GR86", "category": "신차"},
            {"keyword": "IONIQ 5 N", "category": "시승기"},
            {"keyword": "EV9", "category": "뉴스"}
        ]
        return self.redis.get_data("keywords", default_keywords)'''

new_get_kw = '''    def get_keywords(self) -> list:
        """대시보드 및 봇이 정기 수집용으로 참조할 키워드와 카테고리 목록을 반환합니다."""
        # 1. Redis 캐시 우선 조회 (속도 최적화 & Firestore Hang 방지)
        if self.redis:
            val = self.redis.get_data("keywords", None)
            if val is not None:
                return val

        # 2. 캐시 미스 시 Firestore 조회
        kw_list = []
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_keywords").get(timeout=3.0)
                kw_list = [doc.to_dict() for doc in docs]
                if self.redis:
                    self.redis.set_data("keywords", kw_list)
                return kw_list
            except Exception as e:
                print(f"[db.py] Firestore Keywords 조회 실패 (Timeout 등): {e}")

        # 3. 최후의 보루 (기본값)
        default_keywords = [
            {"keyword": "Toyota GR86", "category": "신차"},
            {"keyword": "IONIQ 5 N", "category": "시승기"},
            {"keyword": "EV9", "category": "뉴스"}
        ]
        return default_keywords'''
text = text.replace(old_get_kw, new_get_kw)

old_get_yt = '''    def get_youtube_urls(self) -> list:
        """대시보드에 등록된 수집 대상 유튜브 URL 목록을 반환합니다."""
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_youtube_urls").get(timeout=3.0)
                yt_list = [doc.to_dict() for doc in docs]
                if self.redis:
                    self.redis.set_data("car_news_youtube_urls", yt_list)
                return yt_list
            except Exception as e:
                print(f"[db.py] Firestore YouTube URLs 조회 실패 (Timeout 등): {e}")
        
        return _load_json_file(LOCAL_YOUTUBE_FILE, [])'''

new_get_yt = '''    def get_youtube_urls(self) -> list:
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
        
        return _load_json_file(LOCAL_YOUTUBE_FILE, [])'''
text = text.replace(old_get_yt, new_get_yt)

with open('db.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Done")
