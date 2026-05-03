from openai import OpenAI
from flask import Flask, render_template, request


client = OpenAI(api_key='api_key')

conversation = [{"role": "system", "content": "You are a helpful assistant."}]

def get_response(message):
    conversation.append({"role": "user", "content": message})

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=conversation
    )

    reply = response.choices[0].message.content
    conversation.append({"role": "assistant", "content": reply})
    return reply

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('chatbot.html')

@app.route('/ask', methods=['POST'])
def ask():
    message = request.form['message']
    reply = get_response(message)
    return reply

# def get_response(message):
#     conversation.append({"role": "user", "content": message})
#     response = client.chat.completions.create(
#         model="gpt-3.5-turbo",
#         messages=conversation
#     )
#     reply = response.choices[0].message.content
#     conversation.append({"role": "assistant", "content": reply})
#     return reply

# app = Flask(__name__)

# @app.route("/")
# def home():
#     return render_template("chatbot.html")

# @app.route("/ask", methods=["POST"])
# def ask():
#     try:
#         message = request.form.get("message", "")
#         print(f"📩 Received message: {message}")
#         reply = get_response(message)
#         print(f"🤖 AI reply: {reply}")
#         return jsonify({"response": reply})
#     except Exception as e:
#         print("❌ ERROR:", e)
#         # Return a valid JSON so the frontend doesn't crash
#         return jsonify({"response": f"Server error: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(debug=True)
