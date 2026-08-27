import os
import io
import re
import time
import json
import asyncio
import sqlite3
import logging
import threading
from typing import Optional
from urllib.parse import quote

import aiohttp
import discord
from discord.ext import commands, tasks
from flask import Flask
from PIL import Image, ImageDraw, ImageFont


# ============================================================
# CONFIG & CREDENTIALS
# ============================================================

DEFAULT_TOKEN = "MTU0MTYzOTc5MDM1NTU1NDM4Ng.GUYab3.wZc2OfVHNxsbDJ1C8BHmdHW7XkqxUA7IHNPa28"
TOKEN = os.environ.get("DISCORD_TOKEN", DEFAULT_TOKEN).strip()


# ============================================================
# LOGGING SETUP
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("IG_Monitor")


# ============================================================
# KEEP-ALIVE FLASK
# ============================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "Ultra-Fast 24/7 Bypass Engine Live"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


# ============================================================
# DATABASE
# ============================================================

class Database:
    def __init__(self, db_name="monitors.db"):
        self.db_name = db_name
        self.init_db()

    def get_conn(self):
        return sqlite3.connect(self.db_name, check_same_thread=False)

    def init_db(self):
        try:
            with self.get_conn() as conn:
                conn.execute("""
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
            with self.get_conn() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO monitors
                    (id, guild_id, channel_id, user_id, target, target_type, alert_type, start_time, target_delay)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (m_id, g_id, c_id, u_id, target, t_type, a_type, time.time(), 0.0))
                conn.commit()
        except Exception as e:
            logger.error(f"DB Add Error: {e}")

    def remove_monitor(self, m_id):
        try:
            with self.get_conn() as conn:
                conn.execute("DELETE FROM monitors WHERE id = ?", (m_id,))
                conn.commit()
        except Exception as e:
            logger.error(f"DB Remove Error: {e}")

    def remove_by_target(self, target: str, user_id: int):
        try:
            with self.get_conn() as conn:
                cursor = conn.execute("DELETE FROM monitors WHERE (target = ? OR id LIKE ?) AND user_id = ?", 
                                      (target, f"%{target}%", user_id))
                conn.commit()
                return cursor.rowcount
        except Exception as e:
            logger.error(f"DB Remove Target Error: {e}")
            return 0

    def clear_all(self, user_id: int):
        try:
            with self.get_conn() as conn:
                cursor = conn.execute("DELETE FROM monitors WHERE user_id = ?", (user_id,))
                conn.commit()
                return cursor.rowcount
        except Exception as e:
            logger.error(f"DB Clear Error: {e}")
            return 0

    def get_all(self):
        try:
            with self.get_conn() as conn:
                rows = conn.execute("""
                    SELECT id, guild_id, channel_id, user_id, target, target_type, alert_type, start_time, target_delay
                    FROM monitors
                """).fetchall()
                return [
                    {
                        "id": r[0], "guild_id": r[1], "channel_id": r[2], "user_id": r[3],
                        "target": r[4], "target_type": r[5], "alert_type": r[6],
                        "start_time": r[7], "target_delay": 0.0
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"DB Get Error: {e}")
            return []

    def get_by_user_or_guild(self, user_id: int, guild_id: int):
        try:
            with self.get_conn() as conn:
                return conn.execute("""
                    SELECT id, target, target_type, alert_type, start_time
                    FROM monitors WHERE user_id = ? OR guild_id = ?
                """, (user_id, guild_id)).fetchall()
        except Exception:
            return []

db = Database()


# ============================================================
# CARD RENDERER
# ============================================================

def get_font(size: int, weight="regular"):
    filename = "font_medium.ttf" if weight == "medium" else "font_regular.ttf"
    if os.path.exists(filename):
        try:
            return ImageFont.truetype(filename, size)
        except Exception:
            pass

    fallbacks = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if weight == "medium" else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if weight == "medium" else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "Arial.ttf"
    ]
    for p in fallbacks:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def generate_profile_card(username: str, posts: str, followers: str, following: str, avatar_bytes: Optional[bytes]):
    scale = 2
    width = 450 * scale
    height = 130 * scale

    card = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    draw = ImageDraw.Draw(card)

    draw.rounded_rectangle([(0, 0), (width, height)], radius=16 * scale, fill=(0, 0, 0, 255))

    f_user = get_font(15 * scale, "medium")
    f_stats = get_font(12 * scale, "regular")
    f_btn = get_font(11 * scale, "medium")

    avatar_dim = 76 * scale
    avatar_img = None

    if avatar_bytes:
        try:
            raw = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            min_dim = min(raw.width, raw.height)
            left = (raw.width - min_dim) // 2
            top = (raw.height - min_dim) // 2
            raw = raw.crop((left, top, left + min_dim, top + min_dim))
            raw = raw.resize((avatar_dim, avatar_dim), Image.Resampling.LANCZOS)

            avatar_img = Image.new("RGBA", (avatar_dim, avatar_dim), (0, 0, 0, 0))
            avatar_img.paste(raw, (0, 0))

            mask = Image.new("L", (avatar_dim, avatar_dim), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, avatar_dim - 1, avatar_dim - 1), fill=255)
            avatar_img.putalpha(mask)
        except Exception as e:
            logger.warning(f"Avatar processing warning: {e}")

    if avatar_img is None:
        avatar_img = Image.new("RGBA", (avatar_dim, avatar_dim), (142, 150, 160, 255))
        mask = Image.new("L", (avatar_dim, avatar_dim), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, avatar_dim - 1, avatar_dim - 1), fill=255)
        avatar_img.putalpha(mask)

    avatar_x = 24 * scale
    avatar_y = (height - avatar_dim) // 2
    card.paste(avatar_img, (avatar_x, avatar_y), avatar_img)

    text_start_x = avatar_x + avatar_dim + 16 * scale
    username_text = f"@{username}"
    u_bbox = draw.textbbox((text_start_x, 34 * scale), username_text, font=f_user)
    draw.text((text_start_x, 34 * scale), username_text, fill=(255, 255, 255), font=f_user)

    username_width = u_bbox[2] - u_bbox[0]
    btn_x = text_start_x + username_width + 12 * scale
    btn_y = 30 * scale
    btn_w = 58 * scale
    btn_h = 24 * scale

    draw.rounded_rectangle([(btn_x, btn_y), (btn_x + btn_w, btn_y + btn_h)], radius=5 * scale, fill=(0, 149, 246))

    b_bbox = draw.textbbox((0, 0), "Follow", font=f_btn)
    bw = b_bbox[2] - b_bbox[0]
    bh = b_bbox[3] - b_bbox[1]
    draw.text((btn_x + (btn_w - bw) // 2, btn_y + (btn_h - bh) // 2 - scale), "Follow", fill=(255, 255, 255), font=f_btn)

    dots_x = btn_x + btn_w + 10 * scale
    dots_y = 41 * scale
    dot_r = int(1.5 * scale)
    for i in range(3):
        dx = dots_x + (i * 5 * scale)
        draw.ellipse([(dx, dots_y), (dx + dot_r * 2, dots_y + dot_r * 2)], fill=(255, 255, 255))

    stats_text = f"{posts} posts      {followers} followers      {following} following"
    draw.text((text_start_x, 70 * scale), stats_text, fill=(190, 190, 190), font=f_stats)

    final_img = card.resize((450, 130), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    final_img.save(output, format="PNG")
    output.seek(0)
    return output


# ============================================================
# HIGH-PRECISION SCRAPER ENGINE
# ============================================================

class InstagramSessionScraper:
    @staticmethod
    async def download_image(session, img_url):
        if not img_url:
            return None
        clean_url = img_url.replace("\\u0026", "&").replace("\\/", "/")
        try:
            proxy_url = f"https://images.weserv.nl/?url={quote(clean_url, safe='')}&w=300&h=300&fit=cover"
            async with session.get(proxy_url, timeout=aiohttp.ClientTimeout(total=5)) as res:
                if res.status == 200:
                    data = await res.read()
                    if len(data) > 400:
                        return data
        except Exception:
            pass
        return None

    @classmethod
    async def fetch_account(cls, session, username):
        username = username.strip().lower().replace("@", "")

        # Route 1: Direct IG Web API with App ID Header (Fastest & Most Accurate)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "X-IG-App-ID": "936619743392459",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Site": "same-origin"
        }

        try:
            direct_api = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
            async with session.get(direct_api, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as res:
                if res.status == 200:
                    data = await res.json()
                    user_data = data.get("data", {}).get("user")
                    if user_data:
                        f_count = str(user_data.get("edge_followed_by", {}).get("count", 0))
                        fo_count = str(user_data.get("edge_follow", {}).get("count", 0))
                        p_count = str(user_data.get("edge_owner_to_timeline_media", {}).get("count", 0))
                        avatar_url = user_data.get("profile_pic_url_hd") or user_data.get("profile_pic_url")
                        avatar_bytes = await cls.download_image(session, avatar_url)
                        return {
                            "alive": True,
                            "username": username,
                            "followers": f_count,
                            "following": fo_count,
                            "posts": p_count,
                            "avatar_bytes": avatar_bytes,
                            "url": f"https://www.instagram.com/{username}/"
                        }
                elif res.status == 404:
                    return {"alive": False, "username": username}
        except Exception:
            pass

        # Route 2: Tunnel fallback (AllOrigins / CodeTabs)
        fallback_urls = [
            f"https://api.allorigins.win/raw?url={quote(f'https://www.instagram.com/{username}/')}",
            f"https://api.codetabs.com/v1/proxy?quest=https://www.instagram.com/{username}/"
        ]

        for tunnel_url in fallback_urls:
            try:
                async with session.get(tunnel_url, timeout=aiohttp.ClientTimeout(total=6)) as res:
                    if res.status == 200:
                        html = await res.text()
                        if f"/{username}/" in html or "instagram.com" in html:
                            match = re.search(r'content="([0-9.,KMBkmb]+)\s+Followers,\s+([0-9.,KMBkmb]+)\s+Following,\s+([0-9.,KMBkmb]+)\s+Posts', html)
                            f_count, fo_count, p_count = (match.group(1), match.group(2), match.group(3)) if match else ("1", "0", "0")
                            img_match = re.search(r'property="og:image"\s+content="([^"]+)"', html)
                            avatar_url = img_match.group(1) if img_match else None
                            avatar_bytes = await cls.download_image(session, avatar_url)
                            return {
                                "alive": True,
                                "username": username,
                                "followers": f_count,
                                "following": fo_count,
                                "posts": p_count,
                                "avatar_bytes": avatar_bytes,
                                "url": f"https://www.instagram.com/{username}/"
                            }
                    elif res.status == 404:
                        return {"alive": False, "username": username}
            except Exception:
                continue

        return None

    @classmethod
    async def fetch_post(cls, session, code):
        code = code.strip()
        url = f"https://www.instagram.com/p/{code}/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        }
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as res:
                if res.status == 200:
                    return {"alive": True, "url": url}
                if res.status in (404, 301, 302):
                    return {"alive": False, "url": url}
        except Exception:
            pass
        return None


# ============================================================
# TIME FORMAT
# ============================================================

def format_elapsed(seconds):
    display_secs = min(int(seconds), 110)
    secs = max(1, display_secs)

    if secs < 60:
        return f"{secs} seconds"

    mins = secs // 60
    rem_secs = secs % 60

    if rem_secs == 0:
        return f"{mins} minute"
    return f"{mins} minute, {rem_secs} seconds"


# ============================================================
# BOT ENGINE
# ============================================================

class MonitorBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="/", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()

bot = MonitorBot()


@tasks.loop(seconds=1.5)
async def check_loop():
    targets = db.get_all()
    if not targets:
        return

    now = time.time()
    async with aiohttp.ClientSession() as session:
        for item in targets:
            try:
                channel = bot.get_channel(item["channel_id"])
                if channel is None:
                    try:
                        channel = await bot.fetch_channel(item["channel_id"])
                    except Exception:
                        continue

                target = item["target"]
                t_type = item["target_type"]
                alert_on = item["alert_type"]
                elapsed_raw = now - item["start_time"]
                elapsed_str = format_elapsed(elapsed_raw)

                if t_type == "account":
                    data = await InstagramSessionScraper.fetch_account(session, target)
                    if not data:
                        continue

                    if alert_on == "unban" and data.get("alive"):
                        followers_num = str(data["followers"]).replace(",", "")
                        following_num = str(data["following"]).replace(",", "")

                        description_text = (
                            f"[Account Recovered | @{data['username']} 🏆✅]({data['url']})\n"
                            f"*Followers: {followers_num}\\ Following: {following_num}*\n"
                            f"⏱️ *Time taken: {elapsed_str}*"
                        )

                        embed = discord.Embed(
                            description=description_text,
                            color=discord.Color.from_rgb(46, 204, 113)
                        )

                        notification_preview = f"Account Recovered | @{data['username']} 🏆✅ | Followers: {followers_num} | Time: {elapsed_str}"

                        try:
                            card = generate_profile_card(
                                data["username"],
                                data["posts"],
                                data["followers"],
                                data["following"],
                                data["avatar_bytes"]
                            )
                            file = discord.File(card, filename="instagram_profile.png")
                            embed.set_image(url="attachment://instagram_profile.png")
                            await channel.send(content=notification_preview, embed=embed, file=file)
                        except Exception as e:
                            logger.error(f"Card Send Fail: {e}")
                            await channel.send(content=notification_preview, embed=embed)

                        db.remove_monitor(item["id"])

                    elif alert_on == "ban" and not data.get("alive"):
                        ban_desc = f"⚠️ **Account Suspended / Unavailable** | `@{target}`\n⏱️ *Time taken: {elapsed_str}*"
                        embed = discord.Embed(description=ban_desc, color=discord.Color.from_rgb(231, 76, 60))
                        await channel.send(content=f"⚠️ Account Suspended | @{target}", embed=embed)
                        db.remove_monitor(item["id"])

                elif t_type == "post":
                    p_data = await InstagramSessionScraper.fetch_post(session, target)
                    if not p_data:
                        continue

                    if alert_on == "unban" and p_data.get("alive"):
                        post_desc = f"[🎉 Instagram Post Restored / Recovered ✅]({p_data['url']})\n⏱️ *Time taken: {elapsed_str}*"
                        embed = discord.Embed(description=post_desc, color=discord.Color.from_rgb(46, 204, 113))
                        await channel.send(content=f"🎉 Instagram Post Restored ✅ | {target}", embed=embed)
                        db.remove_monitor(item["id"])

                    elif alert_on == "ban" and not p_data.get("alive"):
                        post_ban_desc = f"⚠️ **Instagram Post Removed / Unavailable**\nPost ID: `{target}`\n⏱️ *Time taken: {elapsed_str}*"
                        embed = discord.Embed(description=post_ban_desc, color=discord.Color.from_rgb(231, 76, 60))
                        await channel.send(content=f"⚠️ Post Removed | {target}", embed=embed)
                        db.remove_monitor(item["id"])

            except Exception as error:
                logger.error(f"Worker Loop Error: {error}")


# ============================================================
# COMMANDS
# ============================================================

@bot.tree.command(name="test", description="Instant live test for any Instagram username.")
async def test_cmd(interaction: discord.Interaction, username: str):
    await interaction.response.defer(thinking=True)
    user = username.strip().replace("@", "").lower()

    async with aiohttp.ClientSession() as session:
        data = await InstagramSessionScraper.fetch_account(session, user)

    if data and data.get("alive"):
        followers_num = str(data["followers"]).replace(",", "")
        following_num = str(data["following"]).replace(",", "")

        description_text = (
            f"[Account Active / Alive | @{data['username']} 🟢]({data['url']})\n"
            f"*Followers: {followers_num}\\ Following: {following_num}*\n"
            f"⚡ *Engine: High-Precision Live*"
        )

        embed = discord.Embed(
            title="🧪 Live Test Result",
            description=description_text,
            color=discord.Color.from_rgb(46, 204, 113)
        )

        try:
            card = generate_profile_card(
                data["username"],
                data["posts"],
                data["followers"],
                data["following"],
                data["avatar_bytes"]
            )
            file = discord.File(card, filename="instagram_profile.png")
            embed.set_image(url="attachment://instagram_profile.png")
            await interaction.followup.send(embed=embed, file=file)
        except Exception:
            await interaction.followup.send(embed=embed)
    elif data and not data.get("alive"):
        embed = discord.Embed(
            title="🧪 Live Test Result",
            description=f"🔴 **Account Unavailable / Suspended:** `@{user}`",
            color=discord.Color.from_rgb(231, 76, 60)
        )
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(f"⚠️ Could not fetch details for `@{user}`. Please check username.")


@bot.tree.command(name="unban_ig", description="Monitor an Instagram public account for recovery.")
async def unban_ig(interaction: discord.Interaction, username: str):
    await interaction.response.defer(thinking=False)
    user = username.strip().replace("@", "").lower()
    db.add_monitor(f"acc_unban_{user}", interaction.guild_id, interaction.channel_id, interaction.user.id, user, "account", "unban")
    await interaction.followup.send(f"🟢 **Monitoring Activated:** Watching `@{user}` for recovery.")


@bot.tree.command(name="ban_ig", description="Monitor an Instagram public account for unavailable status.")
async def ban_ig(interaction: discord.Interaction, username: str):
    await interaction.response.defer(thinking=False)
    user = username.strip().replace("@", "").lower()
    db.add_monitor(f"acc_ban_{user}", interaction.guild_id, interaction.channel_id, interaction.user.id, user, "account", "ban")
    await interaction.followup.send(f"🔴 **Monitoring Activated:** Watching `@{user}` for unavailable status.")


@bot.tree.command(name="unban_igpost", description="Monitor an Instagram post for restoration.")
async def unban_igpost(interaction: discord.Interaction, post: str):
    await interaction.response.defer(thinking=False)
    code = post.strip().rstrip("/").split("/")[-1]
    db.add_monitor(f"post_unban_{code}", interaction.guild_id, interaction.channel_id, interaction.user.id, code, "post", "unban")
    await interaction.followup.send(f"🟢 **Monitoring Activated:** Watching Post `{code}` for restore.")


@bot.tree.command(name="ban_igpost", description="Monitor an Instagram post for removal.")
async def ban_igpost(interaction: discord.Interaction, post: str):
    await interaction.response.defer(thinking=False)
    code = post.strip().rstrip("/").split("/")[-1]
    db.add_monitor(f"post_ban_{code}", interaction.guild_id, interaction.channel_id, interaction.user.id, code, "post", "ban")
    await interaction.followup.send(f"🔴 **Monitoring Activated:** Watching Post `{code}` for removal.")


@bot.tree.command(name="list", description="Show all active monitored targets.")
async def list_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    rows = db.get_by_user_or_guild(interaction.user.id, interaction.guild_id or 0)

    if not rows:
        await interaction.followup.send("❌ No active monitors in queue.")
        return

    embed = discord.Embed(
        title="📋 Active Monitoring List",
        description=f"Total active targets: **{len(rows)}**",
        color=discord.Color.blue()
    )

    for row in rows:
        target, target_type, alert_type, started = row[1], row[2], row[3], int(row[4])
        target_name = f"@{target}" if target_type == "account" else f"Post `{target}`"
        mode = "🟢 Recovery" if alert_type == "unban" else "🔴 Unavailable / Removal"

        embed.add_field(
            name=f"{target_name} ({target_type.capitalize()})",
            value=f"• **Mode:** {mode}\n• **Started:** <t:{started}:R>",
            inline=False
        )

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="remove", description="Remove a specific target or clear all from monitoring.")
async def remove_cmd(interaction: discord.Interaction, target: Optional[str] = None):
    await interaction.response.defer(ephemeral=False)
    
    if not target or target.strip().lower() == "all":
        count = db.clear_all(interaction.user.id)
        await interaction.followup.send(f"🗑️ Cleared **{count}** target(s) from your monitoring queue.")
    else:
        clean_target = target.strip().replace("@", "").lower()
        count = db.remove_by_target(clean_target, interaction.user.id)
        if count > 0:
            await interaction.followup.send(f"✅ Removed `{target}` from monitoring queue.")
        else:
            await interaction.followup.send(f"❌ Target `{target}` not found in your active list.")


@bot.event
async def on_ready():
    logger.info(f"Bot connected as {bot.user}")
    if not check_loop.is_running():
        check_loop.start()


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
