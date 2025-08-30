from celery import Celery
import logging
from functools import partial
import re
import os
import boto3
import subprocess
import tempfile
import concurrent.futures
from extract import main as extract_main
# loading environment variables
from dotenv import load_dotenv
if os.path.exists('/etc/secrets/ENV_FILE'):
    load_dotenv('/etc/secrets/ENV_FILE')
else:
    load_dotenv()
import time

import asyncio
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# text translator modules


# # app = Celery('tasks', broker=os.getenv("CELERY_BROKER_URL"), backend=os.getenv("CELERY_RESULT_BACKEND"))
# app = Celery('tasks', broker="rediss://red-d2o8knuuk2gs73akq910:8ZGeG5EilVSZHjqcDirWV8etzrnQSJiu@singapore-keyvalue.render.com:6379/0")
# # app.conf.broker_url = "rediss://red-d2o8knuuk2gs73akq910:8ZGeG5EilVSZHjqcDirWV8etzrnQSJiu@singapore-keyvalue.render.com:6379"
# app = Celery('tasks')
# app.config_from_object('celeryconfig')

# app.conf.broker_url = "rediss://red-d2o8knuuk2gs73akq910:8ZGeG5EilVSZHjqcDirWV8etzrnQSJiu@singapore-keyvalue.render.com:6379/0" 
# app.conf.result_backend = "rediss://red-d2o8knuuk2gs73akq910:8ZGeG5EilVSZHjqcDirWV8etzrnQSJiu@singapore-keyvalue.render.com:6379/0"
app = Celery('tasks', broker=os.getenv("RENDER_REDIS_URL", "redis://redis:6379")+"/0", backend=os.getenv("RENDER_REDIS_URL", "redis://redis:6379")+"/1")

s3 = boto3.client(
        "s3",
        endpoint_url=os.getenv("ENDPOINT"),
        aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY"),
        region_name=os.getenv("S3_DEFAULT_REGION")
    )


def pdf_to_html(pdf_key):
    with tempfile.TemporaryDirectory() as temp_dir:
        # Use absolute paths for input and output files
        input_pdf = os.path.join(temp_dir, "input.pdf")
        output_html = os.path.join(temp_dir, "output.html")
        try:
            start_processing = time.perf_counter()
            s3.download_file(os.getenv("IN_BUCKET"), pdf_key, input_pdf)
            subprocess.run(["pdf2htmlEX", "--tounicode", "1", "--optimize-text", "0", "--dest-dir", temp_dir, input_pdf, "output.html"], check=False)
            end_processing = time.perf_counter()
            elapsed = end_processing - start_processing
            logger.info(f"pdf download and convertion to html in {elapsed:.2f} seconds")
        except Exception as e:
            print("Error during PDF to HTML conversion or S3 download:", e)
            return 
        
        with open(output_html, "r", encoding="utf-8") as file:
            for line in file:
                yield line  

def async_wrapper(line , from_language, to_language):
    return asyncio.run(extract_main(line, from_language, to_language))


def shrink_font(css_rule, scale=0.7):
    # Match number + unit (px, pt, em, rem, etc.)
    match = re.search(r'font-size\s*:\s*([\d.]+)([a-z%]+)', css_rule)
    if not match:
        return css_rule  

    size_value, unit = match.groups()
    new_rule = re.sub(
        r'font-size\s*:\s*[\d.]+[a-z%]+',
        f'font-size: calc({size_value}{unit} * {scale})',
        css_rule
    )
    return new_rule
    


async def main(from_language, to_language, pdf_key):
    # Create a temporary file with an HTML extension
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp_file:
        output_file = tmp_file.name
        logger.info(f"Created temporary file: {output_file}")
    
    try:
        # Write to the temporary file
        with open(output_file, "w", encoding="utf-8") as outfile:
            lines = pdf_to_html(pdf_key)
            found_pages = False
            for line in lines:
                if line.strip().startswith(".fs"):
                    line = shrink_font(line)
                outfile.write(line)
                if line.strip() == "<div id=\"page-container\">":
                    found_pages = True
                    break

            if found_pages:       
                # Start the processing timer
                start_processing = time.perf_counter()
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
                    process_with_params = partial(async_wrapper, from_language=from_language, to_language=to_language)
                    processed_results = executor.map(process_with_params, lines)
                    for result in processed_results:
                        outfile.write(result)
                
                end_processing = time.perf_counter()
                elapsed = end_processing - start_processing
                logger.info(f"Translation processing completed in {elapsed:.2f} seconds")

        # Generate S3 key for the output file
        s3_output_key = os.path.splitext(pdf_key)[0] + "_" + from_language + "_to_" + to_language + ".html"
        logger.info(f"Uploading to S3 with key: {s3_output_key}")
        
        # Upload the temporary file to S3
        s3.upload_file(output_file, os.getenv("OUT_BUCKET"), s3_output_key)
        logger.info(f"Successfully uploaded translated file to {os.getenv('OUT_BUCKET')}/{s3_output_key}")
        
        return s3_output_key
    
    finally:
        # Clean up the temporary file
        if os.path.exists(output_file):
            os.unlink(output_file)
            logger.info(f"Removed temporary file: {output_file}")

@app.task(name='python_task')
def run_pdf_task(from_language, to_language, pdf_key):
    """Celery task wrapper around async main()."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(main(from_language, to_language, pdf_key))

if __name__ == "__main__":
    start = time.perf_counter()
    asyncio.run(main("en", "fr", "User guide.pdf"))
    end = time.perf_counter()
    elapsed = end - start
    logger.info(f"Processing completed in {elapsed:.2f} seconds")
    if elapsed > 60:
        logger.info(f"({elapsed/60:.2f} minutes)")