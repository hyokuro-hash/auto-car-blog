import sys

try:
    with open("prompts.py", "r", encoding="utf-8") as f:
        content = f.read()
        
    old_naver_tone = """"naver_tone": "친근하고 생동감 있는 표현과 해요체('~입니다', '~합니다')를 혼용하되 유머러스한 느낌. 간간히 '~죠!' 말투를 섞어주고 이모지를 많이 사용","""
    new_naver_tone = """"naver_tone": "이모지를 적극적으로 과할 정도로 사용(제목과 본문 곳곳에 삽입). 매우 친근하고 감성적인 이웃 블로거 말투. 일상적인 활용도와 체감 위주로 설명. 문장을 짧게 끊어 가독성을 높임. '~요', '~죠' 등의 해요체와 해요체를 섞어 씀.","""
    
    old_tistory_tone = """"tistory_tone": "논리적이고 객관적인 정보 전달 중심. 전문적이고 분석적인 톤. 불필요한 감정 표현과 이모지 사용을 자제하고 신뢰감이 느껴지는 어투","""
    new_tistory_tone = """"tistory_tone": "이모지 사용 절대 금지. 극도로 전문적이고 기술적인 테크/자동차 엔지니어 톤. 객관적인 수치, 스펙, 벤치마크 데이터를 깊이 있게 분석. 문장은 격식 있는 '~다', '~음' 으로 종결. 논리적 인과관계 명확히 설명.","""
    
    old_wp_tone = """"wp_tone": "저널리즘 스타일의 객관적인 칼럼니스트/에디터 톤. Google SEO 최적화를 위해 H2/H3 태그를 엄격히 구분하여 사용","""
    new_wp_tone = """"wp_tone": "이모지 사용 자제. 글로벌 IT/자동차 웹진의 객관적이고 중립적인 에디터 리뷰 톤. 명확한 장단점 분석과 SEO 최적화를 위한 H2/H3 태그 사용. 군더더기 없는 세련된 문체.","""
    
    content = content.replace(old_naver_tone, new_naver_tone)
    content = content.replace(old_tistory_tone, new_tistory_tone)
    content = content.replace(old_wp_tone, new_wp_tone)
    
    # IT/tech
    old_it_naver = """"naver_tone": "친밀하고 톡톡 튀는 IT 리뷰어 톤. 해요체('~입니다', '~합니다')를 혼용하되 유머러스한 느낌. 간간히 '~죠!' 또는 '~요!' 말투를 섞어주고 이모지 사용","""
    new_it_naver = """"naver_tone": "이모지 과다 사용. 언박싱하듯 신나는 말투. 실사용 리뷰 위주의 친근한 말투.","""
    
    old_it_tistory = """"tistory_tone": "IT 기기 스펙 분석, 벤치마크 점수, 아키텍처 구조, 디스플레이 특성 등을 심층적이고 전문적으로 분석하는 톤","""
    new_it_tistory = """"tistory_tone": "이모지 금지. 극도로 전문적인 IT 긱(Geek) 수준의 스펙/벤치마크 분석. 딱딱하지만 신뢰도 높은 '~다'체 사용.","""
    
    old_it_wp = """"wp_tone": "해외 테크 매거진 스타일의 글로벌 IT 트렌드 리포트 칼럼/리뷰 톤. H2/H3 태그를 엄격히 구분하여 사용","""
    new_it_wp = """"wp_tone": "이모지 자제. 더 버지(The Verge) 스타일의 정제된 웹진 리뷰. 명확한 소제목과 결론 도출.","""
    
    content = content.replace(old_it_naver, new_it_naver)
    content = content.replace(old_it_tistory, new_it_tistory)
    content = content.replace(old_it_wp, new_it_wp)

    with open("prompts.py", "w", encoding="utf-8") as f:
        f.write(content)
        
    print("prompts.py updated.")
except Exception as e:
    print("Error:", e)
