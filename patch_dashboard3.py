import sys

try:
    with open("templates/dashboard.html", "r", encoding="utf-8") as f:
        html = f.read()

    html = html.replace("renderImageEditorSlots();", "renderImageSlots();")
    html = html.replace("document.getElementById('apply-all-platforms')?.checked", "document.getElementById('apply-all-platforms-checkbox')?.checked")

    with open("templates/dashboard.html", "w", encoding="utf-8") as f:
        f.write(html)
        
    print("dashboard.html patched.")
except Exception as e:
    print("Error:", e)
