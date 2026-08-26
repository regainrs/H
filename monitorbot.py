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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("IG_Monitor")

TOKEN = "MTU0MTYzOTc5MDM1NTU1NDM4Ng.GX7dmr.zFdWGcIHvtWNQ72gd_JUqmp2Xa-Y2AlU2XbvAg"

# ----------------- FLASK KEEP-ALIVE SERVER -----------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Harsh's Monitor is Live 24/7."

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ----------------- DATABASE -----------------
class Database:
    def __init__(self, db_name="monitors.db"):
        self.db_name = db_name
        self.init_db()

    def get_conn(self):
        return sqlite3.connect(self.db_name, check_same_thread=False)

    def init_db(self):
        try:
            with self.get_conn() as conn:
                conn.cursor().execute("""
                    CREATE TABLE IF NOT EXISTS monitors (
                        id TEXT PRIMARY KEY,
                        guild_id INTEGER,
                        channel_id INTEGER,
                        user_id INTEGER,
                        target TEXT,
                        target_type TEXT,
                        alert_type TEXT,
                        start_time REAL
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"DB Init Error: {e}")

    def add_monitor(self, m_id, g_id, c_id, u_id, target, t_type, a_type):
        try:
            with self.get_conn() as conn:
                conn.cursor().execute("""
                    INSERT OR REPLACE INTO monitors (id, guild_id, channel_id, user_id, target, target_type, alert_type, start_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (m_id, g_id, c_id, u_id, target, t_type, a_type, time.time()))
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
                rows = conn.cursor().execute("SELECT id, guild_id, channel_id, user_id, target, target_type, alert_type, start_time FROM monitors").fetchall()
                return [
                    {
                        "id": r[0], "guild_id": r[1], "channel_id": r[2], "user_id": r[3],
                        "target": r[4], "target_type": r[5], "alert_type": r[6],
                        "start_time": r[7]
                    }
                    for r in rows
                ]
        except Exception:
            return []

    def get_by_user_or_guild(self, user_id: int, guild_id: int):
        try:
            with self.get_conn() as conn:
                rows = conn.cursor().execute("SELECT id, target, target_type, alert_type, start_time FROM monitors WHERE user_id = ? OR guild_id = ?", (user_id, guild_id)).fetchall()
                return rows
        except Exception:
            return []

db = Database()

# ----------------- EXACT PROFILE CARD DESIGN -----------------
def generate_profile_card(username: str, posts: int, followers: int, following: int, avatar_url: Optional[str]) -> io.BytesIO:
    width, height = 660, 180
    image = Image.new("RGBA", (width, height), (16, 16, 16, 255))
    draw = ImageDraw.Draw(image)

    # Avatar Circle
    avatar_img = None
    if avatar_url:
        try:
            res = requests.get(avatar_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            if res.status_code == 200:
                avatar_img = Image.open(io.BytesIO(res.content)).convert("RGBA").resize((110, 110))
        except Exception:
            pass

    if not avatar_img:
        avatar_img = Image.new("RGBA", (110, 110), (50, 50, 50, 255))

    mask = Image.new("L", (110, 110), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, 110, 110), fill=255)
    image.paste(avatar_img, (35, 35), mask)

    # UI Badges
    draw.text((170, 42), f"@{username}", fill=(255, 255, 255))
    draw.rounded_rectangle([(330, 38), (410, 68)], radius=6, fill=(0, 149, 246))
    draw.text((348, 44), "Follow", fill=(255, 255, 255))
    draw.text((430, 44), "•••", fill=(200, 200, 200))

    # Counters Row (Format: 1 posts  0 followers  0 following)
    stats_text = f"{posts} posts        {followers} followers        {following} following"
    draw.text((170, 105), stats_text, fill=(215, 215, 215))

    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output

# ----------------- ACCURATE INSTAGRAM CHECKER -----------------
class InstagramScraper:
    @staticmethod
    def check_status(username: str):
        headers_api = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 324.0.0.18.115",
            "x-ig-app-id": "936619743392459",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9"
        }
        
        try:
            url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
            res = requests.get(url, headers=headers_api, timeout=6)
            if res.status_code == 200:
                data = res.json().get("data", {}).get("user")
                if data:
                    return {
                        "alive": True,
                        "username": username,
                        "followers": data.get("edge_followed_by", {}).get("count", 0),
                        "following": data.get("edge_follow", {}).get("count", 0),
                        "posts": data.get("edge_owner_to_timeline_media", {}).get("count", 0),
                        "avatar": data.get("profile_pic_url_hd") or data.get("profile_pic_url"),
                        "url": f"https://instagram.com/{username}"
                    }
            elif res.status_code == 404:
                return {"alive": False, "username": username}
        except Exception:
            pass

        try:
            url_web = f"https://www.instagram.com/{username}/"
            res = requests.get(url_web, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=6, allow_redirects=False)
            if res.status_code == 200:
                return {
                    "alive": True,
                    "username": username,
                    "followers": 0,
                    "following": 0,
                    "posts": 0,
                    "avatar": None,
                    "url": url_web
                }
            elif res.status_code in [404, 302]:
                return {"alive": False, "username": username}
        except Exception:
            pass

        return None

    @staticmethod
    def check_post(code: str):
        try:
            url = f"https://www.instagram.com/p/{code}/"
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6, allow_redirects=False)
            if res.status_code == 200:
                return {"alive": True, "url": url}
            elif res.status_code in [404, 302]:
                return {"alive": False, "url": url}
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
    secs = max(1, int(seconds))
    if secs < 60:
        return f"{secs} seconds"
    mins = secs // 60
    rem_secs = secs % 60
    return f"{mins} minutes, {rem_secs} seconds"

# ----------------- BACKGROUND MONITOR LOOP (Every 10 Seconds) -----------------
@tasks.loop(seconds=10)
async def check_loop():
    targets = db.get_all()
    if not targets:
        return

    for item in targets:
        try:
            channel = bot.get_channel(item["channel_id"])
            if not channel:
                channel = await bot.fetch_channel(item["channel_id"])
            if not channel:
                continue

            target = item["target"]
            t_type = item["target_type"]
            alert_on = item["alert_type"]
            elapsed = format_elapsed(time.time() - item["start_time"])

            if t_type == "account":
                data = InstagramScraper.check_status(target)
                if not data:
                    continue

                if alert_on == "unban" and data["alive"]:
                    embed = discord.Embed(
                        title="Monitoring Status",
                        description=(
                            f"[Instagram Account Recovered | @{target}\n🏆✅]({data['url']})\n"
                            f"Followers: {data['followers']}\n"
                            f"⏱️ Elapsed Time: {elapsed}"
                        ),
                        color=discord.Color.from_rgb(46, 204, 113)
                    )

                    try:
                        card = generate_profile_card(target, data["posts"], data["followers"], data["following"], data["avatar"])
                        file = discord.File(card, filename="card.png")
                        embed.set_image(url="attachment://card.png")
                        await channel.send(embed=embed, file=file)
                    except Exception:
                        await channel.send(embed=embed)

                    db.remove_monitor(item["id"])

                elif alert_on == "ban" and not data["alive"]:
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
                post_data = InstagramScraper.check_post(target)
                if not post_data:
                    continue

                if alert_on == "unban" and post_data["alive"]:
                    embed = discord.Embed(
                        title="Monitoring Status",
                        description=f"🎉 [Instagram Post Restored / Recovered ✅]({post_data['url']})\n⏱️ Elapsed Time: {elapsed}",
                        color=discord.Color.from_rgb(46, 204, 113)
                    )
                    await channel.send(embed=embed)
                    db.remove_monitor(item["id"])

        except Exception as err:
            logger.error(f"Loop error: {err}")

# ----------------- COMMANDS -----------------
@bot.tree.command(name="unban_ig", description="Monitor Instagram account for UNBAN / RECOVERY.")
async def unban_ig(interaction: discord.Interaction, username: str):
    await interaction.response.defer(thinking=False)
    user = username.strip().replace("@", "").lower()
    m_id = f"acc_unban_{user}"
    db.add_monitor(m_id, interaction.guild_id, interaction.channel_id, interaction.user.id, user, "account", "unban")
    await interaction.followup.send(f"🟢 **Monitoring Activated:** Watching `@{user}` for Unban.")

@bot.tree.command(name="ban_ig", description="Monitor Instagram account for BAN / SUSPENSION.")
async def ban_ig(interaction: discord.Interaction, username: str):
    await interaction.response.defer(thinking=False)
    user = username.strip().replace("@", "").lower()
    m_id = f"acc_ban_{user}"
    db.add_monitor(m_id, interaction.guild_id, interaction.channel_id, interaction.user.id, user, "account", "ban")
    await interaction.followup.send(f"🔴 **Monitoring Activated:** Watching `@{user}` for Ban.")

@bot.tree.command(name="unban_igpost", description="Monitor Instagram Post for RESTORE.")
async def unban_igpost(interaction: discord.Interaction, post: str):
    await interaction.response.defer(thinking=False)
    code = post.strip().split("/")[-2] if "/" in post.strip().rstrip("/") else post.strip()
    m_id = f"post_unban_{code}"
    db.add_monitor(m_id, interaction.guild_id, interaction.channel_id, interaction.user.id, code, "post", "unban")
    await interaction.followup.send(f"🟢 **Monitoring Activated:** Watching Post `{code}` for Restore.")

@bot.tree.command(name="ban_igpost", description="Monitor Instagram Post for REMOVAL.")
async def ban_igpost(interaction: discord.Interaction, post: str):
    await interaction.response.defer(thinking=False)
    code = post.strip().split("/")[-2] if "/" in post.strip().rstrip("/") else post.strip()
    m_id = f"post_ban_{code}"
    db.add_monitor(m_id, interaction.guild_id, interaction.channel_id, interaction.user.id, code, "post", "ban")
    await interaction.followup.send(f"🔴 **Monitoring Activated:** Watching Post `{code}` for Removal.")

@bot.tree.command(name="list", description="Show all Instagram accounts/posts currently being monitored.")
async def list_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    rows = db.get_by_user_or_guild(interaction.user.id, interaction.guild_id or 0)
    
    if not rows:
        await interaction.followup.send("❌ No active monitors found in this channel/server.")
        return

    embed = discord.Embed(
        title="📋 Active Monitoring List",
        description="Here are the accounts and posts currently being monitored:",
        color=discord.Color.blue()
    )

    for r in rows:
        # r = (id, target, target_type, alert_type, start_time)
        t_name = f"@{r[1]}" if r[2] == "account" else f"Post `{r[1]}`"
        status_mode = "🟢 Alert on UNBAN" if r[3] == "unban" else "🔴 Alert on BAN"
        started_epoch = int(r[4])
        
        embed.add_field(
            name=f"{t_name} ({r[2].capitalize()})",
            value=f"• **Mode:** {status_mode}\n• **Started:** <t:{started_epoch}:R>",
            inline=False
        )

    await interaction.followup.send(embed=embed)

@bot.event
async def on_ready():
    logger.info(f"Bot connected as {bot.user.name}")
    if not check_loop.is_running():
        check_loop.start()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
