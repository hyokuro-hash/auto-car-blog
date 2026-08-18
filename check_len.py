import json
with open('drafts_cache.json', encoding='utf-8') as f:
    data = json.load(f)
if not data:
    print("No drafts found")
else:
    latest_id = list(data.keys())[-1]
    draft = data[latest_id]
    print(f"Latest Draft ID: {latest_id}")
    for plat in ['naver', 'tistory', 'wordpress']:
        plat_data = draft.get(plat)
        if plat_data:
            md_content = plat_data.get('markdown_content', '')
            print(f"{plat}: {len(md_content)} chars")
        else:
            print(f"{plat}: Not found")
