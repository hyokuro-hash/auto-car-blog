import re

with open('db.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Update get_keywords to use timeout and sync to Redis
old_get_kw = '''    def get_keywords(self) -> list:
        """수집 대상 메인 키워드 목록을 반환합니다."""
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_keywords").get()
                return [doc.to_dict() for doc in docs]
            except Exception as e:
                print(f"[db.py] Firestore Keywords 조회 실패: {e}")'''
new_get_kw = '''    def get_keywords(self) -> list:
        """수집 대상 메인 키워드 목록을 반환합니다."""
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_keywords").get(timeout=3.0)
                kw_list = [doc.to_dict() for doc in docs]
                if self.redis:
                    self.redis.set_data("keywords", kw_list)
                return kw_list
            except Exception as e:
                print(f"[db.py] Firestore Keywords 조회 실패 (Timeout 등): {e}")'''
text = text.replace(old_get_kw, new_get_kw)

# 2. Update add_keyword to always update Redis
old_add_kw = '''        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_keywords").document(keyword).set(kw_data)
                return
            except Exception as e:
                print(f"[db.py] Firestore Keyword 추가 실패: {e}")'''
new_add_kw = '''        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_keywords").document(keyword).set(kw_data, timeout=3.0)
            except Exception as e:
                print(f"[db.py] Firestore Keyword 추가 실패: {e}")'''
text = text.replace(old_add_kw, new_add_kw)

# 3. Update delete_keyword to always update Redis
old_del_kw = '''        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_keywords").document(keyword).delete()
                return
            except Exception as e:
                print(f"[db.py] Firestore Keyword 삭제 실패: {e}")'''
new_del_kw = '''        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_keywords").document(keyword).delete(timeout=3.0)
            except Exception as e:
                print(f"[db.py] Firestore Keyword 삭제 실패: {e}")'''
text = text.replace(old_del_kw, new_del_kw)

# We should do the exact same for get_youtube_urls, add_youtube_url, delete_youtube_url!
old_get_yt = '''    def get_youtube_urls(self) -> list:
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_youtube_urls").get()
                return [doc.to_dict() for doc in docs]
            except Exception as e:
                print(f"[db.py] Firestore YouTube URLs 조회 실패: {e}")'''
new_get_yt = '''    def get_youtube_urls(self) -> list:
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_youtube_urls").get(timeout=3.0)
                yt_list = [doc.to_dict() for doc in docs]
                if self.redis:
                    self.redis.set_data("youtube_urls", yt_list)
                return yt_list
            except Exception as e:
                print(f"[db.py] Firestore YouTube URLs 조회 실패 (Timeout 등): {e}")'''
text = text.replace(old_get_yt, new_get_yt)

old_add_yt = '''        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_youtube_urls").document(doc_id).set(yt_data)
                return
            except Exception as e:
                print(f"[db.py] Firestore YouTube URL 추가 실패: {e}")'''
new_add_yt = '''        if self.firestore.is_available:
            try:
                self.firestore.db.collection("car_news_youtube_urls").document(doc_id).set(yt_data, timeout=3.0)
            except Exception as e:
                print(f"[db.py] Firestore YouTube URL 추가 실패: {e}")'''
text = text.replace(old_add_yt, new_add_yt)

old_del_yt = '''        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_youtube_urls").where("url", "==", url).get()
                for doc in docs:
                    doc.reference.delete()
                return
            except Exception as e:
                print(f"[db.py] Firestore YouTube URL 삭제 실패: {e}")'''
new_del_yt = '''        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_youtube_urls").where("url", "==", url).get(timeout=3.0)
                for doc in docs:
                    doc.reference.delete(timeout=3.0)
            except Exception as e:
                print(f"[db.py] Firestore YouTube URL 삭제 실패: {e}")'''
text = text.replace(old_del_yt, new_del_yt)

with open('db.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Done")
