import discord
from discord import app_commands
from discord.ext import commands, tasks
import re
import os
import asyncio
import datetime
import json
from pathlib import Path
from collections import defaultdict

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is not set.")

ADMIN_ID             = 1046003233325322340
MEMBER_COUNT_CHANNEL = 1474009409951633552
MOD_LOG_CHANNEL      = 1475105670498877541
DEFAULT_ROLE_ID      = 1473980147735724053

SPAM_MSG_LIMIT   = 4
SPAM_TIME_WINDOW = 5
SPAM_TIMEOUT_MIN = 60
RAID_JOIN_LIMIT  = 8
RAID_JOIN_WINDOW = 10

WARNINGS_FILE = Path("bot/warnings.json")

KEY_WORDS = {
    "key", "llave", "clave", "clé", "clef", "chiave", "schlüssel", "schlussel",
    "ключ", "klucz", "chave", "nøgle", "nøkkel", "nyckel", "avain", "anahtar",
    "cheie", "kulcs", "kľúč", "klíč", "çelës", "celes", "ključ", "sleutel",
    "atslēga", "atslega", "raktas", "võti", "voti", "açar", "acar", "kalit",
    "kunci", "ufunguo", "bọtini", "botini", "chabi", "kunji", "mafunguo",
    "gunci", "chìa", "กุญแจ", "钥匙", "鍵", "열쇠", "κλειδί", "kleidi",
    "banali", "kilt", "tulkhuur", "qulf", "kelid", "susi", "kilid", "ракля",
    "klucek", "miftah", "clei", "clave", "khóa", "ключик", "clave", "chiavi",
    "anahtarı", "mafunguo", "anahtarları", "chiave", "bwana", "ufunguo",
    "ugawe", "muhimu", "сілт", "clave", "ключик", "chave", "clau", "llave",
}

SCRIPT_WORDS = {
    "script", "скрипт", "skrypt", "skript", "szkript", "scenariu", "scénario",
    "roteiro", "guión", "guion", "copione", "drehbuch", "skripti", "betik",
    "сценарій", "scenarij", "scenariul", "scénár", "manus", "manuskript",
    "skenario", "skrip", "maandishi", "kịch", "kich", "สคริปต์", "脚本",
    "スクリプト", "스크립트", "σενάριο", "senaryo", "skripts", "skriptas",
    "stsenaarium", "скрипта", "skriptet", "käsikirjoitus", "kasikirjoitus",
    "hati", "iwe", "escritura", "ecriture", "spis", "skripta", "senariju",
    "scenariusz", "skriptum", "skriptis", "escrip", "скрипт", "ssenario",
    "skenaryo", "scenar", "manus", "skripteten", "iwe-afọwọkọ", "maandishi",
    "skripto", "скрипти", "skripte", "سكريبت", "سكريبت", "scr1pt",
}

SCRIPT_RESPONSE = 'Script\n```loadstring(game:HttpGet("https://pighubthebest.vercel.app/loader.lua", true))()```'

spam_tracker: dict[int, list[datetime.datetime]] = defaultdict(list)
raid_join_times: dict[int, list[datetime.datetime]] = defaultdict(list)
processing: set[int] = set()
warnings_data: dict[str, list[dict]] = {}


def load_warnings() -> dict:
    if WARNINGS_FILE.exists():
        try:
            return json.loads(WARNINGS_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_warnings() -> None:
    WARNINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    WARNINGS_FILE.write_text(json.dumps(warnings_data, indent=2, ensure_ascii=False))


warnings_data = load_warnings()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.id == ADMIN_ID
    return app_commands.check(predicate)


def fmt_dt(dt: datetime.datetime | None = None) -> str:
    if dt is None:
        dt = datetime.datetime.utcnow()
    return dt.strftime("%d.%m.%Y %H:%M")


async def get_mod_log(guild: discord.Guild) -> discord.TextChannel | None:
    return guild.get_channel(MOD_LOG_CHANNEL)


async def assign_default_role(member: discord.Member) -> None:
    if member.bot:
        return
    role = member.guild.get_role(DEFAULT_ROLE_ID)
    if role is None:
        return
    if role in member.roles:
        return
    for attempt in range(3):
        try:
            await member.add_roles(role, reason="Auto-assign default role")
            return
        except discord.Forbidden:
            return
        except discord.HTTPException:
            await asyncio.sleep(1.5 * (attempt + 1))


async def bulk_assign_default_role(guild: discord.Guild) -> int:
    if not guild.chunked:
        await guild.chunk(cache=True)
    role = guild.get_role(DEFAULT_ROLE_ID)
    if role is None:
        return 0
    count = 0
    for member in guild.members:
        if member.bot:
            continue
        if role in member.roles:
            continue
        for attempt in range(3):
            try:
                await member.add_roles(role, reason="Startup: assign default role")
                count += 1
                break
            except discord.Forbidden:
                break
            except discord.HTTPException:
                await asyncio.sleep(1.5 * (attempt + 1))
        await asyncio.sleep(0.35)
    return count


async def log_mod_action(
    guild: discord.Guild,
    title: str,
    target: discord.Member | discord.User,
    reason: str,
    moderator: discord.Member | discord.User,
    color: discord.Color,
    extra: list[tuple[str, str]] | None = None,
    warn_count: int | None = None,
) -> None:
    channel = await get_mod_log(guild)
    if channel is None:
        return
    full_title = f"{title} (#{warn_count})" if warn_count is not None else title
    embed = discord.Embed(title=full_title, color=color, timestamp=datetime.datetime.utcnow())
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="User", value=f"{target.name} ({target.id})", inline=False)
    embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
    if extra:
        for name, value in extra:
            embed.add_field(name=name, value=value, inline=False)
    embed.add_field(name="Moderator", value=moderator.name, inline=False)
    embed.set_footer(text=f"Pig Hub • {fmt_dt()}")
    await channel.send(embed=embed)


async def log_antiraid(
    guild: discord.Guild,
    target: discord.Member,
    reason: str,
    action: str,
) -> None:
    channel = await get_mod_log(guild)
    if channel is None:
        return
    embed = discord.Embed(
        title="Anti-Raid",
        color=discord.Color.from_rgb(30, 0, 0),
        timestamp=datetime.datetime.utcnow(),
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="User", value=f"{target.name} ({target.id})", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Action", value=action, inline=False)
    embed.set_footer(text=f"Pig Hub • {fmt_dt()}")
    await channel.send(embed=embed)


async def try_dm(
    user: discord.Member,
    title: str,
    description: str,
    color: discord.Color,
) -> None:
    try:
        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_footer(text="Pig Hub")
        await user.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass


async def handle_spam(message: discord.Message) -> bool:
    uid = message.author.id
    now = datetime.datetime.utcnow()
    spam_tracker[uid] = [
        t for t in spam_tracker[uid]
        if (now - t).total_seconds() <= SPAM_TIME_WINDOW
    ]
    spam_tracker[uid].append(now)
    if len(spam_tracker[uid]) < SPAM_MSG_LIMIT:
        return False
    count = len(spam_tracker[uid])
    spam_tracker[uid].clear()
    member = message.guild.get_member(uid)
    if member is None:
        return True
    if member.guild_permissions.administrator or member.guild_permissions.manage_messages:
        return False
    until = discord.utils.utcnow() + datetime.timedelta(minutes=SPAM_TIMEOUT_MIN)
    try:
        await member.timeout(until, reason="Auto-mute: spam detected")
    except discord.Forbidden:
        pass
    try:
        deleted = await message.channel.purge(
            limit=50,
            check=lambda m: m.author.id == uid,
            bulk=True,
        )
    except discord.Forbidden:
        deleted = []
    embed = discord.Embed(
        title="Anti-Spam Triggered",
        color=discord.Color.red(),
        timestamp=datetime.datetime.utcnow(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="User", value=f"{member.mention} ({member.id})", inline=False)
    embed.add_field(name="Reason", value=f"Duplicate messages ({count} times)", inline=False)
    embed.add_field(
        name="Action",
        value=f"{SPAM_TIMEOUT_MIN}min mute + {len(deleted)} messages deleted",
        inline=False,
    )
    embed.set_footer(text="Pig Hub")
    await message.channel.send(embed=embed, delete_after=10)
    await log_antiraid(
        message.guild,
        member,
        f"Duplicate messages ({count} times)",
        f"{SPAM_TIMEOUT_MIN}min mute + {len(deleted)} messages deleted",
    )
    return True


def matches_words(content: str, word_set: set[str]) -> bool:
    tokens = re.findall(r"[^\s,;!?.\"'()[\]]+", content.lower())
    return any(tok in word_set for tok in tokens)


@tasks.loop(minutes=5)
async def update_member_count() -> None:
    for guild in bot.guilds:
        ch = guild.get_channel(MEMBER_COUNT_CHANNEL)
        if ch is not None:
            try:
                await ch.edit(name=f"Members : {guild.member_count}")
            except (discord.Forbidden, discord.HTTPException):
                pass


@bot.event
async def on_ready() -> None:
    for guild in bot.guilds:
        await bot.tree.sync(guild=guild)
    if not update_member_count.is_running():
        update_member_count.start()
    for guild in bot.guilds:
        await bulk_assign_default_role(guild)


@bot.event
async def on_member_join(member: discord.Member) -> None:
    await assign_default_role(member)

    now = datetime.datetime.utcnow()
    gid = member.guild.id
    raid_join_times[gid].append(now)
    recent = [
        t for t in raid_join_times[gid]
        if (now - t).total_seconds() <= RAID_JOIN_WINDOW
    ]
    raid_join_times[gid] = recent

    ch = await get_mod_log(member.guild)
    if ch is not None:
        embed = discord.Embed(
            description=f"{member.mention} joined the server\n\nID: {member.id}",
            color=discord.Color.from_rgb(0, 180, 80),
            timestamp=datetime.datetime.utcnow(),
        )
        embed.set_author(name="Member Joined", icon_url=member.display_avatar.url)
        embed.set_footer(text=f"Pig Hub • {fmt_dt()}")
        await ch.send(embed=embed)

    if len(recent) >= RAID_JOIN_LIMIT:
        raid_join_times[gid].clear()
        until = discord.utils.utcnow() + datetime.timedelta(minutes=60)
        try:
            await member.timeout(until, reason="Anti-raid: mass join detected")
        except discord.Forbidden:
            pass
        await log_antiraid(
            member.guild,
            member,
            f"Mass join detected ({len(recent)} joins in {RAID_JOIN_WINDOW}s)",
            "1h mute",
        )


@bot.event
async def on_member_remove(member: discord.Member) -> None:
    ch = await get_mod_log(member.guild)
    if ch is not None:
        embed = discord.Embed(
            description=f"{member.mention} left the server\n\nID: {member.id}",
            color=discord.Color.from_rgb(22, 22, 22),
            timestamp=datetime.datetime.utcnow(),
        )
        embed.set_author(name="Member Left", icon_url=member.display_avatar.url)
        embed.set_footer(text=f"Pig Hub • {fmt_dt()}")
        await ch.send(embed=embed)


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return
    if message.id in processing:
        return
    processing.add(message.id)
    try:
        if message.guild:
            is_spam = await handle_spam(message)
            if is_spam:
                return
        content = message.content.strip()
        has_key = matches_words(content, KEY_WORDS)
        has_script = matches_words(content, SCRIPT_WORDS)
        if has_key:
            await message.channel.send("The Key is:\n```ilovepigs```")
        if has_script:
            await message.channel.send(SCRIPT_RESPONSE)
        await bot.process_commands(message)
    finally:
        processing.discard(message.id)


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    if isinstance(error, app_commands.CheckFailure):
        msg = "You do not have permission to use this command."
    elif isinstance(error, app_commands.MissingPermissions):
        msg = "You don't have the required permissions."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "I don't have the required permissions to do that."
    else:
        msg = str(error)
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="mute", description="Timeout a user")
@app_commands.describe(
    user="User to mute",
    duration="Duration in minutes (default 60)",
    reason="Reason for the mute",
)
@is_admin()
async def mute_cmd(
    interaction: discord.Interaction,
    user: discord.Member,
    duration: int = 60,
    reason: str = "No reason provided",
) -> None:
    await interaction.response.defer(ephemeral=True)
    if user.id == ADMIN_ID:
        await interaction.followup.send("Cannot mute the server administrator.", ephemeral=True)
        return
    if user.guild_permissions.administrator:
        await interaction.followup.send("Cannot mute an administrator.", ephemeral=True)
        return
    until = discord.utils.utcnow() + datetime.timedelta(minutes=duration)
    try:
        await user.timeout(until, reason=reason)
        await interaction.followup.send(
            f"Muted {user.mention} for **{duration}** minutes.", ephemeral=True
        )
        await try_dm(
            user,
            "You have been muted",
            f"**Server:** {interaction.guild.name}\n**Duration:** {duration} minutes\n**Reason:** {reason}",
            discord.Color.orange(),
        )
        await log_mod_action(
            interaction.guild,
            "User Muted",
            user,
            reason,
            interaction.user,
            discord.Color.orange(),
            [("Duration", f"{duration} minutes")],
        )
    except discord.Forbidden:
        await interaction.followup.send("Failed to mute user. Check bot permissions.", ephemeral=True)


@bot.tree.command(name="unmute", description="Remove timeout from a user")
@app_commands.describe(user="User to unmute", reason="Reason for unmuting")
@is_admin()
async def unmute_cmd(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str = "No reason provided",
) -> None:
    await interaction.response.defer(ephemeral=True)
    try:
        await user.timeout(None, reason=reason)
        await interaction.followup.send(f"Unmuted {user.mention}.", ephemeral=True)
        await log_mod_action(
            interaction.guild,
            "User Unmuted",
            user,
            reason,
            interaction.user,
            discord.Color.green(),
        )
    except discord.Forbidden:
        await interaction.followup.send("Failed to unmute user.", ephemeral=True)


@bot.tree.command(name="ban", description="Ban a user from the server")
@app_commands.describe(
    user="User to ban",
    reason="Reason for the ban",
    delete_days="Days of messages to delete (0-7)",
)
@is_admin()
async def ban_cmd(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str = "No reason provided",
    delete_days: app_commands.Range[int, 0, 7] = 0,
) -> None:
    await interaction.response.defer(ephemeral=True)
    if user.id == ADMIN_ID:
        await interaction.followup.send("Cannot ban the server administrator.", ephemeral=True)
        return
    if user.guild_permissions.administrator:
        await interaction.followup.send("Cannot ban an administrator.", ephemeral=True)
        return
    try:
        await try_dm(
            user,
            "You have been banned",
            f"**Server:** {interaction.guild.name}\n**Reason:** {reason}",
            discord.Color.dark_red(),
        )
        await user.ban(reason=reason, delete_message_days=delete_days)
        await interaction.followup.send(f"Banned {user.mention}.", ephemeral=True)
        await log_mod_action(
            interaction.guild,
            "User Banned",
            user,
            reason,
            interaction.user,
            discord.Color.dark_red(),
        )
    except discord.Forbidden:
        await interaction.followup.send("Failed to ban user. Check bot permissions.", ephemeral=True)


@bot.tree.command(name="unban", description="Unban a user by their ID")
@app_commands.describe(user_id="The ID of the user to unban", reason="Reason for unbanning")
@is_admin()
async def unban_cmd(
    interaction: discord.Interaction,
    user_id: str,
    reason: str = "No reason provided",
) -> None:
    await interaction.response.defer(ephemeral=True)
    try:
        uid = int(user_id)
    except ValueError:
        await interaction.followup.send("Invalid user ID.", ephemeral=True)
        return
    try:
        user = await bot.fetch_user(uid)
        await interaction.guild.unban(user, reason=reason)
        await interaction.followup.send(f"Unbanned **{user}** ({uid}).", ephemeral=True)
        await log_mod_action(
            interaction.guild,
            "User Unbanned",
            user,
            reason,
            interaction.user,
            discord.Color.green(),
        )
    except discord.NotFound:
        await interaction.followup.send("User not found or is not banned.", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("Failed to unban user.", ephemeral=True)


@bot.tree.command(name="kick", description="Kick a user from the server")
@app_commands.describe(user="User to kick", reason="Reason for the kick")
@is_admin()
async def kick_cmd(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str = "No reason provided",
) -> None:
    await interaction.response.defer(ephemeral=True)
    if user.id == ADMIN_ID:
        await interaction.followup.send("Cannot kick the server administrator.", ephemeral=True)
        return
    if user.guild_permissions.administrator:
        await interaction.followup.send("Cannot kick an administrator.", ephemeral=True)
        return
    try:
        await try_dm(
            user,
            "You have been kicked",
            f"**Server:** {interaction.guild.name}\n**Reason:** {reason}",
            discord.Color.red(),
        )
        await user.kick(reason=reason)
        await interaction.followup.send(f"Kicked {user.mention}.", ephemeral=True)
        await log_mod_action(
            interaction.guild,
            "User Kicked",
            user,
            reason,
            interaction.user,
            discord.Color.red(),
        )
    except discord.Forbidden:
        await interaction.followup.send("Failed to kick user.", ephemeral=True)


@bot.tree.command(name="warn", description="Warn a user")
@app_commands.describe(user="User to warn", reason="Reason for the warning")
@is_admin()
async def warn_cmd(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str = "No reason provided",
) -> None:
    uid_str = str(user.id)
    if uid_str not in warnings_data:
        warnings_data[uid_str] = []
    warnings_data[uid_str].append(
        {
            "reason": reason,
            "moderator": interaction.user.name,
            "moderator_id": interaction.user.id,
            "timestamp": fmt_dt(),
        }
    )
    save_warnings()
    count = len(warnings_data[uid_str])
    await interaction.response.send_message(
        f"Warned {user.mention}. Total warnings: **{count}**",
        ephemeral=True,
    )
    await try_dm(
        user,
        f"You have been warned (#{count})",
        f"**Server:** {interaction.guild.name}\n**Reason:** {reason}",
        discord.Color.yellow(),
    )
    await log_mod_action(
        interaction.guild,
        "User Warned",
        user,
        reason,
        interaction.user,
        discord.Color.yellow(),
        warn_count=count,
    )


@bot.tree.command(name="warnings", description="View warnings for a user")
@app_commands.describe(user="User to check warnings for")
@is_admin()
async def warnings_cmd(
    interaction: discord.Interaction,
    user: discord.Member,
) -> None:
    uid_str = str(user.id)
    warns = warnings_data.get(uid_str, [])
    if not warns:
        await interaction.response.send_message(
            f"{user.mention} has no warnings.", ephemeral=True
        )
        return
    embed = discord.Embed(
        title=f"Warnings for {user.name}",
        description=f"Total: **{len(warns)}**",
        color=discord.Color.yellow(),
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    for i, w in enumerate(warns, 1):
        embed.add_field(
            name=f"Warning #{i}",
            value=(
                f"**Reason:** {w['reason']}\n"
                f"**Moderator:** {w['moderator']}\n"
                f"**Date:** {w['timestamp']}"
            ),
            inline=False,
        )
    embed.set_footer(text="Pig Hub")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="clearwarnings", description="Clear all warnings for a user")
@app_commands.describe(user="User to clear warnings for")
@is_admin()
async def clearwarnings_cmd(
    interaction: discord.Interaction,
    user: discord.Member,
) -> None:
    uid_str = str(user.id)
    removed = len(warnings_data.pop(uid_str, []))
    save_warnings()
    await interaction.response.send_message(
        f"Cleared **{removed}** warning(s) for {user.mention}.",
        ephemeral=True,
    )


@bot.tree.command(name="purge", description="Delete messages in this channel")
@app_commands.describe(amount="Number of messages to delete (1-100)")
@is_admin()
async def purge_cmd(
    interaction: discord.Interaction,
    amount: app_commands.Range[int, 1, 100],
) -> None:
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"Deleted **{len(deleted)}** messages.", ephemeral=True)


@bot.tree.command(name="nuke", description="Delete ALL messages in this channel instantly")
@is_admin()
async def nuke_cmd(interaction: discord.Interaction) -> None:
    channel = interaction.channel
    await interaction.response.defer(ephemeral=True)
    position = channel.position
    new_channel = await channel.clone(reason="Nuke: clear all messages")
    await new_channel.edit(position=position)
    await channel.delete(reason="Nuke: clear all messages")
    embed = discord.Embed(
        title="💥 Channel Nuked",
        description="All messages have been deleted.",
        color=discord.Color.red(),
    )
    embed.set_footer(text="Pig Hub")
    await new_channel.send(embed=embed, delete_after=5)


@bot.tree.command(name="slowmode", description="Set slowmode delay in this channel")
@app_commands.describe(seconds="Slowmode in seconds (0 to disable, max 21600)")
@is_admin()
async def slowmode_cmd(
    interaction: discord.Interaction,
    seconds: app_commands.Range[int, 0, 21600],
) -> None:
    await interaction.channel.edit(slowmode_delay=seconds)
    if seconds == 0:
        await interaction.response.send_message("Slowmode **disabled**.", ephemeral=True)
    else:
        await interaction.response.send_message(
            f"Slowmode set to **{seconds}** seconds.", ephemeral=True
        )


@bot.tree.command(name="lock", description="Lock this channel")
@app_commands.describe(reason="Reason for locking the channel")
@is_admin()
async def lock_cmd(
    interaction: discord.Interaction,
    reason: str = "No reason provided",
) -> None:
    overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False
    await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    embed = discord.Embed(
        title="🔒 Channel Locked",
        description=f"This channel has been locked.\n**Reason:** {reason}",
        color=discord.Color.red(),
        timestamp=datetime.datetime.utcnow(),
    )
    embed.set_footer(text="Pig Hub")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="unlock", description="Unlock this channel")
@app_commands.describe(reason="Reason for unlocking the channel")
@is_admin()
async def unlock_cmd(
    interaction: discord.Interaction,
    reason: str = "No reason provided",
) -> None:
    overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None
    await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    embed = discord.Embed(
        title="🔓 Channel Unlocked",
        description=f"This channel has been unlocked.\n**Reason:** {reason}",
        color=discord.Color.green(),
        timestamp=datetime.datetime.utcnow(),
    )
    embed.set_footer(text="Pig Hub")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="userinfo", description="Get detailed information about a user")
@app_commands.describe(user="User to get info about (defaults to yourself)")
@is_admin()
async def userinfo_cmd(
    interaction: discord.Interaction,
    user: discord.Member | None = None,
) -> None:
    target = user or interaction.user
    color = (
        target.color
        if target.color != discord.Color.default()
        else discord.Color.blurple()
    )
    embed = discord.Embed(
        title=str(target),
        color=color,
        timestamp=datetime.datetime.utcnow(),
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="ID", value=str(target.id), inline=True)
    embed.add_field(name="Nickname", value=target.nick or "None", inline=True)
    embed.add_field(name="Bot", value="Yes" if target.bot else "No", inline=True)
    joined = (
        target.joined_at.strftime("%d.%m.%Y %H:%M")
        if target.joined_at
        else "Unknown"
    )
    embed.add_field(name="Joined Server", value=joined, inline=True)
    embed.add_field(
        name="Account Created",
        value=target.created_at.strftime("%d.%m.%Y %H:%M"),
        inline=True,
    )
    embed.add_field(name="Status", value=str(target.status).capitalize(), inline=True)
    roles = [r.mention for r in reversed(target.roles) if r != interaction.guild.default_role]
    roles_str = " ".join(roles[:10]) if roles else "None"
    if len(roles) > 10:
        roles_str += f" (+{len(roles) - 10} more)"
    embed.add_field(name=f"Roles ({len(roles)})", value=roles_str, inline=False)
    warn_count = len(warnings_data.get(str(target.id), []))
    embed.add_field(name="Warnings", value=str(warn_count), inline=True)
    timed_out = (
        target.timed_out_until is not None
        and target.timed_out_until > discord.utils.utcnow()
    )
    embed.add_field(name="Timed Out", value="Yes" if timed_out else "No", inline=True)
    embed.set_footer(text="Pig Hub")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="serverinfo", description="Get information about this server")
@is_admin()
async def serverinfo_cmd(interaction: discord.Interaction) -> None:
    guild = interaction.guild
    embed = discord.Embed(
        title=guild.name,
        color=discord.Color.blurple(),
        timestamp=datetime.datetime.utcnow(),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    if guild.banner:
        embed.set_image(url=guild.banner.url)
    embed.add_field(name="ID", value=str(guild.id), inline=True)
    embed.add_field(
        name="Owner",
        value=guild.owner.mention if guild.owner else "Unknown",
        inline=True,
    )
    embed.add_field(name="Members", value=str(guild.member_count), inline=True)
    embed.add_field(name="Text Channels", value=str(len(guild.text_channels)), inline=True)
    embed.add_field(name="Voice Channels", value=str(len(guild.voice_channels)), inline=True)
    embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
    embed.add_field(name="Emojis", value=str(len(guild.emojis)), inline=True)
    embed.add_field(name="Boosts", value=str(guild.premium_subscription_count), inline=True)
    embed.add_field(name="Boost Level", value=str(guild.premium_tier), inline=True)
    embed.add_field(
        name="Verification",
        value=str(guild.verification_level).capitalize(),
        inline=True,
    )
    embed.add_field(
        name="Created",
        value=guild.created_at.strftime("%d.%m.%Y %H:%M"),
        inline=False,
    )
    embed.set_footer(text="Pig Hub")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="avatar", description="Get a user's avatar")
@app_commands.describe(user="User to get avatar for (defaults to yourself)")
@is_admin()
async def avatar_cmd(
    interaction: discord.Interaction,
    user: discord.Member | None = None,
) -> None:
    target = user or interaction.user
    embed = discord.Embed(
        title=f"{target.name}'s Avatar",
        color=discord.Color.blurple(),
        timestamp=datetime.datetime.utcnow(),
    )
    embed.set_image(url=target.display_avatar.url)
    embed.add_field(
        name="PNG",
        value=f"[Link]({target.display_avatar.replace(format='png').url})",
        inline=True,
    )
    embed.add_field(
        name="JPG",
        value=f"[Link]({target.display_avatar.replace(format='jpg').url})",
        inline=True,
    )
    embed.add_field(
        name="WEBP",
        value=f"[Link]({target.display_avatar.replace(format='webp').url})",
        inline=True,
    )
    embed.set_footer(text="Pig Hub")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="ping", description="Check bot latency")
@is_admin()
async def ping_cmd(interaction: discord.Interaction) -> None:
    latency_ms = round(bot.latency * 1000)
    if latency_ms < 100:
        color = discord.Color.green()
        label = "Excellent"
    elif latency_ms < 200:
        color = discord.Color.yellow()
        label = "Good"
    else:
        color = discord.Color.red()
        label = "High"
    embed = discord.Embed(
        title="Pong!",
        description=f"Latency: **{latency_ms}ms** — {label}",
        color=color,
        timestamp=datetime.datetime.utcnow(),
    )
    embed.set_footer(text="Pig Hub")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="giverole", description="Give a role to a user")
@app_commands.describe(user="Target user", role="Role to assign", reason="Reason")
@is_admin()
async def giverole_cmd(
    interaction: discord.Interaction,
    user: discord.Member,
    role: discord.Role,
    reason: str = "No reason provided",
) -> None:
    await interaction.response.defer(ephemeral=True)
    try:
        await user.add_roles(role, reason=reason)
        await interaction.followup.send(
            f"Gave {role.mention} to {user.mention}.", ephemeral=True
        )
    except discord.Forbidden:
        await interaction.followup.send("Failed to assign role. Check bot role hierarchy.", ephemeral=True)


@bot.tree.command(name="takerole", description="Remove a role from a user")
@app_commands.describe(user="Target user", role="Role to remove", reason="Reason")
@is_admin()
async def takerole_cmd(
    interaction: discord.Interaction,
    user: discord.Member,
    role: discord.Role,
    reason: str = "No reason provided",
) -> None:
    await interaction.response.defer(ephemeral=True)
    try:
        await user.remove_roles(role, reason=reason)
        await interaction.followup.send(
            f"Removed {role.mention} from {user.mention}.", ephemeral=True
        )
    except discord.Forbidden:
        await interaction.followup.send("Failed to remove role. Check bot role hierarchy.", ephemeral=True)


class AnnounceModal(discord.ui.Modal, title="Send Announcement"):
    announce_title = discord.ui.TextInput(label="Title", required=True, max_length=256)
    announce_content = discord.ui.TextInput(
        label="Content",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=4000,
    )
    announce_color = discord.ui.TextInput(
        label="Color (hex, e.g. #5865F2)",
        required=False,
        max_length=7,
        default="#5865F2",
    )
    announce_image = discord.ui.TextInput(
        label="Image URL (optional)",
        required=False,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        color = discord.Color.blurple()
        raw = self.announce_color.value.strip().lstrip("#")
        if raw:
            try:
                color = discord.Color(int(raw, 16))
            except ValueError:
                pass
        embed = discord.Embed(
            title=self.announce_title.value,
            description=self.announce_content.value,
            color=color,
            timestamp=datetime.datetime.utcnow(),
        )
        if self.announce_image.value.strip():
            embed.set_image(url=self.announce_image.value.strip())
        embed.set_footer(text="Pig Hub")
        await interaction.response.send_message("Announcement sent!", ephemeral=True)
        await interaction.channel.send(embed=embed)


@bot.tree.command(name="announce", description="Send an announcement embed to this channel")
@is_admin()
async def announce_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.send_modal(AnnounceModal())


class EmbedModal(discord.ui.Modal, title="Create Embed"):
    embed_title = discord.ui.TextInput(label="Title", required=True, max_length=256)
    embed_description = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=4000,
    )
    embed_color = discord.ui.TextInput(
        label="Color (hex, e.g. #5865F2)",
        required=False,
        max_length=7,
        default="#5865F2",
    )
    embed_footer = discord.ui.TextInput(
        label="Footer text (optional)",
        required=False,
        max_length=2048,
    )
    embed_image = discord.ui.TextInput(
        label="Image URL (optional)",
        required=False,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        color = discord.Color(0x5865F2)
        raw = self.embed_color.value.strip().lstrip("#")
        if raw:
            try:
                color = discord.Color(int(raw, 16))
            except ValueError:
                pass
        embed = discord.Embed(
            title=self.embed_title.value,
            description=self.embed_description.value,
            color=color,
        )
        if self.embed_footer.value.strip():
            embed.set_footer(text=self.embed_footer.value.strip())
        if self.embed_image.value.strip():
            embed.set_image(url=self.embed_image.value.strip())
        await interaction.response.send_message("Embed sent!", ephemeral=True)
        await interaction.channel.send(embed=embed)


@bot.tree.command(name="embed", description="Send a custom embed message to this channel")
@is_admin()
async def embed_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.send_modal(EmbedModal())


@bot.tree.command(name="help", description="Show all available commands")
@is_admin()
async def help_cmd(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="Pig Hub Bot",
        description="All commands are restricted to the server administrator.",
        color=discord.Color.blurple(),
        timestamp=datetime.datetime.utcnow(),
    )
    embed.add_field(
        name="Moderation",
        value=(
            "`/mute` — Timeout a user\n"
            "`/unmute` — Remove timeout\n"
            "`/ban` — Ban a user\n"
            "`/unban` — Unban by ID\n"
            "`/kick` — Kick a user\n"
            "`/warn` — Warn a user\n"
            "`/warnings` — View warnings\n"
            "`/clearwarnings` — Clear warnings\n"
            "`/purge` — Delete N messages\n"
            "`/nuke` — Delete ALL messages\n"
            "`/slowmode` — Set slowmode\n"
            "`/lock` — Lock channel\n"
            "`/unlock` — Unlock channel\n"
            "`/giverole` — Give a role\n"
            "`/takerole` — Remove a role"
        ),
        inline=False,
    )
    embed.add_field(
        name="Info",
        value=(
            "`/userinfo` — User information\n"
            "`/serverinfo` — Server information\n"
            "`/avatar` — Get user avatar\n"
            "`/ping` — Bot latency"
        ),
        inline=False,
    )
    embed.add_field(
        name="Utility",
        value=(
            "`/announce` — Send an announcement\n"
            "`/embed` — Create embed message\n"
            "`/help` — Show this menu"
        ),
        inline=False,
    )
    embed.add_field(
        name="Auto Features",
        value=(
            "Auto-role on join & startup\n"
            "Anti-spam (mute + log)\n"
            "Anti-raid (mass-join detection)\n"
            "Member count channel updater\n"
            "Join / leave logging\n"
            "Key & Script triggers (50 languages)"
        ),
        inline=False,
    )
    embed.set_footer(text="Pig Hub")
    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.run(TOKEN)
