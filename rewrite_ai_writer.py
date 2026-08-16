import re
import sys
import json
import urllib.parse

try:
    with open("ai_writer.py", "r", encoding="utf-8") as f:
        content = f.read()

    start_idx = content.find("            # 3. ")
    end_idx = content.find("        except Exception as e:")

    if start_idx == -1 or end_idx == -1:
        print("Markers not found!")
        sys.exit(1)

    new_logic = """            # 3. 이미지 통합 업로드 (플랫폼별 구분)
            if keyword and not drive_images:
                if self.status_callback:
                    self.status_callback("이미지 업로드 체크 수행 중...")
                fact_sheet = self.verify_and_filter_images(fact_sheet, keyword)
                
                if db_cache.drive.is_available and web_images:
                    if self.status_callback:
                        self.status_callback("드라이브에 통합 이미지 업로드 수행 중...")
                    
                    all_unique_urls = {}
                    for plat, imgs in web_images.items():
                        for slot, url in imgs.items():
                            if url and url not in all_unique_urls.values():
                                all_unique_urls[f"{plat}_{slot}"] = url
                                
                    if all_unique_urls:
                        print(f"[AIWriter] 드라이브 통합 병합 업로드: {len(all_unique_urls)}장")
                        uploaded_unique_images = db_cache.drive.upload_images_to_drive(keyword, all_unique_urls, task_id)
                        
                        drive_images = {}
                        for plat, imgs in web_images.items():
                            drive_images[plat] = {}
                            for slot, url in imgs.items():
                                key = f"{plat}_{slot}"
                                drive_images[plat][slot] = uploaded_unique_images.get(key, url)
                        
                        if self.status_callback:
                            self.status_callback(f"이미지 업로드 완료: {len(uploaded_unique_images)}장")

            print(f"[AIWriter] 블로그 원고 작성 시작 (Parallel API Calls)...")
            if self.status_callback:
                self.status_callback("플랫폼별 원고 3개 동시 생성 중 (15~30초 소요)...")

            import concurrent.futures
            import markdown
            import urllib.parse
            import json
            
            platforms = ["naver", "tistory", "wordpress"]
            results = {}
            final_mapped_images = {}
            
            def call_llm_for_platform(platform):
                imgs_for_plat = web_images.get(platform, {})
                dynamic_image_slots = list(imgs_for_plat.keys()) if imgs_for_plat else []
                
                prompt_content = prompts.get_platform_blog_prompt(
                    blog_domain, 
                    platform,
                    keyword or "작성 주제", 
                    fact_sheet,
                    dynamic_slots=dynamic_image_slots,
                    use_mascot=use_mascot
                )
                system_instruction = prompts.get_system_persona(blog_domain, platform)
                
                try:
                    response_text = self._call_with_retry(
                        prompt=prompt_content,
                        system_instruction=system_instruction,
                        json_mode=True,
                        response_schema=BlogDraftResponse,
                        max_output_tokens=8192
                    )
                    
                    cleaned_text = re.sub(r"^```json\\s*", "", response_text.strip(), flags=re.MULTILINE|re.IGNORECASE)
                    cleaned_text = re.sub(r"```\\s*$", "", cleaned_text.strip(), flags=re.MULTILINE)
                    
                    draft_data = json.loads(cleaned_text, strict=False)
                    if isinstance(draft_data, list):
                        draft_data = draft_data[0] if draft_data else {}
                    return draft_data
                except Exception as e:
                    print(f"[{platform}] 생성 실패: {e}")
                    return {"title": f"{keyword} {platform} 리뷰", "markdown_content": f"원고 생성 실패: {e}"}

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                future_to_plat = {executor.submit(call_llm_for_platform, plat): plat for plat in platforms}
                for future in concurrent.futures.as_completed(future_to_plat):
                    plat = future_to_plat[future]
                    results[plat] = future.result()

            final_result = {
                "title": results["naver"].get("title", f"{keyword} 총정리")
            }
            
            responsive_style = (
                "<style>\\n"
                "  .auto-car-blog-post { line-height: 1.85; word-break: keep-all; overflow-wrap: break-word; font-size: 16px; color: #333333; }\\n"
                "  .auto-car-blog-post img { max-width: 100%; height: auto; display: block; margin: 1.5em auto; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }\\n"
                "  .auto-car-blog-post table { width: 100%; border-collapse: collapse; margin: 2em 0; display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }\\n"
                "  .auto-car-blog-post th, .auto-car-blog-post td { border: 1px solid #ddd; padding: 10px 12px; text-align: center; }\\n"
                "  .auto-car-blog-post th { background-color: #f7f7f7; font-weight: bold; }\\n"
                "  @media (max-width: 768px) { .auto-car-blog-post { font-size: 15px; } }\\n"
                "</style>\\n"
            )
            
            for platform in platforms:
                plat_data = results[platform]
                plat_md = plat_data.get("markdown_content", plat_data.get("content", ""))
                plat_title = plat_data.get("title", f"{keyword} 리뷰")
                
                # 마스코트 태그 치환
                plat_md_prep = plat_md.replace("{{CHAR_INTRO_GIF}}", f"{{{{CHAR_{platform.upper()}_INTRO_GIF}}}}")
                plat_md_prep = plat_md_prep.replace("{{CHAR_EXTERIOR_GIF}}", f"{{{{CHAR_{platform.upper()}_EXTERIOR_GIF}}}}")
                plat_md_prep = plat_md_prep.replace("{{CHAR_SPECS_GIF}}", f"{{{{CHAR_{platform.upper()}_SPECS_GIF}}}}")
                plat_md_prep = plat_md_prep.replace("{{CHAR_VERSUS_GIF}}", f"{{{{CHAR_{platform.upper()}_VERSUS_GIF}}}}")
                plat_md_prep = plat_md_prep.replace("{{CHAR_OUTRO_GIF}}", f"{{{{CHAR_{platform.upper()}_OUTRO_GIF}}}}")
                
                plat_html_raw = markdown.markdown(plat_md_prep, extensions=['tables'])
                
                html_content = plat_html_raw.replace('\\n', '\\n')
                md_content = plat_md_prep.replace('\\n', '\\n')
                
                char_pattern = re.compile(r'\\{{1,2}CHAR_([A-Z]+)_([A-Z_]+)_GIF\\}{1,2}')
                
                def char_repl_html(match):
                    plat_char = match.group(1)
                    pose = match.group(2)
                    url = f"https://placehold.co/600x400/eeeeee/333333?text={plat_char}+{pose}+Mascot"
                    return f'<img src="{url}" alt="{plat_char} {pose} Mascot" style="max-width:100%; height:auto;" />'
                    
                def char_repl_md(match):
                    plat_char = match.group(1)
                    pose = match.group(2)
                    url = f"https://placehold.co/600x400/eeeeee/333333?text={plat_char}+{pose}+Mascot"
                    return f'![{plat_char} {pose} Mascot]({url})'
                    
                html_content = char_pattern.sub(char_repl_html, html_content)
                md_content = char_pattern.sub(char_repl_md, md_content)
                
                images_to_use = {}
                if drive_images and isinstance(drive_images, dict) and platform in drive_images:
                    images_to_use = drive_images[platform]
                else:
                    images_to_use = web_images.get(platform, {})
                    
                domain_slots = list(images_to_use.keys()) if images_to_use else []
                
                for slot in domain_slots:
                    url = images_to_use.get(slot)
                    if not url:
                        encoded_kw = urllib.parse.quote(keyword)
                        encoded_slot = urllib.parse.quote(slot)
                        url = f"https://placehold.co/800x450/eeeeee/333333?text={encoded_kw}+{encoded_slot}"
                    
                    if platform == "naver":
                        final_mapped_images[slot] = url
                        
                    html_replacement = f'<img src="{url}" alt="{slot}" style="max-width:100%; height:auto; margin:1rem 0; border-radius:8px;" />'
                    md_replacement = f'![{slot}]({url})'
                    
                    tag_template = f"{{{{{slot}}}}}"
                    html_content = html_content.replace(tag_template, html_replacement)
                    md_content = md_content.replace(tag_template, md_replacement)
                    
                    tag_template_single = f"{{{slot}}}"
                    html_content = html_content.replace(tag_template_single, html_replacement)
                    md_content = md_content.replace(tag_template_single, md_replacement)
                    
                leftover_pattern = re.compile(r'\\{{1,2}[A-Z0-9_]+_REAL_[A-Z0-9_]+\\}{1,2}')
                fallback_url = "https://placehold.co/800x450/eeeeee/333333?text=Content+Image"
                html_content = leftover_pattern.sub(f'<img src="{fallback_url}" alt="Placeholder" style="max-width:100%; height:auto;" />', html_content)
                md_content = leftover_pattern.sub(f'![Placeholder]({fallback_url})', md_content)
                
                if platform == "naver":
                    html_content = f'<div class="auto-car-blog-post" style="line-height: 1.85; word-break: keep-all; overflow-wrap: break-word; font-size: 16px;">\\n{html_content}\\n</div>'
                else:
                    html_content = f'<div class="auto-car-blog-post">\\n{responsive_style}\\n{html_content}\\n</div>'
                    
                final_result[platform] = {
                    "title": plat_title,
                    "html_content": html_content,
                    "markdown_content": md_content
                }
                
            final_result["used_images"] = final_mapped_images
            return final_result

"""

    new_content = content[:start_idx] + new_logic + content[end_idx:]

    with open("ai_writer.py", "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Updated ai_writer.py")

except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
