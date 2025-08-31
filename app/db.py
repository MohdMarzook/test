import psycopg2
from dotenv import load_dotenv
import os

# Load environment variables from .env
load_dotenv()

# Fetch variables
DATABASE_URL = os.getenv("DATABASE_URL")

def update(status, pdf_id):
    """
    Update the status of a PDF in the database by pdf_id.
    """
    try:
        connection = psycopg2.connect(DATABASE_URL)
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE public.pdf SET status = %s WHERE pdf_key = %s;",
            (status, pdf_id)
        )
        connection.commit()
        cursor.close()
        connection.close()
        print("Update successful!")
        return True
    except Exception as e:
        print(f"Failed to update: {e}")
        return False