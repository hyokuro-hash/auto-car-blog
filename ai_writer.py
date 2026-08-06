import json
import time
import urllib.parse
import urllib.request
import urllib.error
import random
import asyncio
import concurrent.futures
from google import genai
from google.genai import types
from config import Config
import prompts

# ─── 모델 우선순위 (무료 티어 할당량이 넉넉한 순서로 배치) ───────────────────
# check_models.py로 확인된 실제 지원 모델 목록 기준
MODEL_FALLBACK_CHAIN = [
    "gemini-3.5-flash",          # 메인 모델 (최신 고속 모델)
    "gemini-3.5-flash-lite",     # 1차 폴백 (초경량 모델, 할당량 넉넉함)
    "gemini-3.6-flash",          # 2차 폴백 (가장 최신 모델)
    "gemini-1.5-flash",          # 3차 폴백 (안정적인 이전 세대 백업)
]

# ─── 재시도 설정 ─────────────────────────────────────────────────────────────
RETRY_DELAYS = [2, 4, 8]         # 429/503 에러 시 대기 시간(초)
THROTTLE_DELAY = 2               # API 호출 직전 최소 대기 시간(초)


def _is_rate_limit_error(e: Exception) -> bool:
    """예외가 429 Rate Limit, 503/504 Service Unavailable, Timeout 에러인지 판별합니다."""
    error_msg = str(e).lower()
    return any(err in error_msg for err in ["429", "resource_exhausted", "503", "504", "unavailable", "timeout", "deadline"])


def _call_with_retry(client, prompt: str, system_instruction: str,
                     json_mode: bool = False,
                     status_callback=None,
                     max_output_tokens: int = 4096) -> str:
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
                msg = f"[WARNING] API 할당량 초과로 {delay}초 후 재시도 중... (모델: {model}, {attempt-1}회차)"
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
                    "max_output_tokens": max_output_tokens,
                }
                if json_mode:
                    config_kwargs["response_mime_type"] = "application/json"

                msg_call = f"API 호출 중... (모델: {model}, 시도: {attempt}회)"
                print(f"[AIWriter] {msg_call}")
                if status_callback:
                    status_callback(msg_call)
                    
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(**config_kwargs)
                )
                print(f"[AIWriter] [SUCCESS] 호출 성공 (모델: {model})")
                return response.text.strip()

            except Exception as e:
                if _is_rate_limit_error(e):
                    if attempt <= len(RETRY_DELAYS):
                        # 다음 루프에서 delay를 적용하여 재시도
                        continue
                    else:
                        # 이 모델에서 3회 모두 실패 → 다음 모델로 폴백
                        print(f"[AIWriter] [WARNING] {model} 모델 재시도 3회 모두 실패. 다음 모델로 폴백합니다.")
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
            self.client = genai.Client(
                api_key=self.api_key,
                http_options={'timeout': 60000}
            )
            self.is_configured = True
            print(f"[AIWriter] Google GenAI Client 초기화 성공. (메인 모델: {MODEL_FALLBACK_CHAIN[0]})")
        except TypeError:
            # http_options 파라미터가 지원되지 않는 구버전 SDK 호환
            self.client = genai.Client(api_key=self.api_key)
            self.is_configured = True
            print(f"[AIWriter] Google GenAI Client 초기화 성공 (Timeout 미적용). (메인 모델: {MODEL_FALLBACK_CHAIN[0]})")
        except Exception as e:
            print(f"[AIWriter] Google GenAI Client 초기화 실패: {e}")

    def verify_and_filter_images(self, raw_data: str, keyword: str) -> str:
        """
        raw_data 내의 이미지 URL들을 추출하여 Gemini Vision으로 검증합니다.
        검증을 통과(YES)한 이미지만 남기고 나머지는 제거합니다.
        Vercel 타임아웃 방지를 위해 최대 2개의 이미지만 검증합니다.
        """
        if not self.is_configured or not self.client:
            return raw_data
            
        import re
        import requests
        
        # 정규식 패턴: ![alt](url)
        pattern = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
        matches = pattern.findall(raw_data)
        
        if not matches:
            return raw_data
            
        # 최대 2개만 검증
        matches_to_verify = matches[:2]
        valid_urls = []
        
        for alt, url in matches_to_verify:
            try:
                # 1. 이미지 다운로드 (메모리)
                res = requests.get(url, timeout=5)
                if res.status_code != 200:
                    continue
                    
                image_bytes = res.content
                
                # 2. Gemini Vision 호출 (가벼운 3.5-flash-lite 사용)
                prompt = f"Is the vehicle in this image a {keyword}? Answer strictly with YES or NO."
                
                response = self.client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=[
                        types.Part.from_bytes(data=image_bytes, mime_type=res.headers.get('Content-Type', 'image/jpeg')),
                        prompt
                    ]
                )
                
                answer = response.text.strip().upper()
                if "YES" in answer:
                    valid_urls.append(url)
                    print(f"[AIWriter] 이미지 검증 통과: {url}")
                else:
                    print(f"[AIWriter] 이미지 검증 실패(차량 불일치): {url}")
            except Exception as e:
                print(f"[AIWriter] 이미지 검증 에러 ({url}): {e}")
                
        # 3. 마크다운 교체 로직
        def repl(match):
            match_url = match.group(2)
            if match_url in valid_urls:
                return match.group(0)
            return ""
            
        filtered_data = pattern.sub(repl, raw_data)
        
        if not valid_urls:
            filtered_data += "\n\n[SYSTEM NOTE: 관련 이미지가 모두 검증에 실패하여 제거되었습니다. 원고 작성 시 이미지를 넣지 말고 텍스트로만 구성하세요.]"
            
        return filtered_data

    def _generate_single_platform(self, target_platform: str, raw_data: str, car_name: str, web_images: list) -> dict:
        prompt_content = prompts.BLOG_POST_PROMPT.format(
            target_platform=target_platform,
            car_name=car_name,
            raw_data=raw_data
        )
        
        text = _call_with_retry(
            client=self.client,
            prompt=prompt_content,
            system_instruction=prompts.SYSTEM_PERSONA,
            json_mode=True,
            status_callback=self.status_callback,
            max_output_tokens=4096
        )
        
        import re
        
        def parse_ai_json_response(raw_response_text: str) -> dict:
            try:
                # 1. 마크다운 코드블록 제거
                cleaned_text = re.sub(r"^```json\s*", "", raw_response_text.strip(), flags=re.MULTILINE|re.IGNORECASE)
                cleaned_text = re.sub(r"```\s*$", "", cleaned_text.strip(), flags=re.MULTILINE)
                
                # 2. JSON 파싱 (strict=False로 제어 문자 허용)
                return json.loads(cleaned_text, strict=False)
            except json.JSONDecodeError as e:
                print(f"[AIWriter] JSON 파싱 에러 발생 ({target_platform}): {e}")
                # 파싱 실패 시 예외 처리: 본문 텍스트 전체를 래핑하여 복구
                return {
                    "title": f"[{target_platform}] 원고 복구본 (형식 오류)",
                    "html_content": f"<p>AI가 응답을 JSON 형식으로 완성하지 못했습니다. 아래 복구된 텍스트를 확인하세요.</p><pre style='white-space: pre-wrap;'>{raw_response_text}</pre>",
                    "markdown_content": f"**AI 응답 형식 오류 복구본**\n\n{raw_response_text}"
                }

        result = parse_ai_json_response(text)
        
        html_content = result.get("html_content", "")
        md_content = result.get("markdown_content", "")
        
        # 1. 고정 마스코트 GIF 치환
        import re
        char_pattern = re.compile(r'\{\{CHAR_([A-Z]+)_([A-Z_]+)_GIF\}\}')
        
        def char_repl_html(match):
            platform = match.group(1)
            pose = match.group(2)
            url = f"https://via.placeholder.com/600x400.png?text={platform}+{pose}+Mascot"
            return f'<img src="{url}" alt="{platform} {pose} Mascot" style="max-width:100%; height:auto;" />'
            
        def char_repl_md(match):
            platform = match.group(1)
            pose = match.group(2)
            url = f"https://via.placeholder.com/600x400.png?text={platform}+{pose}+Mascot"
            return f'![{platform} {pose} Mascot]({url})'
            
        html_content = char_pattern.sub(char_repl_html, html_content)
        md_content = char_pattern.sub(char_repl_md, md_content)
        
        # 2. 실차 이미지 동적 매핑
        real_tags = ["EXTERIOR", "INTERIOR", "SPECS", "DRIVING"]
        
        if not web_images:
            web_images = ["https://via.placeholder.com/800x450.png?text=Auto+Blog+Image"]
            
        for i, tag in enumerate(real_tags):
            placeholder = f"{{{{CAR_REAL_{tag}}}}}"
            if placeholder in html_content or placeholder in md_content:
                img_url = web_images[i % len(web_images)]
                html_replacement = f'<img src="{img_url}" alt="{car_name} {tag}" style="max-width:100%; height:auto;" />'
                md_replacement = f'![{car_name} {tag}]({img_url})'
                html_content = html_content.replace(placeholder, html_replacement)
                md_content = md_content.replace(placeholder, md_replacement)
                
        result["html_content"] = html_content
        result["markdown_content"] = md_content
        
        return result

    def generate_blog_post(self, raw_data: str, keyword: str = "", web_images: list = None) -> dict:
        """수집된 원시 데이터를 바탕으로 블로그용 제목, HTML 본문, 마크다운 본문을 생성합니다."""
        if not self.is_configured or not self.client:
            return {
                "title": "[임시] Gemini API Key 미설정",
                "html_content": "<p>Gemini API 키가 없어 생성할 수 없습니다.</p>",
                "markdown_content": "Gemini API 키가 없어 생성할 수 없습니다."
            }

        if web_images is None:
            web_images = []

        try:
            if keyword:
                if self.status_callback:
                    self.status_callback("이미지 정밀 팩트 체크(Vision) 진행 중...")
                raw_data = self.verify_and_filter_images(raw_data, keyword)
                
            print(f"[AIWriter] 블로그 원고 병렬 작성 시작 (NAVER, TISTORY, WORDPRESS)...")
            
            import concurrent.futures
            
            results = {}
            # 3-way 병렬 API 호출 적용 (return_exceptions=True 형태의 동기적 스레드풀 방어)
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                future_to_platform = {
                    executor.submit(self._generate_single_platform, platform, raw_data, keyword, web_images): platform
                    for platform in ["NAVER", "TISTORY", "WORDPRESS"]
                }
                
                for future in concurrent.futures.as_completed(future_to_platform):
                    platform = future_to_platform[future]
                    try:
                        data = future.result()
                        results[platform.lower()] = data
                    except Exception as e:
                        print(f"[AIWriter] {platform} 생성 중 예외 발생: {e}")
                        results[platform.lower()] = {
                            "title": f"[{platform} 에러] 원고 생성 실패",
                            "html_content": f"<p>생성 실패: {e}</p>",
                            "markdown_content": f"생성 실패: {e}"
                        }
            
            naver_data = results.get("naver", {})
            return {
                "title": naver_data.get("title", f"{keyword} 자동차 리뷰"),
                "naver": naver_data,
                "tistory": results.get("tistory", {}),
                "wordpress": results.get("wordpress", {})
            }

        except Exception as e:
            print(f"[AIWriter] 블로그 원고 최종 실패: {e}")
            error_data = {
                "title": "[에러] 블로그 원고 생성 실패",
                "html_content": f"<p>원고 생성 중 오류가 발생했습니다: {str(e)}</p>",
                "markdown_content": f"원고 생성 중 오류가 발생했습니다: {str(e)}"
            }
            return {
                "title": error_data["title"],
                "naver": error_data,
                "tistory": error_data,
                "wordpress": error_data
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
