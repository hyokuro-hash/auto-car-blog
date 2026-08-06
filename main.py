import os
import asyncio
import uvicorn
from fastapi import FastAPI, Request, Response, status, BackgroundTasks
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

# --- Vercel Serverless 및 Webhook 처리를 위한 FastAPI Lifespan 설정 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[Main] Telegram 봇 초기화 시작...")
    await telegram_app.initialize()
    await telegram_app.start()
    print("[Main] Telegram 봇 초기화 완료.")
    yield
    print("[Main] Telegram 봇 종료 중...")
    await telegram_app.stop()
    await telegram_app.shutdown()
    print("[Main] Telegram 봇 종료 완료.")

app = FastAPI(lifespan=lifespan)

# --- 1. 웹 대시보드 뷰 서빙 엔드포인트 ---
@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    """Vercel Serverless 빌드 호환성을 고려하여 dashboard.html 소스를 직접 읽어 서빙합니다."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(base_dir, "templates", "dashboard.html")
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Dashboard Template Not Found</h1><p>templates/dashboard.html 파일을 찾을 수 없습니다.</p>", status_code=404)


# --- 2. 웹 대시보드 API 엔드포인트 ---

@app.get("/api/tasks")
def get_tasks_api():
    """모니터링 보드용 작업 상태 리스트 반환"""
    return db_cache.get_active_tasks()

@app.get("/api/tasks/draft/{draft_id}")
def get_draft_api(draft_id: str):
    """특정 초안 ID의 세부 본문 조회 (원고 검수 모달용)"""
    from telegram_bot import _get_draft
    draft = _get_draft(draft_id)
    if not draft:
        return Response(status_code=404, content="Draft not found")
    return draft

@app.get("/api/keywords")
def get_keywords_api():
    """수집 키워드 조회"""
    return db_cache.get_keywords()

@app.post("/api/keywords")
def add_keyword_api(data: dict):
    """수집 키워드 추가"""
    keyword = data.get("keyword")
    category = data.get("category", "뉴스")
    if keyword:
        db_cache.add_keyword(keyword, category)
        return {"success": True}
    return {"success": False, "error": "Missing keyword"}

@app.delete("/api/keywords")
def delete_keyword_api(keyword: str):
    """수집 키워드 삭제"""
    db_cache.delete_keyword(keyword)
    return {"success": True}

@app.get("/api/schedule")
def get_schedule_api():
    """스케줄 설정 상태 조회"""
    return db_cache.get_schedule_settings()

@app.post("/api/schedule")
def update_schedule_api(data: dict):
    """스케줄 설정 저장"""
    active = data.get("active", True)
    interval_hours = data.get("interval_hours", 24)
    db_cache.update_schedule_settings(active, interval_hours)
    
    # 로컬 구동 시에 동작 중인 스케줄러가 있다면 간격을 리로드할 수 있는 트리거 마련 가능
    print(f"[Scheduler] 스케줄 설정 업데이트: 활성화={active}, 주기={interval_hours}시간")
    return {"success": True}

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
    
    # 플랫폼별 수동 발행 실행
    if platform == "tistory":
        res = BlogPublisher.publish_to_tistory(draft["title"], draft["html_content"])
    elif platform == "wordpress":
        res = BlogPublisher.publish_to_wordpress(draft["title"], draft["html_content"])
    else:
        return {"success": False, "error": "알 수 없는 발행 플랫폼 유형입니다."}
        
    if res.get("success"):
        post_url = res["url"]
        # 중복 방지 캐시 마크
        db_cache.mark_as_published(draft["original_url"], platform, post_url)
        
        # 웹 대시보드에 상태 동기화 업데이트
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


# --- 3. 기존 텔레그램 봇 웹훅 및 일일 크론 엔드포인트 ---

import threading

@app.post("/api/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    if not Config.TELEGRAM_BOT_TOKEN:
        return Response(status_code=status.HTTP_400_BAD_REQUEST)
    try:
        data = await request.json()
        from telegram import Update
        update = Update.de_json(data, telegram_app.bot)

        # 시작: 웹툳에서 즉시 200 OK 반환 후 다음에 파이프라인 실행
        # process_update를 BackgroundTasks로 위임하여 Telegram이 200을 바로 수신하게 함
        def _run_update_sync():
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(telegram_app.process_update(update))
            finally:
                loop.close()

        t = threading.Thread(target=_run_update_sync, daemon=True)
        t.start()

        # Telegram에 200 OK 즉시 반환 (웹툳 재전송 차단)
        return {"status": "ok"}
    except Exception as e:
        print(f"[Webhook Error] {e}")
        return {"status": "ok"}  # 에러에도 200 반환하여 Telegram 재전송 방지

@app.get("/api/cron")
async def daily_cron_trigger():
    # 스케줄 활성화 여부 사전 체크
    schedule_settings = db_cache.get_schedule_settings()
    if not schedule_settings.get("active", True):
        print("[Cron] 정기 수집 스케줄 설정이 비활성화(OFF) 상태입니다. 중단합니다.")
        return {"status": "ignored", "message": "Scheduler is inactive"}

    if not Config.TELEGRAM_CHAT_ID:
        return {"status": "error", "message": "TELEGRAM_CHAT_ID가 정의되지 않았습니다."}

    print("[Cron] 데일리 브리핑 파이프라인 자동 실행 시작...")
    
    # 등록된 키워드 중 하나를 순차 선택하거나 종합적으로 뉴스 수집
    keywords = db_cache.get_keywords()
    query_keyword = keywords[0]["keyword"] if keywords else "EV OR SUV"
    
    task_id = f"task_cron_{int(time.time())}"
    db_cache.update_task_status(task_id, "수집중", 10, title="데일리 종합 뉴스 수집 중")

    loop = asyncio.get_event_loop()
    collected = await loop.run_in_executor(None, CarDataCollector.collect_topic_data, query_keyword, 5)
    
    if not collected:
        db_cache.update_task_status(task_id, "실패", 0, title="브리핑 신규 기사 없음")
        return {"status": "ignored", "message": "새로운 기사가 없습니다."}

    db_cache.update_task_status(task_id, "AI작성중", 50, title="AI 데일리 브리핑 작성 중")
    raw_data_text = "\n".join([f"제목: {x['title']}\n본문: {x['content'][:500]}\n" for x in collected])
    
    blog_draft = await loop.run_in_executor(None, ai_writer.generate_blog_post, raw_data_text)
    tg_summary = await loop.run_in_executor(
        None, 
        ai_writer.generate_telegram_summary, 
        "Daily Auto News Briefing", 
        blog_draft["markdown_content"]
    )

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram_bot import _save_draft
    import time
    
    draft_id = f"draft_cron_{int(time.time())}"
    _save_draft(draft_id, {
        "task_id": task_id,
        "title": blog_draft["title"],
        "html_content": blog_draft["html_content"],
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
        text=f"📅 **일일 자동차 트렌드 브리핑**\n\n{tg_summary}",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    
    return {"status": "success", "draft_id": draft_id}


# --- 4. 로컬 독립 스케줄 제어 핸들러 ---
def local_cron_job():
    # 로컬 스케줄링 작동 시 상태 검사
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


if __name__ == "__main__":
    Config.validate()
    
    if Config.RUN_MODE == "local":
        print("[System] 로컬 실행 모드 감지.")
        print("[System] 1. 백그라운드 APScheduler 스케줄러 초기화...")
        
        # 설정에서 주기를 가져옴
        schedule_settings = db_cache.get_schedule_settings()
        interval_hours = schedule_settings.get("interval_hours", 24)
        
        scheduler = BackgroundScheduler()
        # 대시보드 상태 설정을 반영하기 위해 주기적 간격 트리거 적용 권장 (매 시간마다 설정을 체크하는 방식)
        scheduler.add_job(local_cron_job, CronTrigger(hour=8, minute=0, timezone="Asia/Seoul"))
        scheduler.start()
        print(f"[System] 스케줄러 등록 완료. 매일 08:00에 해외 브리핑 작동 대기.")

        print("[System] 2. 로컬 텔레그램 봇 폴링(Polling) 작동 중. Ctrl+C로 종료.")
        telegram_app.run_polling()
    else:
        print("[System] Vercel Serverless 구동 모드 감지.")
        uvicorn.run("main:app", host="0.0.0.0", port=Config.PORT, reload=True)
