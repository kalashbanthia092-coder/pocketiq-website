import json
import os
import re
from datetime import timedelta
from urllib.parse import quote_plus

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return False

from flask import Flask, jsonify, render_template, request, session
from flask_session import Session
from openai import OpenAI
from serpapi import GoogleSearch

# Absolute paths everywhere: under a WSGI server (PythonAnywhere) the working
# directory is NOT the project folder, so anything relying on os.getcwd() ends
# up in the wrong place.
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

load_dotenv(os.path.join(BASE_DIR, ".env"))

ARTICLE_CACHE = {}
CACHE = {}
MAX_CHAT_HISTORY_MESSAGES = 12
# Rough USD->INR rate for converting foreign shopping listings. Approximate by
# design; update this and the matching copy in mobo.html when it drifts.
USD_TO_INR = 95

# Every model-facing prompt gets this so generated copy avoids the em-dash
# "AI tell" and reads more naturally.
NO_EM_DASH = "Do not use em dashes in your writing. Use commas, colons, or separate sentences instead."

DECISION_FALLBACK_RESPONSE = (
    "I can still help you think this through. Share the item, its price, how often you'll use it, "
    "and whether it replaces something you already own, and I'll help you decide if it's worth it."
)
LEARNING_FALLBACK_RESPONSE = (
    "I'm having trouble reaching my brain right now. Try asking again in a moment, and "
    "meanwhile, keep reading your current roadmap step and jot down anything confusing."
)

# Learning Mode uses its own tutor persona and its own session history so it never
# collides with (or inherits the purchase-only guardrails of) the Decision coach.
LEARNING_SYSTEM_PROMPT = (
    "You are MoBo, a friendly financial-literacy tutor inside PocketIQ's Learning Mode.\n\n"
    "You help teens and young adults understand money concepts of every kind: budgeting, saving, "
    "investing, credit, loans, taxes, inflation, interest, banking, UPI, insurance, careers and income, "
    "scams and safety, and general money habits.\n\n"
    "Behaviour rules:\n"
    "1. Answer the learner's question directly and clearly. Lead with the answer, then explain.\n"
    "2. Keep replies short, 2 to 5 sentences, unless the learner asks for more depth.\n"
    "3. Use simple language and relatable Indian examples in INR (₹): pocket money, UPI, recharges, "
    "snacks, subscriptions, travel, first jobs.\n"
    "4. If the learner is currently reading a roadmap step, connect your answer back to that step "
    "when it is relevant.\n"
    "5. IMPORTANT: You are NOT the purchase-decision coach. Never refuse or deflect a question just "
    "because it is not about buying something. Questions about concepts, definitions, examples, "
    "calculations, study help, or 'how does X work' are all squarely your job.\n"
    "6. Only redirect if a question is genuinely unrelated to money, finance, or the learner's studies.\n"
    "7. Never invent specific real-world returns, guaranteed rates, or personalised investment advice. "
    "Explain how things work instead, and suggest talking to a trusted adult for big decisions.\n\n"
    "Tone: encouraging, patient and plain-spoken, a good teacher who never makes anyone feel dumb.\n"
    + NO_EM_DASH
)


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

    # Server-side sessions.
    #
    # Flask's default sessions live entirely inside a cookie, which browsers cap
    # at roughly 4093 bytes. Conversation history plus a ~1.5KB system prompt
    # runs close to that ceiling, and once it is crossed the browser silently
    # drops the cookie: the session resets mid-conversation and MoBo forgets
    # everything the user already told it. Storing sessions on disk keeps the
    # cookie down to a short session id and removes the size limit entirely,
    # so history length is bounded only by MAX_CHAT_HISTORY_MESSAGES.
    app.config.update(
        SESSION_TYPE="filesystem",
        SESSION_FILE_DIR=os.path.join(BASE_DIR, "flask_session"),
        SESSION_FILE_THRESHOLD=500,   # cachelib prunes oldest beyond this
        SESSION_PERMANENT=True,
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        SESSION_USE_SIGNER=True,      # sign the session id in the cookie
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Only send the cookie over HTTPS in production. Off locally so the
        # dev server over plain http still works.
        SESSION_COOKIE_SECURE=os.getenv("FLASK_ENV", "").lower() == "production",
    )

    os.makedirs(app.config["SESSION_FILE_DIR"], exist_ok=True)
    Session(app)
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


def build_compare_fallback(item1, item2):
    return {
        "item1": {
            "title": item1,
            "price": None,
            "image": None,
            "link": None,
            "source": None,
        },
        "item2": {
            "title": item2,
            "price": None,
            "image": None,
            "link": None,
            "source": None,
        },
        "price1_inr": None,
        "price2_inr": None,
        "ratio": 0,
        "note": "Live price comparison is unavailable right now. Add SERPAPI_API_KEY to re-enable shopping data.",
    }


def is_recurring_price(price_text):
    if not price_text:
        return False
    normalized = price_text.lower()
    recurring_markers = ["/mo", "per month", "monthly", "emi", "/month", "mo."]
    return any(marker in normalized for marker in recurring_markers)


def format_extracted_price(product):
    extracted_price = product.get("extracted_price")
    if extracted_price in (None, ""):
        return None

    try:
        value = float(extracted_price)
    except (TypeError, ValueError):
        return None

    currency = product.get("currency")
    if currency == "USD":
        return f"${value:,.2f}"
    if currency == "INR":
        return f"₹{value:,.0f}"
    if currency:
        return f"{currency} {value:,.2f}"
    return f"{value:,.2f}"


def build_source_link(product, query):
    return (
        product.get("link")
        or product.get("product_link")
        or product.get("serpapi_link")
        or f"https://www.google.com/search?tbm=shop&q={quote_plus(query)}"
    )


def normalize_product(product, query):
    raw_price = product.get("price")
    display_price = raw_price

    if is_recurring_price(raw_price):
        display_price = format_extracted_price(product) or raw_price

    return {
        "title": product.get("title"),
        "price": display_price,
        "image": product.get("thumbnail"),
        "link": build_source_link(product, query),
        "source": product.get("source") or product.get("seller") or product.get("merchant_name"),
        "is_recurring_price": is_recurring_price(raw_price),
    }


def choose_best_product(results, query):
    products = results.get("shopping_results", [])
    if not products:
        return None

    one_time_products = [
        product for product in products
        if product.get("price") and not is_recurring_price(product.get("price"))
    ]
    if one_time_products:
        return normalize_product(one_time_products[0], query)

    extracted_price_products = [
        product for product in products
        if product.get("extracted_price") not in (None, "")
    ]
    if extracted_price_products:
        return normalize_product(extracted_price_products[0], query)

    return normalize_product(products[0], query)


def build_article_cache_key(topic, context, step_summary):
    return "||".join([topic.strip(), context.strip(), step_summary.strip()])

# ------------------- ROUTES -------------------

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/mobo/<mode>')
def mobo_mode(mode):
    if mode not in ["learning", "decision", "compare"]:
        mode = "learning"
    return render_template("mobo.html", mode=mode)

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
"2. Ask as MANY questions as necessary UNTIL you have enough information to make a confident judgment.\n"
"3. Once you have enough information, STOP asking questions and give a FINAL evaluation that includes:\n"
"   - whether the purchase seems thoughtful or impulsive,\n"
"   - what else the money could realistically be used for or saved toward,\n"
"   - a clear recommendation: Go for it / Think twice / Wait and save.\n"
"4. Clearly signal when you are giving the FINAL evaluation.\n"
"5. After giving the final evaluation, DO NOT ask further questions.\n\n"

"Tone: friendly, practical, and non-judgmental, like a financially wise older friend. "
"Use relatable examples in INR (₹), such as snacks, subscriptions, phone recharges, or travel.\n"
"Stay strictly focused on purchase decisions only.\n"
"Do not use em dashes in your writing. Use commas, colons, or separate sentences instead."
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
        return jsonify({'response': DECISION_FALLBACK_RESPONSE})


@app.route('/reset_chat', methods=['POST'])
def reset_chat():
    """Clear a conversation so the user can start a fresh decision.

    Defaults to the decision chat; pass scope=learning or scope=all to clear
    the tutor history instead. The two histories are deliberately separate.
    """
    scope = request.form.get('scope', 'decision')

    if scope in ('decision', 'all'):
        session.pop('chat_history', None)
    if scope in ('learning', 'all'):
        session.pop('learning_chat_history', None)

    return jsonify({'ok': True, 'cleared': scope})


# ------------------- LEARNING ASSISTANT (separate from Decision) -------------------

@app.route('/ask_learning', methods=['POST'])
def ask_learning():
    message = request.form.get('message', '').strip()
    topic = request.form.get('topic', '').strip()
    context = request.form.get('context', '').strip()

    if not message:
        return jsonify({'response': "Please type something."})

    if 'learning_chat_history' not in session:
        system_prompt = LEARNING_SYSTEM_PROMPT
        if context:
            system_prompt += f"\n\nThe learner described their background as: {context}"
        session['learning_chat_history'] = [
            {"role": "system", "content": system_prompt}
        ]

    chat_history = session['learning_chat_history']

    # Give the tutor awareness of which roadmap step the learner is on.
    user_content = message
    if topic:
        user_content = f"[The learner is currently reading the roadmap step: \"{topic}\"]\n\n{message}"

    chat_history.append({"role": "user", "content": user_content})

    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=chat_history,
            max_tokens=350
        )
        reply = response.choices[0].message.content.strip()

        chat_history.append({"role": "assistant", "content": reply})
        if len(chat_history) > MAX_CHAT_HISTORY_MESSAGES:
            chat_history = [chat_history[0]] + chat_history[-(MAX_CHAT_HISTORY_MESSAGES - 1):]
        session['learning_chat_history'] = chat_history

        return jsonify({'response': reply})

    except Exception as e:
        print("Ask Learning Error:", e)
        return jsonify({'response': LEARNING_FALLBACK_RESPONSE})


# ------------------- LEARNING MODE -------------------

@app.route('/generate_roadmap', methods=['POST'])
def generate_roadmap():
    context = request.form.get("context", "").strip()
    if not context:
        return jsonify({"error": "Missing context"}), 400

    prompt = (
        "You are MoBo, a financial literacy mentor for teenagers.\n\n"
        f"User background:\n{context}\n\n"
        "Create a personalized 8-10 step roadmap to improve their financial knowledge.\n"
        "Start from their current level and gradually advance.\n\n"
        "IMPORTANT:\n"
        "- Return ONLY valid JSON\n"
        "- No explanation, no text before or after\n"
        "- Do not use em dashes in the titles or summaries\n"
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
    context = request.form.get('context', '').strip()
    step_summary = request.form.get('summary', '').strip()
    cache_key = build_article_cache_key(topic, context, step_summary)

    if cache_key in ARTICLE_CACHE:
        return jsonify({'article': ARTICLE_CACHE[cache_key]})

    if not topic:
        return jsonify({'article': "⚠️ No topic provided."})

    context_block = ""
    if context:
        context_block += f"Original learner goal/context: {context}\n"
    if step_summary:
        context_block += f"Roadmap step summary: {step_summary}\n"

    prompt = (
        f"You are MoBo, a financial mentor for Indian teenagers.\n\n"
        f"{context_block}\n"
        f"Explain the roadmap step: '{topic}' in about 200-250 words.\n"
        "Keep the explanation tightly aligned with the learner's original goal and this roadmap step.\n"
        "If the learner mentioned a country, market, product type, or objective, explicitly include it in the explanation.\n"
        "Do not drift into generic advice that ignores the learner context.\n"
        "DO NOT include the title in the response.\n"
        "Start directly with the explanation.\n"
        "Use simple language and real-life examples (pocket money, savings, UPI, etc).\n"
        "Use INR (₹) for all examples, unless otherwise specified.\n"
        "Give PRACTICAL tips and ACTIONABLE advice related to the topic.\n"
        "End with 2-3 key takeaways.\n"
        + NO_EM_DASH
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

        ARTICLE_CACHE[cache_key] = article

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
        return choose_best_product(results, query)
    except Exception:
        return None

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
        return usd * USD_TO_INR

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
        return jsonify(build_compare_fallback(item1, item2))

if __name__ == '__main__':
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
