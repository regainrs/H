import os
import io
import re
import time
import asyncio
import sqlite3
import logging
import threading
from datetime import datetime
from typing import Optional, Dict, Any

import aiohttp
import requests
import discord
from discord import app_commands
from discord.ext import commands, tasks
from flask import Flask
from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("IG_Monitor")

TOKEN = "MTU0MTYzOTc5MDM1NTU1NDM4Ng.GX7dmr.zFdWGcIHvtWNQ72gd_JUqmp2Xa-Y2AlU2XbvAg"

# ----------------- FLASK KEEP-ALIVE SERVER -----------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Regainrs Monitor Engine is Live 24/7."

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

# ----------------- ENHANCED PROFILE CARD GENERATOR -----------------
def generate_profile_card(username: str, posts: str, followers: str, following: str, avatar_url: Optional[str]) -> io.BytesIO:
    width, height = 700, 190
    image = Image.new("RGBA", (width, height), (20, 20, 20, 255))
    draw = ImageDraw.Draw(image)

    # Avatar Fetching
    avatar_img = None
    if avatar_url:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15",
                "Referer": "https://www.instagram.com/"
            }
            res = requests.get(avatar_url, headers=headers, timeout=6)
            if res.status_code == 200:
                avatar_img = Image.open(io.BytesIO(res.content)).convert("RGBA").resize((120, 120))
        except Exception as e:
            logger.warning(f"Avatar fetch error: {e}")

    if not avatar_img:
        avatar_img = Image.new("RGBA", (120, 120), (50, 50, 50, 255))
        draw_temp = ImageDraw.Draw(avatar_img)
        draw_temp.ellipse((20, 20, 100, 100), fill=(100, 100, 100, 255))

    mask = Image.new("L", (120, 120), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, 120, 120), fill=255)
    image.paste(avatar_img, (35, 35), mask)

    # Top Row: Username + Follow + Menu
    draw.text((180, 42), f"@{username}", fill=(255, 255, 255))
    draw.rounded_rectangle([(360, 36), (445, 68)], radius=8, fill=(0, 149, 246))
    draw.text((380, 44), "Follow", fill=(255, 255, 255))
    draw.text((465, 42), "•••", fill=(210, 210, 210))

    # Bottom Row: Real Stats (1 posts  0 followers  0 following)
    stats_text = f"{posts} posts        {followers} followers        {following} following"
    draw.text((180, 105), stats_text, fill=(230, 230, 230))

    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output

# ----------------- REALTIME INSTAGRAM SCRAPER -----------------
class FastInstagramScraper:
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 324.0.0.18.115",
        "x-ig-app-id": "936619743392459",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9"
    }

    WEB_HEADERS = {
        "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Accept-Language": "en-US,en;q=0.9"
    }

    @staticmethod
    async def fetch_account(session: aiohttp.ClientSession, username: str):
        # 1. Instagram Web Profile Endpoint
        try:
            url_api = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
            async with session.get(url_api, headers=FastInstagramScraper.HEADERS, timeout=aiohttp.ClientTimeout(total=6)) as res:
                if res.status == 200:
                    data = await res.json()
                    user = data.get("data", {}).get("user")
                    if user:
                        return {
                            "alive": True,
                            "username": username,
                            "followers": str(user.get("edge_followed_by", {}).get("count", 0)),
                            "following": str(user.get("edge_follow", {}).get("count", 0)),
                            "posts": str(user.get("edge_owner_to_timeline_media", {}).get("count", 0)),
                            "avatar": user.get("profile_pic_url_hd") or user.get("profile_pic_url"),
                            "url": f"https://instagram.com/{username}"
                        }
                elif res.status == 404:
                    return {"alive": False, "username": username}
        except Exception:
            pass

        # 2. Meta Tags Extraction Engine
        try:
            url_web = f"https://www.instagram.com/{username}/"
            async with session.get(url_web, headers=FastInstagramScraper.WEB_HEADERS, timeout=aiohttp.ClientTimeout(total=6)) as res:
                text = await res.text()
                if res.status == 404 or "Page Not Found" in text or "isn't available" in text:
                    return {"alive": False, "username": username}

                followers, following, posts = "0", "0", "0"
                match = re.search(r'content="([0-9KkMm,\.]+)\s+Followers,\s+([0-9KkMm,\.]+)\s+Following,\s+([0-9KkMm,\.]+)\s+Posts', text)
                if match:
                    followers = match.group(1)
                    following = match.group(2)
                    posts = match.group(3)

                avatar = None
                avatar_match = re.search(r'og:image"\s+content="([^"]+)"', text)
                if avatar_match:
                    avatar = avatar_match.group(1).replace("&amp;", "&")

                if res.status == 200:
                    return {
                        "alive": True,
                        "username": username,
                        "followers": followers,
                        "following": following,
                        "posts": posts,
                        "avatar": avatar,
                        "url": url_web
                    }
        except Exception:
            pass

        return None

    @staticmethod
    async def fetch_post(session: aiohttp.ClientSession, code: str):
        try:
            url = f"https://www.instagram.com/p/{code}/"
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=aiohttp.ClientTimeout(total=5), allow_redirects=False) as res:
                if res.status == 200:
                    return {"alive": True, "url": url}
                elif res.status in [404, 302]:
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

# ----------------- BACKGROUND MONITOR LOOP -----------------
@tasks.loop(seconds=3)
async def check_loop():
    targets = db.get_all()
    if not targets:
        return

    async with aiohttp.ClientSession() as session:
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
                    data = await FastInstagramScraper.fetch_account(session, target)
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
                        except Exception as e:
                            logger.error(f"Image Send error: {e}")
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
                    p_data = await FastInstagramScraper.fetch_post(session, target)
                    if not p_data:
                        continue

                    if alert_on == "unban" and p_data["alive"]:
                        embed = discord.Embed(
                            title="Monitoring Status",
                            description=f"🎉 [Instagram Post Restored / Recovered ✅]({p_data['url']})\n⏱️ Elapsed Time: {elapsed}",
                            color=discord.Color.from_rgb(46, 204, 113)
                        )
                        await channel.send(embed=embed)
                        db.remove_monitor(item["id"])

            except Exception as err:
                logger.error(f"Check error: {err}")

# ----------------- SLASH COMMANDS -----------------
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

@bot.tree.command(name="list", description="Show all monitored targets.")
async def list_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    rows = db.get_by_user_or_guild(interaction.user.id, interaction.guild_id or 0)
    
    if not rows:
        await interaction.followup.send("❌ No active monitors found in this server.")
        return

    embed = discord.Embed(
        title="📋 Active Monitoring List",
        description="Here are the accounts and posts currently being monitored:",
        color=discord.Color.blue()
    )

    for r in rows:
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
