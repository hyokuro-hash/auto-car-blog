import re

def patch_main():
    with open('main.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Fix run_pipeline_api
    target1 = """            if target == "keywords":
                await run_keyword_pipeline_stage1a_extract(keyword, task_id, blog_domain, base_url, force_collect)
            else:
                await run_multi_youtube_pipeline_stage1_collect(db_cache.get_youtube_urls(), task_id, blog_domain, base_url, force_collect)"""
                
    replacement1 = """            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _fire_and_forget_internal, f"{base_url}/api/worker/run", {
                "target": target, "keyword": keyword, "task_id": task_id, "force_collect": force_collect
            })"""
            
    if target1 in content:
        content = content.replace(target1, replacement1)
        print("Patched run_pipeline_api")
    else:
        print("Failed to patch run_pipeline_api")

    # 2. Fix run_keyword_pipeline_stage1a_extract
    target2 = """            await run_keyword_pipeline_stage1b_scrape(keyword, task_id, blog_domain, base_url, force_collect)"""
    
    # We only want to replace the one inside run_keyword_pipeline_stage1a_extract.
    # Let's find the specific else block in stage1a_extract.
    # It's inside:
    #         if Config.QSTASH_TOKEN and Config.QSTASH_TOKEN != "dummy":
    #             from upstash_qstash import QStash
    #             qstash = QStash(Config.QSTASH_TOKEN)
    #             qstash.message.publish_json(
    #                 url=f"{base_url}/api/worker/stage1_scrape",
    #                 body={"target": "keywords", "keyword": keyword, "task_id": task_id, "force_collect": force_collect}
    #             )
    #         else:
    #             await run_keyword_pipeline_stage1b_scrape(keyword, task_id, blog_domain, base_url, force_collect)
    
    target2_full = """        if Config.QSTASH_TOKEN and Config.QSTASH_TOKEN != "dummy":
            from upstash_qstash import QStash
            qstash = QStash(Config.QSTASH_TOKEN)
            qstash.message.publish_json(
                url=f"{base_url}/api/worker/stage1_scrape",
                body={"target": "keywords", "keyword": keyword, "task_id": task_id, "force_collect": force_collect}
            )
        else:
            await run_keyword_pipeline_stage1b_scrape(keyword, task_id, blog_domain, base_url, force_collect)"""
            
    replacement2_full = """        if Config.QSTASH_TOKEN and Config.QSTASH_TOKEN != "dummy":
            from upstash_qstash import QStash
            qstash = QStash(Config.QSTASH_TOKEN)
            qstash.message.publish_json(
                url=f"{base_url}/api/worker/stage1_scrape",
                body={"target": "keywords", "keyword": keyword, "task_id": task_id, "force_collect": force_collect}
            )
        else:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _fire_and_forget_internal, f"{base_url}/api/worker/stage1_scrape", {
                "target": "keywords", "keyword": keyword, "task_id": task_id, "force_collect": force_collect
            })"""
            
    if target2_full in content:
        content = content.replace(target2_full, replacement2_full)
        print("Patched run_keyword_pipeline_stage1a_extract")
    else:
        print("Failed to patch run_keyword_pipeline_stage1a_extract")

    # 3. Fix generate_post_api
    target3 = """        if Config.QSTASH_TOKEN and Config.QSTASH_TOKEN != "dummy":
            from upstash_qstash import QStash
            qstash = QStash(Config.QSTASH_TOKEN)
            qstash.message.publish_json(
                url=f"{base_url}/api/worker/ai",
                body={"target": "keywords", "task_id": task_id, "selected_images": selected_images, "use_mascot": use_mascot}
            )
        else:
            print("[Warning] QStash Token이 없어 로컬 동기화 처리로 AI 작성을 기동합니다.")
            await run_keyword_pipeline_stage2_ai(task_id, selected_images, use_mascot=use_mascot)"""
            
    replacement3 = """        if Config.QSTASH_TOKEN and Config.QSTASH_TOKEN != "dummy":
            from upstash_qstash import QStash
            qstash = QStash(Config.QSTASH_TOKEN)
            qstash.message.publish_json(
                url=f"{base_url}/api/worker/ai",
                body={"target": "keywords", "task_id": task_id, "selected_images": selected_images, "use_mascot": use_mascot}
            )
        else:
            print("[Warning] QStash Token이 없어 내부 백그라운드 워커로 AI 작성을 기동합니다.")
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _fire_and_forget_internal, f"{base_url}/api/worker/ai", {
                "target": "keywords", "task_id": task_id, "selected_images": selected_images, "use_mascot": use_mascot
            })"""

    if target3 in content:
        content = content.replace(target3, replacement3)
        print("Patched generate_post_api")
    else:
        print("Failed to patch generate_post_api")
        
    with open('main.py', 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == "__main__":
    patch_main()
