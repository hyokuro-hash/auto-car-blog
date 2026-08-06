import json
import google.generativeai as genai
from config import Config
import prompts

class AIWriter:
    """Gemini API를 사용하여 다중 플랫폼용 포스팅 원고를 자동 생성합니다."""
    
    def __init__(self):
        self.api_key = Config.GEMINI_API_KEY
        self.is_configured = False
        self._setup()

    def _setup(self):
        if not self.api_key:
            print("[AIWriter] GEMINI_API_KEY가 구성되지 않았습니다.")
            return
        
        try:
            genai.configure(api_key=self.api_key)
            self.is_configured = True
            print("[AIWriter] Gemini SDK 구성 완료.")
        except Exception as e:
            print(f"[AIWriter] Gemini SDK 초기화 에러: {e}")

    def generate_blog_post(self, raw_data: str) -> dict:
        """
        수집된 원본 데이터를 바탕으로 블로그용 제목, HTML 본문, 마크다운 본문을 생성합니다.
        반환 형식: {"title": str, "html_content": str, "markdown_content": str}
        """
        if not self.is_configured:
            return {
                "title": "[임시] Gemini API Key 미설정",
                "html_content": "<p>Gemini API 키가 없어 생성할 수 없습니다.</p>",
                "markdown_content": "Gemini API 키가 없어 생성할 수 없습니다."
            }

        try:
            # 1.5 Flash 모델 사용 (빠르고 경제적)
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash-latest",
                system_instruction=prompts.SYSTEM_PERSONA
            )
            
            prompt_content = prompts.BLOG_POST_PROMPT.format(raw_data=raw_data)
            
            # JSON 응답 강제 적용
            generation_config = {
                "response_mime_type": "application/json",
                "temperature": 0.7
            }
            
            print("[AIWriter] 블로그 원고 작성 요청 중 (Gemini 1.5 Flash)...")
            response = model.generate_content(
                prompt_content,
                generation_config=generation_config
            )
            
            # JSON 결과 파싱
            result = json.loads(response.text.strip())
            return {
                "title": result.get("title", "자동차 뉴스 브리핑"),
                "html_content": result.get("html_content", ""),
                "markdown_content": result.get("markdown_content", "")
            }
            
        except Exception as e:
            print(f"[AIWriter] 블로그 원고 작성 에러: {e}")
            # 파싱 실패 혹은 오류 발생 시 기본 구조 반환
            return {
                "title": "[에러] 블로그 원고 생성 실패",
                "html_content": f"<p>원고 생성 중 오류가 발생했습니다: {str(e)}</p>",
                "markdown_content": f"원고 생성 중 오류가 발생했습니다: {str(e)}"
            }

    def generate_telegram_summary(self, title: str, content: str) -> str:
        """블로그 원고 내용을 기반으로 텔레그램 브리핑 메시지를 생성합니다."""
        if not self.is_configured:
            return f"**[브리핑]** {title}\n\nGemini API 키가 설정되지 않아 상세 브리핑을 생성할 수 없습니다."

        try:
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash-latest",
                system_instruction=prompts.SYSTEM_PERSONA
            )
            
            prompt_content = prompts.TELEGRAM_SUMMARY_PROMPT.format(
                title=title,
                content=content[:3000]  # 토큰 제한 고려
            )
            
            print("[AIWriter] 텔레그램 브리핑 요약 요청 중...")
            response = model.generate_content(prompt_content)
            return response.text.strip()
            
        except Exception as e:
            print(f"[AIWriter] 텔레그램 요약 에러: {e}")
            return f"**[브리핑]** {title}\n\n요약 생성 중 에러가 발생했습니다."
