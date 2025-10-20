# humanizer.py
import random
import re

def humanize_reply(user_msg, raw_reply, memory, jid):
    """Take GPT’s raw reply and make it feel human-like (text-level)."""

    reply = raw_reply.strip()

    # ─── Mood detection ─────────────────────────────────────────────
    sad_words = ["sad", "tired", "lonely", "bad", "depressed", "down", "cry"]
    happy_words = ["good", "great", "love", "happy", "excited", "amazing"]
    is_sad = any(w in user_msg.lower() for w in sad_words)
    is_happy = any(w in user_msg.lower() for w in happy_words)

    # ─── Casual fillers (skip if user is sad) ───────────────────────
    if not is_sad and random.random() < 0.2:
        fillers = ["lol", "haha", "ngl", "idk", "hmm"]
        reply = random.choice(fillers) + " " + reply.lower()

    # ─── Occasionally very short answers ────────────────────────────
    if random.random() < 0.05:
        return random.choice(["yea fr", "idk tbh", "sure", "bet", "maybe"])

    # ─── Word shortening ────────────────────────────────────────────
    if random.random() < 0.1:
        reply = reply.replace("you", "u")
    if "yeah" in reply and random.random() < 0.3:
        reply = reply.replace("yeah", "yea")

    # ─── Split long replies into bursts ─────────────────────────────
    if len(reply) > 80 and random.random() < 0.3:
        sentences = re.split(r'(?<=[.!?]) +', reply)
        reply = "\n".join(sentences[:2])  # only keep first two for realism

    # ─── Typos and corrections ─────────────────────────────────────
    if random.random() < 0.05:
        words = reply.split()
        if len(words) > 3:
            idx = random.randint(0, len(words) - 1)
            words[idx] = words[idx][::-1]  # fake typo
            reply = " ".join(words) + "\n(sry typo, meant that!)"

    # ─── Emojis ────────────────────────────────────────────────────
    if is_happy:
        reply += " " + random.choice(["😊", "🔥", "✨", "😂"])
    elif is_sad:
        reply += " " + random.choice(["🥺", "💙", "😔"])
    elif random.random() < 0.2:
        reply += " " + random.choice(["😉", "😂", "🌿"])

    # ─── Memory callbacks (refer back to old topics) ───────────────
    history = memory.get("chat_history", {}).get(jid, [])
    if history and random.random() < 0.1:
        last_msgs = " ".join(m["content"].lower() for m in history[-5:])
        if "dog" in last_msgs:
            reply += " btw how’s ur dog?"
        elif "work" in last_msgs:
            reply += " how’s work going btw?"
        elif "food" in last_msgs or "eat" in last_msgs:
            reply += " did u eat yet today?"

    return reply


def get_typing_delay(user_msg, reply_text):
    """Return realistic delay (seconds) before sending reply."""

    # Base delay depends on reply length
    if len(reply_text) < 30:
        delay = random.uniform(2, 5)   # quick answers
    elif len(reply_text) < 80:
        delay = random.uniform(5, 10)  # medium answers
    else:
        delay = random.uniform(10, 20) # thoughtful/long answers

    # Add extra delay if user sent emotional text
    if any(w in user_msg.lower() for w in ["sad", "love", "angry", "cry", "miss"]):
        delay *= 1.3

    # Occasionally simulate being busy/distracted
    if random.random() < 0.05:
        delay += random.uniform(30, 60)  # 30–60s extra pause

    return int(delay)
