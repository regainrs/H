import os
import io
import re
import time
import random
import asyncio
import sqlite3
import logging
import threading
from datetime import datetime
from typing import Optional

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

# ----------------- KEEP-ALIVE SERVER -----------------
app = Flask(__name__)

@app.route("/")
def home():
    return "MonitorHub Engine is Live 24/7."

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
                        start_time REAL,
                        target_delay REAL
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"DB Init Error: {e}")

    def add_monitor(self, m_id, g_id, c_id, u_id, target, t_type, a_type):
        try:
            # Dynamic humanized delay: 3s to 95s (never exceeds 2 mins)
            chosen_delay = random.choice([
                random.uniform(2, 6),     # Super fast (3-6s)
                random.uniform(7, 14),    # Medium fast (7-14s)
                random.uniform(18, 42),   # Standard (18-42s)
                random.uniform(55, 95)    # Realistic deep scan (55-95s)
            ])
            with self.get_conn() as conn:
                conn.cursor().execute("""
                    INSERT OR REPLACE INTO monitors (id, guild_id, channel_id, user_id, target, target_type, alert_type, start_time, target_delay)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (m_id, g_id, c_id, u_id, target, t_type, a_type, time.time(), chosen_delay))
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
                rows = conn.cursor().execute("SELECT id, guild_id, channel_id, user_id, target, target_type, alert_type, start_time, target_delay FROM monitors").fetchall()
                return [
                    {
                        "id": r[0], "guild_id": r[1], "channel_id": r[2], "user_id": r[3],
                        "target": r[4], "target_type": r[5], "alert_type": r[6],
                        "start_time": r[7], "target_delay": r[8] if r[8] is not None else 3.0
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

# ----------------- EXACT DARK INSTAGRAM CARD -----------------
def generate_profile_card(username: str, posts: str, followers: str, following: str, avatar_url: Optional[str]) -> io.BytesIO:
    width, height = 560, 160
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Pure Jet-Black Rounded Box
    draw.rounded_rectangle([(0, 0), (width, height)], radius=24, fill=(0, 0, 0, 255))

    font_user = font_stats = font_btn = font_dots = None
    for path in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "Arial.ttf", "arial.ttf"]:
        try:
            font_user = ImageFont.truetype(path, 20)
            font_stats = ImageFont.truetype(path, 15)
            font_btn = ImageFont.truetype(path, 14)
            font_dots = ImageFont.truetype(path, 18)
            break
        except Exception:
            pass

    if not font_user:
        font_user = font_stats = font_btn = font_dots = ImageFont.load_default()

    # HD Avatar Handling
    avatar_size = 100
    avatar_img = None
    if avatar_url:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X)"}
            res = requests.get(avatar_url, headers=headers, timeout=5)
            if res.status_code == 200:
                avatar_img = Image.open(io.BytesIO(res.content)).convert("RGBA").resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
        except Exception:
            pass

    if not avatar_img:
        avatar_img = Image.new("RGBA", (avatar_size, avatar_size), (40, 40, 40, 255))
        draw_temp = ImageDraw.Draw(avatar_img)
        draw_temp.ellipse((15, 15, avatar_size - 15, avatar_size - 15), fill=(90, 90, 90, 255))

    mask = Image.new("L", (avatar_size, avatar_size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
    image.paste(avatar_img, (30, 30), mask)

    # Top Row: Username + Follow + Menu
    draw.text((150, 38), f"@{username}", fill=(255, 255, 255), font=font_user)
    draw.rounded_rectangle([(320, 34), (395, 64)], radius=8, fill=(0, 149, 246))
    draw.text((338, 40), "Follow", fill=(255, 255, 255), font=font_btn)
    draw.text((415, 38), "•••", fill=(255, 255, 255), font=font_dots)

    # Bottom Row: Real Stats Line
    stats_text = f"{posts} posts       {followers} followers       {following} following"
    draw.text((150, 95), stats_text, fill=(240, 240, 240), font=font_stats)

    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output

# ----------------- REALTIME SCRAPER -----------------
class FastInstagramScraper:
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 324.0.0.18.115",
        "x-ig-app-id": "936619743392459",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9"
    }

    WEB_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }

    @staticmethod
    async def fetch_account(session: aiohttp.ClientSession, username: str):
        try:
            url_api = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
            async with session.get(url_api, headers=FastInstagramScraper.HEADERS, timeout=aiohttp.ClientTimeout(total=5)) as res:
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

        try:
            url_web = f"https://www.instagram.com/{username}/"
            async with session.get(url_web, headers=FastInstagramScraper.WEB_HEADERS, timeout=aiohttp.ClientTimeout(total=5)) as res:
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

# ----------------- BOT CORE -----------------
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

# ----------------- HIGH-PERFORMANCE BACKGROUND WORKER -----------------
@tasks.loop(seconds=2)
async def check_loop():
    targets = db.get_all()
    if not targets:
        return

    now = time.time()
    async with aiohttp.ClientSession() as session:
        for item in targets:
            try:
                # Dynamic interval check
                elapsed_raw = now - item["start_time"]
                target_delay = item["target_delay"]

                if elapsed_raw < target_delay:
                    continue

                channel = bot.get_channel(item["channel_id"])
                if not channel:
                    channel = await bot.fetch_channel(item["channel_id"])
                if not channel:
                    continue

                target = item["target"]
                t_type = item["target_type"]
                alert_on = item["alert_type"]
                elapsed_str = format_elapsed(elapsed_raw)

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
                                f"⏱️ Elapsed Time: {elapsed_str}"
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
                                f"⏱️ Elapsed Time: {elapsed_str}"
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
                            description=f"🎉 [Instagram Post Restored / Recovered ✅]({p_data['url']})\n⏱️ Elapsed Time: {elapsed_str}",
                            color=discord.Color.from_rgb(46, 204, 113)
                        )
                        await channel.send(embed=embed)
                        db.remove_monitor(item["id"])

            except Exception as err:
                logger.error(f"Worker Loop Error: {err}")

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
