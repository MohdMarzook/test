import time
import asyncio
import os
from bs4 import BeautifulSoup as bs4
import logging
from deep_translator import GoogleTranslator
from googletrans import Translator
import requests
import random
from dotenv import load_dotenv


# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Translation cache to avoid duplicate translations
translation_cache = {}

# Track translation service reliability - add the new services
service_stats = {
    "google": {"success": 0, "failure": 0, "last_failure": 0},
    "googletrans": {"success": 0, "failure": 0, "last_failure": 0},
    "mymemory": {"success": 0, "failure": 0, "last_failure": 0},
    # Remove the non-working services
}

# Get email from environment variable or use default
MYMEMORY_EMAIL = os.getenv("MYMEMORY_EMAIL", "your.email@example.com")

# Async sleep function with exponential backoff
async def backoff_sleep(attempt, base=1.0, max_delay=30.0):
    delay = min(base * (2 ** attempt), max_delay)
    await asyncio.sleep(delay)

# Improved translation function with caching and better error handling
async def translate_text(text, from_language="en", to_language="ta"):
    """Translate text with caching for better performance"""
    if not text or text.isspace():
        return text
    
    # Check cache first
    cache_key = f"{text}|{from_language}|{to_language}"
    if cache_key in translation_cache:
        return translation_cache[cache_key]
    
    result = text
    
    # Define translation methods
    async def google_translator(text, from_language, to_language):
        try:
            translator = GoogleTranslator(source=from_language, target=to_language)
            result = translator.translate(text)
            service_stats["google"]["success"] += 1
            return result
        except Exception as e:
            service_stats["google"]["failure"] += 1
            service_stats["google"]["last_failure"] = time.time()
            logger.warning(f"Google Translator failed: {str(e)[:100]}...")
            return None

    async def googletrans_translator(text, from_language, to_language):
        try:
            translator = Translator()
            result = translator.translate(text, src=from_language, dest=to_language).text
            service_stats["googletrans"]["success"] += 1
            return result
        except Exception as e:
            service_stats["googletrans"]["failure"] += 1
            service_stats["googletrans"]["last_failure"] = time.time()
            logger.warning(f"Googletrans failed: {str(e)[:100]}...")
            return None

    async def mymemory_translator(text, from_language, to_language):
        if from_language == "auto":
            return None
        try:
            # Use email from environment variable for higher quota
            url = f"https://api.mymemory.translated.net/get?q={text}&langpair={from_language}|{to_language}&de={MYMEMORY_EMAIL}"
            
            # Add user-agent header to prevent blocking
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Safari/537.36"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                logger.warning(f"MyMemory API returned status code {response.status_code}")
                service_stats["mymemory"]["failure"] += 1
                service_stats["mymemory"]["last_failure"] = time.time()
                return None
                
            data = response.json()
            
            # Check for rate limiting
            if "responseStatus" in data and data["responseStatus"] == 429:
                logger.warning("MyMemory API rate limit reached. Backing off.")
                service_stats["mymemory"]["failure"] += 1
                service_stats["mymemory"]["last_failure"] = time.time()
                return None
            
            if data and "responseData" in data and "translatedText" in data["responseData"]:
                result = data["responseData"]["translatedText"]
                
                # Check quota
                if "responseDetails" in data and "Daily request limit" in str(data["responseDetails"]):
                    logger.warning(f"MyMemory API quota warning: {data['responseDetails']}")
                
                service_stats["mymemory"]["success"] += 1
                return result
            else:
                logger.warning("MyMemory API returned invalid response structure")
                service_stats["mymemory"]["failure"] += 1
                service_stats["mymemory"]["last_failure"] = time.time()
                return None
                
        except requests.exceptions.Timeout:
            logger.warning("MyMemory API request timed out")
            service_stats["mymemory"]["failure"] += 1
            service_stats["mymemory"]["last_failure"] = time.time()
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"MyMemory API request failed: {str(e)[:100]}...")
            service_stats["mymemory"]["failure"] += 1
            service_stats["mymemory"]["last_failure"] = time.time()
            return None
        except Exception as e:
            logger.warning(f"MyMemory translation API failed: {str(e)[:100]}...")
            service_stats["mymemory"]["failure"] += 1
            service_stats["mymemory"]["last_failure"] = time.time()
            return None


    # Smart service selection strategy
    # Calculate success rates
    service_priority = []
    for service, stats in service_stats.items():
        total = stats["success"] + stats["failure"]
        # Avoid division by zero
        if total == 0:
            success_rate = 0.5  # Default to 50% for new services
        else:
            success_rate = stats["success"] / total
            
        # Apply cooling off period for recently failed services
        cooling_factor = 1.0
        if time.time() - stats["last_failure"] < 5:  # 5 seconds cooling
            cooling_factor = 0.5
            
        # Add some randomness (10%)
        randomness = 0.9 + (random.random() * 0.2)  # 0.9 to 1.1
        
        # Final score
        score = success_rate * cooling_factor * randomness
        
        service_priority.append((service, score))
    
    # Sort by score (highest first)
    service_priority.sort(key=lambda x: x[1], reverse=True)
    
    # Try services in priority order
    methods = {
        "google": google_translator,
        "googletrans": googletrans_translator, 
        "mymemory": mymemory_translator,
    }
    
    # Try each method according to priority
    for service_name, _ in service_priority:
        method = methods[service_name]

        # Try up to 3 times per method
        for attempt in range(3):
            result_text = await method(text, from_language, to_language)
            
            if result_text:
                # Cache and return successful translation
                translation_cache[cache_key] = result_text
                return result_text
                
            # Add delay before retry
            if attempt < 1:  # Only delay before the second attempt
                await backoff_sleep(attempt)
    
    # If all methods fail, return original text
    logger.warning("All translation methods failed, returning original text")
    return text

async def process_multiclass(multidiv, from_lang, to_lang):
    """Process and translate content of a div element"""
    if not multidiv or not multidiv.text.strip():
        return
        
    if multidiv.find('span'):
        spans = multidiv.find_all('span')
        for span in spans:
            if span.get('class') and len(span.get('class')) >= 4:
                saved_span = bs4.new_tag(name='span')
                saved_span['class'] = span.get('class')
                saved_span.string = " "
                original_text = multidiv.get_text()
                translated = await translate_text(original_text, from_lang, to_lang)
                multidiv.string = translated
                multidiv.append(saved_span)
                return
                
        original_text = multidiv.get_text()
        translated = await translate_text(original_text, from_lang, to_lang)
        multidiv.string = translated
    else:
        original_text = multidiv.get_text()
        translated = await translate_text(original_text, from_lang, to_lang)
        multidiv.string = translated

async def process_page(line, from_lang, to_lang):
    """Process a single page of HTML content"""
    if line[:11] != "<div id=\"pf":
        return None
        
    soup = bs4(line, 'html.parser')
    page = soup.find('div')
    
    if not page:
        return None
    
    # Collect all subdiv elements that need translation
    translation_tasks = []
    
    for list_of_div in page.find_all('div', recursive=False):
        if not list_of_div.text.strip():
            continue
            
        if list_of_div.get('class') and len(list_of_div.get('class')) > 5:
            # Handle directly
            translation_tasks.append(process_multiclass(list_of_div, from_lang, to_lang))
        else:
            # Handle subdiv elements
            for subdiv in list_of_div.find_all('div', recursive=False):
                if subdiv.text.strip():
                    translation_tasks.append(process_multiclass(subdiv, from_lang, to_lang))
    
    # Execute all translation tasks concurrently
    if translation_tasks:
        await asyncio.gather(*translation_tasks)
        
    return str(soup)

async def main(line, from_lang = "en", to_lang = "ta"):
    """Main async function to orchestrate the process"""
    start = time.perf_counter()

    if line[:11] != "<div id=\"pf":
        return line
    result = await process_page(line, from_lang, to_lang)
    if result:
        return result
    else:
        return line 


    
if __name__ == "__main__":
    # To run all tests, uncomment the following line:
    # asyncio.run(run_all_tests())
    
    # To test an individual service, uncomment and modify the following line:
    # asyncio.run(test_individual_service("google"))
    
    # To run the main translation function:
    asyncio.run(main())
