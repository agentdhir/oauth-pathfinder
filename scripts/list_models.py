"""Print the Gemini models your key can call (use to set GEMINI_MODELS in .env)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
for m in client.models.list():
    if "generateContent" in (m.supported_actions or []):
        print(m.name.removeprefix("models/"))
