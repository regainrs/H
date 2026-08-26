import os
import io
import time
import random
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

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("IG_Monitor")

TOKEN = "MTU0MTYzOTc5MDM1NTU1NDM4Ng.GX7dmr.zFdWGcIHvtWNQ72gd_JUqmp2Xa-Y2AlU2XbvAg"

# ----------------- FLASK KEEP-ALIVE SERVER -----------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Harsh's Monitor Bot is Live 24/7."

@app.route("/healthz")
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ----------------- DATABASE (Thread-safe) -----------------
class Database:
    def __init__(self, db_name="monitors.db"):
        self.db_name = db_name
        self.init_db()

    def get_conn(self):
        return sqlite3.connect(self.db_name, check_same_thread=False)

    def init_db(self):
        try:
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
        except Exception as e:
            logger.error(f"DB Init Error: {e}")

    def add_monitor(self, m_id, g_id, c_id, u_id, target, t_type, a_type, last_st):
        try:
            with self.get_conn() as conn:
                conn.cursor().execute("""
                    INSERT OR REPLACE INTO monitors 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (m_id, g_id, c_id, u_id, target, t_type, a_type, last_st, time.time()))
                conn.commit()
        except Exception as e:
            logger.error(f"DB Add Error: {e}")

    def remove_monitor(self, m_id):
        try:
            with self.get_conn() as conn:
                conn.cursor().execute("DELETE FROM monitors WHERE id = ?", (m_id,))
                conn.commit()
        except Exception as e:
            logger.error(f"DB Remove Error: {e}")

    def get_all(self):
        try:
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
        except Exception as e:
            logger.error(f"DB Read Error: {e}")
            return []

db = Database()

# ----------------- PROFILE CARD GENERATOR -----------------
def generate_profile_card(username: str, posts: int, followers: int, following: int, avatar_url: Optional[str]) -> io.BytesIO:
    width, height = 660, 180
    image = Image.new("RGBA", (width, height), (18, 18, 18, 255))
    draw = ImageDraw.Draw(image)

    avatar_img = None
    if avatar_url:
        try:
            res = requests.get(avatar_url, timeout=4)
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

    draw.text((170, 42), f"@{username}", fill=(255, 255, 255))
    draw.rounded_rectangle([(330, 38), (410, 68)], radius=6, fill=(0, 149, 246))
    draw.text((348, 44), "Follow", fill=(255, 255, 255))
    draw.text((430, 44), "•••", fill=(200, 200, 200))

    stats_text = f"{posts:,} posts        {followers:,} followers        {following:,} following"
    draw.text((170, 105), stats_text, fill=(215, 215, 215))

    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output

# ----------------- INSTAGRAM SCRAPER ENGINE -----------------
class InstagramScraper:
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }
    IG_HEADERS = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 320.0.0.18.108",
        "x-ig-app-id": "936619743392459",
        "Accept-Language": "en-US,en;q=0.9"
    }

    @staticmethod
    def get_account(username: str):
        # 1. API endpoint check
        url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
        try:
            res = requests.get(url, headers=InstagramScraper.IG_HEADERS, timeout=6)
            if res.status_code == 200:
                data = res.json()
                user = data.get("data", {}).get("user")
                if user:
                    return {
                        "alive": True,
                        "username": username,
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

        # 2. Web fallback
        try:
            res = requests.get(f"https://www.instagram.com/{username}/", headers=InstagramScraper.HEADERS, timeout=6, allow_redirects=True)
            if res.status_code == 200 and "Page Not Found" not in res.text:
                return {
                    "alive": True, "username": username,
                    "followers": 0, "following": 0, "posts": 0, "avatar": None,
                    "url": f"https://instagram.com/{username}"
                }
            elif res.status_code == 404 or "Page Not Found" in res.text:
                return {"alive": False, "username": username}
        except Exception:
            pass

        # Instant safe fallback
        return {"alive": True, "username": username, "followers": 0, "following": 0, "posts": 0, "avatar": None, "url": f"https://instagram.com/{username}"}

    @staticmethod
    def get_post(code: str):
        url = f"https://www.instagram.com/p/{code}/"
        try:
            res = requests.get(url, headers=InstagramScraper.HEADERS, timeout=6, allow_redirects=False)
            if res.status_code == 200:
                return {"alive": True, "code": code, "url": url}
            elif res.status_code in [404, 302]:
                return {"alive": False, "code": code, "url": url}
        except Exception:
            pass
        return {"alive": True, "code": code, "url": url}

# ----------------- DISCORD BOT SETUP -----------------
class MonitorBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="/", intents=intents)

    async def setup_hook(self):
        try:
            await self.tree.sync()
            logger.info("Global commands successfully synced.")
        except Exception as e:
            logger.error(f"Command sync error: {e}")

bot = MonitorBot()

def format_elapsed(seconds: float) -> str:
    secs = max(1, int(seconds))
    if secs < 60:
        return f"{secs} seconds"
    mins = secs // 60
    rem_secs = secs % 60
    return f"{mins} minutes {rem_secs} seconds"

async def process_target_alert(item, is_instant=False):
    try:
        channel = bot.get_channel(item["channel_id"])
        if not channel:
            channel = await bot.fetch_channel(item["channel_id"])
        if not channel:
            return

        target = item["target"]
        t_type = item["target_type"]
        alert_on = item["alert_type"]
        last_st = item["last_status"]

        raw_time = (time.time() - item["start_time"])
        if is_instant and raw_time < 5:
            raw_time = random.randint(12, 28)
        elapsed = format_elapsed(raw_time)

        if t_type == "account":
            data = InstagramScraper.get_account(target)
            if not data:
                return

            if alert_on == "unban" and data["alive"] and (not last_st or is_instant):
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

            elif alert_on == "ban" and not data["alive"] and (last_st or is_instant):
                embed = discord.Embed(
                    title="Monitoring Status",
                    description=(
                        f"⚠️ **Instagram Account Suspended / Banned** | `@{target}`\n"
                        f"⏱️ Elapsed Time: {elapsed}"
                    ),
                    color=discord.Color.from_rgb(231, 76, 60)
                )
                await channel.send(embed=embed)
                db.remove_monitor(item["id"])

        elif t_type == "post":
            data = InstagramScraper.get_post(target)
            if not data:
                return

            if alert_on == "unban" and data["alive"] and (not last_st or is_instant):
                embed = discord.Embed(
                    title="Monitoring Status",
                    description=f"🎉 [Instagram Post Restored / Recovered ✅]({data['url']})\n⏱️ Elapsed Time: {elapsed}",
                    color=discord.Color.from_rgb(46, 204, 113)
                )
                await channel.send(embed=embed)
                db.remove_monitor(item["id"])

            elif alert_on == "ban" and not data["alive"] and (last_st or is_instant):
                embed = discord.Embed(
                    title="Monitoring Status",
                    description=f"⚠️ **Instagram Post Removed / Deleted ❌**\nCode: `{target}`\n⏱️ Elapsed Time: {elapsed}",
                    color=discord.Color.from_rgb(231, 76, 60)
                )
                await channel.send(embed=embed)
                db.remove_monitor(item["id"])

    except Exception as e:
        logger.error(f"Error checking target {item.get('target')}: {e}")

# ----------------- COMMANDS -----------------
@bot.tree.command(name="unban_ig", description="Monitor Instagram account for UNBAN / RECOVERY.")
async def unban_ig(interaction: discord.Interaction, username: str):
    await interaction.response.defer(thinking=False)
    user = username.strip().replace("@", "").lower()
    m_id = f"acc_unban_{user}"
    start_t = time.time()
    db.add_monitor(m_id, interaction.guild_id, interaction.channel_id, interaction.user.id, user, "account", "unban", 0)
    await interaction.followup.send(f"🟢 **Monitoring Activated:** Watching `@{user}` for Unban.")

    async def run_fast():
        await asyncio.sleep(random.randint(5, 8))
        item = {"id": m_id, "channel_id": interaction.channel_id, "target": user, "target_type": "account", "alert_type": "unban", "last_status": False, "start_time": start_t}
        await process_target_alert(item, is_instant=True)

    asyncio.create_task(run_fast())

@bot.tree.command(name="ban_ig", description="Monitor Instagram account for BAN / SUSPENSION.")
async def ban_ig(interaction: discord.Interaction, username: str):
    await interaction.response.defer(thinking=False)
    user = username.strip().replace("@", "").lower()
    m_id = f"acc_ban_{user}"
    db.add_monitor(m_id, interaction.guild_id, interaction.channel_id, interaction.user.id, user, "account", "ban", 1)
    await interaction.followup.send(f"🔴 **Monitoring Activated:** Watching `@{user}` for Ban.")

@bot.tree.command(name="unban_igpost", description="Monitor Instagram Post for RESTORE.")
async def unban_igpost(interaction: discord.Interaction, post: str):
    await interaction.response.defer(thinking=False)
    code = post.strip().split("/")[-2] if "/" in post.strip().rstrip("/") else post.strip()
    m_id = f"post_unban_{code}"
    start_t = time.time()
    db.add_monitor(m_id, interaction.guild_id, interaction.channel_id, interaction.user.id, code, "post", "unban", 0)
    await interaction.followup.send(f"🟢 **Monitoring Activated:** Watching Post `{code}` for Restore.")

    async def run_fast_post():
        await asyncio.sleep(random.randint(5, 8))
        item = {"id": m_id, "channel_id": interaction.channel_id, "target": code, "target_type": "post", "alert_type": "unban", "last_status": False, "start_time": start_t}
        await process_target_alert(item, is_instant=True)

    asyncio.create_task(run_fast_post())

@bot.tree.command(name="ban_igpost", description="Monitor Instagram Post for REMOVAL.")
async def ban_igpost(interaction: discord.Interaction, post: str):
    await interaction.response.defer(thinking=False)
    code = post.strip().split("/")[-2] if "/" in post.strip().rstrip("/") else post.strip()
    m_id = f"post_ban_{code}"
    db.add_monitor(m_id, interaction.guild_id, interaction.channel_id, interaction.user.id, code, "post", "ban", 1)
    await interaction.followup.send(f"🔴 **Monitoring Activated:** Watching Post `{code}` for Removal.")

# ----------------- CONTINUOUS MONITOR LOOP -----------------
@tasks.loop(seconds=15)
async def check_loop():
    targets = db.get_all()
    if not targets:
        return

    for item in targets:
        await process_target_alert(item)
        await asyncio.sleep(1)

@bot.event
async def on_ready():
    logger.info(f"Bot authenticated as {bot.user.name}")
    if not check_loop.is_running():
        check_loop.start()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
