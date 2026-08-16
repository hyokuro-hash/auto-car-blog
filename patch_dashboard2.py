import re
import sys

try:
    with open("templates/dashboard.html", "r", encoding="utf-8") as f:
        content = f.read()

    # --- 4. 렌더링 부분을 renderImageSlots()로 대체 ---
    render_start_marker = """                  let slotsHtml = "";
                  const candidates = data.web_images_candidates || {};"""
    
    render_end_marker = """                      }
                  };
              }"""
                
    rs_idx = content.find(render_start_marker)
    if rs_idx != -1:
        # Find the end of the try block or where it exposes window.skipSlotImage
        skip_fn_idx = content.find("window.skipSlotImage = function(slot) {", rs_idx)
        if skip_fn_idx != -1:
            end_fn_idx = content.find("};", skip_fn_idx)
            re_idx = end_fn_idx + 2
        else:
            # Fallback if skipSlotImage is not there
            re_idx = content.find("          }", rs_idx)

        if "renderImageSlots();" not in content[rs_idx:rs_idx+100]:
            new_render = """                  cachedImageCandidates = data.web_images_candidates || {};
                  renderImageSlots();
                  
                  window.skipSlotImage = function(slot) {
                      const applyAll = document.getElementById('apply-all-platforms')?.checked;
                      if (applyAll) {
                          ['naver', 'tistory', 'wordpress'].forEach(p => selectedImagesData[p][slot] = "");
                      } else {
                          selectedImagesData[currentImagePlatform][slot] = "";
                      }
                      renderImageSlots();
                  };"""
            
            content = content[:rs_idx] + new_render + content[re_idx:]
            print("Render Logic injected.")
        else:
            print("Render logic already injected")

        
    # --- 5. selectSlotImage 수정 ---
    select_fn_start = "        function selectSlotImage(slot, url, element) {"
    select_fn_end = 'ring-2 ring-[#FF4D2D]/30";\n        }'
    
    ss_idx = content.find(select_fn_start)
    se_idx = content.find(select_fn_end)
    
    if ss_idx != -1 and se_idx != -1 and "['naver', 'tistory', 'wordpress']" not in content[ss_idx:se_idx]:
        new_select_fn = """        function selectSlotImage(slot, url, element) {
            const applyAll = document.getElementById('apply-all-platforms')?.checked;
            if (applyAll) {
                ['naver', 'tistory', 'wordpress'].forEach(p => selectedImagesData[p][slot] = url);
            } else {
                selectedImagesData[currentImagePlatform][slot] = url;
            }
            renderImageSlots();
        }"""
        content = content[:ss_idx] + new_select_fn + content[se_idx + len(select_fn_end):]
        print("selectSlotImage injected.")
        
    with open("templates/dashboard.html", "w", encoding="utf-8") as f:
        f.write(content)
        
    print("Done")

except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
