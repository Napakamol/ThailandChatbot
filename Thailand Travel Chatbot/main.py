import openai
from langchain_community.llms import Ollama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from flask import Flask, render_template, session
from flask_socketio import SocketIO, emit
import logging
import re
import datetime
import secrets
import mysql.connector

# Setup basic logging
logging.basicConfig(level=logging.DEBUG)

# Create Flask app and SocketIO instance
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
socketio = SocketIO(app)

def format_output(text):
    """Format text to HTML with proper image and link handling"""
    try:
        # Convert bold text
        text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)

        # Handle Google Drive images with export=view
        drive_pattern = r'https://drive\.google\.com/uc\?id=([a-zA-Z0-9_-]+)'
        text = re.sub(drive_pattern, 
            lambda m: f'<img src="https://drive.google.com/uc?export=view&id={m.group(1)}" '
                     f'alt="Google Drive Image" style="max-width:500px; width:100%; height:auto;">', 
            text)

        # Handle regular image URLs
        image_pattern = r'(https?://[^\s]+(?:\.jpg|\.jpeg|\.png|\.gif|\.bmp|\.webp))'
        text = re.sub(image_pattern, 
            r'<img src="\1" alt="Image" style="max-width:500px; width:100%; height:auto;">', 
            text)

        # Handle regular URLs
        text = re.sub(r'(?<!<img src=")(https?://[^\s]+)(?!")', 
            r'<a href="\1" target="_blank">\1</a>', 
            text)

        return text
    except Exception as e:
        logging.error(f"Error in format_output: {e}")
        return text

def connect_db():
    try:
        return mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="travel_chatbot",
            port=3308
        )
    except Exception as e:
        logging.error(f"Database connection error: {e}")
        raise

def get_image_metadata(place_name):
    try:
        db = connect_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM images WHERE place_name = %s", (place_name,))
        result = cursor.fetchone()
        logging.debug(f"Image data retrieved: {result}")
        return result
    except Exception as e:
        logging.error(f"Error retrieving image metadata: {e}")
        return None
    finally:
        if 'db' in locals() and db.is_connected():
            db.close()

def initialise_llama3():
    try:
        # สร้างเทมเพลตสำหรับ Prompt
        prompt_template = ChatPromptTemplate.from_template(
            "You are a travel assistant specializing in Thailand.\n"
            "User's Question: {question}\n"
            "Provide a helpful and informative response."
        )
        llama_model = Ollama(model="llama3:latest")
        output_parser = StrOutputParser()
        # สร้าง pipeline รวม Prompt + Model + Output Parser
        return prompt_template | llama_model | output_parser
    except Exception as e:
        logging.error(f"Failed to initialize chatbot: {e}")
        raise

chatbot_pipeline = initialise_llama3()

@app.route('/')
def main():
    return render_template('index.html')

@socketio.on('send_message')
def handle_send_message(data):
    query_input = data['message']
    chat_history = session.get('history', [])

    try:
        # Append user query to history
        chat_history.append(("user", query_input, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

        # Prepare chat messages
        chat_messages = [(role, message) for role, message, _ in chat_history]
        chat_messages.append(("system", "You are a travel assistant specializing in Thailand. Only answer questions related to travel in Thailand. If the question is unrelated, politely decline."))

        # Get chatbot response
        response = chatbot_pipeline.invoke({"question": query_input})
        
        # Handle image requests
        if any(phrase in query_input.lower() for phrase in ["picture", "image", "photo"]):
            image_data = get_image_metadata("Wat Arun")
            if image_data and image_data["image_url"]:
                image_url = image_data["image_url"]
                # Ensure Google Drive URL has export=view
                if 'drive.google.com' in image_url and 'export=view' not in image_url:
                    image_url = image_url.replace('uc?id=', 'uc?export=view&id=')
                
                response += f"""
                <div class="image-container">
                    <img src="{image_url}" 
                         alt="Wat Arun" 
                         style="max-width:500px; width:100%; height:auto;"
                         onerror="this.onerror=null; this.src='static/images/error.png';">
                    <p>{image_data.get('description', '')}</p>
                </div>
                """
            else:
                response += "\n\nSorry, I couldn't find the requested image."

        # Format and send response
        chat_history.append(("system", response, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        formatted_output = format_output(response)
        session['history'] = chat_history

        emit('receive_message', {
            'message': formatted_output,
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }, json=True)

    except Exception as e:
        logging.error(f"Error in handle_send_message: {e}")
        emit('receive_message', {
            'message': "Sorry, an error occurred while processing your request.",
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

if __name__ == '__main__':
    socketio.run(app, debug=True)