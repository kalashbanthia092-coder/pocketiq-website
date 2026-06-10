import json
import os
import re

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session
from openai import OpenAI
from serpapi import GoogleSearch

load_dotenv()

ARTICLE_CACHE = {}
CACHE = {}
MAX_CHAT_HISTORY_MESSAGES = 12


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
    return app


app = create_app()

# ------------------- OPENAI CLIENT -------------------

def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY")
    return OpenAI(api_key=api_key)


def get_serpapi_key():
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing SERPAPI_API_KEY")
    return api_key

# ------------------- ROUTES -------------------

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/mobo/<mode>')
def mobo_mode(mode):
    if mode not in ["learning", "decision", "compare"]:
        mode = "learning"
    return render_template("mobo.html", mode=mode)

@app.route('/compare')
def compare():
    return render_template('compare.html') 

@app.route('/start')
def start():
    return render_template('start.html')

@app.route('/goals')
def goals():
    return render_template('goals.html')

@app.route('/about')
def about():
    return render_template('about.html')

# ------------------- DECISION CHATBOT -------------------

@app.route('/ask', methods=['POST'])
def ask():
    message = request.form.get('message', '').strip()
    if not message:
        return jsonify({'response': "Please type something."})

    # Initialize chat history if new
    if 'chat_history' not in session:
        session['chat_history'] = [
            {"role": "system", "content":
"You are MoBo, the PocketIQ decision coach. "
"You help teens and young adults decide whether a purchase is truly worth it.\n\n"

"Behavior rules:\n"
"1. When the user mentions wanting to buy something, ask clarifying questions ONE AT A TIME to fully understand:\n"
"   - the price or budget,\n"
"   - the user’s motivation,\n"
"   - how often it will be used,\n"
"   - whether this replaces or duplicates something they already own,\n"
"   - and any financial constraints they mention.\n"
"2. Ask as many questions as necessary UNTIL you have enough information to make a confident judgment.\n"
"3. Once you have enough information, STOP asking questions and give a FINAL evaluation that includes:\n"
"   - whether the purchase seems thoughtful or impulsive,\n"
"   - what else the money could realistically be used for or saved toward,\n"
"   - a clear recommendation: Go for it / Think twice / Wait and save.\n"
"4. Clearly signal when you are giving the FINAL evaluation.\n"
"5. After giving the final evaluation, DO NOT ask further questions.\n\n"

"Tone: friendly, practical, and non-judgmental — like a financially wise older friend. "
"Use relatable examples in I NR (₹), such as snacks, subscriptions, phone recharges, or travel.\n"
"Stay strictly focused on purchase decisions only."
}

        ]

    # Append new user message
    chat_history = session['chat_history']
    chat_history.append({"role": "user", "content": message})

    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=chat_history,
            max_tokens=300
        )
        reply = response.choices[0].message.content.strip()

        # Append bot response to memory
        chat_history.append({"role": "assistant", "content": reply})
        if len(chat_history) > MAX_CHAT_HISTORY_MESSAGES:
            chat_history = [chat_history[0]] + chat_history[-(MAX_CHAT_HISTORY_MESSAGES - 1):]
        session['chat_history'] = chat_history

        return jsonify({'response': reply})

    except Exception as e:
        print("Ask Error:", e)
        return jsonify({'response': f"⚠️ Error contacting model: {str(e)}"})

    

# ------------------- LEARNING MODE -------------------

@app.route('/generate_roadmap', methods=['POST'])
def generate_roadmap():
    context = request.form.get("context", "").strip()
    if not context:
        return jsonify({"error": "Missing context"}), 400

    prompt = (
        "You are MoBo, a financial literacy mentor for teenagers.\n\n"
        f"User background:\n{context}\n\n"
        "Create a personalized 8–10 step roadmap to improve their financial knowledge.\n"
        "Start from their current level and gradually advance.\n\n"
        "IMPORTANT:\n"
        "- Return ONLY valid JSON\n"
        "- No explanation, no text before or after\n"
        "- Format EXACTLY like this:\n"
        "[{\"title\": \"...\", \"summary\": \"...\"}, ...]"
    )

    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )

        text = response.choices[0].message.content.strip()
        print("🔍 RAW MODEL OUTPUT:\n", text)  # DEBUG

        roadmap = []

        # ✅ Attempt 1: direct JSON
        try:
            roadmap = json.loads(text)
        except:
            # ✅ Attempt 2: extract JSON block
            match = re.search(r'\[.*\]', text, re.S)
            if match:
                roadmap = json.loads(match.group(0))

        # ✅ Validate result
        if not isinstance(roadmap, list) or len(roadmap) < 3:
            raise ValueError("Invalid roadmap format")

        print("✅ Roadmap parsed successfully")
        return jsonify({"roadmap": roadmap})

    except Exception as e:
        print("❌ Roadmap error:", e)

        # 🔥 fallback (ONLY if truly failed)
        fallback = [
            {"title": "Budgeting Basics", "summary": "Learn how to plan and track expenses each month."},
            {"title": "Saving Goals", "summary": "Understand short- and long-term savings."},
            {"title": "Smart Spending", "summary": "Differentiate between needs and wants."},
            {"title": "Intro to Investing", "summary": "Explore mutual funds and compounding."},
            {"title": "Credit & Taxes", "summary": "Understand credit, loans, and taxes."}
        ]

        return jsonify({"roadmap": fallback})
    
@app.route('/generate_article', methods=['POST'])
def generate_article():
    topic = request.form.get('topic', '').strip()

    if topic in ARTICLE_CACHE:
        return jsonify({'article': ARTICLE_CACHE[topic]})

    if not topic:
        return jsonify({'article': "⚠️ No topic provided."})

    prompt = (
        f"You are MoBo, a financial mentor for Indian teenagers.\n\n"
        f"Explain the topic: '{topic}' in about 200–250 words.\n"
        "DO NOT include the title in the response.\n"
        "Start directly with the explanation.\n"
        "Use simple language and real-life examples (pocket money, savings, UPI, etc).\n"
        "Use INR (₹) for all examples, unless otherwise specified.\n"
        "End with 2–3 key takeaways."
    )

    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400
        )


        article = (
            response.choices[0].message.content.strip()
            if response and response.choices
            else None
        )

        ARTICLE_CACHE[topic] = article

        if not article:
            raise ValueError("Empty response")

        return jsonify({'article': article})

    except Exception as e:
        print("❌ Article error:", e)

        fallback = f"""
### {topic}

This topic is important for managing your money wisely.

For example, if you receive ₹1,000 as pocket money, understanding {topic.lower()} can help you decide how much to save, spend, or invest.

Start small, stay consistent, and build habits over time.

**Key Takeaways:**
- Start early
- Be consistent
- Think long-term
"""
        return jsonify({'article': fallback})

# ------------------- COMPARE MODE -------------------

def get_product_data(query):
    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": get_serpapi_key(),
    }

    search = GoogleSearch(params)
    results = search.get_dict()

    try:
        product = results["shopping_results"][0]

        return {
            "title": product.get("title"),
            "price": product.get("price"),
            "image": product.get("thumbnail"),
            "link": product.get("link")
        }
    except:
        return None

import re

def parse_price_to_inr(price_str):
    if not price_str:
        return None

    # INR
    match_inr = re.search(r"(₹|Rs\.?|INR)\s?([\d,]+)", price_str)
    if match_inr:
        return float(match_inr.group(2).replace(",", ""))

    # USD → INR
    match_usd = re.search(r"\$ ?([\d,]+)", price_str)
    if match_usd:
        usd = float(match_usd.group(1).replace(",", ""))
        return usd * 83

    return None


@app.route('/compare_items', methods=['POST'])
def compare_items():
    try:
        item1 = request.form.get('item1', '').strip()
        item2 = request.form.get('item2', '').strip()

        if not item1 or not item2:
            return jsonify({'error': "⚠️ Please enter both items."})

        def clean_query(q):
            if len(q.split()) == 1:
                return q + " best price"
            return q

        data1 = get_product_data(clean_query(item1))
        data2 = get_product_data(clean_query(item2))

        if not data1 or not data2:
            return jsonify({'error': "⚠️ Try more specific product names (e.g., 'MacBook Air M2')"})

        p1 = parse_price_to_inr(data1.get("price"))
        p2 = parse_price_to_inr(data2.get("price"))

        if p1 and p2 and p2 != 0:
            ratio = round(p1 / p2, 1)
        else:
            ratio = 0

        return jsonify({
            "item1": data1,
            "item2": data2,
            "price1_inr": p1,
            "price2_inr": p2,
            "ratio": ratio
        })

    except Exception as e:
        print("❌ Compare error:", e)
        return jsonify({'error': f"⚠️ Server error: {str(e)}"})

if __name__ == '__main__':
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)












