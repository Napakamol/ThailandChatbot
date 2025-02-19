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
# Generate a new secret key
app.secret_key = secrets.token_hex(16)
socketio = SocketIO(app)

def format_output(text):
    """แปลง Markdown เป็น HTML โดยให้ลิงก์สามารถคลิกได้ และแสดงรูปถ้าเป็น URL ของรูป"""
    
    # แปลง **bold text** เป็น <strong>
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)

    # ตรวจจับ URL ของรูปภาพปกติ (เช่น .jpg, .png, .gif)
    image_pattern = r'(https?://[^\s]+(?:\.jpg|\.jpeg|\.png|\.gif|\.bmp|\.webp))'
    text = re.sub(image_pattern, r'<img src="\1" alt="Image" style="max-width:100%; height:auto;">', text)

    # ตรวจจับ Google Drive Direct Link และแปลงเป็นรูปภาพ (ใช้ export=view)
    drive_pattern = r'https://drive\.google\.com/uc\?id=([a-zA-Z0-9_-]+)'
    text = re.sub(drive_pattern, r'<img src="https://drive.google.com/uc?export=view&id=\1" alt="Google Drive Image" style="max-width:100%; height:auto;">', text)

    # ตรวจจับ Google Drive แบบ `/file/d/FILE_ID/view` และแปลงเป็น `<img>`
    drive_file_pattern = r'https://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)/view'
    text = re.sub(drive_file_pattern, r'<img src="https://drive.google.com/uc?export=view&id=\1" alt="Google Drive Image" style="max-width:100%; height:auto;">', text)

    # แปลง URL ที่ไม่ใช่รูปภาพเป็น <a href>
    text = re.sub(r'(?<!<img src=")(https?://[^\s]+)(?!")', r'<a href="\1" target="_blank">\1</a>', text)

    return text

# Database connection function
def connect_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",  # Your MySQL username
        password="",  # Your MySQL password (leave blank if default)
        database="travel_chatbot",
        port=3308  # Use the correct port here
    )

# Query the database for image metadata
def get_image_metadata(place_name):
    db = connect_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM images WHERE place_name = %s", (place_name,))
    result = cursor.fetchone()
    db.close()
    return result

# Define chatbot initialization
def initialise_llama3():
    try:
        # Initialize OpenAI LLM and output parser
        llama_model = Ollama(model="llama3:latest")
        format_output = StrOutputParser()

        # Create chain
        chatbot_pipeline = llama_model | format_output
        return chatbot_pipeline
    except Exception as e:
        logging.error(f"Failed to initialize chatbot: {e}")
        raise

# Initialize chatbot
chatbot_pipeline = initialise_llama3()

@app.route('/')
def main():
    return render_template('index.html')

# Modify the handle_send_message function
@socketio.on('send_message')
def handle_send_message(data):
    query_input = data['message']
    chat_history = session.get('history', [])

    try:
        # Append user query to history
        chat_history.append(("user", query_input, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

        chat_messages = [(role, message) for role, message, _ in chat_history]  # Remove timestamp
        chat_messages.append(("system", "You are a travel assistant specializing in Thailand. Only answer questions related to travel in Thailand. If the question is unrelated, politely decline."))

        create_prompt = ChatPromptTemplate.from_messages(chat_messages)

        # Get response from chatbot
        response = chatbot_pipeline.invoke(query_input)

        # Check if the query is related to showing a picture with details
        image_url = None  # Initialize image_url variable
        if "picture with details" in query_input.lower() or "show me a picture" in query_input.lower():
            # Fetch image metadata for 'Wat Arun' from the database
            image_data = get_image_metadata("Wat Arun")
            if image_data:
                image_url = image_data["image_url"]
                description = image_data["description"]
                # Embed the image and description in the response
                response += f"\n\nHere is a picture of Wat Arun: <img src='{image_url}' alt='Wat Arun' width='500'>"
                response += f"<p>{description}</p>"
            else:
                response += "\n\nSorry, I couldn't find a picture for Wat Arun."

        # Append chatbot response to history
        chat_history.append(("system", response, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

        # Format output
        output = format_output(response)
        
        # Update session history
        session['history'] = chat_history

        # Emit response back to client
        emit('receive_message', {
            'message': output,
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }, json=True)

    except Exception as e:
        logging.error(f"Error during chatbot invocation: {e}")
        emit('receive_message', {'message': "Sorry, an error occurred while processing your request.", 'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

if __name__ == '__main__':
    socketio.run(app, debug=True)