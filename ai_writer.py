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
    """
    for model in MODEL_FALLBACK_CHAIN:
        for attempt, delay in enumerate([0] + RETRY_DELAYS, start=1):
            if delay > 0:
                msg = f"[WARNING] API 할당량 초과로 {delay}초 후 재시도 중... (모델: {model}, {attempt-1}회차)"
                print(f"[AIWriter] {msg}")
                if status_callback:
                    status_callback(msg)
                time.sleep(delay)

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
                        continue
                    else:
                        print(f"[AIWriter] [WARNING] {model} 모델 재시도 3회 모두 실패. 다음 모델로 폴백합니다.")
                        break
                else:
                    raise e

    raise Exception("모든 모델 폴백 및 재시도가 실패했습니다. 잠시 후 다시 시도해 주세요.")


class AIWriter:
    """
    구글 최신 GenAI SDK + 지능형 재시도 로직을 탑재한 원고 생성기.
    """

    def __init__(self, status_callback=None):
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
            self.client = genai.Client(api_key=self.api_key)
            self.is_configured = True
            print(f"[AIWriter] Google GenAI Client 초기화 성공 (Timeout 미적용). (메인 모델: {MODEL_FALLBACK_CHAIN[0]})")
        except Exception as e:
            print(f"[AIWriter] Google GenAI Client 초기화 실패: {e}")

    def verify_and_filter_images(self, raw_data: str, keyword: str) -> str:
        """
        raw_data 내의 이미지 URL들을 추출하여 Gemini Vision으로 검증합니다.
        Vercel 타임아웃 방지를 위해 최대 2개의 이미지만 검증합니다.
        """
        if not self.is_configured or not self.client:
            return raw_data
            
        import re
        import requests
        
        pattern = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
        matches = pattern.findall(raw_data)
        
        if not matches:
            return raw_data
            
        matches_to_verify = matches[:2]
        valid_urls = []
        
        for alt, url in matches_to_verify:
            try:
                res = requests.get(url, timeout=5)
                if res.status_code != 200:
                    continue
                    
                image_bytes = res.content
                prompt = f"Is the product/object in this image a {keyword}? Answer strictly with YES or NO."
                
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
                    print(f"[AIWriter] 이미지 검증 실패: {url}")
            except Exception as e:
                print(f"[AIWriter] 이미지 검증 에러 ({url}): {e}")
                
        def repl(match):
            match_url = match.group(2)
            if match_url in valid_urls:
                return match.group(0)
            return ""
            
        filtered_data = pattern.sub(repl, raw_data)
        
        if not valid_urls:
            filtered_data += "\n\n[SYSTEM NOTE: 관련 이미지가 모두 검증에 실패하여 제거되었습니다. 원고 작성 시 이미지를 넣지 말고 텍스트로만 구성하세요.]"
            
        return filtered_data

    def extract_fact_sheet(self, raw_data: str) -> str:
        """
        Gemini를 호출하여 입력 텍스트에서 날짜, 제원 수치, 주요 수치, 주요 사건 등의
        사실 정보(Fact)만 추출하여 구조화된 마크다운 리스트 형태로 반환합니다.
        """
        if not self.is_configured or not self.client:
            return raw_data
            
        try:
            print("[AIWriter] 원시 데이터에서 팩트 시트 추출 중...")
            if self.status_callback:
                self.status_callback("원시 데이터 팩트 시트 정제 중...")
                
            prompt = prompts.FACT_EXTRACTION_PROMPT.format(raw_data=raw_data[:20000])
            text = _call_with_retry(
                client=self.client,
                prompt=prompt,
                system_instruction=prompts.get_system_persona("automotive"),
                json_mode=True,
                status_callback=self.status_callback
            )
            
            import re
            cleaned_text = re.sub(r"^```json\s*", "", text.strip(), flags=re.MULTILINE|re.IGNORECASE)
            cleaned_text = re.sub(r"```\s*$", "", cleaned_text.strip(), flags=re.MULTILINE)
            
            data = json.loads(cleaned_text, strict=False)
            facts = data.get("facts", [])
            if facts:
                return "\n".join([f"- {f}" for f in facts])
            return raw_data
        except Exception as e:
            print(f"[AIWriter] 팩트 시트 추출 실패 (원시 데이터 사용): {e}")
            return raw_data

    def _generate_single_platform(self, target_platform: str, raw_data: str, key_name: str, web_images: list, blog_domain: str = "automotive") -> dict:
        if not self.is_configured or not self.client:
            return {
                "title": f"[임시] {target_platform} API Key 미설정",
                "html_content": f"<p>{target_platform} API 키가 없어 생성할 수 없습니다.</p>",
                "markdown_content": f"{target_platform} API 키가 없어 생성할 수 없습니다."
            }
            
        prompt_content = prompts.get_blog_prompt(blog_domain, target_platform, key_name, raw_data)
        system_instruction = prompts.get_system_persona(blog_domain)
        
        text = _call_with_retry(
            client=self.client,
            prompt=prompt_content,
            system_instruction=system_instruction,
            json_mode=True,
            status_callback=self.status_callback,
            max_output_tokens=4096
        )
        
        import re
        
        def parse_ai_json_response(raw_response_text: str) -> dict:
            try:
                cleaned_text = re.sub(r"^```json\s*", "", raw_response_text.strip(), flags=re.MULTILINE|re.IGNORECASE)
                cleaned_text = re.sub(r"```\s*$", "", cleaned_text.strip(), flags=re.MULTILINE)
                return json.loads(cleaned_text, strict=False)
            except json.JSONDecodeError as e:
                print(f"[AIWriter] JSON 파싱 에러 발생 ({target_platform}): {e}")
                
                title_match = re.search(r'"title"\s*:\s*"([^"]+)"', raw_response_text, re.IGNORECASE)
                title = title_match.group(1) if title_match else f"[{target_platform}] 원고 복구본 (형식 오류)"
                
                html_match = re.search(r'"html_content"\s*:\s*"(.*?)"\s*,\s*"markdown_content"', raw_response_text, re.DOTALL | re.IGNORECASE)
                html_text = html_match.group(1) if html_match else ""
                
                md_match = re.search(r'"markdown_content"\s*:\s*"(.*)', raw_response_text, re.DOTALL | re.IGNORECASE)
                if md_match:
                    md_text = md_match.group(1)
                    md_text = re.sub(r'"\s*\}?\s*$', '', md_text)
                else:
                    md_text = raw_response_text
                    
                if not html_text:
                    html_text = md_text

                return {
                    "title": title,
                    "html_content": html_text,
                    "markdown_content": md_text
                }

        result = parse_ai_json_response(text)
        
        html_content = result.get("html_content", "")
        md_content = result.get("markdown_content", "")
        
        html_content = html_content.replace('\\n', '\n')
        md_content = md_content.replace('\\n', '\n')
        
        # 1. 고정 마스코트 GIF 치환
        char_pattern = re.compile(r'\{{1,2}CHAR_([A-Z]+)_([A-Z_]+)_GIF\}{1,2}')
        
        def char_repl_html(match):
            platform = match.group(1)
            pose = match.group(2)
            url = f"https://placehold.co/600x400/eeeeee/333333?text={platform}+{pose}+Mascot"
            return f'<img src="{url}" alt="{platform} {pose} Mascot" style="max-width:100%; height:auto;" />'
            
        def char_repl_md(match):
            platform = match.group(1)
            pose = match.group(2)
            url = f"https://placehold.co/600x400/eeeeee/333333?text={platform}+{pose}+Mascot"
            return f'![{platform} {pose} Mascot]({url})'
            
        html_content = char_pattern.sub(char_repl_html, html_content)
        md_content = char_pattern.sub(char_repl_md, md_content)
        
        # 2. 실물 이미지 동적 매핑 (도메인별 지원)
        img_config = prompts.DOMAIN_CONFIGS.get(blog_domain, prompts.DOMAIN_CONFIGS["automotive"])
        image_tags = img_config["image_tags"]
        
        if not web_images or len(web_images) == 0:
            web_images = ["https://placehold.co/800x450/eeeeee/333333?text=Content+Image"]
            
        tags_mapping = [
            ("ext", "EXTERIOR"),
            ("int", "INTERIOR"),
            ("specs", "SPECS"),
            ("driving", "DRIVING")
        ]
        
        for i, (key, fallback_label) in enumerate(tags_mapping):
            tag_template = image_tags.get(key)
            if tag_template:
                img_url = web_images[i % len(web_images)]
                html_replacement = f'<img src="{img_url}" alt="{key_name} {fallback_label}" style="max-width:100%; height:auto;" />'
                md_replacement = f'![{key_name} {fallback_label}]({img_url})'
                
                html_content = html_content.replace(tag_template, html_replacement)
                md_content = md_content.replace(tag_template, md_replacement)
                
                tag_template_single = tag_template.replace("{{", "{").replace("}}", "}")
                html_content = html_content.replace(tag_template_single, html_replacement)
                md_content = md_content.replace(tag_template_single, md_replacement)
                
        # 3. 찌꺼기 텍스트 태그 방어 (Fallback)
        leftover_pattern = re.compile(r'\{{1,2}[A-Z0-9_]+_REAL_[A-Z0-9_]+\}{1,2}')
        fallback_url = "https://placehold.co/800x450/eeeeee/333333?text=Content+Image"
        html_content = leftover_pattern.sub(f'<img src="{fallback_url}" alt="Placeholder" style="max-width:100%; height:auto;" />', html_content)
        md_content = leftover_pattern.sub(f'![Placeholder]({fallback_url})', md_content)
                
        result["html_content"] = html_content
        result["markdown_content"] = md_content
        
        return result

    def generate_blog_post(self, raw_data: str, keyword: str = "", web_images: list = None, blog_domain: str = "automotive") -> dict:
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
            # 1단계: 팩트 시트 무손실 추출
            fact_sheet = self.extract_fact_sheet(raw_data)

            # 2단계: 이미지 비전 팩트체크
            if keyword:
                if self.status_callback:
                    self.status_callback("이미지 정밀 팩트 체크(Vision) 진행 중...")
                fact_sheet = self.verify_and_filter_images(fact_sheet, keyword)
                
            print(f"[AIWriter] 블로그 원고 병렬 작성 시작 (NAVER, TISTORY, WORDPRESS) - 도메인: {blog_domain}...")
            
            results = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                future_to_platform = {
                    executor.submit(self._generate_single_platform, platform, fact_sheet, keyword, web_images, blog_domain): platform
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
                "title": naver_data.get("title", f"{keyword} 기술 리뷰"),
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

    def generate_telegram_summary(self, title: str, content: str, blog_domain: str = "automotive") -> str:
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
                system_instruction=prompts.get_system_persona(blog_domain),
                json_mode=False,
                status_callback=self.status_callback
            )
            return text

        except Exception as e:
            print(f"[AIWriter] 텔레그램 요약 최종 실패: {e}")
            return f"**[브리핑]** {title}\n\n요약 생성 중 에러가 발생했습니다."

    def analyze_youtube_video(self, youtube_data: dict, status_callback=None) -> dict:
        """유튜브 영상의 자막/설명 데이터를 분석하여 핵심 검색 키워드와 내용 요약을 추출합니다."""
        if not self.is_configured or not self.client:
            return {
                "keyword": "EV",
                "summary": "유튜브 데이터를 분석할 수 없습니다. (Gemini API 미설정)"
            }
            
        try:
            prompt_content = prompts.YOUTUBE_ANALYSIS_PROMPT.format(
                title=youtube_data.get("title", ""),
                description=youtube_data.get("description", ""),
                transcript=youtube_data.get("transcript", "")[:10000]
            )
            
            text = _call_with_retry(
                client=self.client,
                prompt=prompt_content,
                system_instruction=prompts.get_system_persona("automotive"),
                json_mode=True,
                status_callback=status_callback
            )
            
            import re
            cleaned_text = re.sub(r"^```json\s*", "", text.strip(), flags=re.MULTILINE|re.IGNORECASE)
            cleaned_text = re.sub(r"```\s*$", "", cleaned_text.strip(), flags=re.MULTILINE)
            
            return json.loads(cleaned_text, strict=False)
        except Exception as e:
            print(f"[AIWriter] 유튜브 분석 실패: {e}")
            return {
                "keyword": youtube_data.get("title", "EV").split(" ")[0],
                "summary": f"유튜브 분석 에러 발생: {str(e)[:100]}"
            }

    def suggest_trend_keywords(self, blog_domain: str = "automotive") -> list:
        """
        Gemini API를 활용하여 설정된 도메인의 최신 트렌드/이슈 키워드 5개를 추천합니다.
        """
        if not self.is_configured or not self.client:
            return ["전기차", "자율주행", "신차 출시", "친환경차", "SUV"]
            
        try:
            print(f"[AIWriter] {blog_domain} 관련 트렌드 키워드 생성 요청...")
            prompt = prompts.TREND_SUGGESTION_PROMPT.format(domain=blog_domain)
            text = _call_with_retry(
                client=self.client,
                prompt=prompt,
                system_instruction=prompts.get_system_persona(blog_domain),
                json_mode=True,
                status_callback=self.status_callback
            )
            
            import re
            cleaned_text = re.sub(r"^```json\s*", "", text.strip(), flags=re.MULTILINE|re.IGNORECASE)
            cleaned_text = re.sub(r"```\s*$", "", cleaned_text.strip(), flags=re.MULTILINE)
            
            data = json.loads(cleaned_text, strict=False)
            return data.get("keywords", [])
        except Exception as e:
            print(f"[AIWriter] 트렌드 키워드 추천 실패: {e}")
            # Fallback
            if blog_domain == "it_tech":
                return ["M4 MacBook Pro", "iPhone 16", "AI 스마트폰", "ChatGPT", "Nvidia GPU"]
            elif blog_domain == "finance":
                return ["Fed 금리 인하", "주가 시황", "비트코인 시세", "청약 제도", "반도체 주식"]
            elif blog_domain == "health":
                return ["간헐적 단식", "유산균 추천", "코어 운동", "다이어트 식단", "영양제 섭취법"]
            else:
                return ["Toyota GR86", "IONIQ 5 N", "EV9 결함", "BMW iX 시승기", "하이브리드 신차"]
