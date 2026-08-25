import os
import json
import time
import asyncio
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from aiohttp import web

async def handle_ping(request):
    return web.Response(text="Bot is Alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
# =========================
# CONFIG
# =========================

TOKEN = ("MTU0MTYzOTc5MDM1NTU1NDM4Ng.G-gQPE.34ZE8hZBAp19eHmMp-7DaokjmLY0ei59JStfys")

CHECK_INTERVAL = 60  # seconds
DATA_FILE = "accounts.json"

# True karoge to recovery alert mein @everyone mention hoga
MENTION_EVERYONE = False


# =========================
# DATA
# =========================

def load_accounts():
    if not os.path.exists(DATA_FILE):
        return {}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_accounts(accounts):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2)


accounts = load_accounts()


# =========================
# DISCORD BOT
# =========================

intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================
# STATUS CHECK
# =========================

async def check_public_profile(session, username):
    url = f"https://www.instagram.com/{username}/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/127.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=False
        ) as response:

            if response.status == 404:
                return "unavailable"

            if response.status in (200, 302):
                text = await response.text()
                if "Sorry, this page isn't available" in text or "Page Not Found" in text:
                    return "unavailable"
                return "available"

            return "unknown"

    except asyncio.TimeoutError:
        return "unknown"
    except aiohttp.ClientError:
        return "unknown"


# =========================
# EMBED
# =========================

def make_recovered_embed(username, started_at):
    now = datetime.now(timezone.utc)

    elapsed = int(
        now.timestamp() -
        datetime.fromisoformat(started_at).timestamp()
    )

    hours = elapsed // 3600
    minutes = (elapsed % 3600) // 60
    seconds = elapsed % 60

    embed = discord.Embed(
        title=f"🏆 Account Recovered | @{username}",
        color=discord.Color.green()
    )

    embed.add_field(
        name="👥 Followers",
        value="N/A",
        inline=True
    )

    embed.add_field(
        name="⏱️ Time",
        value=f"{hours} hours, {minutes} minutes, {seconds} seconds",
        inline=True
    )

    embed.add_field(
        name="🔗 Profile",
        value=f"https://www.instagram.com/{username}/",
        inline=False
    )

    embed.add_field(
        name="Started",
        value=started_at.replace("+00:00", " UTC"),
        inline=False
    )

    embed.add_field(
        name="Available",
        value=now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        inline=False
    )

    embed.add_field(
        name="Status",
        value="✅ Account is now active.",
        inline=False
    )

    embed.set_footer(
        text="Public availability monitor"
    )

    return embed


# =========================
# MONITOR LOOP
# =========================

@tasks.loop(seconds=CHECK_INTERVAL)
async def monitor_accounts():

    if not accounts:
        return

    async with aiohttp.ClientSession() as session:

        for username, data in list(accounts.items()):

            channel_id = data.get("channel_id")

            if not channel_id:
                continue

            try:
                channel = bot.get_channel(int(channel_id))

                if channel is None:
                    continue

                old_status = data.get("status", "unknown")

                new_status = await check_public_profile(
                    session,
                    username
                )

                # Ignore unknown responses.
                if new_status == "unknown":
                    continue

                # First check: save state only.
                if old_status == "unknown":
                    data["status"] = new_status

                    if new_status == "unavailable":
                        data["started_at"] = datetime.now(
                            timezone.utc
                        ).isoformat()

                    save_accounts(accounts)
                    continue

                # AVAILABLE -> UNAVAILABLE
                if (
                    old_status == "available"
                    and new_status == "unavailable"
                ):

                    data["status"] = "unavailable"
                    data["started_at"] = datetime.now(
                        timezone.utc
                    ).isoformat()

                    save_accounts(accounts)

                    print(
                        f"[OFFLINE] @{username}"
                    )

                # UNAVAILABLE -> AVAILABLE
                elif (
                    old_status == "unavailable"
                    and new_status == "available"
                ):

                    started_at = data.get(
                        "started_at",
                        datetime.now(timezone.utc).isoformat()
                    )

                    embed = make_recovered_embed(
                        username,
                        started_at
                    )

                    content = (
                        "@everyone"
                        if MENTION_EVERYONE
                        else None
                    )

                    await channel.send(
                        content=content,
                        embed=embed,
                        allowed_mentions=discord.AllowedMentions(
                            everyone=MENTION_EVERYONE
                        )
                    )

                    data["status"] = "available"
                    data["started_at"] = None

                    save_accounts(accounts)

                    print(
                        f"[RECOVERED] @{username}"
                    )

                else:
                    data["status"] = new_status
                    save_accounts(accounts)

            except Exception as e:
                print(
                    f"Monitor error for @{username}: {e}"
                )


@monitor_accounts.before_loop
async def before_monitor():
    await bot.wait_until_ready()


# =========================
# READY
# =========================

@bot.event
async def on_ready():
    await start_web_server()

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Command sync error: {e}")

    if not monitor_accounts.is_running():
        monitor_accounts.start()

    print(f"Logged in as {bot.user}")


# =========================
# /watch
# =========================

@bot.tree.command(
    name="watch",
    description="Monitor a public Instagram profile"
)
@app_commands.describe(
    username="Instagram username"
)
async def watch(
    interaction: discord.Interaction,
    username: str
):

    username = username.strip().lstrip("@")

    accounts[username] = {
        "channel_id": str(interaction.channel_id),
        "status": "unknown",
        "started_at": None
    }

    save_accounts(accounts)

    await interaction.response.send_message(
        f"👁️ Now monitoring **@{username}**.\n"
        f"Checks every **{CHECK_INTERVAL} seconds**."
    )


# =========================
# /unwatch
# =========================

@bot.tree.command(
    name="unwatch",
    description="Stop monitoring an Instagram profile"
)
@app_commands.describe(
    username="Instagram username"
)
async def unwatch(
    interaction: discord.Interaction,
    username: str
):

    username = username.strip().lstrip("@")

    if username not in accounts:
        await interaction.response.send_message(
            f"❌ **@{username}** is not being monitored."
        )
        return

    del accounts[username]
    save_accounts(accounts)

    await interaction.response.send_message(
        f"🛑 Stopped monitoring **@{username}**."
    )


# =========================
# /list
# =========================

@bot.tree.command(
    name="list",
    description="Show monitored accounts"
)
async def list_accounts(
    interaction: discord.Interaction
):

    if not accounts:
        await interaction.response.send_message(
            "📭 No accounts are being monitored."
        )
        return

    lines = []

    for username, data in accounts.items():

        status = data.get(
            "status",
            "unknown"
        )

        emoji = {
            "available": "🟢",
            "unavailable": "🔴",
            "unknown": "⚪"
        }.get(status, "⚪")

        lines.append(
            f"{emoji} **@{username}** — `{status}`"
        )

    await interaction.response.send_message(
        "📋 **Monitored Accounts**\n\n" +
        "\n".join(lines)
    )


# =========================
# /test
# =========================

@bot.tree.command(
    name="test",
    description="Send a test recovery notification"
)
async def test(
    interaction: discord.Interaction
):

    username = "example"

    started = (
        datetime.now(timezone.utc).timestamp()
        - (26 * 3600 + 51 * 60 + 6)
    )

    started_at = datetime.fromtimestamp(
        started,
        timezone.utc
    ).isoformat()

    embed = make_recovered_embed(
        username,
        started_at
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================
# START
# =========================

if not TOKEN:
    raise RuntimeError(
        "DISCORD_BOT_TOKEN environment variable is missing."
    )

bot.run(TOKEN)
