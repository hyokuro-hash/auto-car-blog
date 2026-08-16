import sys

try:
    with open("templates/dashboard.html", "r", encoding="utf-8") as f:
        html = f.read()

    html = html.replace("switchImageTab('naver')", "switchImagePlatform('naver')")
    html = html.replace("document.getElementById('apply-all-platforms')", "document.getElementById('apply-all-platforms-checkbox')")

    with open("templates/dashboard.html", "w", encoding="utf-8") as f:
        f.write(html)
        
    print("dashboard.html patched 4.")
except Exception as e:
    print("Error:", e)
