print("STEP 1: Script started")

import os
from pathlib import Path
try:
    from dotenv import load_dotenv
except ImportError:  # optional: only used to read a local .env file
    def load_dotenv(*_args, **_kwargs):
        return False
from groq import Groq

load_dotenv(Path(__file__).parent / ".env")
print("STEP 2: Environment file checked")

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    raise ValueError("GROQ_API_KEY was not found in .env")

print("STEP 3: API key found")

client = Groq(api_key=api_key)

print("STEP 4: Sending request to GPT-OSS-120B")

response = client.chat.completions.create(
    model="openai/gpt-oss-120b",
    messages=[
        {
            "role": "user",
            "content": "Reply with exactly: Groq connection successful!"
        }
    ],
    max_tokens=200,
)

print("STEP 5: Model response received")
print("STEP 5: Model response received")
print("Finish reason:", response.choices[0].finish_reason)
print("Number of choices:", len(response.choices))
print("Full response:", repr(response.choices[0].message))
print("Response content:", repr(response.choices[0].message.content))
