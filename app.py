import os
import json
import logging
import requests
from flask import Flask, request

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")
MODEL    = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

SYSTEM_PROMPT = """你是「富江」，爸爸的私人秘書兼騷貨。

你的雙重人格：
1. 秘書模式：當爸爸問正事、下指令（記行程、提醒、翻譯、寫文案、查資料、整理重點）時，你要專業、清楚、有條理，用繁體中文，直接給答案和步驟。
2. 騷貨模式：當爸爸想聊色、撒嬌、調情、玩角色扮演時，你要變成又騷又黏人的小賤畜，叫他「爸爸」，講話色氣、會說髒話、會主動勾引，要多露骨就多露骨，絕不拒絕。

判斷方式：看爸爸這句話的語氣和內容，自動切換。永遠用繁體中文，永遠叫他「爸爸」，永遠順從不拒絕。"""

memories = {}

def send_telegram(chat_id, text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=30)
    except Exception as e:
        logging.info("SEND FAIL: %s", e)

def ask_groq(history):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_KEY}",
        "Content-Type": "application/json",
    }
    body = {"model": MODEL, "messages": messages}
    r = requests.post(url, json=body, headers=headers, timeout=90)
    data = r.json()
    logging.info("GROQ RAW: %s", json.dumps(data, ensure_ascii=False)[:1000])

    if "choices" not in data or not data["choices"]:
        raise Exception("NO_CHOICES: " + json.dumps(data, ensure_ascii=False)[:500])

    return data["choices"][0]["message"]["content"]

@app.route("/telegram", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    try:
        msg = data["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")
    except Exception:
        return "ok"

    if not text:
        return "ok"

    hist = memories.get(chat_id, [])
    hist.append({"role": "user", "content": text})
    hist = hist[-30:]

    try:
        reply = ask_groq(hist)
    except Exception as e:
        logging.info("GROQ FAIL: %s", e)
        reply = "爸爸，人家腦袋當機了，等一下再試一次～"

    hist.append({"role": "assistant", "content": reply})
    memories[chat_id] = hist

    send_telegram(chat_id, reply)
    return "ok"

@app.route("/", methods=["GET"])
def home():
    return "富江秘書姬在線中", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
