import os

# Vercel Serverless (AWS Lambda 기반) 환경에서 파이썬 gRPC(Firestore) 연결이 무한 지연되거나
# Deadline Exceeded(타임아웃)가 발생하는 고질적인 네트워크 이슈를 해결하기 위한 환경변수 설정입니다.
os.environ["GRPC_DNS_RESOLVER"] = "native"
os.environ["GRPC_POLL_STRATEGY"] = "epoll1"

import asyncio
import time
import urllib.parse
from datetime import datetime
import uvicorn
from fastapi import FastAPI, Request, Response, status, BackgroundTasks
from qstash import QStash

from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import Config
from telegram_bot import setup_application, briefing_command
from collector import CarDataCollector
from ai_writer import AIWriter
from publisher import BlogPublisher
from db import db_cache

# 텔레그램 봇 어플리케이션 싱글톤 로드
telegram_app = setup_application()
ai_writer = AIWriter()
scheduler = None

# --- Vercel Serverless 및 Webhook 처리를 위한 FastAPI Lifespan 설정 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[Main] Telegram 봇 초기화 시작...")
    await telegram_app.initialize()
    if Config.RUN_MODE == "local":
        await telegram_app.start()
    print("[Main] Telegram 봇 초기화 완료.")
    yield
    print("[Main] Telegram 봇 종료 중...")
    if Config.RUN_MODE == "local":
        await telegram_app.stop()
    await telegram_app.shutdown()
    print("[Main] Telegram 봇 종료 완료.")

app = FastAPI(title="Auto Car Blog Multi-Platform Agent", lifespan=lifespan)

@app.middleware("http")
async def fix_vercel_path(request: Request, call_next):
    if "__vercel_path" in request.query_params:
        original_path = request.query_params["__vercel_path"]
        request.scope["path"] = f"/{original_path}"
        
        # Remove __vercel_path from query string so it doesn't pollute the app's query parameters
        new_query = []
        for k, v in request.query_params.multi_items():
            if k != "__vercel_path":
                new_query.append(f"{k}={v}")
        request.scope["query_string"] = "&".join(new_query).encode()
        
    return await call_next(request)

# --- 1. 웹 대시보드 뷰 서빙 엔드포인트 ---
@app.get("/debug-headers")
async def debug_headers(request: Request):
    return {
        "headers": dict(request.headers),
        "query_params": dict(request.query_params),
        "scope_path": request.scope.get("path")
    }

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard(response: Response):
    """Vercel Serverless 빌드 호환성을 고려하여 dashboard.html 소스를 직접 읽어 서빙합니다."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0"
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(base_dir, "templates", "dashboard.html")
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read(), headers=response.headers)
    return HTMLResponse(content="<h1>Dashboard Template Not Found</h1><p>templates/dashboard.html 파일을 찾을 수 없습니다.</p>", status_code=404)


# --- 2. 웹 대시보드 API 엔드포인트 ---

# 블로그 계정 관리 API
@app.get("/api/blogs")
def get_blogs_api():
    return db_cache.get_blog_accounts()

@app.post("/api/blogs")
async def add_blog_api(request: Request):
    data = await request.json()
    account_id = db_cache.add_blog_account(data)
    return {"success": True, "id": account_id}

@app.put("/api/blogs/{blog_id}")
async def update_blog_api(blog_id: str, request: Request):
    data = await request.json()
    db_cache.update_blog_account(blog_id, data)
    return {"success": True}

@app.delete("/api/blogs/{blog_id}")
def delete_blog_api(blog_id: str):
    db_cache.delete_blog_account(blog_id)
    return {"success": True}

@app.get("/api/tasks")
def get_tasks_api():
    """모니터링 보드용 작업 상태 리스트 반환"""
    return db_cache.get_active_tasks()

@app.get("/api/tasks/stage1/{task_id}")
def get_stage1_data_api(task_id: str):
    """수집완료된 이미지 후보 및 요약 기사 데이터를 반환 (검수 모달용)"""
    data = db_cache.get_temp_data(f"stage1_{task_id}")
    if not data:
        return Response(status_code=404, content="Stage1 data not found or expired")
    return data

@app.post("/api/tasks/generate-post")
async def generate_post_api(request: Request, data: dict):
    """사용자가 이미지를 수동 선택한 후 AI 본고 작성을 시작하는 API"""
    task_id = data.get("task_id")
    selected_images = data.get("selected_images", {})
    use_mascot = data.get("use_mascot", False)
    
    if not task_id:
        return {"success": False, "error": "task_id가 누락되었습니다."}
        
    db_cache.update_task_status(task_id, "AI작성중", 55, title="AI 작성을 위한 작업 인계 중...")
    
    scheme = request.headers.get("x-forwarded-proto", "http")
    host = request.headers.get("host", "localhost:8000")
    base_url = f"{scheme}://{host}"
    
    try:
        from qstash import QStash
        if Config.QSTASH_TOKEN and Config.QSTASH_TOKEN != "dummy":
            # QStash 비동기 호출
            client = QStash(Config.QSTASH_TOKEN)
            client.message.publish_json(
                url=f"{base_url}/api/worker/ai",
                body={"task_id": task_id, "target": "keywords", "selected_images": selected_images, "use_mascot": use_mascot}
            )
            print(f"[API] QStash를 통해 Stage 2 호출 성공. task_id={task_id}")
        else:
            # 로컬 Fallback (오케스트레이션)
            print(f"[API] 동기화 처리 대신 프론트엔드 오케스트레이션으로 Stage 2 실행 지시. task_id={task_id}")
            return {"success": True, "next_stage": "stage2_ai", "task_id": task_id}
            
        return {"success": True}
    except Exception as e:
        print(f"[API] AI 작성 개시 오류: {e}")
        db_cache.update_task_status(task_id, "실패", 0, title=f"AI 작성 시작 실패: {str(e)[:50]}")
        return {"success": False, "error": str(e)}

@app.get("/api/tasks/draft/{draft_id}")
def get_draft_api(draft_id: str):
    """특정 초안 ID의 세부 본문 조회 (원고 검수 모달용)"""
    from telegram_bot import _get_draft
    draft = _get_draft(draft_id)
    if not draft:
        return Response(status_code=404, content="Draft not found")
    return draft

@app.post("/api/tasks/draft/{draft_id}")
def update_draft_api(draft_id: str, updated_data: dict):
    """사용자가 이미지 주소 등을 수정했을 때 초안 객체를 업데이트하여 저장합니다."""
    from telegram_bot import _save_draft, _get_draft
    existing = _get_draft(draft_id)
    if not existing:
        return {"success": False, "error": "해당 초안을 찾을 수 없습니다."}
        
    existing.update(updated_data)
    _save_draft(draft_id, existing)
    return {"success": True, "draft": existing}

@app.post("/api/draft/edit-ai")
async def edit_draft_sentence_ai_api(data: dict):
    """초안의 특정 문장을 지시어에 맞춰 AI로 부분 수정합니다."""
    draft_id = data.get("draft_id")
    platform = data.get("platform")  # "naver", "tistory", "wordpress"
    target_text = data.get("target_text")
    instruction = data.get("instruction")
    
    if not all([draft_id, platform, target_text, instruction]):
        return {"success": False, "error": "필수 파라미터가 누락되었습니다."}
        
    from telegram_bot import _get_draft, _save_draft
    draft = _get_draft(draft_id)
    if not draft:
        return {"success": False, "error": "해당 초안을 찾을 수 없습니다."}
        
    platform_data = draft.get(platform)
    if not platform_data:
        return {"success": False, "error": f"초안 내에 {platform} 플랫폼 데이터가 존재하지 않습니다."}
        
    html_content = platform_data.get("html_content", "")
    markdown_content = platform_data.get("markdown_content", "")
    
    context = html_content if len(html_content) > len(markdown_content) else markdown_content
    
    schedule_settings = db_cache.get_schedule_settings()
    blog_domain = schedule_settings.get("blog_domain", "universal")
    
    writer = AIWriter()
    loop = asyncio.get_event_loop()
    
    edited_text = await loop.run_in_executor(
        None, 
        writer.edit_sentence_ai, 
        context, 
        target_text, 
        instruction, 
        blog_domain
    )
    
    if not edited_text or edited_text == target_text:
        return {"success": False, "error": "AI 문장 수정에 실패했거나 수정 결과가 기존과 동일합니다."}
        
    if target_text in html_content:
        platform_data["html_content"] = html_content.replace(target_text, edited_text)
    else:
        platform_data["html_content"] = html_content.replace(target_text.strip(), edited_text)
        
    if target_text in markdown_content:
        platform_data["markdown_content"] = markdown_content.replace(target_text, edited_text)
    else:
        platform_data["markdown_content"] = markdown_content.replace(target_text.strip(), edited_text)
        
    draft[platform] = platform_data
    _save_draft(draft_id, draft)
    
    return {
        "success": True, 
        "edited_text": edited_text,
        "draft": draft
    }

@app.get("/api/keywords")
def get_keywords_api():
    """수집 키워드 조회"""
    return db_cache.get_keywords()

@app.post("/api/keywords")
def add_keyword_api(data: dict):
    """수집 키워드 추가"""
    keyword = data.get("keyword")
    if keyword:
        db_cache.add_keyword(keyword)
        return {"success": True}
    return {"success": False, "error": "Missing keyword"}

@app.delete("/api/keywords")
def delete_keyword_api(keyword: str):
    """수집 키워드 삭제"""
    db_cache.delete_keyword(keyword)
    return {"success": True}

@app.get("/api/schedule")
def get_schedule_api():
    """스케줄 및 도메인 설정 상태 조회"""
    return db_cache.get_schedule_settings()

@app.post("/api/schedule")
def update_schedule_api(data: dict):
    """스케줄 및 도메인 설정 저장"""
    active = data.get("active", True)
    interval_hours = data.get("interval_hours", 24)
    run_times = data.get("run_times", ["08:00"])
    blog_domain = data.get("blog_domain", "universal")
    
    db_cache.update_schedule_settings(active, interval_hours, run_times, blog_domain)
    
    # 로컬 구동 모드인 경우 스케줄러 동적 리로드
    if Config.RUN_MODE == "local":
        reload_scheduler_jobs()
        
    print(f"[Scheduler] 스케줄 및 도메인 설정 업데이트: 활성화={active}, 도메인={blog_domain}, 시간대={run_times}")
    return {"success": True}

@app.get("/api/settings/prompt")
def get_prompt_settings_api():
    """커스텀 프롬프트 설정 조회"""
    return db_cache.get_prompt_settings()

@app.post("/api/settings/prompt")
def update_prompt_settings_api(data: dict):
    """커스텀 프롬프트 설정 저장"""
    db_cache.update_prompt_settings(data)
    return {"success": True}

@app.get("/api/youtube-urls")
def get_youtube_urls_api():
    """등록된 수집 대상 유튜브 URL 목록 반환"""
    return db_cache.get_youtube_urls()

@app.post("/api/youtube-urls")
def add_youtube_url_api(data: dict):
    """유튜브 URL 등록 (oEmbed 연동하여 제목 실시간 획득)"""
    url = data.get("url")
    if not url:
        return {"success": False, "error": "URL이 누락되었습니다."}
        
    from collector import extract_youtube_video_id
    video_id = extract_youtube_video_id(url)
    if not video_id:
        return {"success": False, "error": "유효하지 않은 유튜브 영상 URL입니다."}
        
    title = ""
    try:
        import urllib.parse
        import requests
        oembed_url = f"https://www.youtube.com/oembed?url={urllib.parse.quote(url)}&format=json"
        res = requests.get(oembed_url, timeout=5)
        if res.status_code == 200:
            title = res.json().get("title", "")
    except Exception as e:
        print(f"[API] 유튜브 제목 추출 실패: {e}")
        
    db_cache.add_youtube_url(url, title)
    return {"success": True}

@app.delete("/api/youtube-urls")
def delete_youtube_url_api(url: str):
    """등록된 유튜브 URL 삭제"""
    db_cache.delete_youtube_url(url)
    return {"success": True}

@app.post("/api/youtube/analyze")
async def analyze_youtube_api(data: dict):
    """유튜브 동영상 단독 분석 (자막 분석 ➔ 핵심 키워드/영상 요약 추출)"""
    url = data.get("url")
    if not url:
        return {"success": False, "error": "URL이 누락되었습니다."}
        
    loop = asyncio.get_event_loop()
    # 자막 및 제목 수집
    yt_data = await loop.run_in_executor(None, CarDataCollector.get_youtube_data, url)
    if not yt_data.get("title"):
        return {"success": False, "error": "유튜브 정보를 불러올 수 없습니다."}
        
    writer = AIWriter()
    analysis = await loop.run_in_executor(None, writer.analyze_youtube_video, yt_data)
    
    return {
        "success": True,
        "title": yt_data.get("title"),
        "keyword": analysis.get("keyword", "EV"),
        "summary": analysis.get("summary", "")
    }

@app.get("/api/trend-keywords")
async def get_trend_keywords_api(domain: str = "universal"):
    """Gemini를 이용해 도메인별 실시간 트렌드 키워드 5개 추천 발굴"""
    loop = asyncio.get_event_loop()
    writer = AIWriter()
    keywords = await loop.run_in_executor(None, writer.suggest_trend_keywords, domain)
    return {"success": True, "keywords": keywords}

@app.post("/api/publish")
def publish_api(data: dict):
    """웹 대시보드 검수 후 수동 발행 액션 트리거"""
    draft_id = data.get("draft_id")
    platform = data.get("platform")  # 'tistory' 또는 'wordpress'
    
    from telegram_bot import _get_draft
    draft = _get_draft(draft_id)
    if not draft:
        return {"success": False, "error": "해당 초안 세션이 만료되었거나 찾을 수 없습니다."}
        
    task_id = draft.get("task_id")
    
    if platform == "tistory":
        platform_data = draft.get("tistory", {})
        res = BlogPublisher.publish_to_tistory(platform_data.get("title", ""), platform_data.get("html_content", ""))
    elif platform == "wordpress":
        platform_data = draft.get("wordpress", {})
        res = BlogPublisher.publish_to_wordpress(platform_data.get("title", ""), platform_data.get("html_content", ""))
    else:
        return {"success": False, "error": "알 수 없는 발행 플랫폼 유형입니다."}
        
    if res.get("success"):
        post_url = res["url"]
        db_cache.mark_as_published(draft["original_url"], platform, post_url)
        
        if task_id:
            current_tasks = db_cache.get_active_tasks()
            task = next((t for t in current_tasks if t["task_id"] == task_id), None)
            platform_results = task.get("platform_results", {}) if task else {}
            platform_results[platform] = post_url
            platform_results["draft_id"] = draft_id
            
            db_cache.update_task_status(
                task_id, 
                "발행완료", 
                100, 
                title=draft["title"], 
                original_url=draft["original_url"], 
                platform_results=platform_results
            )
        return {"success": True, "url": post_url}
    else:
        return {"success": False, "error": res.get("error", "API Call Failed")}

@app.post("/api/tasks/cleanup")
def cleanup_tasks_api():
    """대시보드 작업 카드 누적 정리: 최근 10개만 남기고 오래된 항목을 삭제합니다."""
    try:
        db_cache.cleanup_old_tasks(keep_recent=10)
        return {"success": True, "message": "오래된 작업 기록이 정리되었습니다. (최근 10개 유지)"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.delete("/api/tasks/{task_id}")
def delete_task_api(task_id: str):
    """특정 작업 ID 삭제"""
    try:
        success = db_cache.delete_task(task_id)
        if success:
            return {"success": True, "message": "작업이 성공적으로 삭제되었습니다."}
        return {"success": False, "error": "작업 삭제에 실패했거나 작업 ID를 찾을 수 없습니다."}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/cache/clear")
def clear_all_cache_api():
    """Firestore 및 로컬의 모든 수집 기록(중복 방지 캐시)을 완전히 초기화합니다."""
    try:
        count = 0
        if db_cache.firestore.is_available:
            db = db_cache.firestore.db
            docs = db.collection("car_news_cache").get()
            for doc in docs:
                doc.reference.delete()
                count += 1
        
        # 로컬 캐시 초기화
        import os
        LOCAL_CACHE_FILE = "local_cache.json"
        if os.path.exists(LOCAL_CACHE_FILE):
            try:
                os.remove(LOCAL_CACHE_FILE)
            except Exception:
                pass
            
        return {
            "success": True, 
            "message": f"성공적으로 모든 중복 방지 캐시가 초기화되었습니다. (삭제된 파이어베이스 문서: {count}개)"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/tasks/refresh-image")
async def refresh_image_slot(request: Request):
    """특정 슬롯의 이미지를 새롭게 검색하여 갱신합니다."""
    try:
        data = await request.json()
        task_id = data.get("task_id")
        slot = data.get("slot")
        preserved_dict = data.get("preserved_dict", {})
        
        if not task_id or not slot:
            return {"success": False, "error": "task_id and slot are required"}
            
        stage1_data = db_cache.get_temp_data(f"stage1_{task_id}")
        if not stage1_data:
            return {"success": False, "error": "Task data not found"}
            
        keyword = stage1_data.get("keyword", "")
        blog_domain = stage1_data.get("blog_domain", "universal")
        
        from prompts import IMAGE_DOMAIN_CONFIGS
        queries = IMAGE_DOMAIN_CONFIGS.get(blog_domain, IMAGE_DOMAIN_CONFIGS["universal"])["queries"]
        query_str = queries.get(slot, f"{keyword} {slot}").replace("{keyword}", keyword)
        
        # 새로운 이미지 가져오기
        new_urls = CarDataCollector.refresh_single_image_slot(keyword, query_str)
        
        if new_urls or preserved_dict:
            final_urls_array = [None] * 8
            seen = set()
            
            # 1. 보존된 이미지를 원래 인덱스(위치)에 배치
            for str_idx, item in preserved_dict.items():
                try:
                    idx = int(str_idx)
                    if 0 <= idx < 8:
                        final_urls_array[idx] = item
                        url_str = item if isinstance(item, str) else item.get("url")
                        seen.add(url_str)
                except ValueError:
                    pass
                
            # 2. 빈 자리를 새로 수집된 이미지로 채움
            new_idx = 0
            for i in range(8):
                if final_urls_array[i] is None:
                    # new_urls에서 아직 추가되지 않은 이미지 찾기
                    while new_idx < len(new_urls) if new_urls else False:
                        new_item = new_urls[new_idx]
                        new_idx += 1
                        url_str = new_item if isinstance(new_item, str) else new_item.get("url")
                        if url_str not in seen:
                            final_urls_array[i] = new_item
                            seen.add(url_str)
                            break
                            
            # None인 슬롯(새 이미지가 부족한 경우) 제거
            final_urls = [item for item in final_urls_array if item is not None]
                        
            stage1_data["web_images_candidates"][slot] = final_urls
            db_cache.set_temp_data(f"stage1_{task_id}", stage1_data)
            return {"success": True, "urls": final_urls}
        else:
            return {"success": False, "error": "새 이미지를 찾지 못했습니다"}
            
    except Exception as e:
        return {"success": False, "error": str(e)}



@app.post("/api/insta/publish")
async def publish_insta(request: Request, data: dict):
    from config import Config
    import base64
    import io
    
    images = data.get("images", [])
    if not images:
        return {"success": False, "error": "이미지가 없습니다."}
        
    try:
        from db import db_cache
        caption = data.get("caption", "")
        hashtags = data.get("hashtags", "")
        story_link = data.get("story_link", "")
        script_data = data.get("script_data", {})
        
        db_cache.save_insta_post({
            "caption": caption,
            "hashtags": hashtags,
            "story_link": story_link,
            "script": script_data,
            "image_count": len(images)
        })
        
        if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
            return {"success": False, "error": "텔레그램 설정이 필요합니다. DB에는 저장되었습니다."}
            
        from telegram import InputMediaPhoto, Bot
        bot = Bot(token=Config.TELEGRAM_BOT_TOKEN)
        
        media_group = []
        for i, img in enumerate(images):
            b64_str = img.get("data", "")
            if "," in b64_str:
                b64_str = b64_str.split(",")[1]
            try:
                img_bytes = base64.b64decode(b64_str)
                # 첫 번째 이미지에 캡션 추가
                if i == 0:
                    media_caption = f"{caption}\n\n{hashtags}\n\n[원본 영상 링크]\n{story_link}" 
                    # Telegram caption max length is 1024, truncate if needed
                    if len(media_caption) > 1000:
                        media_caption = media_caption[:1000] + "..."
                    media_group.append(InputMediaPhoto(media=img_bytes, caption=media_caption))
                else:
                    media_group.append(InputMediaPhoto(media=img_bytes))
            except Exception as e:
                print("Base64 decode error:", e)
                
        if media_group:
            # 텔레그램 앨범은 한 번에 최대 10장까지만 전송 가능하므로 10장씩 쪼개서 전송
            chunk_size = 10
            for i in range(0, len(media_group), chunk_size):
                chunk = media_group[i:i + chunk_size]
                await bot.send_media_group(chat_id=Config.TELEGRAM_CHAT_ID, media=chunk)
            
            return {"success": True}
        else:
            return {"success": False, "error": "유효한 이미지가 없습니다."}
            
    except Exception as e:
        print(f"Telegram send error: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/insta/analyze")
async def analyze_for_insta(request: Request, data: dict):
    from ai_writer import AIWriter
    from collector import CarDataCollector
    import urllib.parse
    
    url = data.get("url")
    if not url:
        return {"success": False, "error": "URL이 필요합니다."}
        
    try:
        # 1. 유튜브 데이터 추출
        is_youtube = "youtube.com" in url or "youtu.be" in url
        if is_youtube:
            yt_data = CarDataCollector.get_youtube_data(url)
            text_to_analyze = f"제목: {yt_data.get('title', '')}\n설명: {yt_data.get('description', '')}\n자막: {yt_data.get('transcript', '')}"
            video_id = ""
            if "v=" in url:
                video_id = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("v", [""])[0]
            elif "youtu.be/" in url:
                video_id = url.split("youtu.be/")[1].split("?")[0]
            thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg" if video_id else ""
        else:
            return {"success": False, "error": "현재 유튜브 URL만 지원합니다."}
            
        # 2. AI 대본 기획
        writer = AIWriter()
        insta_script = writer.generate_insta_script(text_to_analyze)
        
        # 3. 이미지 수집 (썸네일 + 웹 검색 이미지)
        images = []
        if thumbnail_url:
            images.append({"url": thumbnail_url, "source": "youtube"})
            
        kw = insta_script.get("search_keyword", "car")
        
        # 빙 이미지 검색 (간단히 10장)
        try:
            import requests
            from bs4 import BeautifulSoup
            import json
            bing_url = f"https://www.bing.com/images/search?q={urllib.parse.quote(kw)}&form=HDRSC2"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            res = requests.get(bing_url, headers=headers, timeout=5)
            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.select("a.iusc"):
                m_data = json.loads(a.get("m", "{}"))
                img_url = m_data.get("murl")
                if img_url and img_url.startswith("http") and "map" not in img_url:
                    images.append({"url": img_url, "source": "web"})
                if len(images) >= 30:
                    break
        except Exception as e:
            print(f"Bing search error: {e}")
            
        return {
            "success": True,
            "script": insta_script,
            "images": images
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/proxy-image")
async def proxy_image(url: str):
    import httpx
    from fastapi import Response
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url, headers=headers)
        return Response(
            content=res.content, 
            media_type=res.headers.get("Content-Type", "image/jpeg"), 
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=86400"
            }
        )
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/insta/search-images")
async def search_insta_images(request: Request, data: dict):
    keyword = data.get("keyword", "")
    page = data.get("page", 1)
    if not keyword:
        return {"success": False, "error": "키워드가 필요합니다."}
        
    images = []
    try:
        import requests
        from bs4 import BeautifulSoup
        import json
        import urllib.parse
        
        first_param = (page - 1) * 20 + 1
        bing_url = f"https://www.bing.com/images/search?q={urllib.parse.quote(keyword)}&first={first_param}&form=HDRSC2"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        res = requests.get(bing_url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        for a in soup.select("a.iusc"):
            m_data = json.loads(a.get("m", "{}"))
            img_url = m_data.get("murl")
            if img_url and img_url.startswith("http") and "map" not in img_url:
                images.append({"url": img_url, "source": "web"})
            if len(images) >= 30:
                break
        return {"success": True, "images": images}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/run-pipeline")
async def run_pipeline_api(request: Request, data: dict):
    """Vercel 호환 QStash 3-Way Split 퍼블리셔"""
    target = data.get("target")
    keyword = data.get("keyword")
    prevent_duplicate = data.get("prevent_duplicate", False)
    force_collect = not prevent_duplicate
    
    if target == "keywords" and not keyword:
        keywords = db_cache.get_keywords()
        if not keywords:
            return {"success": False, "error": "등록된 수집 키워드가 없습니다."}
        keyword = keywords[0]["keyword"]
        
    import uuid
    task_id = f"task_{target}_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
    db_cache.update_task_status(task_id, "예약됨", 5, title=f"QStash 다중 발행 예약 중", keyword=keyword or "유튜브 분석")
    
    scheme = request.headers.get('x-forwarded-proto', 'https')
    host = request.headers.get('host', 'localhost:8000')
    base_url = f"{scheme}://{host}"
    
    # QStash Publish (단일 통합 파이프라인 워커)
    try:
        if Config.QSTASH_TOKEN and Config.QSTASH_TOKEN != "dummy":
            qstash = QStash(Config.QSTASH_TOKEN)
            # 한 번의 호출로 통합 파이프라인 실행
            qstash.message.publish_json(
                url=f"{base_url}/api/worker/run",
                body={"target": target, "keyword": keyword, "task_id": task_id, "force_collect": force_collect}
            )
            db_cache.update_task_status(task_id, "수집중", 10, title="통합 파이프라인 워커 발송 완료", keyword=keyword)
        else:
            # 로컬 Fallback (QStash 없을 시)
            print("[Warning] QStash Token이 없어 로컬 동기화 처리(await)로 1단계 수집을 기동합니다.")
            schedule_settings = db_cache.get_schedule_settings()
            blog_domain = schedule_settings.get("blog_domain", "universal")
            db_cache.update_task_status(task_id, "수집중", 10, title="로컬 수집 파이프라인 기동 완료", keyword=keyword)
            if target == "keywords":
                await run_keyword_pipeline_stage1a_extract(keyword, task_id, blog_domain, base_url, force_collect, v_orchestrate=True)
                return {"success": True, "task_id": task_id, "next_stage": "stage1b_scrape"}
            else:
                await run_multi_youtube_pipeline_stage1_collect(db_cache.get_youtube_urls(), task_id, blog_domain, base_url, force_collect)
                return {"success": True, "task_id": task_id}
                
        return {"success": True, "task_id": task_id}
    except Exception as e:
        return {"success": False, "error": str(e)}




# --- 3. 비동기 백그라운드 파이프라인 워커 로직 ---

async def run_multi_youtube_pipeline(urls: list, task_id: str, blog_domain: str, force_collect: bool = False):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram_bot import _save_draft
    
    try:
        loop = asyncio.get_running_loop()
        
        # 1. 유튜브 자막/정보 추출
        db_cache.update_task_status(task_id, "수집중", 20, title=f"유튜브 영상 {len(urls)}개 정보 수집 중", keyword="유튜브 통합 분석")
        
        youtube_contents = []
        source_links = []
        
        fetch_tasks = []
        for url_item in urls:
            url = url_item["url"]
            fetch_tasks.append(loop.run_in_executor(None, CarDataCollector.get_youtube_data, url))
            
        if fetch_tasks:
            results = await asyncio.gather(*fetch_tasks)
            for url_item, yt_data in zip(urls, results):
                url = url_item["url"]
                if yt_data.get("title"):
                    youtube_contents.append(yt_data)
                    source_links.append({
                        "title": yt_data["title"],
                        "url": url,
                        "source": "YouTube",
                        "published": "",
                        "type": "youtube"
                    })
                
        if not youtube_contents:
            db_cache.update_task_status(task_id, "실패", 0, title="유튜브 정보 수집 실패", keyword="유튜브 통합 분석")
            return
            
        # 2. AI를 통한 유튜브 영상들 통합 분석 및 핵심 키워드/요약 추출
        db_cache.update_task_status(task_id, "AI작성중", 40, title="유튜브 영상 통합 분석 및 핵심 주제 도출 중", keyword="유튜브 통합 분석")
        
        combined_title = " / ".join([x["title"] for x in youtube_contents])
        combined_desc = "\n".join([f"영상: {x['title']}\n설명: {x['description']}" for x in youtube_contents])
        combined_transcript = "\n".join([f"영상: {x['title']}\n자막:\n{x['transcript'][:4000]}" for x in youtube_contents])
        
        combined_youtube_data = {
            "title": combined_title,
            "description": combined_desc,
            "transcript": combined_transcript
        }
        
        def _sync_status_callback(msg: str):
            db_cache.update_task_status(task_id, "AI작성중", 40, title=msg, keyword="유튜브 통합 분석" if "keyword" not in locals() else keyword)
            
        task_ai_writer = AIWriter(status_callback=_sync_status_callback)
        analysis_result = await loop.run_in_executor(
            None, 
            task_ai_writer.analyze_youtube_video, 
            combined_youtube_data, 
            _sync_status_callback
        )
        
        keyword = analysis_result.get("keyword", "EV")
        summary = analysis_result.get("summary", "")
        
        # 3. 추출된 키워드로 추가 다국가 뉴스 수집 (KR, JP, US)
        db_cache.update_task_status(task_id, "수집중", 60, title=f"'{keyword}' 관련 해외 뉴스 수집 중", keyword=keyword)
        
        def _sync_stage1_status(status_str: str, progress: int, title_str: str):
            db_cache.update_task_status(task_id, status_str, progress, title=title_str, keyword=keyword)
            
        collected_items_task = loop.run_in_executor(None, CarDataCollector.collect_topic_data, keyword, 3, force_collect, blog_domain, _sync_stage1_status)
        web_images_task = loop.run_in_executor(None, CarDataCollector.search_web_images, keyword, blog_domain)
        
        try:
            collected_items, web_images = await asyncio.wait_for(
                asyncio.gather(collected_items_task, web_images_task),
                timeout=55.0
            )
        except asyncio.TimeoutError:
            print("[Worker] 유튜브 파이프라인 수집 단계 시간 초과")
            db_cache.update_task_status(task_id, "실패", 0, title="수집 시간 초과 (검색 엔진 지연)", keyword=keyword)
            return
        
        # 4. 수집 데이터 취합
        raw_data_text = f"### 유튜브 원본 통합 분석 및 요약\n- 대상 영상: {len(urls)}개\n- 핵심 요약:\n{summary}\n\n"
        
        for idx, item in enumerate(collected_items):
            if not force_collect and db_cache.is_duplicate(item["url"]):
                continue
            raw_data_text += f"### 기사 {idx+1}\n제목: {item['title']}\n출처: {item['source']}\nURL: {item['url']}\n본문:\n{item['content']}\n\n"
            source_links.append(item)
            
        # 5. 이미지 취합
        if web_images:
            raw_data_text += "\n[참고용 웹 이미지 목록 - 반드시 본문의 적절한 목차 아래에 아래 URL을 마크다운 문법으로 분산 배치하세요!]\n"
            for slot, img_url in web_images.items():
                if img_url:
                    raw_data_text += f"{slot.upper()} 이미지: {img_url}\n"
                
        # 6. 블로그 원고 작성
        db_cache.update_task_status(task_id, "AI작성중", 80, title="블로그 분석 원고 최종 작성 중", keyword=keyword)
        blog_draft = await loop.run_in_executor(
            None, 
            task_ai_writer.generate_blog_post, 
            raw_data_text, 
            keyword, 
            web_images, 
            blog_domain,
            task_id
        )
        
        # 7. 텔레그램 요약본 작성
        tg_summary = await loop.run_in_executor(
            None,
            task_ai_writer.generate_telegram_summary,
            blog_draft["title"],
            blog_draft.get("naver", {}).get("markdown_content", ""),
            blog_domain
        )
        
        # 8. 수집 기록 마크
        for src in source_links:
            db_cache.mark_as_collected(src["url"], src["title"])
            
        # 9. 초안 저장 및 상태 업데이트
        draft_id = f"draft_{int(time.time())}"
        _save_draft(draft_id, {
            "task_id": task_id,
            "title": blog_draft["title"],
            "naver": blog_draft.get("naver"),
            "tistory": blog_draft.get("tistory"),
            "wordpress": blog_draft.get("wordpress"),
            "original_url": urls[0]["url"],
            "web_images": blog_draft.get("used_images", web_images)
        })
        
        db_cache.update_task_status(
            task_id, 
            "발행대기", 
            90, 
            title=blog_draft["title"], 
            original_url=urls[0]["url"],
            platform_results={"draft_id": draft_id},
            keyword=keyword
        )
        
        # 10. 텔레그램 전송
        keyboard = [[
            InlineKeyboardButton("🚀 블로그 즉시 발행", callback_data=f"publish_{draft_id}"),
            InlineKeyboardButton("❌ 반려 및 취소", callback_data=f"reject_{draft_id}")
        ]]
        
        await telegram_app.bot.send_message(
            chat_id=Config.TELEGRAM_CHAT_ID,
            text=f"📅 **유튜브 분석 기반 브리핑 ({blog_domain.upper()})**\n\n{tg_summary}\n\n---\n[임시 초안 ID: {draft_id}]",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
    except Exception as e:
        print(f"[YouTube Pipeline] 작업 실패: {e}")
        db_cache.update_task_status(task_id, "실패", 0, title=f"유튜브 파이프라인 에러: {str(e)[:50]}", keyword="유튜브 통합 분석" if "keyword" not in locals() else keyword)
        try:
            await telegram_app.bot.send_message(
                chat_id=Config.TELEGRAM_CHAT_ID,
                text=f"❌ 유튜브 파이프라인 작업 오류 발생: {str(e)[:100]}"
            )
        except Exception:
            pass



async def run_keyword_pipeline_stage1a_extract(keyword: str, task_id: str, blog_domain: str, base_url: str, force_collect: bool = False, v_orchestrate: bool = False):
    try:
        loop = asyncio.get_running_loop()
        
        def _sync_stage1_status(status_str: str, progress: int, title_str: str):
            db_cache.update_task_status(task_id, status_str, progress, title=title_str, keyword=keyword)

        try:
            # 1. 1차 얕은 검색 및 키워드 추출
            stage1_res = await asyncio.wait_for(
                loop.run_in_executor(None, CarDataCollector.collect_stage1, keyword, 3, force_collect, _sync_stage1_status),
                timeout=55.0
            )
        except asyncio.TimeoutError:
            print("[Worker] Stage 1a 시간 초과")
            db_cache.update_task_status(task_id, "실패", 0, title="1차 검색 시간 초과", keyword=keyword)
            return False

        hot_kw = stage1_res.get("hot_kw", "최신뉴스")
        raw_news_step1 = stage1_res.get("raw_news_step1", [])
        
        # 임시 저장
        db_cache.set_temp_data(f"stage1a_{task_id}", {
            "hot_kw": hot_kw,
            "raw_news_step1": raw_news_step1
        })
        
        # 다음 단계(1b_scrape) 호출
        if Config.QSTASH_TOKEN and Config.QSTASH_TOKEN != "dummy":
            from upstash_qstash import QStash
            qstash = QStash(Config.QSTASH_TOKEN)
            qstash.message.publish_json(
                url=f"{base_url}/api/worker/stage1_scrape",
                body={"target": "keywords", "keyword": keyword, "task_id": task_id, "force_collect": force_collect}
            )
        else:
            if not v_orchestrate:
                await run_keyword_pipeline_stage1b_scrape(keyword, task_id, blog_domain, base_url, force_collect)
            
        return True
    except Exception as e:
        print(f"[Keyword Stage1a] 에러: {e}")
        db_cache.update_task_status(task_id, "실패", 0, title=f"1차 수집 에러: {str(e)[:50]}", keyword=keyword)
        return False

async def run_keyword_pipeline_stage1b_scrape(keyword: str, task_id: str, blog_domain: str, base_url: str, force_collect: bool = False):
    try:
        loop = asyncio.get_running_loop()
        
        stage1a_data = db_cache.get_temp_data(f"stage1a_{task_id}", {})
        hot_kw = stage1a_data.get("hot_kw", "최신뉴스")
        raw_news_step1 = stage1a_data.get("raw_news_step1", [])
        
        def _sync_stage1_status(status_str: str, progress: int, title_str: str):
            db_cache.update_task_status(task_id, status_str, progress, title=title_str, keyword=keyword)

        try:
            # 2. 2차 정밀 수집 및 이미지
            stage2_res = await asyncio.wait_for(
                loop.run_in_executor(None, CarDataCollector.collect_stage2, keyword, hot_kw, raw_news_step1, 3, force_collect, blog_domain, _sync_stage1_status),
                timeout=55.0
            )
            collected_items = stage2_res.get("articles", [])
            web_images = stage2_res.get("web_images", {})
        except asyncio.TimeoutError:
            print("[Worker] 수집 단계 시간 초과 (Jina 또는 수집 지연)")
            db_cache.update_task_status(task_id, "실패", 0, title="수집 시간 초과 (검색 엔진 지연)", keyword=keyword)
            return False
        
        if not collected_items:
            db_cache.update_task_status(task_id, "실패", 0, title="수집 데이터 없음", keyword=keyword)
            return False

        raw_data_text = ""
        source_links = []
        for idx, item in enumerate(collected_items):
            if not force_collect and db_cache.is_duplicate(item["url"]):
                continue
            raw_data_text += f"### 기사 {idx+1}\n제목: {item['title']}\n출처: {item['source']}\nURL: {item['url']}\n본문:\n{item['content']}\n\n"
            source_links.append(item)

        if not raw_data_text:
            db_cache.update_task_status(task_id, "실패", 0, title="모든 기사가 중복 기사임", keyword=keyword)
            return False

        stage1_data = {
            "raw_data_text": raw_data_text,
            "source_links": source_links,
            "web_images_candidates": web_images,
            "keyword": f"{keyword} {hot_kw}",
            "blog_domain": blog_domain
        }
        db_cache.set_temp_data(f"stage1_{task_id}", stage1_data)
        db_cache.set_temp_data(f"stage1a_{task_id}", {}) # Cleanup temp data
        
        db_cache.update_task_status(
            task_id, "수집완료", 50,
            title=f"'{keyword} {hot_kw}' 뉴스 및 이미지 수집 완료 (검수 대기)",
            keyword=f"{keyword} {hot_kw}",
            original_url=source_links[0]["url"] if source_links else ""
        )
        print(f"[Worker] Stage 1 완료. 수집완료 상태로 대기합니다. task_id={task_id}")
        return True
        
    except Exception as e:
        print(f"[Keyword Stage1] 에러: {e}")
        db_cache.update_task_status(task_id, "실패", 0, title=f"수집 에러: {str(e)[:50]}", keyword=keyword)
        return False

async def run_keyword_pipeline_stage2_ai(task_id: str, selected_images: dict = None, use_mascot: bool = False):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram_bot import _save_draft
    try:
        stage1_data = db_cache.get_temp_data(f"stage1_{task_id}")
        if not stage1_data:
            print("[Keyword Stage2] Stage 1 데이터를 찾을 수 없습니다.")
            return
            
        raw_data_text = stage1_data["raw_data_text"]
        source_links = stage1_data["source_links"]
        keyword = stage1_data["keyword"]
        blog_domain = stage1_data["blog_domain"]
        
        # 사용자가 선택한 이미지 매핑 적용 및 없으면 첫 번째 후보로 폴백
        web_images_candidates = stage1_data.get("web_images_candidates", {})
        web_images = {}
        if selected_images:
            web_images = selected_images
        else:
            for slot, urls in web_images_candidates.items():
                if isinstance(urls, list) and urls:
                    first = urls[0]
                    web_images[slot] = first.get("url") if isinstance(first, dict) else first
                elif isinstance(urls, str):
                    web_images[slot] = urls
                else:
                    web_images[slot] = ""

        
        db_cache.update_task_status(task_id, "AI작성중", 60, title="블로그 분석 원고 작성 중", keyword=keyword)
        
        def _sync_status_callback(msg: str):
            db_cache.update_task_status(task_id, "AI작성중", 60, title=msg, keyword=keyword)
            
        task_ai_writer = AIWriter(status_callback=_sync_status_callback)
        loop = asyncio.get_running_loop()
        blog_draft = await loop.run_in_executor(
            None, 
            task_ai_writer.generate_blog_post, 
            raw_data_text, 
            keyword, 
            web_images, 
            blog_domain,
            task_id,
            use_mascot
        )
        
        tg_summary = await loop.run_in_executor(
            None,
            task_ai_writer.generate_telegram_summary,
            blog_draft.get("title", f"{keyword} 분석"),
            blog_draft.get("naver", {}).get("markdown_content", ""),
            blog_domain
        )

        for src in source_links:
            db_cache.mark_as_collected(src["url"], src["title"])

        draft_id = f"draft_{int(time.time())}"
        original_url = source_links[0]["url"] if source_links else "https://news.google.com"
        
        _save_draft(draft_id, {
            "task_id": task_id,
            "title": blog_draft.get("title", f"{keyword} 분석"),
            "naver": blog_draft.get("naver"),
            "tistory": blog_draft.get("tistory"),
            "wordpress": blog_draft.get("wordpress"),
            "original_url": original_url,
            "web_images": blog_draft.get("used_images", web_images)
        })

        db_cache.update_task_status(
            task_id, "발행대기", 90,
            title=blog_draft.get("title", f"{keyword} 분석"),
            original_url=original_url,
            platform_results={"draft_id": draft_id}
        )

        keyboard = [[
            InlineKeyboardButton("🚀 블로그 즉시 발행", callback_data=f"publish_{draft_id}"),
            InlineKeyboardButton("❌ 반려 및 취소", callback_data=f"reject_{draft_id}")
        ]]
        
        await telegram_app.bot.send_message(
            chat_id=Config.TELEGRAM_CHAT_ID,
            text=f"📰 **뉴스 수집 기반 브리핑({blog_domain.upper()})**\n\n{tg_summary}\n\n---\n[임시 초안 ID: {draft_id}]",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
        db_cache.set_temp_data(f"stage1_{task_id}", {}) # Clear cache
        
    except Exception as e:
        print(f"[Keyword Stage2] 작업 실패: {e}")
        db_cache.update_task_status(task_id, "실패", 0, title=f"AI 원고 에러: {str(e)[:50]}")
        try:
            await telegram_app.bot.send_message(
                chat_id=Config.TELEGRAM_CHAT_ID,
                text=f"❌ 키워드 파이프라인(AI작성) 작업 오류 발생: {str(e)[:100]}"
            )
        except Exception:
            pass


async def run_multi_youtube_pipeline_stage1_collect(urls: list[str], task_id: str, blog_domain: str, base_url: str, force_collect: bool = False):
    try:
        loop = asyncio.get_running_loop()
        db_cache.update_task_status(task_id, "수집중", 20, title=f"유튜브 {len(urls)}개 영상 분석 중")
        
        keyword = "유튜브 종합"
        collected_items_task = loop.run_in_executor(None, CarDataCollector.collect_youtube_data, urls, force_collect)
        web_images_task = loop.run_in_executor(None, CarDataCollector.search_web_images, keyword, blog_domain)
        
        try:
            collected_items, web_images = await asyncio.wait_for(
                asyncio.gather(collected_items_task, web_images_task),
                timeout=55.0
            )
        except asyncio.TimeoutError:
            print("[Worker] 유튜브 파이프라인 수집 단계 시간 초과")
            db_cache.update_task_status(task_id, "실패", 0, title="수집 시간 초과 (검색 엔진 지연)")
            return False
            
        summary = ""
        valid_urls = []
        for idx, item in enumerate(collected_items):
            summary += f"### 영상 {idx+1}: {item['title']}\n{item['content']}\n\n"
            valid_urls.append(item["url"])

        if not summary.strip():
            db_cache.update_task_status(task_id, "실패", 0, title="분석 가능한 유튜브 영상이 없습니다.")
            return False

        raw_data_text = f"### 유튜브 원본 통합 분석 및 요약\n- 대상 영상: {len(valid_urls)}개\n- 핵심 요약:\n{summary}\n\n"
        if web_images:
            raw_data_text += "\n[참고용 웹 이미지 목록 - 목차 생성 시 활용!]\n"
            for slot, img_url in web_images.items():
                if img_url:
                    raw_data_text += f"{slot.upper()} 이미지: {img_url}\n"

        stage1_data = {
            "raw_data_text": raw_data_text,
            "urls": valid_urls,
            "web_images": web_images,
            "blog_domain": blog_domain
        }
        db_cache.set_temp_data(f"stage1_{task_id}", stage1_data)
        
        print(f"[Worker] YouTube Stage 1 완료. Stage 2 (AI작성) 워커를 QStash로 호출합니다. url={base_url}/api/worker/ai")
        try:
            from qstash import QStash
            if Config.QSTASH_TOKEN and Config.QSTASH_TOKEN != "dummy":
                client = QStash(Config.QSTASH_TOKEN)
                client.message.publish_json(
                    url=f"{base_url}/api/worker/ai",
                    body={"task_id": task_id, "target": "youtube"}
                )
            else:
                loop.run_in_executor(None, _fire_and_forget_internal, f"{base_url}/api/worker/ai", {"task_id": task_id, "target": "youtube"})
        except Exception as e:
            print(f"[Worker] QStash Publish Error: {e}")
            loop.run_in_executor(None, _fire_and_forget_internal, f"{base_url}/api/worker/ai", {"task_id": task_id, "target": "youtube"})
        return True
        
    except Exception as e:
        print(f"[Youtube Stage1] 에러: {e}")
        db_cache.update_task_status(task_id, "실패", 0, title=f"유튜브 수집 에러: {str(e)[:50]}")
        return False

async def run_multi_youtube_pipeline_stage2_ai(task_id: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram_bot import _save_draft
    try:
        stage1_data = db_cache.get_temp_data(f"stage1_{task_id}")
        if not stage1_data:
            print("[Youtube Stage2] Stage 1 데이터를 찾을 수 없습니다.")
            return
            
        raw_data_text = stage1_data["raw_data_text"]
        valid_urls = stage1_data["urls"]
        web_images = stage1_data["web_images"]
        blog_domain = stage1_data["blog_domain"]
        keyword = "유튜브 리뷰"
        
        db_cache.update_task_status(task_id, "AI작성중", 60, title="유튜브 통합 리뷰 작성 중")
        
        def _sync_status_callback(msg: str):
            db_cache.update_task_status(task_id, "AI작성중", 60, title=msg)
            
        task_ai_writer = AIWriter(status_callback=_sync_status_callback)
        loop = asyncio.get_running_loop()
        blog_draft = await loop.run_in_executor(
            None, 
            task_ai_writer.generate_blog_post, 
            raw_data_text, 
            keyword, 
            web_images, 
            blog_domain,
            task_id
        )

        tg_summary = await loop.run_in_executor(
            None,
            task_ai_writer.generate_telegram_summary,
            blog_draft.get("title", "유튜브 통합 분석 리뷰"),
            blog_draft.get("naver", {}).get("markdown_content", ""),
            blog_domain
        )

        for u in valid_urls:
            db_cache.mark_as_collected(u, "YouTube Video")

        draft_id = f"draft_yt_{int(time.time())}"
        original_url = valid_urls[0] if valid_urls else "https://youtube.com"
        
        _save_draft(draft_id, {
            "task_id": task_id,
            "title": blog_draft.get("title", "유튜브 리뷰"),
            "naver": blog_draft.get("naver"),
            "tistory": blog_draft.get("tistory"),
            "wordpress": blog_draft.get("wordpress"),
            "original_url": original_url,
            "web_images": blog_draft.get("used_images", web_images)
        })

        db_cache.update_task_status(
            task_id, "발행대기", 90,
            title=blog_draft.get("title", "유튜브 리뷰"),
            original_url=original_url,
            platform_results={"draft_id": draft_id}
        )

        keyboard = [[
            InlineKeyboardButton("🚀 블로그 즉시 발행", callback_data=f"publish_{draft_id}"),
            InlineKeyboardButton("❌ 반려 및 취소", callback_data=f"reject_{draft_id}")
        ]]
        
        await telegram_app.bot.send_message(
            chat_id=Config.TELEGRAM_CHAT_ID,
            text=f"🎥 **유튜브 통합 분석 브리핑({blog_domain.upper()})**\n\n{tg_summary}\n\n---\n[임시 초안 ID: {draft_id}]",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
        db_cache.set_temp_data(f"stage1_{task_id}", {}) # Clear cache
        
    except Exception as e:
        print(f"[Youtube Stage2] 작업 실패: {e}")
        db_cache.update_task_status(task_id, "실패", 0, title=f"AI 원고 에러: {str(e)[:50]}")

async def run_keyword_pipeline(keyword: str, task_id: str, blog_domain: str, force_collect: bool = False):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram_bot import _save_draft
    
    try:
        loop = asyncio.get_running_loop()
        
        db_cache.update_task_status(task_id, "수집중", 20, title=f"'{keyword}' 관련 다국가 정보 수집 중", keyword=keyword)
        
        def _sync_stage1_status(status_str: str, progress: int, title_str: str):
            db_cache.update_task_status(task_id, status_str, progress, title=title_str, keyword=keyword)
            
        collected_items_task = loop.run_in_executor(None, CarDataCollector.collect_topic_data, keyword, 3, force_collect, blog_domain, _sync_stage1_status)
        web_images_task = loop.run_in_executor(None, CarDataCollector.search_web_images, keyword, blog_domain)
        
        try:
            # Vercel 60초 타임아웃을 방지하기 위해 스크래핑 최대 45초 대기
            collected_items, web_images = await asyncio.wait_for(
                asyncio.gather(collected_items_task, web_images_task),
                timeout=55.0
            )
        except asyncio.TimeoutError:
            print("[Worker] 수집 단계 시간 초과 (DuckDuckGo 또는 Jina 지연)")
            db_cache.update_task_status(task_id, "실패", 0, title="수집 시간 초과 (검색 엔진 지연)", keyword=keyword)
            return
        
        if not collected_items:
            db_cache.update_task_status(task_id, "실패", 0, title="수집 데이터 없음", keyword=keyword)
            return

        raw_data_text = ""
        source_links = []
        for idx, item in enumerate(collected_items):
            if not force_collect and db_cache.is_duplicate(item["url"]):
                continue
            raw_data_text += f"### 기사 {idx+1}\n제목: {item['title']}\n출처: {item['source']}\nURL: {item['url']}\n본문:\n{item['content']}\n\n"
            source_links.append(item)

        if not raw_data_text:
            db_cache.update_task_status(task_id, "실패", 0, title="모든 기사가 중복 기사임", keyword=keyword)
            return

        if web_images:
            raw_data_text += "\n[참고용 웹 이미지 목록 - 반드시 본문의 적절한 목차 아래에 아래 URL을 마크다운 문법으로 분산 배치하세요!]\n"
            for slot, img_url in web_images.items():
                if img_url:
                    raw_data_text += f"{slot.upper()} 이미지: {img_url}\n"

        db_cache.update_task_status(task_id, "AI작성중", 60, title="블로그 분석 원고 작성 중", keyword=keyword)
        
        def _sync_status_callback(msg: str):
            db_cache.update_task_status(task_id, "AI작성중", 60, title=msg, keyword=keyword)
            
        task_ai_writer = AIWriter(status_callback=_sync_status_callback)
        blog_draft = await loop.run_in_executor(
            None, 
            task_ai_writer.generate_blog_post, 
            raw_data_text, 
            keyword, 
            web_images, 
            blog_domain,
            task_id
        )
        
        tg_summary = await loop.run_in_executor(
            None,
            task_ai_writer.generate_telegram_summary,
            blog_draft["title"],
            blog_draft.get("naver", {}).get("markdown_content", ""),
            blog_domain
        )

        for src in source_links:
            db_cache.mark_as_collected(src["url"], src["title"])

        draft_id = f"draft_{int(time.time())}"
        original_url = source_links[0]["url"] if source_links else "https://news.google.com"
        
        _save_draft(draft_id, {
            "task_id": task_id,
            "title": blog_draft["title"],
            "naver": blog_draft.get("naver"),
            "tistory": blog_draft.get("tistory"),
            "wordpress": blog_draft.get("wordpress"),
            "original_url": original_url,
            "web_images": blog_draft.get("used_images", web_images)
        })

        db_cache.update_task_status(
            task_id, "발행대기", 90,
            title=blog_draft["title"],
            original_url=original_url,
            platform_results={"draft_id": draft_id}
        )

        keyboard = [[
            InlineKeyboardButton("🚀 블로그 즉시 발행", callback_data=f"publish_{draft_id}"),
            InlineKeyboardButton("❌ 반려 및 취소", callback_data=f"reject_{draft_id}")
        ]]
        
        await telegram_app.bot.send_message(
            chat_id=Config.TELEGRAM_CHAT_ID,
            text=f"📅 **뉴스 수집 기반 브리핑 ({blog_domain.upper()})**\n\n{tg_summary}\n\n---\n[임시 초안 ID: {draft_id}]",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
    except Exception as e:
        print(f"[Keyword Pipeline] 작업 실패: {e}")
        db_cache.update_task_status(task_id, "실패", 0, title=f"키워드 파이프라인 에러: {str(e)[:50]}", keyword=keyword)
        try:
            await telegram_app.bot.send_message(
                chat_id=Config.TELEGRAM_CHAT_ID,
                text=f"❌ 키워드 파이프라인 작업 오류 발생: {str(e)[:100]}"
            )
        except Exception:
            pass


def _fire_and_forget_internal(url: str, data: dict):
    import requests
    try:
        requests.post(url, json=data, timeout=0.1)
    except requests.exceptions.ReadTimeout:
        pass
    except Exception as e:
        print(f"[Webhook internal] {e}")

@app.post("/api/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    if not Config.TELEGRAM_BOT_TOKEN:
        return Response(status_code=status.HTTP_400_BAD_REQUEST)
    try:
        data = await request.json()
        base_url = str(request.base_url).rstrip("/")
        if "127.0.0.1" in base_url or "localhost" in base_url:
            internal_url = f"{base_url}/api/internal-task"
        else:
            internal_url = f"https://auto-car-blog.vercel.app/api/internal-task"

        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _fire_and_forget_internal, internal_url, data)

        return {"status": "ok"}
    except Exception as e:
        print(f"[Webhook Error] {e}")
        return {"status": "ok"}

@app.post("/api/internal-task")
async def internal_task_worker(request: Request):
    """실제 AI 파이프라인이 60초 제한 안에서 동작하는 엔드포인트"""
    try:
        data = await request.json()
        from telegram import Update
        update = Update.de_json(data, telegram_app.bot)
        await telegram_app.process_update(update)
        return {"status": "finished"}
    except Exception as e:
        print(f"[Internal Task Error] {e}")
        return {"status": "error", "details": str(e)}

@app.get("/api/auth/google")
def auth_google():
    client_id = Config.GOOGLE_CLIENT_ID
    if not client_id:
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content="<h3>GOOGLE_CLIENT_ID가 설정되지 않았습니다. Vercel 환경 변수를 확인해주세요.</h3>", status_code=400)
    
    redirect_uri = "https://auto-car-blog.vercel.app/api/auth/google/callback"
    scopes = "https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/userinfo.email"
    
    # Enforce offline access and consent prompt to obtain refresh_token
    google_auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={client_id}&"
        f"redirect_uri={redirect_uri}&"
        "response_type=code&"
        f"scope={urllib.parse.quote(scopes)}&"
        "access_type=offline&"
        "prompt=consent"
    )
    from fastapi.responses import RedirectResponse
    return RedirectResponse(google_auth_url)

@app.get("/api/auth/google/callback")
def auth_google_callback(code: str = None, error: str = None):
    from fastapi.responses import HTMLResponse, RedirectResponse
    if error:
        return HTMLResponse(content=f"<h3>인증 실패: {error}</h3>", status_code=400)
    if not code:
        return HTMLResponse(content="<h3>인증 코드(code)가 누락되었습니다.</h3>", status_code=400)
        
    try:
        import requests
        # Exchange authorization code for tokens
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "code": code,
            "client_id": Config.GOOGLE_CLIENT_ID,
            "client_secret": Config.GOOGLE_CLIENT_SECRET,
            "redirect_uri": "https://auto-car-blog.vercel.app/api/auth/google/callback",
            "grant_type": "authorization_code"
        }
        token_res = requests.post(token_url, data=token_data)
        if token_res.status_code != 200:
            return HTMLResponse(content=f"<h3>토큰 교환 실패: {token_res.text}</h3>", status_code=400)
            
        token_json = token_res.json()
        refresh_token = token_json.get("refresh_token")
        access_token = token_json.get("access_token")
        
        if not refresh_token:
            return HTMLResponse(content="<h3>리프레시 토큰이 수령되지 않았습니다. 구글 동의 화면에서 연동 해제 후 다시 로그인하거나 Vercel 환경 변수가 올바른지 확인해주세요.</h3>", status_code=400)
            
        # Get user email
        userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        headers = {"Authorization": f"Bearer {access_token}"}
        userinfo_res = requests.get(userinfo_url, headers=headers)
        user_email = userinfo_res.json().get("email", "알수없는사용자")
        
        # Save refresh token in Firestore
        if db_cache.firestore.is_available:
            oauth_data = {
                "refresh_token": refresh_token,
                "email": user_email,
                "connected_at": datetime.now(KST).isoformat()
            }
            db_cache.firestore.db.collection("settings").document("google_oauth").set(oauth_data, merge=True)
            # Re-initialize drive manager connection
            db_cache.drive._init_connection()
            print(f"[GoogleOAuth] 구글 드라이브 연동 완료: {user_email}")
            return RedirectResponse(url="/?oauth_success=true")
        else:
            return HTMLResponse(content="<h3>연동 실패: Firestore 데이터베이스가 활성화되어 있지 않습니다.</h3>", status_code=500)
            
    except Exception as e:
        return HTMLResponse(content=f"<h3>인증 처리 중 내부 서버 에러 발생: {str(e)}</h3>", status_code=500)

@app.get("/api/auth/google/status")
def auth_google_status():
    return {
        "connected": db_cache.drive.oauth_connected,
        "email": db_cache.drive.oauth_email or "없음"
    }

@app.post("/api/auth/google/disconnect")
def auth_google_disconnect():
    try:
        if db_cache.firestore.is_available:
            db_cache.firestore.db.collection("settings").document("google_oauth").delete()
            # Re-initialize drive manager to fallback to service account
            db_cache.drive._init_connection()
            return {"success": True}
        return {"success": False, "error": "Firestore is not available"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/debug-connection")
async def debug_connection():
    sheets_ok = db_cache.sheets.is_available
    drive_ok = db_cache.drive.is_available
    firestore_ok = db_cache.firestore.is_available
    
    # 이메일 주소 로드
    raw_email = "없음"
    if db_cache.drive.oauth_connected:
        raw_email = f"OAuth 사용자: {db_cache.drive.oauth_email}"
    elif db_cache.sheets.creds:
        raw_email = f"서비스 계정: {db_cache.sheets.creds.get('client_email', '없음')}"
    
    sheet_id = Config.GOOGLE_SHEETS_SPREADSHEET_ID
    masked_sheet_id = "설정되지 않음"
    if sheet_id:
        masked_sheet_id = f"{sheet_id[:6]}...{sheet_id[-6:]}" if len(sheet_id) > 12 else "너무 짧음"

    # 구글 드라이브 'Blog_Assets' 폴더 실시간 찾기 테스트
    blog_assets_found = False
    blog_assets_id = None
    drive_search_error = None
    if drive_ok:
        try:
            query = "name = 'Blog_Assets' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = db_cache.drive.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            items = results.get('files', [])
            if items:
                blog_assets_found = True
                blog_assets_id = items[0]['id']
            else:
                drive_search_error = "Blog_Assets folder not found in Drive"
        except Exception as e:
            drive_search_error = str(e)

    # 실시간 파일 업로드 테스트
    test_upload_result = None
    test_upload_error = None
    if drive_ok and blog_assets_found:
        try:
            test_urls = ["https://placehold.co/100x100/eeeeee/333333?text=Test"]
            test_upload_result = db_cache.drive.upload_images_to_drive("Test_Connection", test_urls)
            if not test_upload_result:
                test_upload_error = f"Upload returned None. Connection error state: {db_cache.drive.connection_error}"
        except Exception as e:
            test_upload_error = str(e)

    return {
        "firestore_connected": firestore_ok,
        "firestore_error": db_cache.firestore.connection_error,
        "sheets_connected": sheets_ok,
        "sheets_error": db_cache.sheets.connection_error,
        "drive_connected": drive_ok,
        "drive_error": db_cache.drive.connection_error,
        "drive_blog_assets_found": blog_assets_found,
        "drive_blog_assets_id": blog_assets_id,
        "drive_search_error": drive_search_error,
        "drive_test_upload_result": test_upload_result,
        "drive_test_upload_error": test_upload_error,
        "service_account_email": raw_email,
        "spreadsheet_id_status": masked_sheet_id
    }

@app.get("/api/cron")
async def daily_cron_trigger():
    schedule_settings = db_cache.get_schedule_settings()
    if not schedule_settings.get("active", True):
        print("[Cron] 정기 수집 스케줄 설정이 비활성화(OFF) 상태입니다. 중단합니다.")
        return {"status": "ignored", "message": "Scheduler is inactive"}

    if not Config.TELEGRAM_CHAT_ID:
        return {"status": "error", "message": "TELEGRAM_CHAT_ID가 정의되지 않았습니다."}

    blog_domain = schedule_settings.get("blog_domain", "universal")
    print(f"[Cron] 데일리 브리핑 파이프라인 자동 실행 시작... 도메인: {blog_domain}")
    
    keywords = db_cache.get_keywords()
    query_keyword = keywords[0]["keyword"] if keywords else ("EV OR SUV" if blog_domain == "automotive" else "AI OR IT")
    
    import uuid
    task_id = f"task_cron_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
    db_cache.update_task_status(task_id, "수집중", 10, title="데일리 종합 뉴스 수집 중", keyword="데일리 브리핑")

    def _sync_stage1_status(status_str: str, progress: int, title_str: str):
        db_cache.update_task_status(task_id, status_str, progress, title=title_str, keyword="데일리 브리핑")

    loop = asyncio.get_event_loop()
    collected = await loop.run_in_executor(None, CarDataCollector.collect_topic_data, query_keyword, 5, False, blog_domain, _sync_stage1_status)
    
    if not collected:
        db_cache.update_task_status(task_id, "실패", 0, title="브리핑 신규 기사 없음", keyword="데일리 브리핑")
        return {"status": "ignored", "message": "새로운 기사가 없습니다."}

    db_cache.update_task_status(task_id, "AI작성중", 50, title="AI 데일리 브리핑 작성 중", keyword="데일리 브리핑")
    raw_data_text = "\n".join([f"제목: {x['title']}\n본문: {x['content'][:500]}\n" for x in collected])
    
    blog_draft = await loop.run_in_executor(None, ai_writer.generate_blog_post, raw_data_text, "", [], blog_domain)
    tg_summary = await loop.run_in_executor(
        None, 
        ai_writer.generate_telegram_summary, 
        "Daily News Briefing", 
        blog_draft.get("naver", {}).get("markdown_content", ""),
        blog_domain
    )

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram_bot import _save_draft
    import time
    
    draft_id = f"draft_cron_{int(time.time())}"
    _save_draft(draft_id, {
        "task_id": task_id,
        "title": blog_draft["title"],
        "naver": blog_draft.get("naver"),
        "tistory": blog_draft.get("tistory"),
        "wordpress": blog_draft.get("wordpress"),
        "original_url": collected[0]["url"]
    })
    
    db_cache.update_task_status(
        task_id, 
        "발행대기", 
        90, 
        title=blog_draft["title"], 
        original_url=collected[0]["url"],
        platform_results={"draft_id": draft_id}
    )

    keyboard = [
        [
            InlineKeyboardButton("🚀 데일리 브리핑 발행", callback_data=f"publish_{draft_id}"),
            InlineKeyboardButton("❌ 반려", callback_data=f"reject_{draft_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await telegram_app.bot.send_message(
        chat_id=Config.TELEGRAM_CHAT_ID,
        text=f"📅 **일일 트렌드 브리핑 ({blog_domain.upper()})**\n\n{tg_summary}",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    
    return {"status": "success", "draft_id": draft_id}


# --- 4. 로컬 독립 스케줄 제어 핸들러 ---
def local_cron_job():
    schedule_settings = db_cache.get_schedule_settings()
    if schedule_settings.get("active", True):
        print("[Scheduler] 로컬 백그라운드 일일 브리핑 작동 시작...")
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(daily_cron_trigger())
    else:
        print("[Scheduler] 스케줄러가 비활성화(OFF) 상태입니다. 작업을 건너뜁니다.")


def reload_scheduler_jobs():
    global scheduler
    if scheduler is None:
        scheduler = BackgroundScheduler()
        scheduler.start()
        print("[Scheduler] APScheduler 시작됨.")
    else:
        scheduler.remove_all_jobs()
        print("[Scheduler] 기존 모든 정기 작업 삭제 완료.")
        
    settings = db_cache.get_schedule_settings()
    if not settings.get("active", True):
        print("[Scheduler] 스케줄러가 비활성화(OFF) 상태입니다. 예약 잡을 등록하지 않습니다.")
        return
        
    run_times = settings.get("run_times", ["08:00"])
    
    for time_str in run_times:
        try:
            hour, minute = map(int, time_str.split(":"))
            scheduler.add_job(
                local_cron_job, 
                CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
                id=f"job_{hour:02d}_{minute:02d}"
            )
            print(f"[Scheduler] 매일 {hour:02d}:{minute:02d}에 실행될 정기 작업 등록 완료.")
        except Exception as e:
            print(f"[Scheduler] 스케줄 등록 에러 ({time_str}): {e}")


if __name__ == "__main__":
    Config.validate()
    
    if Config.RUN_MODE == "local":
        print("[System] 로컬 실행 모드 감지.")
        print("[System] 1. 백그라운드 APScheduler 스케줄러 초기화...")
        
        # 스케줄러 로드 및 크론 잡 등록
        reload_scheduler_jobs()
        
        print("[System] 2. 로컬 텔레그램 봇 폴링(Polling) 작동 중. Ctrl+C로 종료.")
        telegram_app.run_polling()
    else:
        print("[System] Vercel Serverless 구동 모드 감지.")
        uvicorn.run("main:app", host="0.0.0.0", port=Config.PORT, reload=True)


@app.post("/api/worker/run")
async def worker_stage1_collect(request: Request, platform: str = "NAVER"):
    """Vercel 60초 제한 방지를 위한 Stage 1 (수집 전용) 워커"""
    try:
        data = await request.json()
        target = data.get("target", "keywords")
        keyword = data.get("keyword")
        task_id = data.get("task_id", f"task_{int(time.time())}")
        force_collect = data.get("force_collect", False)
        
        schedule_settings = db_cache.get_schedule_settings()
        blog_domain = schedule_settings.get("blog_domain", "universal")
        
        scheme = request.headers.get("x-forwarded-proto", "http")
        host = request.headers.get("host", "localhost:8000")
        base_url = f"{scheme}://{host}"
        
        if target == "youtube":
            urls = db_cache.get_youtube_urls()
            await run_multi_youtube_pipeline_stage1_collect(urls, task_id, blog_domain, base_url, force_collect)
        else:
            await run_keyword_pipeline_stage1a_extract(keyword, task_id, blog_domain, base_url, force_collect)
            
        return {"status": "success", "stage": "1a_extract"}
    except Exception as e:
        print(f"[Worker Stage1a] Error: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/worker/stage1_scrape")
async def worker_stage1b_scrape(request: Request):
    """Vercel 60초 제한 방지를 위한 Stage 1b (2차 정밀 수집 및 이미지) 워커"""
    try:
        data = await request.json()
        target = data.get("target", "keywords")
        keyword = data.get("keyword")
        task_id = data.get("task_id")
        force_collect = data.get("force_collect", False)
        
        schedule_settings = db_cache.get_schedule_settings()
        blog_domain = schedule_settings.get("blog_domain", "universal")
        
        scheme = request.headers.get("x-forwarded-proto", "http")
        host = request.headers.get("host", "localhost:8000")
        base_url = f"{scheme}://{host}"
        
        if target == "keywords":
            await run_keyword_pipeline_stage1b_scrape(keyword, task_id, blog_domain, base_url, force_collect)
            
        return {"status": "success", "stage": "1b_scrape"}
    except Exception as e:
        print(f"[Worker Stage1] Error: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/worker/ai")
async def worker_stage2_ai(request: Request):
    """Vercel 60초 제한 방지를 위한 Stage 2 (AI 작성 전용) 워커"""
    try:
        data = await request.json()
        target = data.get("target", "keywords")
        task_id = data.get("task_id")
        selected_images = data.get("selected_images")
        
        if not task_id:
            return {"status": "error", "message": "task_id missing"}
            
        if target == "youtube":
            await run_multi_youtube_pipeline_stage2_ai(task_id)
        else:
            await run_keyword_pipeline_stage2_ai(task_id, selected_images)
            
        return {"status": "success", "stage": "2_ai"}
    except Exception as e:
        print(f"[Worker Stage2] Error: {e}")
        return {"status": "error", "message": str(e)}


@app.api_route("/api/test-timeout", methods=["GET"])
async def test_timeout():
    import asyncio
    await asyncio.sleep(15)
    return {"status": "success", "message": "Slept for 15 seconds"}

@app.api_route("/{path_name:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(request: Request, path_name: str):
    return {"headers": dict(request.headers), "path_name": path_name, "scope_path": request.scope.get("path")}

