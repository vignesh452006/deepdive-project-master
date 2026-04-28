import os
import requests
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, 'gemini.env'))

class QuizGenerator:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in gemini.env")
        
        # 2025 LATEST FREE MODELS
        self.model_options = [
            "gemini-2.5-flash-lite", # Current Free-Tier Favorite
            "gemini-2.0-flash", 
            "gemini-1.5-flash-latest" # Final legacy fallback
        ]

    def generate_quiz(self, topic, num_q):
        prompt = f"Generate {num_q} MCQs about {topic} as a JSON list. Return ONLY the JSON."
        
        for model_name in self.model_options:
            # We use the 'v1' stable endpoint
            url = f"https://generativelanguage.googleapis.com/v1/models/{model_name}:generateContent?key={self.api_key}"
            
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.7}
            }

            try:
                response = requests.post(url, json=payload, timeout=20)
                
                if response.status_code == 200:
                    data = response.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                
                print(f"Model {model_name} failed: {response.status_code}")
                # If we get a 403 again, we stop immediately to check the key
                if response.status_code == 403:
                    print("ERROR: New API key is also being blocked. Check AI Studio settings.")
                    return "[]"
                    
            except Exception as e:
                print(f"Network error: {e}")
                continue

        return "[]"