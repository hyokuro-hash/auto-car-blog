import json
import time
from google import genai
from google.genai import types
from config import Config
import prompts

# ─── 모델 우선순위 (무료 티어 할당량이 넉넉한 순서로 배치) ───────────────────
# check_models.py로 확인된 실제 지원 모델 목록 기준
MODEL_FALLBACK_CHAIN = [
    "gemini-2.0-flash",          # 메인 모델
    "gemini-2.0-flash-lite",     # 1차 폴백 (경량, 할당량 더 넉넉함)
    "gemini-2.5-flash",          # 2차 폴백 (최신 고성능)
]

# ─── 재시도 설정 ─────────────────────────────────────────────────────────────
# Vercel Hobby 플랜 최대 60초 내에서 완주 가능한 딜레이 설정
# 총 최악 소요: 스로틀(2s) + 3회×(딜레이+스로틀2s) = 2 + 3+2 + 5+2 + 8+2 = 24s per model
RETRY_DELAYS = [3, 5, 8]         # 429 에러 시 대기 시간(초): 3 → 5 → 8 (Vercel 60s 제한 고려)
THROTTLE_DELAY = 2               # API 호출 직전 최소 대기 시간(초)


def _is_rate_limit_error(e: Exception) -> bool:
    """예외가 429 Rate Limit / 할당량 초과 에러인지 판별합니다."""
    return "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)


def _call_with_retry(client, prompt: str, system_instruction: str,
                     json_mode: bool = False,
                     status_callback=None) -> str:
    """
    지능형 재시도 + 모델 폴백 로직을 포함한 Gemini API 호출 함수.

    - 429 발생 시: 10초 → 30초 → 60초 대기 후 재시도 (같은 모델)
    - 3회 재시도 후에도 실패 시: 다음 백업 모델로 폴백
    - status_callback(msg): 재시도 상태를 외부(대시보드/텔레그램)에 전달하는 콜백
    """
    for model in MODEL_FALLBACK_CHAIN:
        for attempt, delay in enumerate([0] + RETRY_DELAYS, start=1):
            # 첫 번째 시도가 아닐 때 대기
            if delay > 0:
                msg = f"⚠️ API 할당량 초과로 {delay}초 후 재시도 중... (모델: {model}, {attempt-1}회차)"
                print(f"[AIWriter] {msg}")
                if status_callback:
                    status_callback(msg)
                time.sleep(delay)

            # 호출 전 스로틀링 (RPM 초과 방지)
            if THROTTLE_DELAY > 0:
                time.sleep(THROTTLE_DELAY)

            try:
                config_kwargs = {
                    "system_instruction": system_instruction,
                    "temperature": 0.7,
                }
                if json_mode:
                    config_kwargs["response_mime_type"] = "application/json"

                print(f"[AIWriter] API 호출 중... (모델: {model}, 시도: {attempt}회)")
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(**config_kwargs)
                )
                print(f"[AIWriter] ✅ 호출 성공 (모델: {model})")
                return response.text.strip()

            except Exception as e:
                if _is_rate_limit_error(e):
                    if attempt <= len(RETRY_DELAYS):
                        # 다음 루프에서 delay를 적용하여 재시도
                        continue
                    else:
                        # 이 모델에서 3회 모두 실패 → 다음 모델로 폴백
                        print(f"[AIWriter] ⚠️ {model} 모델 재시도 3회 모두 실패. 다음 모델로 폴백합니다.")
                        break
                else:
                    # 429가 아닌 다른 에러는 즉시 예외 재발생
                    raise e

    raise Exception("모든 모델 폴백 및 재시도가 실패했습니다. 잠시 후 다시 시도해 주세요.")


class AIWriter:
    """
    구글 최신 GenAI SDK + 지능형 재시도 로직을 탑재한 원고 생성기.
    - 429 발생 시 자동 Exponential Backoff 재시도 (10s → 30s → 60s)
    - 재시도 실패 시 백업 모델 자동 폴백
    - API 호출 간 5초 스로틀링 적용
    """

    def __init__(self, status_callback=None):
        """
        Args:
            status_callback: 재시도 상태 메시지를 전달받을 콜백 함수.
                             (예: lambda msg: db.update_task_status(..., title=msg))
        """
        self.api_key = Config.GEMINI_API_KEY
        self.client = None
        self.is_configured = False
        self.status_callback = status_callback
        self._setup()

    def _setup(self):
        if not self.api_key:
            print("[AIWriter] GEMINI_API_KEY가 구성되지 않았습니다.")
            return

        try:
            self.client = genai.Client(api_key=self.api_key)
            self.is_configured = True
            print(f"[AIWriter] Google GenAI Client 초기화 성공. (메인 모델: {MODEL_FALLBACK_CHAIN[0]})")
        except Exception as e:
            print(f"[AIWriter] Google GenAI Client 초기화 실패: {e}")

    def generate_blog_post(self, raw_data: str) -> dict:
        """수집된 원시 데이터를 바탕으로 블로그용 제목, HTML 본문, 마크다운 본문을 생성합니다."""
        if not self.is_configured or not self.client:
            return {
                "title": "[임시] Gemini API Key 미설정",
                "html_content": "<p>Gemini API 키가 없어 생성할 수 없습니다.</p>",
                "markdown_content": "Gemini API 키가 없어 생성할 수 없습니다."
            }

        try:
            prompt_content = prompts.BLOG_POST_PROMPT.format(raw_data=raw_data)
            print(f"[AIWriter] 블로그 원고 작성 시작...")

            text = _call_with_retry(
                client=self.client,
                prompt=prompt_content,
                system_instruction=prompts.SYSTEM_PERSONA,
                json_mode=True,
                status_callback=self.status_callback
            )

            result = json.loads(text)
            return {
                "title": result.get("title", "자동차 뉴스 브리핑"),
                "html_content": result.get("html_content", ""),
                "markdown_content": result.get("markdown_content", "")
            }

        except Exception as e:
            print(f"[AIWriter] 블로그 원고 최종 실패: {e}")
            return {
                "title": "[에러] 블로그 원고 생성 실패",
                "html_content": f"<p>원고 생성 중 오류가 발생했습니다: {str(e)}</p>",
                "markdown_content": f"원고 생성 중 오류가 발생했습니다: {str(e)}"
            }

    def generate_telegram_summary(self, title: str, content: str) -> str:
        """블로그 원고 내용을 기반으로 텔레그램 브리핑 메시지를 생성합니다."""
        if not self.is_configured or not self.client:
            return f"**[브리핑]** {title}\n\nGemini API 키가 설정되지 않아 상세 브리핑을 생성할 수 없습니다."

        try:
            prompt_content = prompts.TELEGRAM_SUMMARY_PROMPT.format(
                title=title,
                content=content[:3000]
            )
            print(f"[AIWriter] 텔레그램 요약 생성 시작...")

            text = _call_with_retry(
                client=self.client,
                prompt=prompt_content,
                system_instruction=prompts.SYSTEM_PERSONA,
                json_mode=False,
                status_callback=self.status_callback
            )
            return text

        except Exception as e:
            print(f"[AIWriter] 텔레그램 요약 최종 실패: {e}")
            return f"**[브리핑]** {title}\n\n요약 생성 중 에러가 발생했습니다."
