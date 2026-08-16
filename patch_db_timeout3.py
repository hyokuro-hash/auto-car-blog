with open('db.py', 'r', encoding='utf-8') as f:
    text = f.read()

old_get_yt = '''    def get_youtube_urls(self) -> list:
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_youtube_urls").get()
                return [doc.to_dict() for doc in docs]
            except Exception as e:'''
new_get_yt = '''    def get_youtube_urls(self) -> list:
        if self.firestore.is_available:
            try:
                docs = self.firestore.db.collection("car_news_youtube_urls").get(timeout=3.0)
                yt_list = [doc.to_dict() for doc in docs]
                if self.redis:
                    self.redis.set_data("car_news_youtube_urls", yt_list)
                return yt_list
            except Exception as e:'''
text = text.replace(old_get_yt, new_get_yt)

with open('db.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Done")
