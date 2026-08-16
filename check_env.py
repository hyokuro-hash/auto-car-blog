import os
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("QSTASH_TOKEN")
print(f"QSTASH_TOKEN: {token}")
