import os
import json
import asyncio
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from config import Config
from collector import CarDataCollector
from ai_writer import AIWriter
from publisher import BlogPublisher
from db import db_cache

# Vercel Serverless 구동 시 인메모리 유실 대응을 위한 임시 초안 저장소 파일
DRAFTS_FILE = "drafts_cache.json"
# AIWriter는 작업별로 status_callback을 연결하여 재시도 상태를 대시보드에 반영합니다.
# 글로벌 인스턴스는 콜백 없이 기본 생성 (briefing 등 단순 호출용)
ai_writer = AIWriter()

def _save_draft(draft_id: str, data: dict):
    """임시 초안 데이터를 파일 또는 Firestore에 저장합니다."""
    if db_cache.firestore.is_available:
        try:
            db_cache.firestore.db.collection("car_news_drafts").document(draft_id).set(data)
            return
        except Exception as e:
            print(f"[TelegramBot] Firestore 초안 저장 실패: {e}")
            
    cache = {}
    if os.path.exists(DRAFTS_FILE):
        try:
            with open(DRAFTS_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            pass
    cache[draft_id] = data
    with open(DRAFTS_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def _get_draft(draft_id: str) -> dict:
    """임시 초안 데이터를 조회합니다."""
    if db_cache.firestore.is_available:
        try:
            doc = db_cache.firestore.db.collection("car_news_drafts").document(draft_id).get()
            if doc.exists:
                return doc.to_dict()
        except Exception as e:
            print(f"[TelegramBot] Firestore 초안 조회 실패: {e}")

    if os.path.exists(DRAFTS_FILE):
        try:
            with open(DRAFTS_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                return cache.get(draft_id)
        except Exception:
            pass
    return None


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start 커맨드 응답"""
    welcome_text = (
        "🤖 **Auto Car Blog 자동화 시스템 봇**\n\n"
        "사용 가능한 명령어:\n"
        "👉 `/news [차종/키워드]` : 해당 차종 관련 해외 뉴스 수집 및 AI 초안 작성\n"
        "👉 `/briefing` : 수동으로 오늘의 데일리 해외 자동차 뉴스 브리핑 실행"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def _run_news_pipeline(update: Update, keyword: str, force_collect: bool, task_id: str):
    """AI 생성 파이프라인을 백그라운드에서 실행합니다.
    news_command가 즉시 반환되어 Telegram에 200 OK가 전달되므로 재전송이 발생하지 않습니다."""
    status_msg = None
    try:
        status_msg = await update.message.reply_text(f"🔍 '{keyword}' 관련 해외 자동차 뉴스 및 오너 커뮤니티 데이터 수집 중...")

        loop = asyncio.get_running_loop()
        collected_items = await loop.run_in_executor(None, CarDataCollector.collect_topic_data, keyword, 3)

        if not collected_items:
            db_cache.update_task_status(task_id, "실패", 0, title="수집 데이터 없음")
            await status_msg.edit_text("❌ 수집된 새로운 기사가 없습니다.")
            return

        # 2단계: AI 분석 및 원고 작성 상태 전환 (진행률 40%)
        db_cache.update_task_status(task_id, "AI작성중", 40, title=f"'{keyword}' 뉴스 분석 중")
        await status_msg.edit_text("✍️ Jina Reader 스크래핑 데이터 분석 및 AI 원고 작성 중...")

        raw_data_text = ""
        source_links = []
        for idx, item in enumerate(collected_items):
            if not force_collect and db_cache.is_duplicate(item["url"]):
                continue
            raw_data_text += f"### 기사 {idx+1}\n제목: {item['title']}\n출처: {item['source']}\nURL: {item['url']}\n본문:\n{item['content']}\n\n"
            source_links.append(item)

        if not raw_data_text:
            db_cache.update_task_status(task_id, "실패", 0, title="모든 기사가 중복 기사임")
            await status_msg.edit_text("⚠️ 수집된 기사가 이미 전부 캐싱(중복) 처리되어 있습니다.")
            return

        # 이미지 수집 추가
        web_images = await loop.run_in_executor(None, CarDataCollector.search_web_images, keyword, 4)
        if web_images:
            raw_data_text += "\n[참고용 웹 이미지 목록 - 반드시 본문의 적절한 목차 아래에 아래 URL을 마크다운 문법으로 분산 배치하세요!]\n"
            for idx, img_url in enumerate(web_images.values()):
                raw_data_text += f"이미지{idx+1}: {img_url}\n"

        # 3단계: AI 생성 (진행률 70%) - 재시도 상태를 대시보드에 반영
        db_cache.update_task_status(task_id, "AI작성중", 70, title="AI 초안 작성 마무리 중")

        def _sync_status_callback(msg: str):
            db_cache.update_task_status(task_id, "AI작성중", 70, title=msg)
            print(f"[TelegramBot] 재시도 상태: {msg}")

        task_ai_writer = AIWriter(status_callback=_sync_status_callback)

        blog_draft = await loop.run_in_executor(None, task_ai_writer.generate_blog_post, raw_data_text, keyword, web_images)
        tg_summary = await loop.run_in_executor(
            None,
            task_ai_writer.generate_telegram_summary,
            blog_draft["title"],
            blog_draft.get("naver", {}).get("markdown_content", "")
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
            "original_url": original_url
        })

        # 4단계: 발행 대기 상태 전환 (진행률 90%)
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
        await status_msg.delete()
        await update.message.reply_text(
            f"{tg_summary}\n\n---\n[임시 초안 ID: {draft_id}]",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        print(f"[TelegramBot] 파이프라인 실패: {e}")
        db_cache.update_task_status(task_id, "실패", 0, title=f"에러: {str(e)[:50]}")
        try:
            if status_msg:
                await status_msg.edit_text(f"❌ 작업 중 오류가 발생했습니다: {str(e)[:100]}")
        except Exception:
            pass


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/news [키워드] 커맨드.
    웹훅에서 즉시 반환하고 파이프라인은 백그라운드로 실행 → Telegram 재전송 차단."""
    if not context.args:
        await update.message.reply_text("💡 사용법: `/news [차종명 또는 키워드]` (예: `/news IONIQ 5`)", parse_mode="Markdown")
        return

    keyword = " ".join(context.args)
    force_collect = False
    if " --force" in keyword or " -f" in keyword:
        force_collect = True
        keyword = keyword.replace(" --force", "").replace(" -f", "").strip()

    # 단 하나의 task_id를 생성하고 전체 파이프라인 동안 유지
    task_id = f"task_{int(time.time())}"
    print(f"[TelegramBot] 신규 작업 감지 (Task ID: {task_id}, 키워드: {keyword})")
    db_cache.update_task_status(task_id, "수집중", 10, title=f"'{keyword}' 관련 수집 시작", original_url="")

    # Vercel 환경에서는 /api/internal-task 엔드포인트에서 이 라우트가 실행되므로,
    # 백그라운드로 넘기지 않고 여기서 완전히 await 해야 프로세스가 종료되지 않습니다.
    await _run_news_pipeline(update, keyword, force_collect, task_id)




async def briefing_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/briefing 데일리 자동차 업계 동향 브리핑 즉시 실행 (실시간 상태 동기화)"""
    task_id = f"task_brief_{int(time.time())}"
    db_cache.update_task_status(task_id, "수집중", 10, title="데일리 종합 뉴스 수집 중")

    status_msg = await update.message.reply_text("🌐 데일리 해외 자동차 뉴스 종합 브리핑 수집 시작...")
    
    # 대표 키워드로 뉴스 수집
    loop = asyncio.get_running_loop()
    collected = await loop.run_in_executor(None, CarDataCollector.collect_topic_data, "EV OR SUV OR 自動運転", 5)
    
    if not collected:
        db_cache.update_task_status(task_id, "실패", 0, title="브리핑 신규 기사 없음")
        await status_msg.edit_text("❌ 브리핑에 활용할 신규 뉴스가 없습니다.")
        return
        
    db_cache.update_task_status(task_id, "AI작성중", 50, title="종합 분석 및 초안 생성 중")
    await status_msg.edit_text("📝 수집된 기사 종합 분석 및 데일리 브리핑 작성 중...")
    
    raw_data_text = "\n".join([f"제목: {x['title']}\n본문: {x['content'][:500]}\n" for x in collected])
    
    blog_draft = await loop.run_in_executor(None, ai_writer.generate_blog_post, raw_data_text, "", [])
    tg_summary = await loop.run_in_executor(
        None, 
        ai_writer.generate_telegram_summary, 
        f"Daily Briefing - {datetime.now().strftime('%Y-%m-%d')}", 
        blog_draft.get("naver", {}).get("markdown_content", "")
    )
    
    draft_id = f"draft_brief_{int(time.time())}"
    original_url = collected[0]["url"]
    
    _save_draft(draft_id, {
        "task_id": task_id,
        "title": blog_draft["title"],
        "naver": blog_draft.get("naver"),
        "tistory": blog_draft.get("tistory"),
        "wordpress": blog_draft.get("wordpress"),
        "original_url": original_url
    })
    
    db_cache.update_task_status(
        task_id, 
        "발행대기", 
        90, 
        title=blog_draft["title"], 
        original_url=original_url,
        platform_results={"draft_id": draft_id}
    )
    
    keyboard = [
        [
            InlineKeyboardButton("🚀 데일리 브리핑 발행", callback_data=f"publish_{draft_id}"),
            InlineKeyboardButton("❌ 반려", callback_data=f"reject_{draft_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await status_msg.delete()
    await update.message.reply_text(
        f"📅 오늘의 자동차 뉴스 데일리 브리핑\n\n{tg_summary}",
        reply_markup=reply_markup
    )


async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """인라인 버튼 콜백 핸들러 (발행 / 반려 처리 및 대시보드 상태 갱신)"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    action, draft_id = data.split("_", 1)
    
    draft = _get_draft(draft_id)
    task_id = draft.get("task_id") if draft else None
    
    if action == "reject":
        if task_id:
            db_cache.update_task_status(task_id, "반려됨", 100, title=draft.get("title") if draft else "반려된 포스팅")
        await query.edit_message_text(
            text=f"{query.message.text}\n\n🔴 반려되었습니다. (발행 취소)"
        )
        return
        
    if action == "publish":
        await query.edit_message_text(
            text=f"{query.message.text}\n\n⏳ 블로그 발행 중..."
        )
        
        if not draft:
            await query.edit_message_text(
                text=f"{query.message.text}\n\n❌ 오류: 초안 세션이 만료되었거나 찾을 수 없습니다."
            )
            return

        # 백그라운드 블로그 포스팅 발행
        loop = asyncio.get_running_loop()
        publish_results = await loop.run_in_executor(
            None, 
            BlogPublisher.publish_multi_platform, 
            draft["original_url"], 
            draft
        )

        # 결과 텍스트 포맷팅
        result_text = "✨ 블로그 발행 완료!\n"
        if publish_results:
            for platform, url in publish_results.items():
                if platform != "naver_screenshot":
                    result_text += f"- {platform.capitalize()}: {url}\n"
                    
            # 네이버 스크린샷이 존재하면 사진 전송
            screenshot_path = publish_results.get("naver_screenshot")
            if screenshot_path and os.path.exists(screenshot_path):
                try:
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=open(screenshot_path, 'rb'),
                        caption="📸 [네이버 봇 작업 보고서]\n성공적으로 에디터에 작성했습니다!"
                    )
                except Exception as e:
                    print(f"Failed to send screenshot: {e}")
        else:
            result_text += "- 발행 실패 또는 대기중"
            
        # 5단계: 발행 완료 상태 전환 (진행률 100%)
        if task_id:
            db_cache.update_task_status(
                task_id, 
                "발행완료", 
                100, 
                title=draft["title"], 
                original_url=draft["original_url"], 
                platform_results=publish_results
            )
            
        await query.edit_message_text(
            text=f"{query.message.text}\n\n{result_text}",
            disable_web_page_preview=True
        )


def setup_application() -> Application:
    """Application 인스턴스를 생성하고 핸들러를 등록합니다."""
    bot_token = Config.TELEGRAM_BOT_TOKEN
    if not bot_token:
        bot_token = "dummy_token"

    application = ApplicationBuilder().token(bot_token).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("news", news_command))
    application.add_handler(CommandHandler("briefing", briefing_command))
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    
    return application
