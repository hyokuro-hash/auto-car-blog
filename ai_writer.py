import json
from google import genai
from google.genai import types
from config import Config
import prompts

class AIWriter:
    """구글 최신 GenAI SDK를 사용하여 원고를 생성합니다.
    모델: gemini-2.0-flash (현재 API 키에서 지원하는 안정 최신 버전)"""
    
    # 사용할 모델명 (API 키가 지원하는 모델 기준)
    MODEL_NAME = "gemini-2.0-flash"
    
    def __init__(self):
        self.api_key = Config.GEMINI_API_KEY
        self.client = None
        self.is_configured = False
        self._setup()

    def _setup(self):
        if not self.api_key:
            print("[AIWriter] GEMINI_API_KEY가 구성되지 않았습니다.")
            return
        
        try:
            self.client = genai.Client(api_key=self.api_key)
            self.is_configured = True
            print(f"[AIWriter] Google GenAI Client 초기화 성공. (모델: {self.MODEL_NAME})")
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
            print(f"[AIWriter] 블로그 원고 작성 요청 중 ({self.MODEL_NAME})...")
            
            response = self.client.models.generate_content(
                model=self.MODEL_NAME,
                contents=prompt_content,
                config=types.GenerateContentConfig(
                    system_instruction=prompts.SYSTEM_PERSONA,
                    response_mime_type="application/json",
                    temperature=0.7
                )
            )
            
            result = json.loads(response.text.strip())
            return {
                "title": result.get("title", "자동차 뉴스 브리핑"),
                "html_content": result.get("html_content", ""),
                "markdown_content": result.get("markdown_content", "")
            }
            
        except Exception as e:
            print(f"[AIWriter] 블로그 원고 작성 에러: {e}")
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
            
            print(f"[AIWriter] 텔레그램 요약 요청 중 ({self.MODEL_NAME})...")
            response = self.client.models.generate_content(
                model=self.MODEL_NAME,
                contents=prompt_content,
                config=types.GenerateContentConfig(
                    system_instruction=prompts.SYSTEM_PERSONA,
                    temperature=0.7
                )
            )
            return response.text.strip()
            
        except Exception as e:
            print(f"[AIWriter] 텔레그램 요약 에러: {e}")
            return f"**[브리핑]** {title}\n\n요약 생성 중 에러가 발생했습니다."
