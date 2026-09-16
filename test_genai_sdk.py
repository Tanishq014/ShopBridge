from app.extraction.gemini_provider import GeminiProvider
import asyncio

def test_gemini_provider_import():
    try:
        provider = GeminiProvider()
        print("Provider instantiated.")
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    test_gemini_provider_import()
