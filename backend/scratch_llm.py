import os
import sys
import django

# Set up Django environment to access settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
from core.llm_provider import LLMProvider

def main():
    # Attempt to load the GROQ API key from settings or environment
    api_key = getattr(settings, 'GROQ_API_KEY', None) or os.environ.get('GROQ_API_KEY')
    if not api_key:
        print("Error: GROQ_API_KEY not found in settings or environment.")
        print("Please set GROQ_API_KEY as an environment variable to run this scratch script.")
        sys.exit(1)
        
    provider = LLMProvider(api_key=api_key, model_name="llama3-8b-8192", timeout=30)
    
    system_prompt = "You are a helpful assistant. Output valid JSON with a single key 'summaryTemplate' containing your greeting."
    user_prompt = "Say hello."
    
    print("Sending request to Groq...")
    try:
        response = provider.request_template(system_prompt, user_prompt)
        print("Response received:")
        print(response)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
