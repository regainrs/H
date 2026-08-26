import os
import io
import time
import sqlite3
import logging
import threading
from datetime import datetime
from typing import Optional, Dict, Any

import requests
import discord
from discord import app_commands
from discord.ext import commands, tasks
from flask import Flask
from PIL import Image, ImageDraw

# ----------------- CONFIGURATION & LOGGING -----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("IG_Monitor")

TOKEN = "MTU0MTYzOTc5MDM1NTU1NDM4Ng.GX7dmr.zFdWGcIHvtWNQ72gd_JUqmp2Xa-Y2AlU2XbvAg"

# ----------------- FLASK KEEP-ALIVE SERVER -----------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Harsh's Monitor Bot is Running 24/7."

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ----------------- DATABASE (SQLite) -----------------
class Database:
    def __init__(self, db_name="monitors.db"):
        self.db_name = db_name
        self.init_db()

    def get_conn(self):
        return sqlite3.connect(self.db_name)

    def init_db(self):
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS monitors (
                    id TEXT PRIMARY KEY,
                    guild_id INTEGER,
                    channel_id INTEGER,
                    user_id INTEGER,
                    target TEXT,
                    target_type TEXT,
                    alert_type TEXT,
                    last_status INTEGER,
                    start_time REAL
                )
            """)
            conn.commit()

    def add_monitor(self, m_id, g_id, c_id, u_id, target, t_type, a_type, last_st):
        with self.get_conn() as conn:
            conn.cursor().execute("""
                INSERT OR REPLACE INTO monitors 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (m_id, g_id, c_id, u_id, target, t_type, a_type, last_st, time.time()))
            conn.commit()

    def remove_monitor(self, m_id):
        with self.get_conn() as conn:
            conn.cursor().execute("DELETE FROM monitors WHERE id = ?", (m_id,))
            conn.commit()

    def get_all(self):
        with self.get_conn() as conn:
            rows = conn.cursor().execute("SELECT id, guild_id, channel_id, user_id, target, target_type, alert_type, last_status, start_time FROM monitors").fetchall()
            return [
                {
                    "id": r[0], "guild_id": r[1], "channel_id": r[2], "user_id": r[3],
                    "target": r[4], "target_type": r[5], "alert_type": r[6],
                    "last_status": bool(r[7]), "start_time": r[8]
                }
                for r in rows
            ]

db = Database()

# ----------------- PROFILE CARD GENERATOR -----------------
def generate_profile_card(username: str, posts: int, followers: int, following: int, avatar_url: Optional[str]) -> io.BytesIO:
    width, height = 660, 180
    image = Image.new("RGBA", (width, height), (18, 18, 18, 255))
    draw = ImageDraw.Draw(image)

    # Avatar Circle Fetch
    avatar_img = None
    if avatar_url:
        try:
            res = requests.get(avatar_url, timeout=5)
            if res.status_code == 200:
                avatar_img = Image.open(io.BytesIO(res.content)).convert("RGBA").resize((110, 110))
        except Exception:
            pass

    if not avatar_img:
        avatar_img = Image.new("RGBA", (110, 110), (60, 60, 60, 255))

    mask = Image.new("L", (110, 110), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, 110, 110), fill=255)
    image.paste(avatar_img, (35, 35), mask)

    # UI Elements & Badges
    draw.text((170, 42), f"@{username}", fill=(255, 255, 255))
    draw.rounded_rectangle([(330, 38), (410, 68)], radius=6, fill=(0, 149, 246))
    draw.text((348, 44), "Follow", fill=(255, 255, 255))
    draw.text((430, 44), "•••", fill=(200, 200, 200))

    # Counters Row
    stats_text = f"{posts:,} posts        {followers:,} followers        {following:,} following"
    draw.text((170, 105), stats_text, fill=(215, 215, 215))

    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output

# ----------------- INSTAGRAM SCRAPER ENGINE -----------------
class InstagramScraper:
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    IG_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "x-ig-app-id": "936619743392459",
        "Accept-Language": "en-US,en;q=0.9"
    }

    @staticmethod
    def get_account(username: str):
        url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
        try:
            res = requests.get(url, headers=InstagramScraper.IG_HEADERS, timeout=10)
            if res.status_code == 200:
                user = res.json().get("data", {}).get("user", {})
                return {
                    "alive": True,
                    "username": username,
                    "full_name": user.get("full_name") or username,
                    "followers": user.get("edge_followed_by", {}).get("count", 0),
                    "following": user.get("edge_follow", {}).get("count", 0),
                    "posts": user.get("edge_owner_to_timeline_media", {}).get("count", 0),
                    "avatar": user.get("profile_pic_url_hd") or user.get("profile_pic_url"),
                    "url": f"https://instagram.com/{username}"
                }
            elif res.status_code == 404:
                return {"alive": False, "username": username}
        except Exception:
            pass

        # Fallback Check
        try:
            res = requests.get(f"https://www.instagram.com/{username}/", headers=InstagramScraper.HEADERS, timeout=10, allow_redirects=False)
            if res.status_code == 200:
                return {
                    "alive": True, "username": username, "full_name": username,
                    "followers": 0, "following": 0, "posts": 0, "avatar": None,
                    "url": f"https://instagram.com/{username}"
                }
            elif res.status_code in [404, 302]:
                return {"alive": False, "username": username}
        except Exception:
            pass
        return None

    @staticmethod
    def get_post(code: str):
        url = f"https://www.instagram.com/p/{code}/"
        try:
            res = requests.get(url, headers=InstagramScraper.HEADERS, timeout=10, allow_redirects=False)
            if res.status_code == 200:
                return {"alive": True, "code": code, "url": url}
            elif res.status_code in [404, 302]:
                return {"alive": False, "code": code, "url": url}
        except Exception:
            pass
        return None

# ----------------- DISCORD BOT SETUP -----------------
class MonitorBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="/", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()

bot = MonitorBot()

def format_elapsed(seconds: float) -> str:
    secs = int(seconds)
    if secs < 60:
        return f"{secs} seconds"
    mins = secs // 60
    rem_secs = secs % 60
    return f"{mins} minutes {rem_secs} seconds"

# ----------------- COMMANDS -----------------
@bot.tree.command(name="unban_ig", description="Monitor Instagram account for UNBAN / RECOVERY.")
async def unban_ig(interaction: discord.Interaction, username: str):
    user = username.strip().replace("@", "").lower()
    db.add_monitor(f"acc_unban_{user}", interaction.guild_id, interaction.channel_id, interaction.user.id, user, "account", "unban", 0)
    await interaction.response.send_message(f"🟢 **Monitoring Activated:** Watching `@{user}` for Unban.", ephemeral=False)

@bot.tree.command(name="ban_ig", description="Monitor Instagram account for BAN / SUSPENSION.")
async def ban_ig(interaction: discord.Interaction, username: str):
    user = username.strip().replace("@", "").lower()
    db.add_monitor(f"acc_ban_{user}", interaction.guild_id, interaction.channel_id, interaction.user.id, user, "account", "ban", 1)
    await interaction.response.send_message(f"🔴 **Monitoring Activated:** Watching `@{user}` for Ban.", ephemeral=False)

@bot.tree.command(name="unban_igpost", description="Monitor Instagram Post for RESTORE.")
async def unban_igpost(interaction: discord.Interaction, post: str):
    code = post.strip().split("/")[-2] if "/" in post.strip().rstrip("/") else post.strip()
    db.add_monitor(f"post_unban_{code}", interaction.guild_id, interaction.channel_id, interaction.user.id, code, "post", "unban", 0)
    await interaction.response.send_message(f"🟢 **Monitoring Activated:** Watching Post `{code}` for Restore.", ephemeral=False)

@bot.tree.command(name="ban_igpost", description="Monitor Instagram Post for REMOVAL.")
async def ban_igpost(interaction: discord.Interaction, post: str):
    code = post.strip().split("/")[-2] if "/" in post.strip().rstrip("/") else post.strip()
    db.add_monitor(f"post_ban_{code}", interaction.guild_id, interaction.channel_id, interaction.user.id, code, "post", "ban", 1)
    await interaction.response.send_message(f"🔴 **Monitoring Activated:** Watching Post `{code}` for Removal.", ephemeral=False)

# ----------------- CONTINUOUS MONITOR LOOP -----------------
@tasks.loop(seconds=30)
async def check_loop():
    targets = db.get_all()
    if not targets:
        return

    for item in targets:
        channel = bot.get_channel(item["channel_id"])
        if not channel:
            continue

        target = item["target"]
        t_type = item["target_type"]
        alert_on = item["alert_type"]
        last_st = item["last_status"]
        elapsed = format_elapsed(time.time() - item["start_time"])

        if t_type == "account":
            data = InstagramScraper.get_account(target)
            if not data:
                continue

            # ACCOUNT UNBANNED / RECOVERED (EXACT MATCH TO YOUR UI)
            if alert_on == "unban" and data["alive"] and not last_st:
                embed = discord.Embed(
                    title="Monitoring Status",
                    description=(
                        f"[Instagram Account Recovered | @{target} 🏆✅]({data['url']})\n"
                        f"Followers: {data['followers']}\n"
                        f"⏱️ Elapsed Time: {elapsed}"
                    ),
                    color=discord.Color.from_rgb(46, 204, 113)
                )

                card_bytes = generate_profile_card(
                    username=target,
                    posts=data["posts"],
                    followers=data["followers"],
                    following=data["following"],
                    avatar_url=data["avatar"]
                )
                file = discord.File(card_bytes, filename="profile_card.png")
                embed.set_image(url="attachment://profile_card.png")

                await channel.send(embed=embed, file=file)
                db.remove_monitor(item["id"])

            # ACCOUNT BANNED
            elif alert_on == "ban" and not data["alive"] and last_st:
                embed = discord.Embed(
                    title="Monitoring Status",
                    description=(
                        f"⚠️ **Instagram Account Suspended / Banned** | `@{target}`\n"
                        f"🔗 URL: https://instagram.com/{target}\n"
                        f"⏱️ Elapsed Time: {elapsed}"
                    ),
                    color=discord.Color.from_rgb(231, 76, 60)
                )
                await channel.send(embed=embed)
                db.remove_monitor(item["id"])

        elif t_type == "post":
            data = InstagramScraper.get_post(target)
            if not data:
                continue

            # POST RESTORED
            if alert_on == "unban" and data["alive"] and not last_st:
                embed = discord.Embed(
                    title="Monitoring Status",
                    description=(
                        f"🎉 [Instagram Post Restored / Recovered ✅]({data['url']})\n"
                        f"Code: `{target}`\n"
                        f"⏱️ Elapsed Time: {elapsed}"
                    ),
                    color=discord.Color.from_rgb(46, 204, 113)
                )
                await channel.send(embed=embed)
                db.remove_monitor(item["id"])

            # POST REMOVED
            elif alert_on == "ban" and not data["alive"] and last_st:
                embed = discord.Embed(
                    title="Monitoring Status",
                    description=(
                        f"⚠️ **Instagram Post Removed / Deleted ❌**\n"
                        f"Code: `{target}`\n"
                        f"⏱️ Elapsed Time: {elapsed}"
                    ),
                    color=discord.Color.from_rgb(231, 76, 60)
                )
                await channel.send(embed=embed)
                db.remove_monitor(item["id"])

        time.sleep(1)

@bot.event
async def on_ready():
    logger.info(f"Bot connected successfully as {bot.user.name}")
    if not check_loop.is_running():
        check_loop.start()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
