import os
import json
import re
import traceback
import random
from datetime import datetime, timezone
import pytz
import langid
import uuid
import httpx 

from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask import send_from_directory
from openai import OpenAI
from humanize import humanize_reply, get_typing_delay
# Improved language detection
def safe_detect_lang(text):
    try:
        if len(text.split()) < 3:  # too short, default to English
            return "en"
        lang = detect(text)
        # If detector says something weird but message has only English chars, fallback to en
        if lang not in ["en", "es", "pt", "fr", "de"]:  # only allow common langs you want
            return "en"
        return lang
    except:
        return "en"



# ─────────────────────────────────────────────────────────────────────────────
# API KEY & OPENAI CLIENT
# ─────────────────────────────────────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
api_key = None
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, encoding="utf-8") as f:
        api_key = json.load(f).get("openai_api_key")
if not api_key:
    api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("No API key. Put it in config.json under openai_api_key or set OPENAI_API_KEY.")

# NEW, FIXED CODE
# Create a custom http client that explicitly disables proxies
http_client = httpx.Client()

# Pass that client to OpenAI so it uses our proxy-free settings
client = OpenAI(api_key=api_key, http_client=http_client)
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# ─────────────────────────────────────────────────────────────────────────────
# MEMORY
# ─────────────────────────────────────────────────────────────────────────────
MEM_PATH = os.path.join(os.path.dirname(__file__), "memory.json")
if os.path.exists(MEM_PATH):
    with open(MEM_PATH, encoding="utf-8") as f:
        memory = json.load(f)
else:
    memory = {
        "my_profile": [],
        "personality_profile": [],
        "allowed_contacts": [],
        "settings": {
            "timezone": "America/Guatemala",
            "approval_enabled": False,
            "date_day_first": False,
            "self_labels": ["You", "Julio"]
        },
        "images": [],
        "images_sent": {},          # { jid: [filenames...] }
        "chat_history": {},         # { jid: [ {role, content, ts} ] }
        "contacts_info": {},        # { jid: {...} }
        "pending_for_approval": [], # [{jid, user_msg, reply, images: []}]
        "pending_approved": [],     # consumed by index.js poller
        "missed_messages": {},
        "synced_wa_ids": {}
    }

def save_memory():
    with open(MEM_PATH, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)

# ─────────────────────────────────────────────────────────────────────────────
# IMAGES
# ─────────────────────────────────────────────────────────────────────────────
IMAGES_DIR = os.path.join(os.path.dirname(__file__), "images")
def refresh_images():
    if os.path.isdir(IMAGES_DIR):
        imgs = sorted(os.listdir(IMAGES_DIR))
    else:
        imgs = []
    memory["images"] = imgs
    if memory.get("image_index", 0) >= len(imgs):
        memory["image_index"] = 0
    save_memory()

# ─────────────────────────────────────────────────────────────────────────────
# FLASK APP
# ─────────────────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["DEBUG"] = True

SYSTEM_BASE = (

)


# ─────────────────────────────────────────────────────────────────────────────
# OPENAI HELPER
# ─────────────────────────────────────────────────────────────────────────────
def chat_complete(messages, temperature=0.7, max_tokens=200, top_p=0.9):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
    )
    return resp.choices[0].message.content.strip()


# ─────────────────────────────────────────────────────────────────────────────
# NAV PAGES
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/dashboard")
def dashboard():
    # ✅ Step 1: Load notifications before clearing
    notifications = memory.get("notifications", [])

    # ✅ Step 2: Automatically clear them after viewing
    if notifications:
        memory["notifications"] = []
        save_memory()

    # ✅ Step 3: Render dashboard with updated info
    return render_template(
        "index.html",
        approval_enabled=memory["settings"].get("approval_enabled", False),
        pending_for_approval=memory.get("pending_for_approval", []),
        allowed_contacts=memory.get("allowed_contacts", []),
        contacts_info=memory.get("contacts_info", {}),
        knowledge_gaps=memory.get("knowledge_gaps", []),
        notifications=notifications  # pass to template
    )


@app.route("/contact_profile/<path:jid>")
def show_contact_profile(jid):
    profiles = memory.setdefault("person_profiles", {})
    profile = profiles.setdefault(jid, {"info": "", "style": "", "summary": ""})

    # Look up saved name from allowed_contacts
    contact_name = next(
        (c.get("name") for c in memory.get("allowed_contacts", []) if c["jid"] == jid),
        jid
    )

    # ✅ Get or create contact info
    contact_info = memory.setdefault("contacts_info", {}).setdefault(jid, {})
    media_dir = contact_info.get("media_dir")

    # ✅ Ensure objectives key exists
    contact_info.setdefault("objectives", [])

    # ✅ Collect media files (if any)
    media_files = []
    if media_dir and os.path.isdir(media_dir):
        media_files = [
            f for f in os.listdir(media_dir)
            if os.path.isfile(os.path.join(media_dir, f))
        ]

    # ✅ Render template with 'contact' and 'objectives'
    return render_template(
        "contact_profile.html",
        jid=jid,
        contact_name=contact_name,
        profile=profile,
        summary=profile.get("summary"),
        media_dir=media_dir,
        media_files=media_files,
        contact=contact_info,  # ✅ added for Jinja template compatibility
        objectives=contact_info["objectives"],  # ✅ safe and direct
    )


# ➕ Add Objective
@app.route("/add_objective/<path:jid>", methods=["POST"])
def add_objective(jid):
    obj_type = request.form.get("type", "linguistic").strip().lower()
    description = request.form.get("description", "").strip()
    min_days = int(request.form.get("min_days", 7))
    max_days = int(request.form.get("max_days", 14))

    if not description:
        return redirect(url_for("show_contact_profile", jid=jid))

    # Ask GPT to propose a strategy based on type
    if obj_type == "linguistic":
        prompt = (
            f"Create a conversational strategy to achieve this linguistic goal: '{description}'. "
            f"The goal should be achieved gradually within {min_days}-{max_days} days. "
            "Focus on natural repetition and emotional tone. Write 2–3 sentences."
        )
    else:  # behavioral
        prompt = (
            f"Create a conversational strategy to achieve this behavioral goal: '{description}'. "
            f"Focus on influencing behavior or attitude change over {min_days}-{max_days} days. "
            "Keep it subtle and emotionally intelligent. Write 2–3 sentences."
        )

    strategy = chat_complete(
        [
            {"role": "system", "content": "You are an expert in subtle conversational influence and relationship psychology."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=120
    )

    new_obj = {
        "id": str(uuid.uuid4()),
        "type": obj_type,
        "description": description,
        "status": "in_progress",
        "progress": 0,
        "occurrences_needed": random.randint(3, 6),
        "strategy": strategy,
        "notes": [],
        "min_days": min_days,
        "max_days": max_days,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    contact_info = memory.setdefault("contacts_info", {}).setdefault(jid, {})
    contact_info.setdefault("objectives", []).append(new_obj)
    save_memory()

    # Notify dashboard
    memory.setdefault("notifications", []).append({
        "jid": jid,
        "message": f"New {obj_type} objective added: {description}",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    save_memory()

    return redirect(url_for("show_contact_profile", jid=jid))



# ✅ Mark Objective as Complete
@app.route("/complete_objective/<path:jid>/<obj_id>", methods=["POST"])
def complete_objective(jid, obj_id):
    objectives = memory.setdefault("contacts_info", {}).setdefault(jid, {}).setdefault("objectives", [])
    for obj in objectives:
        if obj["id"] == obj_id:
            obj["status"] = "completed"
            add_notification(jid, f"✅ Objective completed for {jid}: “{obj['description']}”")
            obj["notes"].append("Manually marked complete by user.")
            break
    save_memory()
    return redirect(url_for("show_contact_profile", jid=jid))


# ❌ Delete Objective
@app.route("/delete_objective/<path:jid>/<obj_id>", methods=["POST"])
def delete_objective(jid, obj_id):
    objectives = memory.setdefault("contacts_info", {}).setdefault(jid, {}).setdefault("objectives", [])
    memory["contacts_info"][jid]["objectives"] = [obj for obj in objectives if obj["id"] != obj_id]
    add_notification(jid, f"🗑️ Objective deleted for {jid}")
    save_memory()
    return redirect(url_for("show_contact_profile", jid=jid))



@app.route("/update_profile_style/<path:jid>", methods=["POST"])
def update_profile_style(jid):
    new_style = request.form.get("style", "").strip()
    if new_style:
        memory.setdefault("person_profiles", {}).setdefault(jid, {})["style"] = new_style
        save_memory()
    return redirect(url_for("show_contact_profile", jid=jid))

@app.route("/update_profile_info/<path:jid>", methods=["POST"])
def update_profile_info(jid):
    new_info = request.form.get("info", "").strip()
    # Note: We allow saving even if it's empty to clear the field
    memory.setdefault("person_profiles", {}).setdefault(jid, {})["info"] = new_info
    save_memory()
    return redirect(url_for("show_contact_profile", jid=jid))


@app.route("/update_media_dir/<path:jid>", methods=["POST"])
def update_media_dir(jid):
    new_dir = request.form.get("media_dir", "").strip()
    if new_dir and os.path.isdir(new_dir):  # ✅ only save if folder exists
        contact_info = memory.setdefault("contacts_info", {}).setdefault(jid, {})
        contact_info["media_dir"] = new_dir

        # Scan for media files in that folder
        files = sorted(os.listdir(new_dir))
        contact_info["media_files"] = files

        save_memory()
    else:
        print(f"⚠️ Invalid directory provided: {new_dir}")
    return redirect(url_for("show_contact_profile", jid=jid))


@app.route("/summarize_contact/<path:jid>", methods=["POST"])
def summarize_contact(jid):
    hist = memory.get("chat_history", {}).get(jid, [])
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in hist[-50:])  # last 50 msgs
    summary = chat_complete(
        [
            {"role": "system", "content": "Summarize this contact’s personality, interests, and relationship with Julio."},
            {"role": "user", "content": transcript}
        ],
        temperature=0.4, max_tokens=250
    )

    info = memory.setdefault("person_profiles", {}).setdefault(jid, {})
    info["last_summary"] = summary
    save_memory()
    return redirect(url_for("show_contact_profile", jid=jid))


# keep old "/" working too
@app.route("/")
def index_redirect():
    # load dashboard
    result = dashboard()

    # Clear notifications after viewing
    memory["notifications"] = []
    save_memory()

    return result


@app.route("/nav/sync")
def nav_sync():
    return render_template(
        "sync.html",
        allowed_contacts=memory.get("allowed_contacts", []),
        self_labels=memory["settings"].get("self_labels", ["You"]),
        date_day_first=memory["settings"].get("date_day_first", False),
    )

@app.route("/nav/profile")
def nav_profile():
    return render_template("profile_facts.html", my_profile=memory.get("my_profile", []))

@app.route("/nav/personality")
def nav_personality():
    return render_template(
        "personality.html",
        personality_profile=memory.get("personality_profile", [])
    )

@app.route("/nav/contacts")
def nav_contacts():
    return render_template(
        "contacts.html",
        allowed_contacts=memory.get("allowed_contacts", []),
        contacts_info=memory.get("contacts_info", {})
    )


# ─────────────────────────────────────────────────────────────────────────────
# SMALL UTILS / REGEX
# ─────────────────────────────────────────────────────────────────────────────
WYD_RE = re.compile(
    r"(?:\bwhat(?:'s| is)? (?:are )?you doing\b|\bwyd\b|"
    r"\bq(?:ué|ue)? (?:estás|estas) haciendo\b|\bqué haces\b)",
    re.I
)

IMAGE_RE = re.compile(
    r"(?:\b(?:send|show|share|give|see|have|want|send me|show me|share me)"
    r"(?:\s+me|\s+us)?\b.{0,25})?"
    r"\b(?:image|images|photo|photos|picture|pictures|pic|pics|selfie|selfies)\b"
    r"(?:.{0,25}\b(?:of\s+you|yourself))?",
    re.I
)

MORE_RE = re.compile(r"\b(?:more|another|again|extra|mas|más|otra|otro|otros|otras)\b", re.I)
RESET_IMAGES_RE = re.compile(r"\b(?:start over|from the beginning|reset (?:pics|photos|images))\b", re.I)

# “thanks” + pic words; also explicit words -> don’t auto-send images
THANKS_RE = re.compile(r"\b(?:thanks|thank you|appreciate|gracias|ty)\b", re.I)
PIC_WORD_RE = re.compile(r"\b(?:pic|pics|photo|photos|image|images|selfie|selfies)\b", re.I)
EXPLICIT_RE = re.compile(r"\b(?:dick|penis|nude|naked|xxx|nsfw|explicit)\b", re.I)

def strip_media_placeholders(text: str) -> bool:
    t = text.strip().lower()
    return t in {
        "<media omitted>", "<arquivo de mídia oculto>", "<arquivo de mÍdia oculto>",
        "<imagen omitida>", "<imagem omitida>", "<immagine omessa>", "<medien ausgeschlossen>"
    }

def parse_datetime_parts(date_s, time_s, ampm, day_first: bool, tzname: str):
    parts = re.split(r"[/-]", date_s.strip())
    if len(parts) != 3:
        return datetime.now(timezone.utc).isoformat()

    a, b, y = parts
    a = int(a); b = int(b); y = int(y)
    if y < 100:
        y += 2000

    if day_first or a > 12:
        day, month = a, b
    else:
        month, day = a, b

    hh, mm = time_s.strip().split(":")
    hh = int(hh); mm = int(mm)

    if ampm:
        ap = ampm.lower()
        if ap == "pm" and hh != 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0

    try:
        tz = pytz.timezone(tzname)
    except Exception:
        tz = pytz.UTC

    try:
        dt = tz.localize(datetime(y, month, day, hh, mm))
        return dt.isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()

def parse_whatsapp_export(text: str, self_labels, tzname: str, day_first: bool):
    start_re = re.compile(
        r"""^
        (\d{1,2}[/-]\d{1,2}[/-]\d{2,4}),?\s+
        (\d{1,2}:\d{2})\s*
        (?:(AM|PM|am|pm))?\s*
        [\-\u2013]\s
        ([^:]+):\s
        (.*)$
        """, re.VERBOSE
    )

    messages = []
    cur = None

    lines = text.splitlines()
    for line in lines:
        m = start_re.match(line)
        if m:
            if cur:
                messages.append(cur)
                cur = None

            date_s, time_s, ampm, sender, content = m.groups()
            if ":" not in line and not content:
                continue
            if strip_media_placeholders(content):
                continue

            sender_clean = sender.strip()
            role = "assistant" if sender_clean in self_labels else "user"
            ts = parse_datetime_parts(date_s, time_s, ampm, day_first, tzname)
            cur = {"role": role, "content": content.strip(), "ts": ts}
        else:
            if cur and not strip_media_placeholders(line):
                cur["content"] += "\n" + line.strip()

    if cur:
        messages.append(cur)

    return [m for m in messages if m["content"].strip()]

def merge_into_history(jid: str, parsed_msgs: list):
    """Merge parsed messages into history only for allowed contacts."""
    if not any(c["jid"] == jid for c in memory.get("allowed_contacts", [])):
        return 0, 0  # 🚫 skip unknown contacts completely

    hist = memory.setdefault("chat_history", {}).setdefault(jid, [])
    tail = hist[-200:]
    seen = {(m["role"], m["content"].strip()) for m in tail}
    added = 0
    for m in parsed_msgs:
        key = (m["role"], m["content"].strip())
        if key in seen:
            continue
        hist.append(m)
        seen.add(key)
        added += 1
    save_memory()
    return added, len(parsed_msgs)

def ensure_contact_struct(jid: str):
    """Only create contact structures if jid is in allowed_contacts."""
    if not any(c["jid"] == jid for c in memory.get("allowed_contacts", [])):
        return  # 🚫 don’t create anything for unknown contacts

    memory.setdefault("chat_history", {}).setdefault(jid, [])
    memory.setdefault("images_sent", {}).setdefault(jid, [])
    contact_info = memory.setdefault("contacts_info", {}).setdefault(jid, {})

    # ✅ Ensure objectives structure exists
    contact_info.setdefault("objectives", [])
    
    # ✅ NEW: Ensure the update counter exists
    contact_info.setdefault("messages_since_profile_update", 0)

    # No save_memory() here, it will be saved by the calling function

    save_memory()

def recent_user_asked_for_photos(jid: str, within: int = 6) -> bool:
    """Look back a few user turns for an image request to interpret 'more'."""
    for m in reversed(memory.setdefault("chat_history", {}).get(jid, [])):
        if m["role"] != "user":
            continue
        if IMAGE_RE.search(m["content"]):
            return True
        within -= 1
        if within <= 0:
            break
    return False


def add_notification(jid, message):
    memory.setdefault("notifications", []).append({
        "jid": jid,
        "message": message,
        "ts": datetime.now(timezone.utc).isoformat()
    })
    # Keep only last 50
    memory["notifications"] = memory["notifications"][-50:]
    save_memory()




# ─────────────────────────────────────────────────────────────────────────────
# FACT / PERSONALITY CRUD
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/edit_fact/<int:idx>")
def edit_fact(idx):
    if idx < 0 or idx >= len(memory["my_profile"]):
        return redirect(url_for("index"))
    return render_template("edit_fact.html", idx=idx, fact=memory["my_profile"][idx])

@app.route("/update_fact/<int:idx>", methods=["POST"])
def update_fact(idx):
    new = request.form.get("fact","").strip()
    if new and 0 <= idx < len(memory["my_profile"]):
        memory["my_profile"][idx] = new
        save_memory()
    return redirect(url_for("nav_profile"))

@app.route("/add_fact", methods=["POST"])
def add_fact():
    fact = request.form.get("fact","").strip()
    if fact:
        memory.setdefault("my_profile", []).append(fact)
        save_memory()
    return redirect(url_for("nav_profile"))

@app.route("/remove_fact/<int:idx>", methods=["POST"])
def remove_fact(idx):
    if 0 <= idx < len(memory["my_profile"]):
        memory["my_profile"].pop(idx)
        save_memory()
    return redirect(url_for("nav_profile"))

@app.route("/edit_personality/<int:idx>")
def edit_personality(idx):
    if idx < 0 or idx >= len(memory["personality_profile"]):
        return redirect(url_for("index"))
    return render_template("edit_personality.html", idx=idx, trait=memory["personality_profile"][idx])

@app.route("/update_personality/<int:idx>", methods=["POST"])
def update_personality(idx):
    new = request.form.get("trait","").strip()
    if new and 0 <= idx < len(memory["personality_profile"]):
        memory["personality_profile"][idx] = new
        save_memory()
    return redirect(url_for("nav_personality"))

@app.route("/add_personality", methods=["POST"])
def add_personality():
    trait = request.form.get("trait","").strip()
    if trait:
        memory.setdefault("personality_profile", []).append(trait)
        save_memory()
    return redirect(url_for("nav_personality"))

@app.route("/remove_personality/<int:idx>", methods=["POST"])
def remove_personality(idx):
    if 0 <= idx < len(memory["personality_profile"]):
        memory["personality_profile"].pop(idx)
        save_memory()
    return redirect(url_for("nav_personality"))

# ─────────────────────────────────────────────────────────────────────────────
# CONTACTS + SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/update_contact_name", methods=["POST"])
def update_contact_name():
    jid  = request.form.get("jid","").strip()
    name = request.form.get("name","").strip()
    for c in memory.get("allowed_contacts", []):
        if c["jid"] == jid:
            c["name"] = name
            break
    save_memory()
    return redirect(url_for("nav_contacts"))

@app.route("/add_contact", methods=["POST"])
def add_contact():
    jid = request.form.get("jid","").strip()
    if jid and not any(c["jid"] == jid for c in memory.get("allowed_contacts", [])):
        memory.setdefault("allowed_contacts", []).append({
            "jid": jid, "enabled": True, "name": ""
        })
        ensure_contact_struct(jid)
        save_memory()
    return redirect(url_for("nav_contacts"))

@app.route("/toggle_contact/<jid>", methods=["POST"])
def toggle_contact(jid):
    for c in memory.get("allowed_contacts", []):
        if c["jid"] == jid:
            c["enabled"] = not c.get("enabled", False)
            if c["enabled"]:
                ensure_contact_struct(jid)
            break
    save_memory()
    return redirect(url_for("nav_contacts"))

@app.route("/remove_contact/<jid>", methods=["POST"])
def remove_contact(jid):
    memory["allowed_contacts"] = [
        c for c in memory.get("allowed_contacts", []) if c["jid"] != jid
    ]
    memory.get("chat_history", {}).pop(jid, None)
    memory.get("images_sent", {}).pop(jid, None)
    memory.get("contacts_info", {}).pop(jid, None)
    memory["pending_for_approval"] = [
        it for it in memory.get("pending_for_approval", []) if it.get("jid") != jid
    ]
    memory["pending_approved"] = [
        it for it in memory.get("pending_approved", []) if it.get("jid") != jid
    ]
    memory.get("missed_messages", {}).pop(jid, None)
    memory.get("synced_wa_ids", {}).pop(jid, None)

    save_memory()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"status": "ok"})
    return redirect(url_for("nav_contacts"))

@app.route("/toggle_approval", methods=["POST"])
def toggle_approval():
    curr = memory["settings"].get("approval_enabled", False)
    memory["settings"]["approval_enabled"] = not curr
    save_memory()
    return redirect(url_for("index"))


@app.route("/media/<path:jid>/<path:filename>")
def serve_media(jid, filename):
    contact_info = memory.setdefault("contacts_info", {}).get(jid, {})
    media_dir = contact_info.get("media_dir")

    if not media_dir or not os.path.isdir(media_dir):
        return "Media directory not set or missing.", 404

    return send_from_directory(media_dir, filename)

# ─────────────────────────────────────────────────────────────────────────────
# APPROVAL WORKFLOW
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/approve_reply/<int:idx>", methods=["POST"])
def approve_reply(idx):
    pend = memory.get("pending_for_approval", [])
    if 0 <= idx < len(pend):
        item = pend.pop(idx)
        # Push localized reply
        memory.setdefault("pending_approved", []).append({
            "jid": item.get("jid"),
            "reply": item.get("reply", ""),   # this is localized
            "images": item.get("images", [])
        })
        hist = memory.setdefault("chat_history", {}).setdefault(item["jid"], [])
        hist.append({
            "role": "assistant",
            "content": item.get("reply", ""), # localized
            "ts": datetime.now(timezone.utc).isoformat()
        })
        save_memory()
    return redirect(url_for("index"))

@app.route("/approve_with_edit/<int:idx>", methods=["POST"])
def approve_with_edit(idx):
    pend = memory.get("pending_for_approval", [])
    if 0 <= idx < len(pend):
        item = pend.pop(idx)
        
        # ✅ FIX: Get the edited text from the form.
        # It looks for "edited_reply", which is the name of your textarea.
        # If for some reason it's empty, it safely falls back to the original reply.
        edited_text = request.form.get("edited_reply", item.get("reply", ""))

        # ✅ FIX: Use the 'edited_text' variable when adding to the approved queue.
        memory.setdefault("pending_approved", []).append({
            "jid": item.get("jid"),
            "reply": edited_text,
            "images": item.get("images", [])
        })
        
        hist = memory.setdefault("chat_history", {}).setdefault(item["jid"], [])
        # ✅ FIX: Use the 'edited_text' variable when saving to chat history.
        hist.append({
            "role": "assistant",
            "content": edited_text,
            "ts": datetime.now(timezone.utc).isoformat()
        })
        save_memory()
    return redirect(url_for("index"))

@app.route("/reject_reply/<int:idx>", methods=["POST"])
def reject_reply(idx):
    if 0 <= idx < len(memory.get("pending_for_approval", [])):
        memory["pending_for_approval"].pop(idx)
        save_memory()
    return redirect(url_for("index"))

@app.route("/regenerate_reply/<int:idx>", methods=["POST"])
def regenerate_reply(idx):
    pend = memory.get("pending_for_approval", [])
    if not (0 <= idx < len(pend)):
        return redirect(url_for("index"))
    instruction = request.form.get("instruction", "").strip()
    item = pend[idx]
    jid = item["jid"]
    user_msg = item["user_msg"]

    # keep any images already attached to this pending item
    keep_images = item.get("images", [])

    # build prompt
    system = SYSTEM_BASE
    if memory.get("my_profile"):
        system += "\n\nFacts about Julio:\n" + "\n".join(f"- {f}" for f in memory["my_profile"])
    if memory.get("personality_profile"):
        system += "\n\nPersonality guidelines:\n" + "\n".join(f"- {t}" for t in memory["personality_profile"])
    last10 = memory["chat_history"].get(jid, [])[-10:]
    system += "\n\nRecent conversation:\n" + "\n".join(f"{m['role']}: {m['content']}" for m in last10)

    new_text = chat_complete(
        [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
            {"role": "user",   "content": f"Regenerate the reply with this guidance: {instruction}"}
        ],
        temperature=0.7, max_tokens=150, top_p=0.9
    )
    pend[idx]["reply"] = new_text
    pend[idx]["images"] = keep_images
    save_memory()
    return redirect(url_for("index"))

@app.route("/pending", methods=["GET"])
def get_pending():
    return jsonify({
        "pending_for_approval": memory.get("pending_for_approval", []),
        "approval_enabled": memory["settings"].get("approval_enabled", False)
    })

# Consumed by index.js poller; it will send images then the text.
@app.route("/approved_batch", methods=["GET"])
def approved_batch():
    items = memory.get("pending_approved", [])
    memory["pending_approved"] = []
    save_memory()
    return jsonify(items=items)

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARIES
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/summary/<path:jid>", methods=["GET"])
def summary(jid):
    hist = memory.get("chat_history", {}).get(jid, [])
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in hist)
    text = chat_complete(
        [
            {"role":"system","content":
             "Summarize the most important personal details and personality traits from this conversation."},
            {"role":"user","content":transcript}
        ],
        temperature=0.3, max_tokens=300, top_p=1.0
    )
    return jsonify(summary=text)

@app.route("/generate_contact_summary/<path:jid>", methods=["POST"])
def generate_contact_summary(jid):
    hist = memory.get("chat_history", {}).get(jid, [])
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in hist[-40:])

    summary = chat_complete(
        [
            {"role": "system", "content": "Summarize the important details, personality traits, and context."},
            {"role": "user", "content": transcript},
        ],
        temperature=0.4,
        max_tokens=250,
        top_p=0.9,
    )

    profiles = memory.setdefault("person_profiles", {})
    profile = profiles.setdefault(jid, {})
    profile["summary"] = summary
    profile["last_summarized"] = datetime.now(timezone.utc).isoformat()
    save_memory()

    # Instead of JSON, refresh profile page
    return redirect(url_for("show_contact_profile", jid=jid))

# ─────────────────────────────────────────────────────────────────────────────
# IMPORT CHAT EXPORT (helper for sync)
# ─────────────────────────────────────────────────────────────────────────────
def import_chat_export(jid: str, text: str, self_label: str, day_first: bool):
    """
    Parse a WhatsApp .txt export and merge it into memory['chat_history'].
    Returns (added_messages, parsed_total).
    """
    tzname = memory["settings"].get("timezone", "America/Guatemala")
    self_labels = [self_label] + memory["settings"].get("self_labels", [])

    parsed_msgs = parse_whatsapp_export(text, self_labels, tzname, day_first)
    added, parsed = merge_into_history(jid, parsed_msgs)

    # ensure contact exists
    ensure_contact_struct(jid)

    return added, parsed
# ─────────────────────────────────────────────────────────────────────────────
# UPLOAD & SYNC EXPORTED CHAT
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/upload_chat", methods=["POST"])
def upload_chat():
    file = request.files["file"]
    jid = request.form["jid"]
    self_label = request.form["self_label"]
    day_first = request.form.get("day_first") == "true"

    if file and file.filename.endswith(".txt"):
        text = file.read().decode("utf-8", errors="ignore")
        added, parsed = import_chat_export(jid, text, self_label, day_first)

        success_message = f"✅ Sync completed! Parsed {parsed} lines, added {added} messages for {jid}."

        return render_template(
            "sync.html",
            allowed_contacts=memory["allowed_contacts"],
            self_labels=memory.get("self_labels", []),
            date_day_first=memory.get("date_day_first", False),
            success_message=success_message
        )

    # fallback if no file
    return redirect(url_for("nav_sync"))
# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html",
        my_profile=memory["my_profile"],
        personality_profile=memory["personality_profile"],
        allowed_contacts=memory["allowed_contacts"],
        pending_for_approval=memory["pending_for_approval"],
        approval_enabled=memory["settings"].get("approval_enabled", False),
        contacts_info=memory.get("contacts_info", {}),
        self_labels=memory["settings"].get("self_labels", ["You"]),
        date_day_first=memory["settings"].get("date_day_first", False)
    )


def update_contact_profile_with_ai(jid):
    """
    Analyzes recent conversation and automatically refines the contact's
    'info' and 'style' profile fields.
    """
    print(f"[INFO] Running automatic profile update for {jid}...")
    try:
        profiles = memory.setdefault("person_profiles", {})
        profile = profiles.setdefault(jid, {"info": "", "style": "", "summary": ""})
        
        current_info = profile.get("info", "")
        current_style = profile.get("style", "")
        
        # Get the last 40 messages for context
        transcript = "\n".join(
            f"{m['role']}: {m['content']}" 
            for m in memory.get("chat_history", {}).get(jid, [])[-40:]
        )

        if not transcript.strip():
            print(f"[INFO] No transcript for {jid}, skipping profile update.")
            return

        prompt = f"""
You are a profile analyst AI. Your job is to refine a contact's profile based on recent conversation.
Analyze the provided transcript and update the existing 'info' and 'style' sections.

**RULES:**
1.  **Refine, Don't Replace:** Integrate new learnings into the existing text. Do not remove existing user-written notes unless they are explicitly contradicted in the conversation.
2.  **'Info' is for Facts:** Extract concrete, objective facts about the person (e.g., job, family, plans, preferences).
3.  **'Style' is for Communication:** Analyze their linguistic style (e.g., formality, emoji use, sentence length, common phrases, tone).
4.  **Output JSON:** Respond ONLY with a valid JSON object with two keys: "updated_info" and "updated_style".

**EXISTING INFO:**
---
{current_info}
---

**EXISTING STYLE:**
---
{current_style}
---

**RECENT CONVERSATION TRANSCRIPT:**
---
{transcript}
---

Now, provide the complete, updated profile sections in a single JSON object.
"""

        response_str = chat_complete(
            [{"role": "system", "content": prompt}],
            temperature=0.4,
            max_tokens=500
        )
        
        # Safely parse the JSON response
        updates = json.loads(response_str)
        new_info = updates.get("updated_info")
        new_style = updates.get("updated_style")

        if new_info is not None and new_info != current_info:
            profile["info"] = new_info
            add_notification(jid, "🤖 AI automatically updated the 'Info' profile.")
            print(f"[SUCCESS] Updated 'info' for {jid}.")

        if new_style is not None and new_style != current_style:
            profile["style"] = new_style
            add_notification(jid, "🤖 AI automatically updated the 'Style' profile.")
            print(f"[SUCCESS] Updated 'style' for {jid}.")

    except Exception as e:
        print(f"[ERROR] Failed to automatically update profile for {jid}: {e}")
# ─────────────────────────────────────────────────────────────────────────────
# REPLY ENDPOINT (context-aware)
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/reply", methods=["POST"])
def reply():
    try:
        refresh_images()
        data = request.get_json(force=True)
        jid = data.get("sender") or data.get("jid")
        msg = (data.get("message") or data.get("text") or "").strip()
        # ADD THIS LINE
        if not msg:
            return jsonify(reply="") # Ignore empty messages

        # 🚫 Block unknown contacts before struct creation
        if not any(c["jid"] == jid and c.get("enabled") for c in memory["allowed_contacts"]):
            return jsonify(reply="")

        ensure_contact_struct(jid)  # ✅ Only runs if allowed

        # ✅ NEW: Holding variables for our single exit point
        final_reply = None
        images_to_send = []
        user_msg_for_approval = msg  # Save original message for the approval queue

        hist = memory.setdefault("chat_history", {}).setdefault(jid, [])
        hist.append({"role": "user", "content": msg, "ts": datetime.now(timezone.utc).isoformat()})
        # Note: Save memory once here to log the user message immediately
        save_memory()

        # ---------------------------------------------------------------------
        # Section 1: Rule-Based Logic (No direct returns!)
        # ---------------------------------------------------------------------
        
        # Rule 1: "what are you doing" (Guatemala time)
        if WYD_RE.search(msg):
            tz = memory["settings"].get("timezone", "America/Guatemala")
            now = datetime.now(pytz.timezone(tz))
            hour = now.hour
            if 12 <= hour < 13:
                final_reply = "I’m on lunch break right now, back to work at 1 PM."
            elif 6 <= hour < 15:
                final_reply = "I’m here working with my clients and doing related tasks."

        # Rule 2: Clock question
        elif re.search(r"\b(?:what(?:'s| is)? the time|current time)\b", msg, re.I):
            tz = memory["settings"].get("timezone", "America/Guatemala")
            now = datetime.now(pytz.timezone(tz))
            final_reply = f"The current time in Guatemala is {now.strftime('%I:%M %p').lstrip('0')}."

        # Rule 3: Reset image flow
        elif RESET_IMAGES_RE.search(msg):
            memory.setdefault("images_sent", {}).setdefault(jid, [])
            memory["images_sent"][jid] = []
            final_reply = "Resetting the gallery — I’ll start from the top next time you ask 😊"

        # Rule 4: Context guard for photo requests
        elif (THANKS_RE.search(msg) and PIC_WORD_RE.search(msg)) or EXPLICIT_RE.search(msg):
            final_reply = "You’re sweet. I’m glad you liked them. Want more travel or everyday moments? 😉"

        # Rule 5: Photo requests and follow-ups
        else:
            asked_photos = IMAGE_RE.search(msg)
            wants_more_only = MORE_RE.search(msg) and not asked_photos
            if asked_photos or wants_more_only:
                followup_ok = wants_more_only and (recent_user_asked_for_photos(jid) or bool(memory["images_sent"].get(jid)))
                if asked_photos or followup_ok:
                    imgs = memory.get("images", [])
                    sent = memory.setdefault("images_sent", {}).get(jid, [])
                    rem = [i for i in imgs if i not in sent]
                    if not rem:
                        out_lines = [
                            "That’s what I have for now 😌. Once I take more, I’ll gladly share them with you.",
                            "I’m out of photos at the moment — when I snap new ones, they’re yours 😊.",
                        ]
                        final_reply = random.choice(out_lines)
                    else:
                        batch = rem[:2]
                        images_to_send = batch
                        closings = ["Hope you like them 😉", "Thought you’d enjoy these ✨", "Just for you 💫"]
                        final_reply = random.choice(closings)
                        # We only track sent images when the reply is actually sent (handled later)
                else:
                    final_reply = "Do you mean more photos? If so, say the word 'photos' and I’ll send some 📸"
        
        # ---------------------------------------------------------------------
        # Section 2: GPT-Powered Logic (only if no rule was met)
        # ---------------------------------------------------------------------
        if final_reply is None:
            # ... inside the 'if final_reply is None:' block ...
            system = SYSTEM_BASE
            if memory.get("my_profile"):
                system += "\n\nFacts about Julio:\n" + "\n".join(f"- {f}" for f in memory["my_profile"])
            if memory.get("personality_profile"):
                system += "\n\nPersonality guidelines:\n" + "\n".join(f"- {t}" for t in memory["personality_profile"])

            # ✅ NEW: Add contact-specific info and style from their profile
            profiles = memory.get("person_profiles", {})
            contact_profile = profiles.get(jid, {})
            if contact_profile.get("info"):
                system += f"\n\nIMPORTANT FACTS TO REMEMBER ABOUT THIS PERSON:\n{contact_profile['info']}"
            if contact_profile.get("style"):
                system += f"\n\nADOPT THIS SPECIFIC STYLE FOR THIS PERSON:\n{contact_profile['style']}"

            last10 = memory["chat_history"][jid][-10:]
            system += "\n\nRecent conversation:\n" + "\n".join(f"{m['role']}: {m['content']}" for m in last10)

            lang, _ = langid.classify(msg)

            raw_reply_en = chat_complete(
                [{"role": "system", "content": system},
                 {"role": "user", "content": f"(Reply in English only)\n\n{msg}"}],
                temperature=0.7, max_tokens=150, top_p=0.9
            )

            if raw_reply_en.startswith("[NEED_INFO:"):
                missing_topic = raw_reply_en.replace("[NEED_INFO:", "").replace("]", "").strip()
                memory.setdefault("knowledge_gaps", []).append(missing_topic)
                final_reply = f"(⚠️ Missing info: {missing_topic})"
            else:
                reply_translated = raw_reply_en
                if lang != "en":
                    reply_translated = chat_complete(
                        [
                            {"role": "system", "content": "Translate naturally, keep tone conversational."},
                            {"role": "user", "content": f"Translate to natural {lang.upper()}:\n\n{raw_reply_en}"}
                        ],
                        temperature=0.7, max_tokens=200, top_p=0.9
                    )
                final_reply = humanize_reply(msg, reply_translated, memory, jid)

        # ───────────────────────────────────────────────────────────────────
        # FINAL EXIT POINT: All replies must pass through here.
        # ───────────────────────────────────────────────────────────────────
        if final_reply:
            if memory["settings"].get("approval_enabled"):
                memory.setdefault("pending_for_approval", []).append({
                    "jid": jid,
                    "user_msg": user_msg_for_approval,
                    "reply": final_reply,
                    "images": images_to_send
                })
                save_memory()
                return jsonify(reply="")
            else:
                # Approval is OFF, send directly
                hist.append({"role": "assistant", "content": final_reply, "ts": datetime.now(timezone.utc).isoformat()})
                
                # If we are sending images, log them now
                if images_to_send:
                    memory.setdefault("images_sent", {}).setdefault(jid, []).extend(images_to_send)

                # Check for objective progress (only when sending automatically)
                objectives = memory.get("contacts_info", {}).get(jid, {}).get("objectives", [])
                for obj in objectives:
                    if obj.get("status") != "in_progress": continue
                    
                    progress_made = False
                    if obj["type"] == "linguistic":
                        key_terms = [w.strip().lower() for w in obj["description"].split() if len(w) > 3]
                        if any(term in msg.lower() for term in key_terms):
                            progress_made = True
                            obj["notes"].append(f"Matched linguistic cue in message: '{msg}'")
                    
                    elif obj["type"] == "behavioral":
                        progress_detected = chat_complete(
                            [
                                {"role": "system", "content": "You are a precise behavior progress detector."},
                                {"role": "user", "content": f"Objective: {obj['description']}\nMessage: {msg}\nDoes this message show progress? Reply only 'yes' or 'no'."}
                            ],
                            temperature=0.1, max_tokens=3
                        ).strip().lower()
                        if "yes" in progress_detected:
                            progress_made = True
                            obj["notes"].append(f"Behavioral cue detected in message: '{msg}'")
                    
                    if progress_made:
                        obj["progress"] = obj.get("progress", 0) + 1
                        if obj["progress"] >= obj.get("occurrences_needed", 5):
                            obj["status"] = "completed"
                            add_notification(jid, f"✅ Objective completed: “{obj['description']}”")

                save_memory()
                return jsonify(reply=final_reply, images=images_to_send)

        # If no reply was generated, return empty
        return jsonify(reply="")


    # ... inside reply(), right before the 'except' block ...

        # ---------------------------------------------------------------------
        # Section 3: Automatic Profile Update Trigger
        # ---------------------------------------------------------------------
        contact_info = memory.setdefault("contacts_info", {}).setdefault(jid, {})
        counter = contact_info.get("messages_since_profile_update", 0) + 1
        contact_info["messages_since_profile_update"] = counter

        # Trigger the update every 20 messages
        if counter >= 20:
            update_contact_profile_with_ai(jid)
            contact_info["messages_since_profile_update"] = 0 # Reset counter
        
        save_memory() # Final save before returning
        
        # This should be the last part of the 'try' block
        if final_reply and not memory["settings"].get("approval_enabled"):
             return jsonify(reply=final_reply, images=images_to_send)
        else:
             return jsonify(reply="")
             
    except Exception as e:
        traceback.print_exc()
        return jsonify(reply=f"Error: {e}"), 500

@app.route("/add_knowledge_gap", methods=["POST"])
def add_knowledge_gap():
    gap_key = request.form.get("gap", "").strip()
    gap_value = request.form.get("gap_value", "").strip()
    target = request.form.get("target", "facts")  # default to facts

    if not gap_key or not gap_value:
        return redirect(url_for("dashboard"))

    # ✅ Save info into my_profile or personality_profile
    entry = f"{gap_key}: {gap_value}"
    if target == "facts":
        memory.setdefault("my_profile", []).append(entry)
    elif target == "personality":
        memory.setdefault("personality_profile", []).append(entry)
        add_notification("system", f"🧩 Knowledge gap filled: “{gap_key}” → “{gap_value}”")


    # ✅ Remove gap from knowledge_gaps
    if gap_key in memory.get("knowledge_gaps", []):
        memory["knowledge_gaps"].remove(gap_key)

    # ✅ Regenerate replies that were blocked by this gap
    pending = memory.get("pending_for_approval", [])
    for item in pending:
        if "Missing info" in item["reply"] or "[NEED_INFO" in item["reply"]:
            jid = item["jid"]
            msg = item["user_msg"]

            try:
                # Build updated system prompt
                system = SYSTEM_BASE
                if memory.get("my_profile"):
                    system += "\n\nFacts about Julio:\n" + "\n".join(f"- {f}" for f in memory["my_profile"])
                if memory.get("personality_profile"):
                    system += "\n\nPersonality guidelines:\n" + "\n".join(f"- {t}" for t in memory["personality_profile"])
                last10 = memory["chat_history"].get(jid, [])[-10:]
                system += "\n\nRecent conversation:\n" + "\n".join(f"{m['role']}: {m['content']}" for m in last10)

                # Fresh GPT reply (English first)
                raw_reply_en = chat_complete(
                    [{"role": "system", "content": system},
                     {"role": "user", "content": f"(Reply in English only)\n\n{msg}"}],
                    temperature=0.7, max_tokens=150, top_p=0.9
                )

                # Detect language
                try:
                    lang = safe_detect_lang(msg)
                except Exception:
                    lang = "en"

                # Translate if needed
                if lang != "en":
                    reply_final = chat_complete(
                        [
                            {"role": "system", "content": "Translate naturally, keep tone conversational and human."},
                            {"role": "user", "content": f"Translate the following English reply into natural {lang.upper()}, keep it conversational and romantic:\n\n{raw_reply_en}"}
                        ],
                        temperature=0.7, max_tokens=150, top_p=0.9
                    )
                else:
                    reply_final = raw_reply_en

                # Humanize
                reply_final = humanize_reply(msg, reply_final, memory, jid)

                # ✅ Always update the pending item
                item["reply_en"] = raw_reply_en
                item["reply"] = reply_final

                print(f"[INFO] Regenerated reply for {jid}: {reply_final[:60]}...")

            except Exception as e:
                print(f"[ERROR] Failed to regenerate reply for {jid}: {e}")
                # ✅ Fallback reply instead of leaving NEED_INFO
                item["reply_en"] = "(Could not regenerate reply)"
                item["reply"] = f"(Could not regenerate reply, but I saved your fact about {gap_key}.)"

    # ✅ Save updated memory
    save_memory()

    return redirect(url_for("dashboard"))




# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"🚀 Julio is up on {MODEL}!")
    app.run(host="0.0.0.0", port=5001)
