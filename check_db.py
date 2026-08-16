import os
from dotenv import load_dotenv
load_dotenv()

from db import db_cache

if not db_cache.firestore.is_available:
    print("Firestore not available")
    exit()

docs = db_cache.firestore.db.collection("car_news_drafts").order_by("task_id", direction="DESCENDING").limit(1).get()
for doc in docs:
    data = doc.to_dict()
    print(f"Draft ID: {doc.id}")
    import json
    # Print only web_images
    print("web_images:", json.dumps(data.get("web_images", "NOT_FOUND"), ensure_ascii=False))
