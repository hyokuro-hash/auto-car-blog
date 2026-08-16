with open('db.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Update get_keywords to use timeout and sync to Redis
old_get_kw = '''    def get_keywords(self) -> list:
        """대시보드 및 봇이 정기 수집용으로 참조할 키워드와 카테고리 목록을 반환합니다."""
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_keywords").get()
                return [doc.to_dict() for doc in docs]
            except Exception as e:'''
new_get_kw = '''    def get_keywords(self) -> list:
        """대시보드 및 봇이 정기 수집용으로 참조할 키워드와 카테고리 목록을 반환합니다."""
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_keywords").get(timeout=3.0)
                kw_list = [doc.to_dict() for doc in docs]
                if self.redis:
                    self.redis.set_data("keywords", kw_list)
                return kw_list
            except Exception as e:'''
text = text.replace(old_get_kw, new_get_kw)

with open('db.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Done")
