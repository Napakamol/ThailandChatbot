from langchain_community.llms import Ollama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from flask import Flask, render_template, session
from flask_socketio import SocketIO, emit
import logging
import re
import datetime
import secrets

# Setup basic logging
logging.basicConfig(level=logging.DEBUG)

# Create Flask app and SocketIO instance
app = Flask(__name__)
# Generate a new secret key
app.secret_key = secrets.token_hex(16)
socketio = SocketIO(app)

# Define a function to format text by converting Markdown bold syntax to HTML strong tags
def format_output(text):
    """Convert Markdown bold syntax to HTML strong tags."""
    return re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)

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

@socketio.on('send_message')
def handle_send_message(data):
    query_input = data['message']
    chat_history = session.get('history', [])

    try:
        # Append user query to history
        chat_history.append(("user", query_input, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

        chat_messages = [(role, message) for role, message, _ in chat_history]  # ตัด timestamp ออก
        chat_messages.append(("system", "You are my personal assistant"))
        create_prompt = ChatPromptTemplate.from_messages(chat_messages)


        # Get response from chatbot
        response = chatbot_pipeline.invoke(query_input)


        # Append chatbot response to history
        chat_history.append(("system", response, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

        # Format output
        output = format_output(response)
        
        # Update session history
        session['history'] = chat_history

        # Emit response back to client
        emit('receive_message', {'message': output, 'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
    except Exception as e:
        logging.error(f"Error during chatbot invocation: {e}")
        emit('receive_message', {'message': "Sorry, an error occurred while processing your request.", 'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

if __name__ == '__main__':
    socketio.run(app, debug=True) 
# Define route for home page
@app.route('/', methods=['GET', 'POST'])
def main():
    query_input = None
    output = None
    if request.method == 'POST':
        query_input = request.form.get('query-input')
        if query_input:
            try:
                response = chatbot_pipeline.invoke({'question': query_input})
                output = format_output(response)
            except Exception as e:
                logging.error(f"Error during chatbot invocation: {e}")
                output = "Sorry, an error occurred while processing your request."
    return render_template('index.html', query_input=query_input, output=output)

if __name__ == '__main__':
    app.run(debug=True)
