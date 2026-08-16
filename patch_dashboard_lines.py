import sys

try:
    with open("templates/dashboard.html", "r", encoding="utf-8") as f:
        lines = f.readlines()

    start_idx = -1
    end_idx = -1

    # Find start
    for i, line in enumerate(lines):
        if "// Render image slots candidate selectors" in line:
            start_idx = i
            break
            
    # Find end
    if start_idx != -1:
        for i in range(start_idx, len(lines)):
            if "window.skipSlotImage = function(slot)" in lines[i]:
                # find the closing braces
                brace_count = 0
                found_start = False
                for j in range(i, len(lines)):
                    if "{" in lines[j]:
                        brace_count += lines[j].count("{")
                        found_start = True
                    if "}" in lines[j]:
                        brace_count -= lines[j].count("}")
                    if found_start and brace_count == 0:
                        # include next two lines which are closing the modal block maybe? No, just replace up to this block
                        end_idx = j
                        break
                break

    if start_idx != -1 and end_idx != -1:
        new_render = """                // Render image slots candidate selectors
                cachedImageCandidates = data.web_images_candidates || {};
                renderImageSlots();
                
                // Expose skip function globally
                window.skipSlotImage = function(slot) {
                    const applyAll = document.getElementById('apply-all-platforms')?.checked;
                    if (applyAll) {
                        ['naver', 'tistory', 'wordpress'].forEach(p => selectedImagesData[p][slot] = "");
                    } else {
                        selectedImagesData[currentImagePlatform][slot] = "";
                    }
                    renderImageSlots();
                };
"""
        
        lines = lines[:start_idx] + [new_render] + lines[end_idx+1:]
        
        with open("templates/dashboard.html", "w", encoding="utf-8") as f:
            f.writelines(lines)
            
        print("Render Logic replaced.")
    else:
        print("Could not find start or end index.")

except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
