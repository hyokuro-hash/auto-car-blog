import json
import requests
from config import Config
import prompts

class AIWriter:
    """구글 Gemini REST API를 직접 호출하여 SDK 버전 호환성 문제 없이 안전하게 원고를 생성합니다."""
    
    def __init__(self):
        self.api_key = Config.GEMINI_API_KEY
        self.is_configured = bool(self.api_key)
        if self.is_configured:
            print("[AIWriter] Gemini REST API 클라이언트 구성 완료.")
        else:
            print("[AIWriter] GEMINI_API_KEY가 구성되지 않았습니다.")

    def _call_gemini_api(self, prompt: str, system_instruction: str = None, json_mode: bool = False) -> str:
        """Gemini v1 REST API 엔드포인트를 직접 POST 호출합니다."""
        # v1 버전의 안정적인 공식 REST API 주소 사용 (v1beta의 모델 누락 문제 원천 방지)
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={self.api_key}"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.7
            }
        }
        
        # 시스템 페르소나 설정이 있다면 주입
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [
                    {"text": system_instruction}
                ]
            }
            
        # JSON 출력 모드 강제 적용 여부
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
            
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                res_data = response.json()
                # JSON 결과 트리 파싱하여 생성 텍스트만 추출
                text = res_data["candidates"][0]["content"]["parts"][0]["text"]
                return text.strip()
            else:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            print(f"[AIWriter] Gemini REST API 호출 에러: {e}")
            raise e

    def generate_blog_post(self, raw_data: str) -> dict:
        """수집된 원시 데이터를 바탕으로 블로그 포스팅 원고를 생성합니다."""
        if not self.is_configured:
            return {
                "title": "[임시] Gemini API Key 미설정",
                "html_content": "<p>Gemini API 키가 없어 생성할 수 없습니다.</p>",
                "markdown_content": "Gemini API 키가 없어 생성할 수 없습니다."
            }

        try:
            prompt_content = prompts.BLOG_POST_PROMPT.format(raw_data=raw_data)
            print("[AIWriter] 블로그 원고 작성 요청 중 (Gemini v1 REST API)...")
            
            response_text = self._call_gemini_api(
                prompt=prompt_content,
                system_instruction=prompts.SYSTEM_PERSONA,
                json_mode=True
            )
            
            result = json.loads(response_text)
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
        if not self.is_configured:
            return f"**[브리핑]** {title}\n\nGemini API 키가 설정되지 않아 상세 브리핑을 생성할 수 없습니다."

        try:
            prompt_content = prompts.TELEGRAM_SUMMARY_PROMPT.format(
                title=title,
                content=content[:3000]  # 컨텍스트 제한 고려
            )
            print("[AIWriter] 텔레그램 브리핑 요약 요청 중 (Gemini v1 REST API)...")
            
            response_text = self._call_gemini_api(
                prompt=prompt_content,
                system_instruction=prompts.SYSTEM_PERSONA,
                json_mode=False
            )
            return response_text
            
        except Exception as e:
            print(f"[AIWriter] 텔레그램 요약 에러: {e}")
            return f"**[브리핑]** {title}\n\n요약 생성 중 에러가 발생했습니다."
