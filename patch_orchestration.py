import re

def patch_main():
    with open('main.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Modify run_keyword_pipeline_stage1a_extract to accept v_orchestrate
    target1 = "async def run_keyword_pipeline_stage1a_extract(keyword: str, task_id: str, blog_domain: str, base_url: str, force_collect: bool = False):"
    replacement1 = "async def run_keyword_pipeline_stage1a_extract(keyword: str, task_id: str, blog_domain: str, base_url: str, force_collect: bool = False, v_orchestrate: bool = False):"
    content = content.replace(target1, replacement1)

    # 2. Prevent await stage1b if v_orchestrate is True
    target2 = """        if Config.QSTASH_TOKEN and Config.QSTASH_TOKEN != "dummy":
            from upstash_qstash import QStash
            qstash = QStash(Config.QSTASH_TOKEN)
            qstash.message.publish_json(
                url=f"{base_url}/api/worker/stage1_scrape",
                body={"target": "keywords", "keyword": keyword, "task_id": task_id, "force_collect": force_collect}
            )
        else:
            await run_keyword_pipeline_stage1b_scrape(keyword, task_id, blog_domain, base_url, force_collect)"""
            
    replacement2 = """        if Config.QSTASH_TOKEN and Config.QSTASH_TOKEN != "dummy":
            from upstash_qstash import QStash
            qstash = QStash(Config.QSTASH_TOKEN)
            qstash.message.publish_json(
                url=f"{base_url}/api/worker/stage1_scrape",
                body={"target": "keywords", "keyword": keyword, "task_id": task_id, "force_collect": force_collect}
            )
        else:
            if not v_orchestrate:
                await run_keyword_pipeline_stage1b_scrape(keyword, task_id, blog_domain, base_url, force_collect)"""
    content = content.replace(target2, replacement2)

    # 3. Modify run_pipeline_api to return next_stage and pass v_orchestrate
    target3 = """            if target == "keywords":
                await run_keyword_pipeline_stage1a_extract(keyword, task_id, blog_domain, base_url, force_collect)
            else:
                await run_multi_youtube_pipeline_stage1_collect(db_cache.get_youtube_urls(), task_id, blog_domain, base_url, force_collect)
            
        return {"success": True, "task_id": task_id}"""
        
    replacement3 = """            if target == "keywords":
                await run_keyword_pipeline_stage1a_extract(keyword, task_id, blog_domain, base_url, force_collect, v_orchestrate=True)
                return {"success": True, "task_id": task_id, "next_stage": "stage1b_scrape"}
            else:
                await run_multi_youtube_pipeline_stage1_collect(db_cache.get_youtube_urls(), task_id, blog_domain, base_url, force_collect)
                return {"success": True, "task_id": task_id}
                
        return {"success": True, "task_id": task_id}"""
    content = content.replace(target3, replacement3)

    with open('main.py', 'w', encoding='utf-8') as f:
        f.write(content)

def patch_dashboard():
    with open('templates/dashboard.html', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Modify runKeywordPipeline
    target_dashboard = """                  if (data.success) {
                      showToast(`✅ '${keyword}' 파이프라인 완료`, "success");
                  } else {
                      showToast(`❌ 실패: ${data.error}`, "error");
                  }
                  fetchTasks();
              })
              .catch(err => {
                  showToast("⚠️ 파이프라인 가동 통신 실패", "error");
                  fetchTasks();
              });"""
              
    replacement_dashboard = """                  if (data.success) {
                      if (data.next_stage === 'stage1b_scrape') {
                          showToast(`✅ '${keyword}' 1차 수집 완료! 2차 정밀 수집을 백그라운드로 이어서 진행합니다.`, "success");
                          fetchWithTimeout("/api/worker/stage1_scrape", {
                              method: "POST",
                              headers: {"Content-Type": "application/json"},
                              body: JSON.stringify({
                                  target: "keywords",
                                  keyword: keyword,
                                  task_id: data.task_id,
                                  force_collect: !preventDuplicate
                              }),
                              timeout: 120000
                          }).then(r => r.json()).then(d => {
                              fetchTasks();
                          }).catch(e => {
                              showToast("⚠️ 2차 정밀 수집 통신 지연 (백그라운드에서 계속 진행될 수 있습니다)", "error");
                              fetchTasks();
                          });
                      } else {
                          showToast(`✅ '${keyword}' 파이프라인 완료`, "success");
                      }
                  } else {
                      showToast(`❌ 실패: ${data.error}`, "error");
                  }
                  fetchTasks();
              })
              .catch(err => {
                  showToast("⚠️ 파이프라인 가동 통신 실패", "error");
                  fetchTasks();
              });"""
              
    content = content.replace(target_dashboard, replacement_dashboard)
    
    with open('templates/dashboard.html', 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == "__main__":
    patch_main()
    patch_dashboard()
    print("Patched orchestration")
