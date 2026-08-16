import re

def patch_timeouts():
    with open('main.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Change all timeout=45.0 to timeout=55.0
    content = content.replace("timeout=45.0", "timeout=55.0")
    
    # Change timeout=30.0 to timeout=55.0 for stage1a
    content = content.replace("timeout=30.0", "timeout=55.0")

    with open('main.py', 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == "__main__":
    patch_timeouts()
    print("Timeouts patched to 55.0s")
