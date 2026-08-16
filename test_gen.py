import asyncio
import json
import time
from ai_writer import AIWriter
from collector import CarDataCollector
from telegram_bot import _save_draft

async def main():
    print("Collecting data...")
    collected = await asyncio.to_thread(CarDataCollector.collect_topic_data, "IONIQ 5", 2)
    if not collected:
        print("No data collected.")
        return
        
    raw_data_text = ""
    for idx, item in enumerate(collected):
        raw_data_text += f"### 기사 {idx+1}\n제목: {item['title']}\n출처: {item['source']}\nURL: {item['url']}\n본문:\n{item['content']}\n\n"

    print("Fetching images...")
    web_images = await asyncio.to_thread(CarDataCollector.search_web_images, "IONIQ 5", 4)
    if web_images:
        raw_data_text += "\n[참고용 웹 이미지 목록 - 반드시 본문의 적절한 목차 아래에 아래 URL을 마크다운 문법으로 분산 배치하세요!]\n"
        for idx, img_url in enumerate(web_images.values()):
            raw_data_text += f"이미지{idx+1}: {img_url}\n"

    print("Generating AI draft...")
    writer = AIWriter()
    blog_draft = writer.generate_blog_post(raw_data_text, "IONIQ 5", web_images)
    
    print("\n[Generated Draft Keys]:", blog_draft.keys())
    for plat in ["naver", "tistory", "wordpress"]:
        print(f"\n--- {plat.upper()} ---")
        plat_data = blog_draft.get(plat)
        if plat_data:
            print("Title:", plat_data.get("title"))
            print("HTML Length:", len(plat_data.get("html_content", "")))
            print("MD Length:", len(plat_data.get("markdown_content", "")))
        else:
            print("Missing!")
            
    draft_id = f"test_{int(time.time())}"
    _save_draft(draft_id, {
        "task_id": "task_test",
        "title": blog_draft["title"],
        "naver": blog_draft.get("naver"),
        "tistory": blog_draft.get("tistory"),
        "wordpress": blog_draft.get("wordpress"),
        "original_url": collected[0]["url"]
    })
    print(f"\nDraft saved as {draft_id}.")

if __name__ == "__main__":
    asyncio.run(main())
