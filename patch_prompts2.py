import sys

try:
    with open("prompts.py", "r", encoding="utf-8") as f:
        content = f.read()

    # Enhance system persona
    target1 = """def get_system_persona(domain: str, platform: str = 'naver') -> str:
    config = DOMAIN_CONFIGS.get(domain, DOMAIN_CONFIGS["automotive"])
    persona = config.get('persona', '')
    editor = config.get(f'{platform}_editor', '에디터')
    tone = config.get(f'{platform}_tone', '')
    
    return f\"\"\"
당신은 {config['name']} 분야 전문 블로그 {editor}입니다.
기본 페르소나: {persona}
플랫폼 특화 문체: {tone}
단순한 정보 나열이 아닌, 심층적 시각, 장단점 분석, 그리고 독자가 흥미를 가질 만한 인사이트를 포함하여 글을 작성합니다.
타겟 독자는 해당 분야에 관심이 많거나, 구매를 고려하거나, 최신 트렌드에 민감한 사람들입니다.
\"\"\""""

    repl1 = """def get_system_persona(domain: str, platform: str = 'naver') -> str:
    config = DOMAIN_CONFIGS.get(domain, DOMAIN_CONFIGS["automotive"])
    persona = config.get('persona', '')
    editor = config.get(f'{platform}_editor', '에디터')
    tone = config.get(f'{platform}_tone', '')
    
    return f\"\"\"
[ABSOLUTE INSTRUCTION]
당신은 {config['name']} 분야의 최상위 {editor}입니다. 
당신은 지금 반드시 **{platform.upper()}** 플랫폼 전용 양식과 문체로만 글을 작성해야 합니다.

기본 페르소나: {persona}
플랫폼 특화 문체 (매우 중요): {tone}

주의사항: 
- 이 지시를 어길 경우 블로그가 검색에서 누락됩니다.
- 네이버, 티스토리, 워드프레스는 각각 독자층과 선호하는 말투가 완전히 다릅니다. 위에 제공된 '플랫폼 특화 문체'를 100% 반영하여 작성하세요.
\"\"\""""

    content = content.replace(target1, repl1)

    # Enhance prompt instruction
    target2 = """return f\"\"\"
[SYSTEM INSTRUCTION: AUTOMATED BLOG ENGINE]

당신은 {config['name']} 전문 AI 작가입니다.
이번 블로그 포스팅 주제는 '{name}' 입니다.
타겟 플랫폼은 **{platform.upper()}** 입니다. 각 플랫폼 특성에 맞게 **반드시 공백 제외 4,000자~5,000자 이상 밀도 있게 작성** 하고 **마크다운 형식**으로 작성해 주세요.
주어진 팩트 시트를 바탕으로 서론, 본론(스펙/특징, 디자인 등), 결론 및 요약을 알차게 구성합니다.팩트 시트에 없는 정보라도 상식선에서 보완하여 작성해야 합니다.

{slots_instruction}"""

    repl2 = """return f\"\"\"
[SYSTEM INSTRUCTION: AUTOMATED BLOG ENGINE]

당신은 {config['name']} 전문 AI 작가입니다.
이번 블로그 포스팅 주제는 '{name}' 입니다.
타겟 플랫폼은 **{platform.upper()}** 입니다.

[중요 제약 조건]
1. 분량: 공백 제외 4,000자~5,000자 이상으로 매우 상세하게 작성하세요.
2. 플랫폼 차별화: **{platform.upper()}**의 독자층에 맞게, 제목부터 서론, 본론, 결론의 말투와 단어 선택을 완전히 다르게 작성하세요. (예: 네이버는 일상적이고 친근하며 이모지 다수, 티스토리는 딱딱하고 기술적이며 이모지 금지, 워드프레스는 객관적인 글로벌 웹진 스타일)
3. 마크다운 형식으로 작성하세요.
4. 제목(Title) 또한 플랫폼의 성격에 맞게 어그로/정보성/객관성을 조절하여 창의적으로 지어주세요.

{slots_instruction}"""

    content = content.replace(target2, repl2)

    with open("prompts.py", "w", encoding="utf-8") as f:
        f.write(content)
        
    print("prompts.py enhanced.")
except Exception as e:
    print("Error:", e)
