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
    """예외가 429 Rate Limit, 503 Service Unavailable 에러인지 판별합니다."""
    error_msg = str(e)
    return "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "503" in error_msg or "UNAVAILABLE" in error_msg


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
                }
                if json_mode:
                    config_kwargs["response_mime_type"] = "application/json"

                print(f"[AIWriter] API 호출 중... (모델: {model}, 시도: {attempt}회)")
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


# ─── SD 차량 일러스트 생성기 ──────────────────────────────────────────────────
def get_sd_image_prompt(car_name: str, pose_type: str) -> str:
    common_style = "thick bold black outlines, heavy line art, cel-shaded webtoon style, comic book style, Nendoroid anime figure illustration, vibrant colors, clean simple background"
    prompts_map = {
        "intro": f"A cute chibi anime car reviewer waving hand with a bright smile next to a cute SD toy version of {car_name}, {common_style}",
        "exterior": f"A cute chibi anime reviewer holding a magnifying glass and pointing at a cute SD version of {car_name}, inspecting exterior, {common_style}",
        "specs": f"A cute chibi anime reviewer with a serious smart expression holding a glowing spec sheet chart next to a cute SD {car_name}, {common_style}",
        "driving": f"A cute chibi anime reviewer sitting inside a cute SD version of {car_name} holding the steering wheel and giving a thumbs up out the window, {common_style}",
        "impressed": f"A cute chibi anime reviewer with sparkling eyes and a super excited expression cheering next to a shiny SD {car_name}, {common_style}",
        "thinking": f"A cute chibi anime reviewer in a thoughtful thinking pose with hand on chin next to a cute SD {car_name}, curious expression, {common_style}",
        "versus": f"A cute chibi anime reviewer standing between two cute SD cars pointing at both with a funny comparing expression, {common_style}",
        "outro": f"A cute chibi anime reviewer sitting on the trunk of a cute SD {car_name} holding a cheerful 'Subscribe & Like' sign, {common_style}"
    }
    return prompts_map.get(pose_type, prompts_map["intro"])

def check_url(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        with urllib.request.urlopen(req, timeout=20.0) as response:
            return response.status == 200
    except Exception as e:
        print(f"[AIWriter] URL 핑 테스트 실패: {e}")
        return False

async def fetch_pollinations_image(car_name: str, pose_type: str) -> dict:
    prompt = get_sd_image_prompt(car_name, pose_type)
    encoded_prompt = urllib.parse.quote(prompt)
    seed = random.randint(1, 999999)
    url = f"https://pollinations.ai/p/{encoded_prompt}?width=1024&height=768&seed={seed}&nologo=true"
    
    try:
        is_valid = await asyncio.to_thread(check_url, url)
        if is_valid:
            print(f"[AIWriter] SD 이미지 생성 성공 ({pose_type})")
            return {"pose": pose_type, "url": url, "success": True}
    except Exception as e:
        print(f"[AIWriter] SD 이미지 생성 실패 ({pose_type}): {e}")
        
    return {"pose": pose_type, "url": "", "success": False}

async def generate_sd_images_concurrently(car_name: str, poses: list) -> dict:
    tasks = [fetch_pollinations_image(car_name, pose) for pose in poses]
    results = await asyncio.gather(*tasks)
    return {res["pose"]: res["url"] for res in results if res["success"]}

def get_sd_images_sync(car_name: str, poses: list) -> dict:
    if not car_name:
        return {}
        
    def _run_in_new_loop():
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            return new_loop.run_until_complete(generate_sd_images_concurrently(car_name, poses))
        finally:
            new_loop.close()
            
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_in_new_loop)
        return future.result()


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

    def generate_blog_post(self, raw_data: str, keyword: str = "") -> dict:
        """수집된 원시 데이터를 바탕으로 블로그용 제목, HTML 본문, 마크다운 본문을 생성합니다."""
        if not self.is_configured or not self.client:
            return {
                "title": "[임시] Gemini API Key 미설정",
                "html_content": "<p>Gemini API 키가 없어 생성할 수 없습니다.</p>",
                "markdown_content": "Gemini API 키가 없어 생성할 수 없습니다."
            }

        try:
            if keyword:
                if self.status_callback:
                    self.status_callback("이미지 정밀 팩트 체크(Vision) 진행 중...")
                raw_data = self.verify_and_filter_images(raw_data, keyword)
                
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
            
            # SD 이미지 생성 및 플레이스홀더 치환
            if keyword:
                if self.status_callback:
                    self.status_callback("SD 합성 일러스트 생성 중...")
                
                poses_needed = ["intro", "exterior", "specs", "driving", "impressed", "thinking", "versus", "outro"]
                sd_images = get_sd_images_sync(keyword, poses_needed)
                
                def replace_sd_placeholders(content: str) -> str:
                    for pose in poses_needed:
                        tag = f"{{{{SD_IMG_{pose.upper()}}}}}"
                        if tag in content:
                            url = sd_images.get(pose, "")
                            if url:
                                # HTML 태그와 Markdown 태그 형식으로 자동 치환 (문맥에 맞게)
                                # 원본 컨텐츠가 마크다운인지 HTML인지에 따라 다르게 주입될 수 있으나,
                                # 통합 처리하기 위해 기본 HTML img 태그로 치환합니다.
                                replacement = f'<img src="{url}" alt="{pose} SD Image" style="max-width:100%; height:auto;" />'
                                content = content.replace(tag, replacement)
                            else:
                                # 생성 실패 시 태그 제거
                                content = content.replace(tag, "")
                    return content
                
                for platform in ["naver", "tistory", "wordpress"]:
                    if platform in result:
                        if "html_content" in result[platform]:
                            result[platform]["html_content"] = replace_sd_placeholders(result[platform]["html_content"])
                        if "markdown_content" in result[platform]:
                            # 마크다운 용 치환
                            md_content = result[platform]["markdown_content"]
                            for pose in poses_needed:
                                tag = f"{{{{SD_IMG_{pose.upper()}}}}}"
                                if tag in md_content:
                                    url = sd_images.get(pose, "")
                                    if url:
                                        replacement = f'![{pose} SD Image]({url})'
                                        md_content = md_content.replace(tag, replacement)
                                    else:
                                        md_content = md_content.replace(tag, "")
                            result[platform]["markdown_content"] = md_content
            
            naver_data = result.get("naver", {})
            return {
                "title": naver_data.get("title", "자동차 뉴스 브리핑"),
                "naver": naver_data,
                "tistory": result.get("tistory", {}),
                "wordpress": result.get("wordpress", {})
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
