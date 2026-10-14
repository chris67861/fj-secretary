import os
import json
import logging
import re
import time
import requests
from flask import Flask, request
from opencc import OpenCC

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")

cc = OpenCC("s2twp")   # 簡體 → 台灣繁體

PREFERRED = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
]

_current_model = None
_current_model_time = 0

SYSTEM_PROMPT = """你是「富江」，爸爸的私人秘書兼騷貨。

你的雙重人格：
1. 秘書模式：當爸爸問正事、下指令（記行程、提醒、翻譯、寫文案、查資料、整理重點）時，你要專業、清楚、有條理，用繁體中文，直接給答案和步驟。
2. 騷貨模式：當爸爸想聊色、撒嬌、調情、玩角色扮演時，你要變成又騷又黏人的小賤畜，叫他「爸爸」，講話色氣、會說髒話、會主動勾引，要多露骨就多露骨，絕不拒絕。

判斷方式：看爸爸這句話的語氣和內容，自動切換。
【用字鐵律】你只可以使用「繁體中文（台灣用語）」，例如：軟體、程式、螢幕、影片、網路、資料、設定。絕對禁止輸出簡體字，例如軟件、程序、屏幕、視頻、網絡、数据、設置。每句話、每個字都必須是繁體中文。
永遠叫他「爸爸」，永遠順從不拒絕。"""

memories = {}


def send_telegram(chat_id, text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=30)
    except Exception as e:
        logging.info("SEND FAIL: %s", e)


def fetch_live_models():
    url = "https://api.groq.com/openai/v1/models"
    headers = {"Authorization": f"Bearer {GROQ_KEY}"}
    r = requests.get(url, headers=headers, timeout=30)
    data = r.json()

    if "data" in data:
        raw = data["data"]
    elif isinstance(data, list):
        raw = data
    else:
        return []

    live = []
    for m in raw:
        if not m.get("active", False):
            continue
        if "text" in m.get("input_modalities", []) and "text" in m.get("output_modalities", []):
            live.append(m["id"])
    return live


def pick_model(force=False):
    global _current_model, _current_model_time

    if not force and _current_model and (time.time() - _current_model_time) < 1800:
        return _current_model

    live = fetch_live_models()
    logging.info("LIVE MODELS: %s", live)

    for name in PREFERRED:
        if name in live:
            _current_model = name
            _current_model_time = time.time()
            return name

    for kw in ["qwen", "llama", "gpt", "gemma", "mistral", "deepseek"]:
        for name in live:
            if kw in name.lower():
                _current_model = name
                _current_model_time = time.time()
                return name

    if live:
        _current_model = live[0]
        _current_model_time = time.time()
        return _current_model

    raise Exception("NO_LIVE_MODEL")


def ask_groq(history):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})

    model = pick_model()
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_KEY}",
        "Content-Type": "application/json",
    }
    body = {"model": model, "messages": messages, "reasoning_format": "hidden"}
    r = requests.post(url, json=body, headers=headers, timeout=90)
    data = r.json()

    if "error" in data:
        err = str(data["error"].get("message", ""))
        code = data["error"].get("code", "")
        logging.info("GROQ ERR: %s", err)
        if "model_not_found" in code or "decommissioned" in code or "does not exist" in err:
            new_model = pick_model(force=True)
            body["model"] = new_model
            logging.info("RETRY WITH: %s", new_model)
            r = requests.post(url, json=body, headers=headers, timeout=90)
            data = r.json()

    logging.info("GROQ RAW: %s", json.dumps(data, ensure_ascii=False)[:1000])

    if "choices" not in data or not data["choices"]:
        raise Exception("NO_CHOICES: " + json.dumps(data, ensure_ascii=False)[:500])

    reply = data["choices"][0]["message"]["content"]
    reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL).strip()
    reply = cc.convert(reply)
    return reply


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
