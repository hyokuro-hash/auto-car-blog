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


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/news [키워드] 커맨드 - 즉시 수집 및 AI 포스팅 작성 (실시간 진행률 동기화 적용)"""
    if not context.args:
        await update.message.reply_text("💡 사용법: `/news [차종명 또는 키워드]` (예: `/news IONIQ 5`)", parse_mode="Markdown")
        return

    keyword = " ".join(context.args)
    
    # 강제 재수집 옵션(--force 또는 -f) 적용
    force_collect = False
    if " --force" in keyword or " -f" in keyword:
        force_collect = True
        keyword = keyword.replace(" --force", "").replace(" -f", "").strip()
    
    # 웹 대시보드 상태 모니터링 연동을 위한 고유 Task ID 생성
    task_id = f"task_{int(time.time())}"
    print(f"[TelegramBot] 신규 작업 감지 (Task ID: {task_id}, 키워드: {keyword})")
    
    # 1단계: 수집 시작 기록 (진행률 10%)
    db_cache.update_task_status(task_id, "수집중", 10, title=f"'{keyword}' 관련 수집 중", original_url="")

    status_msg = await update.message.reply_text(f"🔍 '{keyword}' 관련 해외 자동차 뉴스 및 오너 커뮤니티 데이터 수집 중...")

    # 백그라운드 데이터 수집
    loop = asyncio.get_running_loop()
    collected_items = await loop.run_in_executor(None, CarDataCollector.collect_topic_data, keyword, 3)

    if not collected_items:
        db_cache.update_task_status(task_id, "실패", 0, title="수집 데이터 없음")
        await status_msg.edit_text("❌ 수집된 새로운 기사가 없습니다.")
        return

    # 2단계: AI 분석 및 원고 작성 상태 전환 (진행률 40%)
    db_cache.update_task_status(task_id, "AI작성중", 40, title=f"'{keyword}' 뉴스 분석 중")
    await status_msg.edit_text("✍️ Jina Reader 스크래핑 데이터 분석 및 AI 원고 작성 중...")

    # 수집한 원문들 머지 및 중복 필터링
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

    # 3단계: AI 생성 및 결과 캐싱 (진행률 80%)
    db_cache.update_task_status(task_id, "AI작성중", 70, title="AI 초안 작성 마무리 중")
    
    blog_draft = await loop.run_in_executor(None, ai_writer.generate_blog_post, raw_data_text)
    tg_summary = await loop.run_in_executor(
        None, 
        ai_writer.generate_telegram_summary, 
        blog_draft["title"], 
        blog_draft["markdown_content"]
    )

    # 중복 캐시 등록
    for src in source_links:
        db_cache.mark_as_collected(src["url"], src["title"])

    # 웹 대시보드 및 봇 버튼 클릭 시 매핑할 임시 초안 저장
    draft_id = f"draft_{int(time.time())}"
    original_url = source_links[0]["url"] if source_links else "https://news.google.com"
    
    draft_data = {
        "task_id": task_id,
        "title": blog_draft["title"],
        "html_content": blog_draft["html_content"],
        "original_url": original_url
    }
    _save_draft(draft_id, draft_data)

    # 4단계: 발행 대기 상태 전환 (진행률 90%)
    db_cache.update_task_status(
        task_id, 
        "발행대기", 
        90, 
        title=blog_draft["title"], 
        original_url=original_url,
        platform_results={"draft_id": draft_id}
    )

    # 인라인 키보드 생성 (발행 / 반려)
    keyboard = [
        [
            InlineKeyboardButton("🚀 블로그 즉시 발행", callback_data=f"publish_{draft_id}"),
            InlineKeyboardButton("❌ 반려 및 취소", callback_data=f"reject_{draft_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await status_msg.delete()
    await update.message.reply_text(
        f"{tg_summary}\n\n*---\n[임시 초안 ID: {draft_id}]*",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


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
    
    blog_draft = await loop.run_in_executor(None, ai_writer.generate_blog_post, raw_data_text)
    tg_summary = await loop.run_in_executor(
        None, 
        ai_writer.generate_telegram_summary, 
        f"Daily Briefing - {datetime.now().strftime('%Y-%m-%d')}", 
        blog_draft["markdown_content"]
    )
    
    draft_id = f"draft_brief_{int(time.time())}"
    original_url = collected[0]["url"]
    
    _save_draft(draft_id, {
        "task_id": task_id,
        "title": blog_draft["title"],
        "html_content": blog_draft["html_content"],
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
        f"📅 **오늘의 자동차 뉴스 데일리 브리핑**\n\n{tg_summary}",
        reply_markup=reply_markup,
        parse_mode="Markdown"
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
            text=f"{query.message.text}\n\n🔴 **반려되었습니다. (발행 취소)**"
        )
        return
        
    if action == "publish":
        await query.edit_message_text(
            text=f"{query.message.text}\n\n⏳ **블로그 발행 중...**"
        )
        
        if not draft:
            await query.edit_message_text(
                text=f"{query.message.text}\n\n❌ **오류: 초안 세션이 만료되었거나 찾을 수 없습니다.**"
            )
            return

        # 백그라운드 블로그 포스팅 발행
        loop = asyncio.get_running_loop()
        publish_results = await loop.run_in_executor(
            None, 
            BlogPublisher.publish_multi_platform, 
            draft["original_url"], 
            draft["title"], 
            draft["html_content"]
        )

        # 결과 텍스트 포맷팅
        result_text = "🎉 **블로그 발행 완료!**\n"
        if publish_results:
            for platform, url in publish_results.items():
                result_text += f"- **{platform.capitalize()}**: [글 보기]({url})\n"
        else:
            result_text += "- 발행 실패 혹은 임시 Mock 데이터 전송"
            
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
            parse_mode="Markdown",
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
