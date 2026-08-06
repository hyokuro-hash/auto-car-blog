import asyncio
import uvicorn
from fastapi import FastAPI, Request, Response, status
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import Config
from telegram_bot import setup_application, briefing_command
from collector import CarDataCollector
from ai_writer import AIWriter
from publisher import BlogPublisher

# 텔레그램 봇 어플리케이션 싱글톤 로드
telegram_app = setup_application()
ai_writer = AIWriter()

# --- Vercel Serverless 스케줄러 대안 및 Webhook 처리를 위한 FastAPI Lifespan 설정 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Webhook 작동을 위해 봇 엔진 초기화
    print("[Main] Telegram 봇 초기화 시작...")
    await telegram_app.initialize()
    await telegram_app.start()
    print("[Main] Telegram 봇 초기화 완료.")
    yield
    # 종료 처리
    print("[Main] Telegram 봇 종료 중...")
    await telegram_app.stop()
    await telegram_app.shutdown()
    print("[Main] Telegram 봇 종료 완료.")

app = FastAPI(lifespan=lifespan)

# --- FastAPI API 엔드포인트 정의 ---
@app.get("/")
def read_root():
    return {"status": "running", "mode": Config.RUN_MODE}

@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    """텔레그램 웹훅 업데이트 처리기 (Vercel 배포 시 사용)"""
    if not Config.TELEGRAM_BOT_TOKEN:
        return Response(status_code=status.HTTP_400_BAD_REQUEST)
        
    try:
        data = await request.json()
        from telegram import Update
        update = Update.de_json(data, telegram_app.bot)
        # 비동기로 업데이트 큐에 전달하여 처리
        await telegram_app.process_update(update)
        return {"status": "processed"}
    except Exception as e:
        print(f"[Webhook Error] {e}")
        return {"status": "error", "details": str(e)}

@app.get("/api/cron")
async def daily_cron_trigger():
    """외부 Cron(Vercel Cron 등)에 의해 트리거되는 일일 자동 브리핑 배포 엔드포인트"""
    if not Config.TELEGRAM_CHAT_ID:
        return {"status": "error", "message": "TELEGRAM_CHAT_ID가 정의되지 않았습니다."}

    print("[Cron] 데일리 브리핑 파이프라인 자동 실행 시작...")
    
    # 1. 핫 키워드 수집
    loop = asyncio.get_event_loop()
    collected = await loop.run_in_executor(None, CarDataCollector.collect_topic_data, "EV OR SUV OR 自動運転", 5)
    
    if not collected:
        return {"status": "ignored", "message": "새로운 기사가 없습니다."}

    raw_data_text = "\n".join([f"제목: {x['title']}\n본문: {x['content'][:500]}\n" for x in collected])
    
    # 2. AI 초안 생성
    blog_draft = await loop.run_in_executor(None, ai_writer.generate_blog_post, raw_data_text)
    tg_summary = await loop.run_in_executor(
        None, 
        ai_writer.generate_telegram_summary, 
        "Daily Auto News Briefing", 
        blog_draft["markdown_content"]
    )

    # 3. 텔레그램 채널로 즉시 전송
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram_bot import _save_draft
    import time
    
    draft_id = f"draft_cron_{int(time.time())}"
    _save_draft(draft_id, {
        "title": blog_draft["title"],
        "html_content": blog_draft["html_content"],
        "original_url": collected[0]["url"]
    })
    
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


# --- 로컬 독립 구동용 데일리 브리핑 트리거 함수 ---
def local_cron_job():
    """로컬 독립 실행 시 APScheduler를 통해 구동되는 래퍼"""
    print("[Scheduler] 정기 스케줄 작동 (매일 오전 08:00)...")
    # 비동기 함수 실행을 위해 이벤트 루프 생성 또는 획득
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    loop.run_until_complete(daily_cron_trigger())


# --- 통합 실행 엔트리포인트 ---
if __name__ == "__main__":
    Config.validate()
    
    if Config.RUN_MODE == "local":
        print("[System] 로컬 실행 모드 감지.")
        print("[System] 1. 백그라운드 APScheduler 스케줄러 초기화...")
        # APScheduler 스케줄러 등록: 매일 아침 08:00에 실행
        scheduler = BackgroundScheduler()
        scheduler.add_job(local_cron_job, CronTrigger(hour=8, minute=0, timezone="Asia/Seoul"))
        scheduler.start()
        print("[System] 스케줄러 등록 완료. 매일 08:00에 해외 자동차 브리핑 수집 시작.")

        # 2. 로컬 텔레그램 폴링 실행 (FastAPI 서버 없이 단독 봇 구동)
        print("[System] 2. 로컬 텔레그램 봇 폴링(Polling) 작동 중. Ctrl+C로 종료.")
        # run_polling은 동기 blocking 함수이므로 봇이 계속 실행됨
        telegram_app.run_polling()
        
    else:
        print("[System] Vercel Serverless / ASGI 구동 모드 감지.")
        # Vercel에서 구동될 시 기본 8000 포트로 FastAPI ASGI 서버 로드
        uvicorn.run("main:app", host="0.0.0.0", port=Config.PORT, reload=True)
