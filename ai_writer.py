from typing import Optional, Union
import json
import time
import urllib.parse
import urllib.request
import urllib.error
import random
import asyncio
import concurrent.futures
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from config import Config
import prompts

# ─── Pydantic 구조화된 출력 스키마 정의 ──────────────────────────────────────────

class BlogDraftResponse(BaseModel):
    title: str = Field(description="블로그 제목 (후킹 및 SEO 최적화)")
    naver_content: str = Field(description="네이버 블로그 독자를 위한 스토리텔링 중심의 가독성 높은 마크다운 원고")
    tistory_content: str = Field(description="티스토리 블로그 독자를 위한 기술적 깊이와 객관적 팩트 분석 중심의 마크다운 원고")
    wordpress_content: str = Field(description="워드프레스 독자 및 구글 검색 노출(SEO)을 위한 체계적인 계층 구조(H2/H3) 중심의 마크다운 원고")

class YoutubeAnalysisResponse(BaseModel):
    keywords: list[str] = Field(description="구글 뉴스 검색에 사용할 핵심 토픽 키워드 리스트 (영문 명칭 권장)")
    summary: str = Field(description="동영상 트랜스크립트 주요 내용 및 리뷰 요약")

class TrendSuggestionResponse(BaseModel):
    keywords: list[str] = Field(description="최신 핫 트렌드 추천 키워드 5개 목록")

class DynamicImageSlot(BaseModel):
    label: str = Field(description="슬롯의 이름 (예: '거리 전경', '실내 인테리어')")
    query: str = Field(description="검색 엔진에 직접 입력될 구체적인 검색어. {{keyword}}를 반드시 포함하세요. (예: '{{keyword}} 거리 풍경 사진')")

class DynamicImageQueriesResponse(BaseModel):
    slots: list[DynamicImageSlot] = Field(description="키워드에 맞는 블로그 포스팅에 필요한 이미지 구도(슬롯) 및 검색 쿼리 목록. (최소 3개, 최대 5개)")

class FactExtractionResponse(BaseModel):
    facts: list[str] = Field(description="원본에서 추출한 객관적 팩트(수치, 제원 등) 목록")

class SpecsDBSchema(BaseModel):
    model_name: str = Field(description="공식 모델명 (예: 현대 아이오닉 5 2025)")
    price_info: str = Field(description="가격 정보 (예: 5,240만 원 ~ 6,242만 원)")
    performance: str = Field(description="동력 성능 및 출력/토크 (예: 최고 출력 168kW, 최대 토크 350Nm)")
    battery: str = Field(description="배터리 용량 및 주행거리 제원 (예: 84.0kWh 배터리, 1회 충전 주행거리 485km)")
    pros_cons: str = Field(description="주요 장단점 핵심 요약")
    market_review: str = Field(description="대중 및 시장의 오너 평가")

class TranslateResponse(BaseModel):
    translated_text: str = Field(description="한국어로 자연스럽게 번역된 텍스트 본문")
# ─── 모델 우선순위 동적 생성 (Config.GEMINI_MODEL 설정이 있으면 최우선 배치) ─
MODEL_FALLBACK_CHAIN = []
preferred_model = getattr(Config, "GEMINI_MODEL", "gemini-3.1-flash-lite")
if preferred_model:
    MODEL_FALLBACK_CHAIN.append(preferred_model)

for m in ["gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-1.5-flash", "gemini-3.5-flash", "gemini-3.6-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"]:
    if m not in MODEL_FALLBACK_CHAIN:
        MODEL_FALLBACK_CHAIN.append(m)

# ─── 재시도 설정 ─────────────────────────────────────────────────────────────
RETRY_DELAYS = [2, 4, 8]         # 429/503 에러 시 대기 시간(초)
THROTTLE_DELAY = 1               # API 호출 직전 최소 대기 시간(초)


def _is_rate_limit_error(e: Exception) -> bool:
    """예외가 429 Rate Limit, 503/504 Service Unavailable, Timeout 에러인지 판별합니다."""
    error_msg = str(e).lower()
    return any(err in error_msg for err in ["429", "resource_exhausted", "503", "504", "unavailable", "timeout", "deadline"])


class AIWriter:

    def generate_insta_script(self, text: str) -> dict:
        import json
        prompt = f'''
        You are an expert Instagram content creator and marketer.
        Analyze the following text (e.g., YouTube transcript or article) and summarize it into a multi-slide Card News format for the Feed, and matching Story hooks.
        
        Rules:
        1. Feed length: Based on the content length, generate between 5 to 10 short, punchy feed slides. Do not write too much text per slide.
        2. Story hooks: For EVERY feed slide generated, generate exactly ONE matching Story slide. If there are N feed slides, there MUST be exactly N story slides.
        3. Story Strategy: The stories are for attracting non-followers and bringing them to the feed. Use a mix of "Live Now" announcements, curiosity-inducing hooks, and calls to action (e.g., "Check out the full review on our feed!"). Vary the hooks slightly based on the specific feed slide's content.
        4. Caption & Hashtags: Write a highly engaging Instagram Feed Caption (본문) using emojis, spacing, and a strong CTA. Also provide 10-15 relevant hashtags.

        Text to analyze:
        {text[:4000]}

                Output MUST be in strict JSON format. Do not include markdown code blocks.
        {{
            "feed": [
                {{"slide": 1, "text": "Catchy Title/Headline (Max 30 chars)"}},
                {{"slide": 2, "text": "Main Point 1 (Max 40 chars)"}},
                ... (up to 10 slides depending on content)
            ],
            "story": [
                {{"slide": 1, "text": "Hook for slide 1"}},
                ... (must be EXACTLY the same number of slides as feed)
            ],
            "caption": "본문 내용 캡션 작성 (이모지 포함, 줄바꿈 포함)",
            "hashtags": ["자동차", "신차", "리뷰"],
            "search_keyword": "1-2 word English keyword for images"
        }}
        '''
        try:
            # Use the correct wrapper method for the new Google GenAI SDK
            result_text = self._call_with_retry(
                prompt=prompt, 
                system_instruction="You are an expert Instagram content creator.",
                json_mode=True,
                response_schema={"type": "OBJECT", "properties": {
                    "feed": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"slide": {"type": "INTEGER"}, "text": {"type": "STRING"}}}},
                    "story": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"slide": {"type": "INTEGER"}, "text": {"type": "STRING"}}}},
                    "caption": {"type": "STRING"},
                    "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "search_keyword": {"type": "STRING"}
                }}
            )
            
            if result_text.startswith("```json"):
                result_text = result_text.replace("```json", "").replace("```", "").strip()
            if result_text.startswith("```"):
                result_text = result_text.replace("```", "").strip()
            return json.loads(result_text)
        except Exception as e:
            print(f"Insta Script Gen Error: {e}")
            return {
                "feed": [{"slide": i, "text": f"Error: {e}"} for i in range(1, 6)],
                "story": [{"slide": i, "text": f"Error: {e}"} for i in range(1, 6)],
                "search_keyword": "car"
            }

    """
    구글 최신 GenAI SDK + Structured Outputs 로직을 탑재한 원고 생성기.
    """

    def __init__(self, status_callback=None):
        # 쉼표(,)로 구분된 여러 API 키 파싱 지원
        self.api_keys = [k.strip() for k in getattr(Config, "GEMINI_API_KEY", "").split(",") if k.strip()] if getattr(Config, "GEMINI_API_KEY", "") else []
        self.current_key_idx = 0
        self.client = None
        self.is_configured = False
        self.status_callback = status_callback
        self._setup()

    def _setup(self):
        if not self.api_keys:
            print("[AIWriter] GEMINI_API_KEY가 구성되지 않았습니다.")
            return

        api_key = self.api_keys[self.current_key_idx]
        try:
            self.client = genai.Client(
                api_key=api_key,
                http_options={'timeout': 60000}
            )
            self.is_configured = True
            print(f"[AIWriter] Google GenAI Client 초기화 성공. (키 인덱스: {self.current_key_idx}, 메인 모델: {MODEL_FALLBACK_CHAIN[0]})")
        except TypeError:
            self.client = genai.Client(api_key=api_key)
            self.is_configured = True
            print(f"[AIWriter] Google GenAI Client 초기화 성공 (Timeout 미적용). (키 인덱스: {self.current_key_idx}, 메인 모델: {MODEL_FALLBACK_CHAIN[0]})")
        except Exception as e:
            print(f"[AIWriter] Google GenAI Client 초기화 실패: {e}")

    def rotate_key(self) -> bool:
        """API 키 한도 초과 시 다음 키로 로테이션합니다."""
        if len(self.api_keys) <= 1:
            return False
        self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
        msg = f"[AIWriter] API 키 한도 초과로 인해 다음 키로 로테이션합니다. (키: {self.current_key_idx + 1}/{len(self.api_keys)})"
        print(msg)
        if self.status_callback:
            try:
                self.status_callback(msg)
            except Exception as ce:
                print(f"[AIWriter] status_callback 에러 무시: {ce}")
        self._setup()
        return True

    def _call_with_retry(self, prompt: Union[str, list], system_instruction: str,
                         json_mode: bool = False,
                         response_schema=None,
                         max_output_tokens: int = 4096) -> str:
        """
        지능형 재시도 + 모델 폴백 로직 + API 키 자동 로테이션 + Structured Outputs를 지원하는 Gemini API 호출 함수.
        """
        errors = []
        for model in MODEL_FALLBACK_CHAIN:
            # 사용 가능한 키 개수만큼 시도
            keys_to_try = max(len(self.api_keys), 1)
            for key_attempt in range(keys_to_try):
                last_error_was_rate_limit = False
                break_outer = False

                for attempt, delay in enumerate([0] + RETRY_DELAYS, start=1):
                    if delay > 0:
                        msg = f"[WARNING] API 호출 지연 대기 중... {delay}초 후 재시도 (모델: {model}, {attempt-1}회차)"
                        print(f"[AIWriter] {msg}")
                        if self.status_callback:
                            try:
                                self.status_callback(msg)
                            except Exception as ce:
                                print(f"[AIWriter] status_callback 에러 무시: {ce}")
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
                        # [중요] response_schema를 강제하면 5,000자 이상의 긴 마크다운 텍스트 생성 시 빈 문자열을 반환하는 버그가 있으므로 주석 처리합니다.
                        # if response_schema:
                        #     config_kwargs["response_schema"] = response_schema

                        
                        config_kwargs["safety_settings"] = [
                            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
                            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE")
                        ]

                        msg_call = f"API 호출 중... (모델: {model}, 시도: {attempt}회, 키: {self.current_key_idx+1}/{len(self.api_keys)})"
                        print(f"[AIWriter] {msg_call}")
                        if self.status_callback:
                            try:
                                self.status_callback(msg_call)
                            except Exception as ce:
                                print(f"[AIWriter] status_callback 에러 무시: {ce}")
                            
                        response = self.client.models.generate_content(
                            model=model,
                            contents=prompt,
                            config=types.GenerateContentConfig(**config_kwargs)
                        )
                        print(f"[AIWriter] [SUCCESS] 호출 성공 (모델: {model}, 키 인덱스: {self.current_key_idx})")
                        if not response.text:
                            raise Exception(f"응답 텍스트가 비어있습니다. (Safety 차단 가능성): {response}")
                        return response.text.strip()

                    except Exception as e:
                        err_str = str(e)
                        if len(err_str) > 200:
                            err_str = err_str[:200] + "..."
                        err_msg = f"{model} 시도 {attempt}회 (키 {self.current_key_idx+1}): {err_str}"
                        print(f"[AIWriter] [ERROR] {err_msg}")
                        errors.append(err_msg)
                        
                        is_rate_limit = _is_rate_limit_error(e)
                        last_error_was_rate_limit = is_rate_limit
                        
                        # "limit: 0"이 포함되어 있으면 오늘 일일 한도가 만료된 영구 한도 초과 상태이므로,
                        # 동일 키로 재시도 대기를 하지 않고 즉시 다음 키로 전환(Rotate)을 가속화합니다.
                        is_permanent_quota = "limit: 0" in str(e).lower() or "limit:0" in str(e).lower()
                        
                        # 일시적 429 레이트 리밋 등인 경우 내부 재시도 진행 (영구 차단이 아닐 때만)
                        if is_rate_limit and not is_permanent_quota:
                            if attempt < len(RETRY_DELAYS) + 1:
                                continue

                        # 429 에러(한도 초과)이며 다른 여분의 API 키가 있다면 키를 변경하고 동일 모델 재시도
                        if is_rate_limit and len(self.api_keys) > 1:
                            if self.rotate_key():
                                # 새 키로 즉시 같은 모델 재시도를 위해 attempt 루프를 탈출하고
                                # key_attempt 루프의 다음 회차로 넘어갑니다.
                                break

                        # 모델명 404, 지원 만료 혹은 재시도 횟수 초과의 경우 다음 모델로 즉시 폴백
                        print(f"[AIWriter] [WARNING] {model} 오류로 인해 다음 폴백 모델로 넘어갑니다.")
                        break_outer = True
                        break
                else:
                    # attempt 루프가 break 없이 완료된 경우 (즉, 모든 attempt를 다 돌았는데 429로 실패한 경우)
                    # 키가 여러개라면 다음 키를 써서 같은 모델을 시도해볼 수 있도록 로테이션 후 계속 시도
                    if len(self.api_keys) > 1:
                        self.rotate_key()
                        continue
                    break
                # break로 탈출한 경우: 키 로테이션을 시도했거나 모델 스위치
                # rate limit이 아닌 다른 치명적 에러(404 등) 또는 break_outer 플래그가 참이면 이 모델 시도를 전면 종료하고 다음 모델로
                if break_outer or not last_error_was_rate_limit:
                    break

        if errors:
            raise Exception("전체 폴백 모델 오류 로그:\n" + "\n".join(errors))
        raise Exception("모든 모델 폴백 및 재시도가 실패했습니다. 잠시 후 다시 시도해 주세요.")

    def translate_to_korean(self, text: str) -> str:
        """스크랩한 기사 본문을 분석하여 블로그 초안(샘플) 형태의 요약본으로 변환합니다."""
        if not text or not text.strip():
            return text
            
        import re
        # 불필요한 마크다운 링크 [텍스트](URL) 제거하여 토큰 절약 및 AI 혼동 방지
        clean_text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        
        # 앞뒤 불필요한 공백 제거, 텍스트가 너무 길면 적당히 자름 (토큰 한도 보호)
        clean_text = clean_text.strip()[:6000]
            
        sys_msg = "주어진 텍스트를 분석하여, 블로그 포스팅 작성을 위한 '가안(샘플 초안) 형태'로 깔끔하게 정리해 주세요. 단순 번역이 아니라 서론/본론/결론의 흐름이 느껴지도록 재작성하며, 출력결과물에 마크다운 링크(URL)나 불필요한 메뉴/광고 텍스트는 절대 포함하지 마세요."
        
        try:
            res = self._call_with_retry(
                prompt=f"다음 원본 텍스트를 바탕으로 블로그 작성용 샘플 초안 요약을 작성해 주세요:\n\n{clean_text}",
                system_instruction=sys_msg
            )
            return res if res else text
        except Exception as e:
            print(f"[AIWriter] 요약 생성 중 오류: {e}")
            return f"[AI 초안 요약 생성 실패]\n에러: {e}\n\n원본:\n{clean_text[:500]}..."

    def translate_keyword(self, keyword: str, target_lang: str) -> str:
        """검색 키워드를 특정 언어로 번역합니다 (예: en, ja)."""
        if not keyword or not keyword.strip():
            return keyword
            
        sys_msg = f"주어진 키워드를 '{target_lang}' 언어로 번역하세요. 결과로 번역된 단어만 짧게 출력하세요. 부가 설명은 생략하세요."
        
        try:
            res = self._call_with_retry(
                prompt=f"다음 키워드를 번역하세요:\n\n{keyword}",
                system_instruction=sys_msg
            )
            return res.strip() if res else keyword
        except Exception:
            return keyword

    def extract_hot_keyword_from_titles(self, titles: list[str], base_keyword: str = "", domain: str = "universal", past_titles: list[str] = None, force_collect: bool = False) -> str:
        """
        제공된 뉴스 제목(헤드라인) 리스트를 기반으로 가장 핵심적이고 뜨거운 이슈 키워드 1개만 신속하게 추출합니다.
        과거 이력(past_titles)이 주어지면 이를 회피하여 중복 없는 새로운 시각의 키워드를 뽑아냅니다.
        """
        if not titles:
            return "최신뉴스"
            
        titles_text = "\n".join([f"- {t}" for t in titles])
        
        history_instruction = ""
        if past_titles:
            past_text = "\n".join([f"- {t}" for t in past_titles])
            if force_collect:
                history_instruction = (
                    f"We have previously written about the following topics:\n{past_text}\n"
                    f"Since 'Duplicate Prevention' is OFF (Force Collect), you may select a sub-topic related to these, but MUST focus on a DIFFERENT aspect or perspective. (e.g. if we wrote about 'engine defect', choose 'suspension defect' or 'interior updates' instead of engine).\n"
                )
            else:
                history_instruction = (
                    f"CRITICAL WARNING: We have ALREADY extensively covered the following past topics:\n{past_text}\n"
                    f"You MUST extract a COMPLETELY NEW sub-topic that does NOT overlap with the past topics above. Avoid any topic that sounds similar to the past titles.\n"
                )
                
        prompt = (
            f"Here is a list of recent news headlines related to '{base_keyword}':\n{titles_text}\n\n"
            f"{history_instruction}"
            f"Analyze the recent headlines and extract ONLY ONE most trending, critical, or interesting sub-topic keyword/phrase in Korean (e.g., '리콜', '결함', '화재', '시승기', '출시일', '스펙', '가격', '보조금', '디자인', '연비' 등).\n"
            f"CRITICAL: Do NOT extract '{base_keyword}' itself or any part of it (e.g., if base_keyword is '올뉴넥쏘', do NOT extract '넥쏘'). The extracted keyword must be a specific topic or attribute that narrows down the search.\n"
            "Do NOT output any other words, explanations, or sentences. Output exactly one word."
        )
        
        system_instruction = "You are a professional universal content creator. Your goal is to identify the single most trending and novel keyword from the headlines, strictly adhering to the avoidance rules if past history is provided."
        
        try:
            # 1초대 빠른 응답을 위해 max_output_tokens와 temperature를 낮춤
            response = self._call_with_retry(
                prompt=prompt,
                system_instruction=system_instruction,
                max_output_tokens=10
            )
            # 특수문자나 작은따옴표/큰따옴표 정제
            keyword = response.replace("'", "").replace('"', "").replace("[", "").replace("]", "").strip()
            
            # Post-processing: Reject if it's just a part of the base_keyword
            if keyword and base_keyword:
                kw_clean = keyword.replace(" ", "").lower()
                base_clean = base_keyword.replace(" ", "").lower()
                if kw_clean in base_clean or base_clean in kw_clean:
                    print(f"[AIWriter] 거부된 핵심 키워드 (기본 키워드와 유사함): {keyword}")
                    return "최신뉴스"
                    
            print(f"[AIWriter] 추출된 핵심 키워드: {keyword}")
            return keyword if keyword else "최신뉴스"
        except Exception as e:
            print(f"[AIWriter] 키워드 추출 에러 (폴백): {e}")
            return "최신뉴스"

    def generate_dynamic_image_queries(self, keyword: str, hot_kw: str, domain: str = "universal") -> dict:
        """
        주어진 키워드와 핫 키워드, 도메인을 바탕으로 블로그 포스팅에 필요한 이미지 구도(슬롯)와 검색 쿼리를 동적으로 생성합니다.
        """
        prompt = (
            f"주제 키워드: '{keyword}', 관련 핫 이슈/트렌드: '{hot_kw}', "
            f"당신은 블로그 포스팅 기획자입니다. 위 주제로 글을 작성할 때 시각적으로 풍부한 포스팅을 만들기 위해 필요한 '이미지 구도(슬롯)' 3~5개를 기획하세요.\n"
            f"각 슬롯에 대해 짧고 명확한 한글 라벨(label)과, 검색 엔진(Bing/DuckDuckGo)에서 이미지를 찾을 때 사용할 검색 쿼리(query)를 작성하세요.\n"
            f"**주의사항**: 검색 쿼리는 반드시 입력된 키워드의 언어(예: 한국어)를 그대로 유지해야 하며, 영어를 강제하지 마세요. "
            f"원래 키워드에 '사진', '전경', '특징' 등의 자연스러운 검색용 단어만 덧붙이세요.\n"
            f"예시(한국어 지역): {{\"slots\": [{{\"label\": \"거리 전경\", \"query\": \"{keyword} 거리 풍경 사진\"}}, {{\"label\": \"주요 매장\", \"query\": \"{keyword} 유명 카페 외관\"}}]}}\n"
            f"예시(IT 기기): {{\"slots\": [{{\"label\": \"전면 디자인\", \"query\": \"{keyword} 전면 디자인\"}}, {{\"label\": \"상세 스펙\", \"query\": \"{keyword} 상세 리뷰 사진\"}}]}}"
        )
        
        system_instruction = "You are an expert content planner. Output the necessary image slots and their search queries in JSON format exactly matching the DynamicImageQueriesResponse schema."
        
        try:
            response = self._call_with_retry(
                prompt=prompt,
                system_instruction=system_instruction,
                json_mode=True,
                response_schema=DynamicImageQueriesResponse
            )
            # JSON 파싱
            if isinstance(response, str):
                data = json.loads(response)
            else:
                data = response
            
            slots = data.get("slots", [])
            # 기본 폴백 구조화
            if not slots:
                raise ValueError("생성된 슬롯이 없습니다.")
            
            # 딕셔너리로 변환 { "label": "query" }
            queries_dict = {}
            for item in slots[:5]:  # 최대 5개
                label = item.get("label")
                query = item.get("query")
                if label and query:
                    queries_dict[label] = query
            return queries_dict
            
        except Exception as e:
            print(f"[AIWriter] 동적 이미지 쿼리 생성 에러 (폴백 사용): {e}")
            # 에러 발생 시 자동차 기본 폴백 반환
            return {
                "외관 (Exterior)": f"{keyword} official press exterior -rendering -mockup",
                "실내 (Interior)": f"{keyword} interior dashboard cabin steering",
                "제원/세부 (Specifications)": f"{keyword} specifications sheet table",
                "주행/도로 (Driving)": f"{keyword} driving road motion"
            }

    def verify_and_filter_images(self, raw_data: str, keyword: str) -> str:
        """
        raw_data 내의 이미지 URL들을 추출하여 Gemini Vision으로 검증합니다.
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
                prompt_text = f"Is the product/object in this image a {keyword}? Answer strictly with YES or NO."
                
                contents = [
                    types.Part.from_bytes(data=image_bytes, mime_type=res.headers.get('Content-Type', 'image/jpeg')),
                    prompt_text
                ]
                
                answer = self._call_with_retry(
                    prompt=contents,
                    system_instruction=prompts.get_system_persona("universal"),
                    json_mode=False,
                    max_output_tokens=10
                )
                
                answer = answer.strip().upper()
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

    def verify_mapped_images_concurrently(self, keyword: str, mapped_images: dict, domain: str = "universal") -> dict:
        """
        Gemini Vision을 사용하여 웹 검색에서 찾아진 슬롯 매핑 이미지들을 병렬로 고속 분석합니다.
        """
        if not mapped_images:
            return {}
            
        import requests
        from google.genai import types
        import concurrent.futures
        from prompts import IMAGE_DOMAIN_CONFIGS
        
        if domain not in IMAGE_DOMAIN_CONFIGS:
            domain = "universal"
            
        domain_config = IMAGE_DOMAIN_CONFIGS[domain]
        slots = domain_config["slots"]
        vision_prompts = domain_config["vision_prompts"]
        
        print(f"[AIWriter] '{keyword}' 이미지 병렬 비전 검증을 시작합니다...")
        
        def _verify_single_image(slot, url):
            if not url or "placehold.co" in url:
                return slot, url
                
            try:
                res = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.google.com/"})
                if res.status_code != 200:
                    return slot, None
                
                image_bytes = res.content
                prompt_text = f"""
Analyze this image and determine if it represents '{keyword}' AND specifically depicts {vision_prompts[slot]}.
If it's a generic but correct representation (like a close-up, dashboard, or spec sheet) related to the keyword, reasonably accept it.
Output format: Answer strictly with 'valid' or 'invalid' in lowercase.
"""
                contents = [
                    types.Part.from_bytes(data=image_bytes, mime_type=res.headers.get('Content-Type', 'image/jpeg')),
                    prompt_text
                ]
                
                result = self._call_with_retry(
                    prompt=contents,
                    system_instruction="You are a strict image classifier. Output only 'valid' or 'invalid'.",
                    json_mode=False,
                    max_output_tokens=10
                ).strip().lower()
                
                print(f"[AIWriter] {slot} 검증 결과 ({url[:50]}...): {result}")
                
                if result == "valid":
                    return slot, url
                else:
                    return slot, None
            except Exception as e:
                print(f"[AIWriter] {slot} 개별 비전 검증 에러: {e}")
                return slot, None
                
        verified_images = {slot: None for slot in slots}
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_verify_single_image, slot, url): slot for slot, url in mapped_images.items()}
            for future in concurrent.futures.as_completed(futures):
                slot = futures[future]
                try:
                    res_slot, res_url = future.result()
                    verified_images[res_slot] = res_url
                except Exception as e:
                    print(f"[AIWriter] Thread 에러 ({slot}): {e}")
        
        # 유효성 검증 실패 시 플레이스홀더 적용은 Drive Uploader에서 처리하므로 None 유지
        print(f"[AIWriter] 최종 비전 병렬 검증 매핑: {verified_images}")
        return verified_images
            
        import requests
        from google.genai import types
        
        print(f"[AIWriter] '{keyword}' 이미지 {len(image_urls)}개 비전 검증 및 분류를 시작합니다...")
        
        candidates = {
            "ext": [],
            "int": [],
            "specs": [],
            "driving": []
        }
        
        for url in image_urls:
            try:
                res = requests.get(url, timeout=5)
                if res.status_code != 200:
                    continue
                
                image_bytes = res.content
                prompt_text = f"""
Analyze this image and determine:
1. Is it related to the vehicle/object '{keyword}'?
2. If YES, classify it into exactly ONE of the following categories:
   - 'exterior': Outward appearance, body, front/rear/side views of the car.
   - 'interior': Dashboard, seats, steering wheel, steering console, inner cabin.
   - 'specs': Spec sheet, specifications table, charts showing data numbers.
   - 'driving': The car driving on a road, track, or in motion.
   - 'invalid': Not related to '{keyword}', or low quality, or not fitting any of these.

Output format: Answer strictly with the category name ('exterior', 'interior', 'specs', 'driving', 'invalid') in lowercase.
"""
                contents = [
                    types.Part.from_bytes(data=image_bytes, mime_type=res.headers.get('Content-Type', 'image/jpeg')),
                    prompt_text
                ]
                
                category = self._call_with_retry(
                    prompt=contents,
                    system_instruction="You are an expert image classifier. Output only the category: 'image1', 'image2', 'image3', 'image4', or 'invalid'.",
                    json_mode=False,
                    max_output_tokens=15
                ).strip().lower()
                
                print(f"[AIWriter] 이미지 분류 결과 ({url[:60]}...): {category}")
                
                if category in candidates:
                    candidates[category].append(url)
            except Exception as e:
                print(f"[AIWriter] 이미지 개별 분류 에러: {e}")
                
        # 각 슬롯에 분류된 이미지 채우기
        used_urls = set()
        
        for slot in ["ext", "int", "specs", "driving"]:
            if candidates[slot]:
                for c_url in candidates[slot]:
                    if c_url not in used_urls:
                        mapped_images[slot] = c_url
                        used_urls.add(c_url)
                        break
                        
        # 비전 분류에서 매칭되지 않은 슬롯은 Mismatched 이미지 유입을 차단하기 위해 롤백 할당하지 않고 비워둠
        # (비워둔 슬롯은 구글 드라이브 업로더에서 공식 플레이스홀더 이미지로 대체 처리됨)
                
        print(f"[AIWriter] 최종 카테고리 매핑 이미지: {mapped_images}")
        return mapped_images

    def extract_fact_sheet(self, raw_data: str) -> str:
        """
        Gemini를 호출하여 입력 텍스트에서 사실 정보(Fact)만 추출하여 구조화된 마크다운 리스트 형태로 반환합니다.
        """
        if not self.is_configured or not self.client:
            return raw_data
            
        try:
            print("[AIWriter] 원시 데이터에서 팩트 시트 추출 중...")
            if self.status_callback:
                self.status_callback("원시 데이터 팩트 시트 정제 중...")
                
            prompt = prompts.FACT_EXTRACTION_PROMPT.format(raw_data=raw_data[:20000])
            text = self._call_with_retry(
                prompt=prompt,
                system_instruction=prompts.get_system_persona("universal"),
                json_mode=True,
                response_schema=FactExtractionResponse
            )
            
            import re
            cleaned_text = re.sub(r"^```json\s*", "", text.strip(), flags=re.MULTILINE|re.IGNORECASE)
            cleaned_text = re.sub(r"```\s*$", "", cleaned_text.strip(), flags=re.MULTILINE)
            
            data = json.loads(cleaned_text, strict=False)
            if isinstance(data, list):
                data = data[0] if data else {}
            facts = data.get("facts", [])
            if facts:
                return "\n".join([f"- {f}" for f in facts])
            return raw_data
        except Exception as e:
            print(f"[AIWriter] 팩트 시트 추출 실패 (원시 데이터 사용): {e}")
            return raw_data

    def _extract_structured_specs(self, keyword: str, fact_sheet: str) -> dict:
        """팩트 시트에서 SpecsDB 컬럼용 구조화된 제원 정보를 추출합니다."""
        try:
            prompt = f"""
            아래 제공된 팩트 시트 데이터를 바탕으로, 키워드 '{keyword}' 제품의 SpecsDB 구조화된 제원 항목을 추출해 주세요.
            팩트 시트에 명시되어 있지 않은 항목은 비워두지 말고 '정보 없음' 또는 확인된 유추 데이터로 채우십시오.

            데이터:
            {fact_sheet}
            """
            text = self._call_with_retry(
                prompt=prompt,
                system_instruction="당신은 데이터 정제 전문가입니다. 제공된 사실 데이터만을 기반으로 Pydantic 스키마 형식에 맞춰 출력하세요.",
                json_mode=True,
                response_schema=SpecsDBSchema,
                max_output_tokens=1024
            )
            import re
            cleaned_text = re.sub(r"^```json\s*", "", text.strip(), flags=re.MULTILINE|re.IGNORECASE)
            cleaned_text = re.sub(r"```\s*$", "", cleaned_text.strip(), flags=re.MULTILINE)
            data = json.loads(cleaned_text, strict=False)
            if isinstance(data, list):
                data = data[0] if data else {}
            return {
                "공식모델명": data.get("model_name", keyword),
                "가격정보": data.get("price_info", "확인 중"),
                "출력토크": data.get("performance", "확인 중"),
                "배터리제원": data.get("battery", "확인 중"),
                "장단점": data.get("pros_cons", "확인 중"),
                "시장평가": data.get("market_review", "확인 중")
            }
        except Exception as e:
            print(f"[AIWriter] SpecsDB 구조화 추출 실패: {e}")
            return {
                "공식모델명": keyword,
                "가격정보": "확인 중",
                "출력토크": "확인 중",
                "배터리제원": "확인 중",
                "장단점": "확인 중",
                "시장평가": "확인 중"
            }

    def generate_blog_post(self, raw_data: str, keyword: str = "", web_images: dict = None, blog_domain: str = "universal", task_id: str = "", use_mascot: bool = False) -> dict:
        """수집된 원시 데이터를 바탕으로 블로그용 제목, HTML 본문, 마크다운 본문을 생성합니다."""
        if not self.is_configured or not self.client:
            error_data = {
                "title": "[임시] Gemini API Key 미설정",
                "html_content": "<p>Gemini API 키가 없어 생성할 수 없습니다.</p>",
                "markdown_content": "Gemini API 키가 없어 생성할 수 없습니다."
            }
            return {
                "title": error_data["title"],
                "naver": error_data,
                "tistory": error_data,
                "wordpress": error_data
            }

        if web_images is None:
            web_images = {}

        try:
            from db import db_cache
            
            # 1. 구글 드라이브 이미지 조회
            drive_images = None
            if keyword:
                drive_images = db_cache.drive.get_drive_images(keyword)

            # 2. 팩트 시트 추출 (구글 시트 SpecsDB 캐시 우선 조회)
            cached_specs = None
            if keyword:
                cached_specs = db_cache.sheets.get_specs(keyword)

            if cached_specs:
                print(f"[AIWriter] SpecsDB 캐시 히트! AI 스펙 분석 단계를 생략합니다: {keyword}")
                if self.status_callback:
                    self.status_callback("구글 시트 제원 데이터(SpecsDB) 로드 완료.")
                
                # 최신 기사 제목 파싱
                latest_headlines = []
                import re
                headlines = re.findall(r"제목:\s*(.*)", raw_data)
                for h in headlines:
                    h_clean = h.strip()
                    if h_clean and h_clean not in latest_headlines:
                        latest_headlines.append(h_clean)
                
                headline_str = ", ".join(latest_headlines[:3]) if latest_headlines else "없음"
                
                fact_sheet = f"""### {keyword} 핵심 제원 및 요약 정보 (캐시)
- **공식 모델/제품명**: {cached_specs.get('공식모델명', '')}
- **가격/비용 정보**: {cached_specs.get('가격정보', '')}
- **성능/출력 제원**: {cached_specs.get('출력토크', '')}
- **상세/배터리 제원**: {cached_specs.get('배터리제원', '')}
- **핵심 장단점 요약**: {cached_specs.get('장단점', '')}
- **시장 오너 평가**: {cached_specs.get('시장평가', '')}
- **최신 뉴스 헤드라인**: {headline_str}

=======================================================
### 📌 [매우 중요] 최신 수집된 원본 기사 및 상세 데이터 (본문 작성 시 적극 활용)
{raw_data}
=======================================================
"""
            else:
                # 캐시 미스 시 기존 Jina/BS4 팩트 시트 추출 수행
                extracted_facts = self.extract_fact_sheet(raw_data)
                
                # 추출된 제원을 구조화하여 구글 시트 SpecsDB에 라이트백
                if keyword and extracted_facts and extracted_facts != raw_data:
                    print(f"[AIWriter] SpecsDB 캐시 미스! 신규 제원 데이터를 구글 시트에 캐싱합니다: {keyword}")
                    specs_dict = self._extract_structured_specs(keyword, extracted_facts)
                    db_cache.sheets.save_specs(keyword, specs_dict)
                    
                fact_sheet = f"""### {keyword} 추출된 팩트 정보
{extracted_facts}

=======================================================
### 📌 [매우 중요] 최신 수집된 원본 기사 및 상세 데이터 (본문 작성 시 적극 활용)
{raw_data}
=======================================================
"""

            # 3. 이미지 비전 팩트체크 (구글 드라이브 이미지가 없을 때만 DDG + Vision 수행)
            if keyword and not drive_images:
                if self.status_callback:
                    self.status_callback("이미지 정밀 팩트 체크(Vision) 진행 중...")
                fact_sheet = self.verify_and_filter_images(fact_sheet, keyword)
                
            # 구글 드라이브에 자동으로 폴더를 생성하고 다운로드하여 업로드 캐싱 진행
            if keyword and db_cache.drive.is_available and web_images:
                # 사용자가 직접 선택했거나 이미 1차적으로 확정된 이미지이므로 비전 검증을 생략합니다.
                if self.status_callback:
                    self.status_callback("이미지 구글 드라이브 업로드/업데이트 진행 중...")
                print(f"[AIWriter] 구글 드라이브에 '{keyword}' 수집 에셋 폴더 업로드를 확인합니다...")
                
                # web_images 구조(flat/nested) 그대로 db.py에 전달. db.py가 내부적으로 구조를 판단하여 처리함.
                drive_images = db_cache.drive.upload_images_to_drive(keyword, web_images, task_id)
                
                if self.status_callback:
                    self.status_callback(f"이미지 드라이브 연동 완료")

            print(f"[AIWriter] 통합 블로그 원고 작성 시작 (Single API Call) - 도메인: {blog_domain}...")
            
            if self.status_callback:
                self.status_callback("블로그 원고 생성 중...")
                
            is_nested = web_images and any(isinstance(v, dict) for v in web_images.values())
            if is_nested:
                dynamic_image_slots = [k for k, v in web_images.get("naver", {}).items() if v]
            else:
                dynamic_image_slots = [k for k, v in web_images.items() if v] if web_images else []
                
            custom_settings = db_cache.get_prompt_settings()
            
            prompt_content = prompts.get_unified_blog_prompt(
                blog_domain, 
                keyword or "작성 주제", 
                fact_sheet,
                dynamic_slots=dynamic_image_slots,
                use_mascot=use_mascot,
                custom_settings=custom_settings
            )
            system_instruction = prompts.get_system_persona(blog_domain, custom_settings=custom_settings)
            
            # 단 한 번의 호출로 3개 플랫폼 콘텐츠 동시 생성 및 Pydantic 파싱 보장
            response_text = self._call_with_retry(
                prompt=prompt_content,
                system_instruction=system_instruction,
                json_mode=True,
                response_schema=BlogDraftResponse,
                max_output_tokens=8192
            )
            
            import re
            cleaned_text = re.sub(r"^```json\s*", "", response_text.strip(), flags=re.MULTILINE|re.IGNORECASE)
            cleaned_text = re.sub(r"```\s*$", "", cleaned_text.strip(), flags=re.MULTILINE)
            
            draft_data = json.loads(cleaned_text, strict=False)
            
            if isinstance(draft_data, list):
                draft_data = draft_data[0] if draft_data else {}
            
            final_mapped_images = {}
            
            # 이미지 매핑용 헬퍼 함수
            def post_process_content(html_content, md_content, platform_name):
                nonlocal final_mapped_images
                # 개행 문자 복원
                html_content = html_content.replace('\\n', '\n')
                md_content = md_content.replace('\\n', '\n')
                
                # 마스코트 치환
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
                
                # 실물 이미지 동적 매핑
                images_to_use = {}
                is_nested_web = web_images and any(isinstance(v, dict) for v in web_images.values())
                is_nested_drive = drive_images and any(isinstance(v, dict) for v in drive_images.values())

                if is_nested_web:
                    if is_nested_drive:
                        images_to_use = drive_images.get(platform_name) or web_images.get(platform_name)
                    else:
                        images_to_use = drive_images if drive_images else web_images.get(platform_name)
                else:
                    if is_nested_drive:
                        # 사용자는 공통(Flat)을 원하는데 드라이브엔 개별(Nested)로 저장되어 있다면 네이버(또는 첫번째) 것을 공통으로 사용
                        images_to_use = drive_images.get("naver") or drive_images.get(list(drive_images.keys())[0]) or web_images
                    else:
                        images_to_use = drive_images if drive_images else web_images
                
                if not images_to_use:
                    images_to_use = {}
                else:
                    images_to_use = {k: v for k, v in images_to_use.items() if v}
                    
                domain_slots = list(images_to_use.keys())
                
                for slot in domain_slots:
                    tag_template = f"{{{{{slot}}}}}"
                    img_url = images_to_use.get(slot)
                    if not img_url:
                        import urllib.parse
                        encoded_kw = urllib.parse.quote(keyword)
                        encoded_slot = urllib.parse.quote(slot)
                        img_url = f"https://placehold.co/800x450/eeeeee/333333?text={encoded_kw}+{encoded_slot}"
                        
                    # 마크다운 파서가 ~ (strikethrough)나 괄호, 공백 등을 오작동하지 않도록 안전하게 인코딩
                    safe_md_url = img_url.replace("~", "%7E").replace("(", "%28").replace(")", "%29").replace(" ", "%20")
                    
                    html_replacement = f'<img src="{img_url}" alt="{keyword} {slot}" style="max-width:100%; height:auto;" />'
                    md_replacement = f'![{keyword} {slot}]({safe_md_url})'
                    
                    html_content = html_content.replace(tag_template, html_replacement)
                    md_content = md_content.replace(tag_template, md_replacement)
                    
                    # 싱글 브라켓 태그 방어
                    tag_template_single = tag_template.replace("{{", "{").replace("}}", "}")
                    html_content = html_content.replace(tag_template_single, html_replacement)
                    md_content = md_content.replace(tag_template_single, md_replacement)

                # 플랫폼별로 이미지가 분리되어 있는 경우, 플랫폼별로 매핑 이미지를 저장
                if is_nested_web or is_nested_drive:
                    if platform_name not in final_mapped_images:
                        final_mapped_images[platform_name] = {}
                    for slot in domain_slots:
                        url = images_to_use.get(slot)
                        if not url:
                            import urllib.parse
                            encoded_kw = urllib.parse.quote(keyword)
                            encoded_slot = urllib.parse.quote(slot)
                            url = f"https://placehold.co/800x450/eeeeee/333333?text={encoded_kw}+{encoded_slot}"
                        final_mapped_images[platform_name][slot] = url
                else:
                    # 첫 번째 플랫폼 렌더링 시에만 최종 매핑 이미지 목록을 저장 (슬롯 순서 엄격히 유지)
                    if not final_mapped_images:
                        for slot in domain_slots:
                            url = images_to_use.get(slot)
                            if not url:
                                import urllib.parse
                                encoded_kw = urllib.parse.quote(keyword)
                                encoded_slot = urllib.parse.quote(slot)
                                url = f"https://placehold.co/800x450/eeeeee/333333?text={encoded_kw}+{encoded_slot}"
                            final_mapped_images[slot] = url

                        
                # 찌꺼기 텍스트 태그 방어 (Fallback)
                leftover_pattern = re.compile(r'\{{1,2}[A-Z0-9_]+_REAL_[A-Z0-9_]+\}{1,2}')
                fallback_url = "https://placehold.co/800x450/eeeeee/333333?text=Content+Image"
                html_content = leftover_pattern.sub(f'<img src="{fallback_url}" alt="Placeholder" style="max-width:100%; height:auto;" />', html_content)
                md_content = leftover_pattern.sub(f'![Placeholder]({fallback_url})', md_content)
                
                return html_content, md_content
                
            # Naver, Tistory, WordPress 각 본문 가공
            import markdown
            
            naver_md = draft_data.get("naver_content", "")
            tistory_md = draft_data.get("tistory_content", "")
            wordpress_md = draft_data.get("wordpress_content", "")
            
            master_md = draft_data.get("markdown_content", "")
            if not master_md or not master_md.strip():
                master_md = draft_data.get("content", "")
            if not master_md or not master_md.strip():
                # 최후의 수단: 딕셔너리 내부를 재귀적으로 탐색하여 가장 긴 텍스트 값을 본문으로 사용
                def extract_longest_string(obj):
                    longest = ""
                    if isinstance(obj, str):
                        return obj
                    elif isinstance(obj, dict):
                        for v in obj.values():
                            val = extract_longest_string(v)
                            if len(val) > len(longest):
                                longest = val
                    elif isinstance(obj, list):
                        for item in obj:
                            val = extract_longest_string(item)
                            if len(val) > len(longest):
                                longest = val
                    return longest
                master_md = extract_longest_string(draft_data)
                
            naver_md = naver_md if naver_md.strip() else master_md
            tistory_md = tistory_md if tistory_md.strip() else master_md
            wordpress_md = wordpress_md if wordpress_md.strip() else master_md
            
            naver_title = draft_data.get("naver_title", "") or draft_data.get("title", "")
            tistory_title = draft_data.get("tistory_title", "") or draft_data.get("title", "")
            wordpress_title = draft_data.get("wordpress_title", "") or draft_data.get("title", "")
            
            if not naver_title:
                # 중첩 구조에서 명시적인 title 찾기
                def extract_title(obj, target_key):
                    if isinstance(obj, dict):
                        if target_key in obj and isinstance(obj[target_key], str) and obj[target_key].strip():
                            return obj[target_key]
                        if "title" in obj and isinstance(obj["title"], str) and obj["title"].strip():
                            return obj["title"]
                        for v in obj.values():
                            res = extract_title(v, target_key)
                            if res: return res
                    return ""
                naver_title = extract_title(draft_data, "naver_title")
                tistory_title = extract_title(draft_data, "tistory_title")
                wordpress_title = extract_title(draft_data, "wordpress_title")
                
                if not naver_title:
                    # 딕셔너리에서 제목스러운 짧은 문자열 찾기
                    def find_short_string(obj):
                        if isinstance(obj, str) and 5 < len(obj) < 100:
                            return obj
                        if isinstance(obj, dict):
                            for k, v in obj.items():
                                if k not in ("markdown_content", "content", "naver_content", "tistory_content", "wordpress_content"):
                                    res = find_short_string(v)
                                    if res: return res
                        return ""
                    naver_title = find_short_string(draft_data)
                    
                if not naver_title:
                    naver_title = f"{keyword} 전문 분석"
                    
            # Fallback for tistory and wp titles if they are still empty
            if not tistory_title: tistory_title = naver_title
            if not wordpress_title: wordpress_title = naver_title

            # 1. 각 플랫폼 전용 태그로 치환 (GIF 마스코트용)
            def prepare_platform_tags(text, platform):
                plat_upper = platform.upper()
                text = text.replace("{{CHAR_INTRO_GIF}}", f"{{{{CHAR_{plat_upper}_INTRO_GIF}}}}")
                text = text.replace("{{CHAR_EXTERIOR_GIF}}", f"{{{{CHAR_{plat_upper}_EXTERIOR_GIF}}}}")
                text = text.replace("{{CHAR_SPECS_GIF}}", f"{{{{CHAR_{plat_upper}_SPECS_GIF}}}}")
                text = text.replace("{{CHAR_VERSUS_GIF}}", f"{{{{CHAR_{plat_upper}_VERSUS_GIF}}}}")
                text = text.replace("{{CHAR_OUTRO_GIF}}", f"{{{{CHAR_{plat_upper}_OUTRO_GIF}}}}")
                return text

            naver_md_prep = prepare_platform_tags(naver_md, "naver")
            tistory_md_prep = prepare_platform_tags(tistory_md, "tistory")
            wordpress_md_prep = prepare_platform_tags(wordpress_md, "wp")

            n_html_raw = markdown.markdown(naver_md_prep, extensions=['tables'])
            t_html_raw = markdown.markdown(tistory_md_prep, extensions=['tables'])
            w_html_raw = markdown.markdown(wordpress_md_prep, extensions=['tables'])

            n_html, n_md = post_process_content(n_html_raw, naver_md_prep, "naver")
            t_html, t_md = post_process_content(t_html_raw, tistory_md_prep, "tistory")
            w_html, w_md = post_process_content(w_html_raw, wordpress_md_prep, "wordpress")
            
            # 모바일/태블릿/폴더블용 반응형 스타일 래퍼 적용
            responsive_style = (
                "<style>\n"
                "  .auto-car-blog-post { line-height: 1.85; word-break: keep-all; overflow-wrap: break-word; font-size: 16px; color: #333333; }\n"
                "  .auto-car-blog-post img { max-width: 100%; height: auto; display: block; margin: 1.5em auto; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }\n"
                "  .auto-car-blog-post table { width: 100%; border-collapse: collapse; margin: 2em 0; display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }\n"
                "  .auto-car-blog-post th, .auto-car-blog-post td { border: 1px solid #ddd; padding: 10px 12px; text-align: center; }\n"
                "  .auto-car-blog-post th { background-color: #f7f7f7; font-weight: bold; }\n"
                "  @media (max-width: 768px) { .auto-car-blog-post { font-size: 15px; } }\n"
                "</style>\n"
            )
            
            n_html = f'<div class="auto-car-blog-post" style="line-height: 1.85; word-break: keep-all; overflow-wrap: break-word; font-size: 16px;">\n{n_html}\n</div>'
            t_html = f'<div class="auto-car-blog-post">\n{responsive_style}\n{t_html}\n</div>'
            w_html = f'<div class="auto-car-blog-post">\n{responsive_style}\n{w_html}\n</div>'
            
            return {
                "title": naver_title,
                "naver": {
                    "title": naver_title,
                    "html_content": n_html,
                    "markdown_content": n_md
                },
                "tistory": {
                    "title": tistory_title,
                    "html_content": t_html,
                    "markdown_content": t_md
                },
                "wordpress": {
                    "title": wordpress_title,
                    "html_content": w_html,
                    "markdown_content": w_md
                },
                "used_images": final_mapped_images
            }

        except Exception as e:
            print(f"[AIWriter] 블로그 원고 최종 실패: {e}")
            error_data = {
                "title": "[에러] 블로그 원고 생성 실패",
                "html_content": f"<div style='white-space: pre-wrap; font-family: Consolas, monospace; font-size: 12px; text-align: left; background-color: #1e1e1e; color: #f4f4f4; padding: 15px; border-radius: 8px; max-height: 450px; overflow-y: auto;'>[원고 생성 중 오류가 발생했습니다]\n\n{str(e)}</div>",
                "markdown_content": f"원고 생성 중 오류가 발생했습니다:\n\n{str(e)}"
            }
            return {
                "title": error_data["title"],
                "naver": error_data,
                "tistory": error_data,
                "wordpress": error_data
            }

    def generate_telegram_summary(self, title: str, content: str, blog_domain: str = "universal") -> str:
        """블로그 원고 내용을 기반으로 텔레그램 브리핑 메시지를 생성합니다."""
        if not self.is_configured or not self.client:
            return f"**[브리핑]** {title}\n\nGemini API 키가 설정되지 않아 상세 브리핑을 생성할 수 없습니다."

        try:
            prompt_content = prompts.TELEGRAM_SUMMARY_PROMPT.format(
                title=title,
                content=content[:3000]
            )
            print(f"[AIWriter] 텔레그램 요약 생성 시작...")

            text = self._call_with_retry(
                prompt=prompt_content,
                system_instruction=prompts.get_system_persona(blog_domain),
                json_mode=False
            )
            return text

        except Exception as e:
            print(f"[AIWriter] 텔레그램 요약 최종 실패: {e}")
            return f"**[브리핑]** {title}\n\n요약 생성 중 에러가 발생했습니다."

    def analyze_youtube_video(self, youtube_data: dict, status_callback=None) -> dict:
        """유튜브 영상의 자막/설명 데이터를 분석하여 핵심 검색 키워드 목록과 내용 요약을 추출합니다."""
        if not self.is_configured or not self.client:
            return {
                "keywords": ["EV"],
                "summary": "유튜브 데이터를 분석할 수 없습니다. (Gemini API 미설정)"
            }
            
        try:
            prompt_content = prompts.YOUTUBE_ANALYSIS_PROMPT.format(
                title=youtube_data.get("title", ""),
                description=youtube_data.get("description", ""),
                transcript=youtube_data.get("transcript", "")[:10000]
            )
            
            old_callback = self.status_callback
            self.status_callback = status_callback
            try:
                text = self._call_with_retry(
                    prompt=prompt_content,
                    system_instruction=prompts.get_system_persona("universal"),
                    json_mode=True,
                    response_schema=YoutubeAnalysisResponse
                )
            finally:
                self.status_callback = old_callback
            
            import re
            cleaned_text = re.sub(r"^```json\s*", "", text.strip(), flags=re.MULTILINE|re.IGNORECASE)
            cleaned_text = re.sub(r"```\s*$", "", cleaned_text.strip(), flags=re.MULTILINE)
            
            return json.loads(cleaned_text, strict=False)
        except Exception as e:
            print(f"[AIWriter] 유튜브 분석 실패: {e}")
            return {
                "keywords": [youtube_data.get("title", "EV").split(" ")[0]],
                "summary": f"유튜브 분석 에러 발생: {str(e)[:100]}"
            }

    def suggest_trend_keywords(self, blog_domain: str = "universal") -> list:
        """
        Gemini API를 활용하여 설정된 도메인의 최신 트렌드/이슈 키워드 5개를 추천합니다.
        """
        if not self.is_configured or not self.client:
            return ["전기차", "자율주행", "신차 출시", "친환경차", "SUV"]
            
        try:
            print(f"[AIWriter] {blog_domain} 관련 트렌드 키워드 생성 요청...")
            prompt = prompts.TREND_SUGGESTION_PROMPT.format(domain=blog_domain)
            text = self._call_with_retry(
                prompt=prompt,
                system_instruction=prompts.get_system_persona(blog_domain),
                json_mode=True,
                response_schema=TrendSuggestionResponse
            )
            
            import re
            cleaned_text = re.sub(r"^```json\s*", "", text.strip(), flags=re.MULTILINE|re.IGNORECASE)
            cleaned_text = re.sub(r"```\s*$", "", cleaned_text.strip(), flags=re.MULTILINE)
            
            data = json.loads(cleaned_text, strict=False)
            if isinstance(data, list):
                data = data[0] if data else {}
            return data.get("keywords", [])
        except Exception as e:
            print(f"[AIWriter] 트렌드 키워드 추천 실패: {e}")
            if blog_domain == "it_tech":
                return ["M4 MacBook Pro", "iPhone 16", "AI 스마트폰", "ChatGPT", "Nvidia GPU"]
            elif blog_domain == "finance":
                return ["Fed 금리 인하", "주가 시황", "비트코인 시세", "청약 제도", "반도체 주식"]
            elif blog_domain == "health":
                return ["간헐적 단식", "유산균 추천", "코어 운동", "다이어트 식단", "영양제 섭취법"]
            else:
                return ["Toyota GR86", "IONIQ 5 N", "EV9 결함", "BMW iX 시승기", "하이브리드 신차"]

    def edit_sentence_ai(self, context: str, target_text: str, instruction: str, domain: str = "universal") -> str:
        """
        Gemini를 호출하여 특정 문맥 내의 지정된 대상 문장을 사용자의 요청 사항에 맞춰 수정 및 보강합니다.
        """
        if not self.is_configured or not self.client:
            return target_text
            
        try:
            print(f"[AIWriter] AI 부분 문장 수정 요청... 대상 텍스트: {target_text[:30]}...")
            if self.status_callback:
                self.status_callback("AI 부분 문장 수정 중...")
                
            prompt = prompts.AI_SENTENCE_EDIT_PROMPT.format(
                domain=domain,
                context=context[:6000],
                target_text=target_text,
                instruction=instruction
            )
            
            text = self._call_with_retry(
                prompt=prompt,
                system_instruction=prompts.get_system_persona(domain),
                json_mode=False,
                max_output_tokens=2048
            )
            
            cleaned = text.strip()
            if cleaned.startswith('"') and cleaned.endswith('"'):
                cleaned = cleaned[1:-1].strip()
            if cleaned.startswith("'") and cleaned.endswith("'"):
                cleaned = cleaned[1:-1].strip()
                
            return cleaned
        except Exception as e:
            print(f"[AIWriter] AI 부분 문장 수정 실패: {e}")
            return target_text
