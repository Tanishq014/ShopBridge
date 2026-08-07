from app.extraction.gemini_provider import GeminiProvider
import asyncio

async def test():
    try:
        provider = GeminiProvider()
        print("Provider instantiated.")
        # We can't easily test upload without a real file but we can check if classes imported.
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(test())
