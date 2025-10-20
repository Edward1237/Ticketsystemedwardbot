# bot.py

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import io
import asyncio
from dotenv import load_dotenv

# --- SETTINGS MANAGEMENT (for multi-server) ---
SETTINGS_FILE = 'settings.json'

def load_settings():
    """Loads settings from settings.json"""
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"Warning: {SETTINGS_FILE} is corrupted or empty. Starting with default settings.")
        return {}

def save_settings(settings):
    """Saves settings to settings.json"""
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)

# --- BOT SETUP ---

# Load token from .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    print("Error: DISCORD_TOKEN not found. Please create a .env file with your bot token.")
    exit()

# Define intents
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True
intents.message_content = True

# --- DYNAMIC PREFIX FUNCTION ---
def get_prefix(bot_instance, message):
    """Gets the prefix for the specific guild."""
    if not message.guild:
        return commands.when_mentioned_or("!")(bot_instance, message) # Default '!' in DMs

    settings = bot_instance.settings.get(str(message.guild.id), {})
    prefix = settings.get("prefix", "!") # Default '!'
    return commands.when_mentioned_or(prefix)(bot_instance, message)

# Bot definition
class TicketBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=get_prefix, intents=intents)
        self.settings = load_settings()
        self.persistent_views_added = False
        self.remove_command('help')

    async def setup_hook(self):
        if not self.persistent_views_added:
            self.add_view(TicketPanelView(bot=self))
            self.add_view(TicketCloseView(bot=self))
            self.add_view(AppealReviewView(bot=self))
            self.persistent_views_added = True
        try:
            await self.tree.sync()
            print("Slash commands synced.")
        except Exception as e:
            print(f"Failed to sync slash commands: {e}")

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('Bot is ready and listening for commands.')
        print('------')

    def get_guild_settings(self, guild_id):
        """Gets settings for a specific guild, creating if not found."""
        guild_id_str = str(guild_id)
        if guild_id_str not in self.settings:
            self.settings[guild_id_str] = {
                "panel_channel": None, "ticket_category": None, "archive_category": None,
                "staff_role": None, "escalation_role": None, "appeal_channel": None,
                "prefix": "!", "ticket_counter": 1, "blacklist": {}
            }
            save_settings(self.settings)

        defaults = {
            "blacklist": {}, "appeal_channel": None, "escalation_role": None,
            "prefix": "!", "ticket_counter": 1
        }
        updated = False
        guild_settings = self.settings[guild_id_str]
        for key, default_value in defaults.items():
            if key not in guild_settings:
                guild_settings[key] = default_value
                updated = True
        if updated:
            save_settings(self.settings)
        return guild_settings

    def update_guild_setting(self, guild_id, key, value):
        settings = self.get_guild_settings(guild_id)
        settings[key] = value
        save_settings(self.settings)

bot = TicketBot()

# --- GLOBAL CHECK TO IGNORE DMS ---
@bot.check
async def globally_ignore_dms(ctx):
    return ctx.guild is not None

# --- HELPER FUNCTIONS ---

def create_embed(title: str, description: str, color: discord.Color) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)

async def send_embed_response(ctx_or_interaction, title: str, description: str, color: discord.Color, ephemeral: bool = True):
    embed = create_embed(title, description, color)
    try:
        if isinstance(ctx_or_interaction, discord.Interaction):
            if ctx_or_interaction.response.is_done():
                await ctx_or_interaction.followup.send(embed=embed, ephemeral=ephemeral)
            else:
                await ctx_or_interaction.response.send_message(embed=embed, ephemeral=ephemeral)
        else:
            await ctx_or_interaction.send(embed=embed, ephemeral=ephemeral)
    except discord.errors.InteractionResponded:
         await ctx_or_interaction.followup.send(embed=embed, ephemeral=ephemeral)
    except Exception as e:
        print(f"Error sending embed response: {e}")

# --- ERROR HANDLING ---
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await send_embed_response(ctx, "Permission Denied", f"Sorry {ctx.author.mention}, you don't have permission.", discord.Color.red())
    elif isinstance(error, commands.CheckFailure): pass # Handled by checks
    elif isinstance(error, commands.ChannelNotFound):
        await send_embed_response(ctx, "Error", "Channel not found.", discord.Color.red())
    elif isinstance(error, commands.RoleNotFound):
        await send_embed_response(ctx, "Error", "Role not found.", discord.Color.red())
    elif isinstance(error, commands.MissingRequiredArgument):
        await send_embed_response(ctx, "Error", f"Missing argument: `{error.param.name}`", discord.Color.orange())
    elif isinstance(error, commands.CommandNotFound): pass # Ignore unknown commands
    elif isinstance(error, commands.BadArgument):
         await send_embed_response(ctx, "Error", f"Invalid argument provided. Please check the command usage.", discord.Color.orange())
    else:
        print(f"Unhandled error in command '{ctx.command}': {error}")
        try:
            if ctx.guild: await send_embed_response(ctx, "Error", "An unexpected error occurred.", discord.Color.dark_red())
        except Exception as e: print(f"Failed to send error message: {e}")

# --- HELPER FUNCTIONS ---
# (check_setup remains the same)
async def check_setup(ctx_or_interaction):
    """Checks if the bot is fully set up for the guild."""
    settings = bot.get_guild_settings(ctx_or_interaction.guild.id)
    if not all([settings['panel_channel'], settings['ticket_category'], settings['archive_category'], settings['staff_role']]):
        embed = discord.Embed(
            title="Bot Not Fully Setup!",
            description="An admin needs to run all setup commands first:",
            color=discord.Color.red()
        )
        embed.add_field(name="`/set_panel_channel`", value="Sets the channel for the ticket panel.", inline=False)
        embed.add_field(name="`/set_ticket_category`", value="Sets the category for new tickets.", inline=False)
        embed.add_field(name="`/set_archive_category`", value="Sets the category for closed tickets.", inline=False)
        embed.add_field(name="`/set_staff_role`", value="Sets the role to ping for new tickets.", inline=False)

        if isinstance(ctx_or_interaction, discord.Interaction):
            # Check if already responded
            if not ctx_or_interaction.response.is_done():
                 await ctx_or_interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                 await ctx_or_interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await ctx_or_interaction.send(embed=embed, ephemeral=True)
        return False
    return True

# --- NEW: Helper to count user's open tickets ---
def count_user_tickets(guild: discord.Guild, user_id: int, category_id: int, ticket_type: str = None) -> int:
    """Counts open tickets for a user, optionally filtering by type."""
    category = guild.get_channel(category_id)
    if not category or not isinstance(category, discord.CategoryChannel):
        return 0

    count = 0
    user_id_str = str(user_id)
    for channel in category.text_channels:
        if channel.topic and f"ticket-user-{user_id_str}" in channel.topic:
            if ticket_type:
                # Check if the specific type is in the topic
                if f"type-{ticket_type}" in channel.topic:
                    count += 1
            else:
                # Count all tickets if no type specified
                count += 1
    return count

# --- UPDATED: create_ticket_channel adds type to topic ---
async def create_ticket_channel(interaction: discord.Interaction, ticket_type_name: str, settings: dict):
    """Creates a new ticket channel."""
    guild = interaction.guild
    user = interaction.user

    staff_role = guild.get_role(settings['staff_role'])
    if not staff_role:
        await send_embed_response(interaction, "Setup Error", "Staff Role not found.", discord.Color.red())
        return None, None

    category = guild.get_channel(settings['ticket_category'])
    if not category:
        await send_embed_response(interaction, "Setup Error", "Ticket Category not found.", discord.Color.red())
        return None, None

    # Check for existing ticket (general check, specific type check happens in button)
    # This remains as a fallback, primary limit check is done before calling this func.
    if count_user_tickets(guild, user.id, category.id) > 0: # Check if ANY ticket exists
        # Find the existing channel to mention it
        existing_channel = None
        for channel in category.text_channels:
             if channel.topic and f"ticket-user-{user.id}" in channel.topic:
                 existing_channel = channel
                 break
        if existing_channel:
            await send_embed_response(interaction, "Ticket Exists", f"You already have an open ticket: {existing_channel.mention}", discord.Color.orange())
            return None, None
        # If somehow count > 0 but no channel found, proceed cautiously

    ticket_num = settings['ticket_counter']
    bot.update_guild_setting(guild.id, "ticket_counter", ticket_num + 1)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
        staff_role: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True)
    }

    try:
        safe_user_name = "".join(c for c in user.name if c.isalnum() or c in ('-', '_')).lower() or "user"
        channel_name = f"{ticket_type_name}-{ticket_num}-{safe_user_name}"[:100]
        # --- ADD TICKET TYPE TO TOPIC ---
        topic = f"ticket-user-{user.id} type-{ticket_type_name}"
        # --- END CHANGE ---
        new_channel = await category.create_text_channel(name=channel_name, overwrites=overwrites, topic=topic)
    except discord.Forbidden:
        await send_embed_response(interaction, "Permissions Error", "I lack permissions to create channels.", discord.Color.red())
        return None, None
    except Exception as e:
        await send_embed_response(interaction, "Error", f"Error creating channel: {e}", discord.Color.red())
        return None, None

    return new_channel, staff_role


async def generate_transcript(channel: discord.TextChannel):
    # (generate_transcript remains the same)
    messages = []
    async for msg in channel.history(limit=None, oldest_first=True):
        timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')
        if not msg.author.bot:
            messages.append(f"[{timestamp}] {msg.author.display_name} ({msg.author.id}): {msg.content}")
        if msg.attachments:
            for att in msg.attachments:
                messages.append(f"[{timestamp}] [Attachment from {msg.author.display_name}: {att.url}]")

    transcript_content = "\n".join(messages)
    if not transcript_content:
        transcript_content = "No messages were sent in this ticket."

    return io.BytesIO(transcript_content.encode('utf-8'))

# --- APPEAL/MODAL CLASSES ---
# (AppealReasonModal, AppealReviewView, ConfirmAppealView, AppealStartView remain the same)
class AppealReasonModal(discord.ui.Modal):
    def __init__(self, bot: TicketBot, action: str, original_message: discord.Message, guild: discord.Guild, appealing_user_id: int):
        super().__init__(title=f"Appeal {action} Reason")

        self.bot = bot
        self.action = action # "Approve" or "Reject"
        self.original_message = original_message
        self.guild = guild
        self.appealing_user_id = appealing_user_id

        self.reason_input = discord.ui.TextInput(
            label="Reason", style=discord.TextStyle.paragraph,
            placeholder=f"Enter the reason for {action.lower()}ing this appeal...",
            required=True, min_length=3
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        staff_member = interaction.user
        reason = self.reason_input.value
        try: appealing_user = await self.bot.fetch_user(self.appealing_user_id)
        except discord.NotFound:
            await interaction.followup.send(embed=create_embed("Error", "Could not find user.", discord.Color.red()))
            return

        if not self.original_message.embeds:
            await interaction.followup.send(embed=create_embed("Error", "Original embed missing.", discord.Color.red()))
            return
        original_embed = self.original_message.embeds[0]
        new_embed = original_embed.copy()

        if self.action == "Approve":
            title = "✅ Appeal Approved"; color = discord.Color.green()
            try:
                dm_embed = create_embed(title, f"Appeal for **{self.guild.name}** approved.\nReason:\n```{reason}```", color)
                await appealing_user.send(embed=dm_embed)
            except discord.Forbidden: pass
            settings = self.bot.get_guild_settings(self.guild.id)
            user_id_str = str(self.appealing_user_id)
            if user_id_str in settings["blacklist"]:
                del settings["blacklist"][user_id_str]; save_settings(self.bot.settings)
        else: # Reject
            title = "❌ Appeal Rejected"; color = discord.Color.red()
            try:
                dm_embed = create_embed(title, f"Appeal for **{self.guild.name}** rejected.\nReason:\n```{reason}```", color)
                await appealing_user.send(embed=dm_embed)
            except discord.Forbidden: pass

        new_embed.title = f"[{self.action.upper()}D] Blacklist Appeal"; new_embed.color = color
        new_embed.add_field(name=f"{title} by {staff_member.display_name}", value=f"```{reason}```", inline=False)
        await self.original_message.edit(embed=new_embed, view=None)
        await interaction.followup.send(embed=create_embed("Success", f"Appeal {self.action.lower()}d.", color))

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"Error in AppealReasonModal: {error}")
        await interaction.followup.send("Error processing appeal.", ephemeral=True)

class AppealReviewView(discord.ui.View):
    def __init__(self, bot: TicketBot = None): super().__init__(timeout=None); self.bot = bot
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not self.bot: self.bot = interaction.client
        settings = self.bot.get_guild_settings(interaction.guild.id)
        staff_role_id = settings.get('staff_role')
        if not staff_role_id: await send_embed_response(interaction, "Error", "Staff role not configured.", discord.Color.red()); return False
        staff_role = interaction.guild.get_role(staff_role_id); is_admin = interaction.user.guild_permissions.administrator
        if (staff_role and staff_role in interaction.user.roles) or is_admin: return True
        else: await send_embed_response(interaction, "Permission Denied", "Staff only.", discord.Color.red()); return False
    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅", custom_id="appeal:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.message.embeds: await send_embed_response(interaction, "Error", "Embed missing.", discord.Color.red()); return
        embed = interaction.message.embeds[0]
        if not embed.footer or "User ID:" not in embed.footer.text: await send_embed_response(interaction, "Error", "User ID missing.", discord.Color.red()); return
        try: user_id = int(embed.footer.text.split(": ")[1])
        except (IndexError, ValueError): await send_embed_response(interaction, "Error", "Cannot parse User ID.", discord.Color.red()); return
        modal = AppealReasonModal(bot=self.bot, action="Approve", original_message=interaction.message, guild=interaction.guild, appealing_user_id=user_id)
        await interaction.response.send_modal(modal)
    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌", custom_id="appeal:reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.message.embeds: await send_embed_response(interaction, "Error", "Embed missing.", discord.Color.red()); return
        embed = interaction.message.embeds[0]
        if not embed.footer or "User ID:" not in embed.footer.text: await send_embed_response(interaction, "Error", "User ID missing.", discord.Color.red()); return
        try: user_id = int(embed.footer.text.split(": ")[1])
        except (IndexError, ValueError): await send_embed_response(interaction, "Error", "Cannot parse User ID.", discord.Color.red()); return
        modal = AppealReasonModal(bot=self.bot, action="Reject", original_message=interaction.message, guild=interaction.guild, appealing_user_id=user_id)
        await interaction.response.send_modal(modal)

class ConfirmAppealView(discord.ui.View):
    def __init__(self, bot: TicketBot, answers: dict, guild: discord.Guild, appeal_channel: discord.TextChannel, messages_to_delete: list):
        super().__init__(timeout=600); self.bot = bot; self.answers = answers; self.guild = guild
        self.appeal_channel = appeal_channel; self.messages_to_delete = messages_to_delete; self.message = None
    async def cleanup(self, interaction: discord.Interaction = None):
        self.stop()
        for msg in self.messages_to_delete:
            try: await msg.delete()
            except (discord.NotFound, discord.Forbidden): pass
        try:
            if interaction: await interaction.message.delete()
            elif self.message: await self.message.delete()
        except: pass
    @discord.ui.button(label="Submit Appeal", style=discord.ButtonStyle.success, emoji="✅")
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        embed = create_embed("New Blacklist Appeal", f"**User:** {interaction.user.mention} (`{interaction.user.id}`)\n**Server:** {self.guild.name}", discord.Color.gold())
        embed.add_field(name="1. Unfairly Blacklisted?", value=f"```{self.answers['q1']}```", inline=False)
        embed.add_field(name="2. Why Unblacklist?", value=f"```{self.answers['q2']}```", inline=False)
        embed.add_field(name="3. Proof", value=self.answers['proof'], inline=False)
        embed.set_footer(text=f"User ID: {interaction.user.id}")
        view_to_send = AppealReviewView(bot=self.bot)
        try:
            await self.appeal_channel.send(embed=embed, view=view_to_send)
            await interaction.followup.send(embed=create_embed("✅ Appeal Submitted", "Sent to staff.", discord.Color.green()))
        except discord.Forbidden: await interaction.followup.send(embed=create_embed("Error", "Cannot submit appeal.", discord.Color.red()))
        except Exception as e: print(f"Error submitting appeal: {e}"); await interaction.followup.send(embed=create_embed("Error", "Unexpected error.", discord.Color.red()))
        await self.cleanup(interaction)
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await interaction.followup.send(embed=create_embed("Appeal Cancelled", "", discord.Color.red()))
        await self.cleanup(interaction)
    async def on_timeout(self):
        for item in self.children: item.disabled = True
        try:
            if self.message: await self.message.edit(embed=create_embed("Appeal Timed Out", "", discord.Color.red()), view=self)
        except Exception as e: print(f"Failed edit on timeout: {e}")
        await self.cleanup()

class AppealStartView(discord.ui.View):
    def __init__(self, bot: TicketBot, guild: discord.Guild, reason: str):
        super().__init__(timeout=1800); self.bot = bot; self.guild = guild; self.reason = reason; self.message = None
    async def ask_question(self, channel, user, embed, min_length=0, check_proof=False, timeout=600.0):
        bot_msgs = [await channel.send(embed=embed)]
        while True:
            try: msg = await self.bot.wait_for('message', check=lambda m: m.author == user and m.channel == channel, timeout=timeout)
            except asyncio.TimeoutError: await channel.send(embed=create_embed("Timed Out", "Appeal cancelled.", discord.Color.red())); return bot_msgs, None
            if check_proof: return bot_msgs, msg
            if len(msg.content) < min_length: bot_msgs.append(await channel.send(embed=create_embed("Too Short", f"Min {min_length} chars.", discord.Color.orange()))); continue
            return bot_msgs, msg
    @discord.ui.button(label="Start Appeal", style=discord.ButtonStyle.primary, emoji="📜")
    async def start_appeal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        for item in self.children: item.disabled = True
        await interaction.edit_original_response(view=self)
        channel = interaction.channel; user = interaction.user
        messages_to_delete = [interaction.message]; answers = {}
        settings = self.bot.get_guild_settings(self.guild.id); appeal_channel_id = settings.get("appeal_channel")
        if not appeal_channel_id: await channel.send(embed=create_embed("Error", f"Appeal system for **{self.guild.name}** not configured.", discord.Color.red())); return
        appeal_channel = self.guild.get_channel(appeal_channel_id)
        if not appeal_channel: await channel.send(embed=create_embed("Error", f"Appeal system for **{self.guild.name}** broken.", discord.Color.red())); return

        q1_embed = create_embed("Appeal: Q1/3", "Why unfairly blacklisted?", discord.Color.blue()).set_footer(text="10 min, min 3 chars.")
        bot_msgs, answer1_msg = await self.ask_question(channel, user, q1_embed, 3); messages_to_delete.extend(bot_msgs)
        if not answer1_msg: return; messages_to_delete.append(answer1_msg); answers['q1'] = answer1_msg.content

        q2_embed = create_embed("Appeal: Q2/3", "Why unblacklist?", discord.Color.blue()).set_footer(text="10 min, min 3 chars.")
        bot_msgs, answer2_msg = await self.ask_question(channel, user, q2_embed, 3); messages_to_delete.extend(bot_msgs)
        if not answer2_msg: return; messages_to_delete.append(answer2_msg); answers['q2'] = answer2_msg.content

        q3_embed = create_embed("Appeal: Q3/3", "Provide proof (screenshots, etc.) or type `N/A`.", discord.Color.blue()).set_footer(text="10 min.")
        bot_msgs, answer3_msg = await self.ask_question(channel, user, q3_embed, 0, check_proof=True); messages_to_delete.extend(bot_msgs)
        if not answer3_msg: return; messages_to_delete.append(answer3_msg)
        proof_content = answer3_msg.content if answer3_msg.content else "N/A"
        if answer3_msg.attachments: proof_urls = "\n".join([att.url for att in answer3_msg.attachments]); proof_content = f"{proof_content}\n{proof_urls}" if proof_content != "N/A" else proof_urls
        answers['proof'] = proof_content

        summary_embed = create_embed("Confirm Appeal", "Review answers. Submit?", discord.Color.green())
        summary_embed.add_field(name="1. Unfairly?", value=f"```{answers['q1']}```", inline=False)
        summary_embed.add_field(name="2. Why Unblacklist?", value=f"```{answers['q2']}```", inline=False)
        summary_embed.add_field(name="3. Proof", value=answers['proof'], inline=False)
        confirm_view = ConfirmAppealView(self.bot, answers, self.guild, appeal_channel, messages_to_delete)
        confirm_view.message = await channel.send(embed=summary_embed, view=confirm_view)
    async def on_timeout(self):
        for item in self.children: item.disabled = True
        try:
             if self.message: await self.message.edit(view=self)
        except Exception as e: print(f"Failed edit appeal start on timeout: {e}")

# --- TICKET PANEL VIEW ---
class TicketPanelView(discord.ui.View):
    def __init__(self, bot: TicketBot = None): super().__init__(timeout=None); self.bot = bot
    # (send_appeal_dm remains the same)
    async def send_appeal_dm(self, user: discord.Member, guild: discord.Guild, reason: str):
        embed = create_embed(f"Blacklisted on {guild.name}", f"Reason:\n```{reason}```\nSubmit an appeal?", discord.Color.red())
        view = AppealStartView(bot=self.bot, guild=guild, reason=reason)
        try: view.message = await user.send(embed=embed, view=view)
        except discord.Forbidden: pass
        except Exception as e: print(f"Failed to send appeal DM: {e}")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not self.bot: self.bot = interaction.client
        settings = self.bot.get_guild_settings(interaction.guild.id)
        # --- BLACKLIST CHECK ---
        blacklist = settings.get("blacklist", {}); user_id_str = str(interaction.user.id)
        if user_id_str in blacklist:
            reason = blacklist[user_id_str]
            await send_embed_response(interaction, "Blacklisted", "", discord.Color.red())
            await self.send_appeal_dm(interaction.user, interaction.guild, reason)
            return False
        # --- Check setup ---
        if not all([settings['panel_channel'], settings['ticket_category'], settings['archive_category'], settings['staff_role']]):
            await send_embed_response(interaction, "System Offline", "Not configured.", discord.Color.red())
            return False
        return True

    # --- UPDATED BUTTONS WITH LIMIT CHECKS ---
    @discord.ui.button(label="Standard Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="panel:standard")
    async def standard_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "ticket"
        LIMIT = 3
        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, settings['ticket_category'], TICKET_TYPE)
        if current_tickets >= LIMIT:
            await send_embed_response(interaction, "Limit Reached", f"You can only have {LIMIT} open standard tickets at a time.", discord.Color.orange())
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if channel:
            await send_embed_response(interaction, "Ticket Created", f"{channel.mention}", discord.Color.green())
            embed = discord.Embed(title="🎫 Standard Ticket", description=f"Welcome, {interaction.user.mention}!\nPlease describe your issue. {staff_role.mention} will assist.", color=discord.Color.blue())
            await channel.send(embed=embed, content=f"{interaction.user.mention} {staff_role.mention}", view=TicketCloseView(bot=self.bot))

    @discord.ui.button(label="Tryout", style=discord.ButtonStyle.success, emoji="⚔️", custom_id="panel:tryout")
    async def tryout_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "tryout"
        LIMIT = 1
        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, settings['ticket_category'], TICKET_TYPE)
        if current_tickets >= LIMIT:
            await send_embed_response(interaction, "Limit Reached", f"You can only have {LIMIT} open tryout ticket at a time.", discord.Color.orange())
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if not channel: return

        await send_embed_response(interaction, "Ticket Created", f"{channel.mention}", discord.Color.green())
        try: await channel.send(f"{interaction.user.mention} {staff_role.mention}", delete_after=1)
        except Exception: pass

        try: # --- Tryout Application Logic ---
            username_embed = create_embed("⚔️ Tryout: Step 1/2", "Reply with Roblox Username.", discord.Color.green()).set_footer(text="5 min.")
            bot_msg_1 = await channel.send(embed=username_embed)
            def check_username(m): return m.channel == channel and m.author == interaction.user
            username_msg = await self.bot.wait_for('message', check=check_username, timeout=300.0)
            roblox_username = username_msg.content

            stats_embed = create_embed("⚔️ Tryout: Step 2/2", f"`{roblox_username}`\nSend stats screenshot.", discord.Color.green()).set_footer(text="5 min, must be image.")
            bot_msg_2 = await channel.send(embed=stats_embed)
            def check_stats(m): return m.channel == channel and m.author == interaction.user and m.attachments and m.attachments[0].content_type and m.attachments[0].content_type.startswith('image')
            stats_msg = await self.bot.wait_for('message', check=check_stats, timeout=300.0)

            stats_screenshot_url = stats_msg.attachments[0].url if stats_msg.attachments else None
            print(f"Stats URL: {stats_screenshot_url}") # Debugging

            # --- NO MESSAGE DELETION ---

            success_embed = create_embed("✅ Tryout Complete!", f"{interaction.user.mention}, {staff_role.mention} will review.", discord.Color.brand_green())
            success_embed.add_field(name="Roblox Username", value=roblox_username, inline=False)
            if stats_screenshot_url:
                try: success_embed.set_image(url=stats_screenshot_url)
                except Exception as e: print(f"Error setting image: {e}"); success_embed.add_field(name="Image Error", value="Could not embed.", inline=False)
            else: success_embed.add_field(name="Stats Image", value="Not provided/found.", inline=False)

            await channel.send(embed=success_embed, view=TicketCloseView(bot=self.bot))

        except asyncio.TimeoutError:
            timeout_embed = create_embed("Ticket Closed", "Auto-closed: Inactivity.", discord.Color.red())
            try:
                await channel.send(embed=timeout_embed); await asyncio.sleep(10)
                await channel.delete(reason="Tryout timeout")
            except (discord.NotFound, discord.Forbidden): pass
            except Exception as e: print(f"Error during timeout cleanup: {e}")
        except Exception as e:
            print(f"Error in tryout ({channel.id}): {e}")
            try: await channel.send(embed=create_embed("Error", "Unexpected error.", discord.Color.red()))
            except Exception: pass

    @discord.ui.button(label="Report a User", style=discord.ButtonStyle.danger, emoji="🚨", custom_id="panel:report")
    async def report_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = self.bot.get_guild_settings(interaction.guild.id)
        TICKET_TYPE = "report"
        LIMIT = 10
        current_tickets = count_user_tickets(interaction.guild, interaction.user.id, settings['ticket_category'], TICKET_TYPE)
        if current_tickets >= LIMIT:
            await send_embed_response(interaction, "Limit Reached", f"You can only have {LIMIT} open report tickets at a time.", discord.Color.orange())
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        channel, staff_role = await create_ticket_channel(interaction, TICKET_TYPE, settings)
        if channel:
            await send_embed_response(interaction, "Ticket Created", f"{channel.mention}", discord.Color.green())
            embed = discord.Embed(title="🚨 User Report", description=f"{interaction.user.mention}, provide user, reason, proof. {staff_role.mention} will assist.", color=discord.Color.red())
            await channel.send(embed=embed, content=f"{interaction.user.mention} {staff_role.mention}", view=TicketCloseView(bot=self.bot))

# --- NEW CLOSE REASON MODAL ---
class CloseReasonModal(discord.ui.Modal, title="Close Ticket Reason"):
    reason_input = discord.ui.TextInput(
        label="Reason for Closing",
        style=discord.TextStyle.paragraph,
        placeholder="Enter the reason for closing this ticket...",
        required=True,
        min_length=3
    )

    def __init__(self, bot_instance: TicketBot, target_channel: discord.TextChannel, closer: discord.Member):
        super().__init__()
        self.bot = bot_instance
        self.target_channel = target_channel
        self.closer = closer

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        reason = self.reason_input.value
        # Find the actual TicketCloseView logic to call it
        # We need to pass the reason along
        view = TicketCloseView(bot=self.bot) # Instantiate to access the method
        await view.close_ticket_logic(self.target_channel, self.closer, reason)
        await interaction.followup.send("Closing ticket...", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"Error in CloseReasonModal: {error}")
        await interaction.followup.send("An error occurred.", ephemeral=True)

# --- UPDATED TICKET CLOSE VIEW ---
class TicketCloseView(discord.ui.View):
    def __init__(self, bot: TicketBot = None): super().__init__(timeout=None); self.bot = bot

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket:close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Opens modal to ask for close reason."""
        if not self.bot: self.bot = interaction.client
        # --- OPEN MODAL INSTEAD OF CLOSING DIRECTLY ---
        modal = CloseReasonModal(bot_instance=self.bot, target_channel=interaction.channel, closer=interaction.user)
        await interaction.response.send_modal(modal)
        # --- END CHANGE ---

    @discord.ui.button(label="Delete Ticket", style=discord.ButtonStyle.secondary, emoji="🗑️", custom_id="ticket:delete")
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # (delete_ticket logic remains the same)
        if not self.bot: self.bot = interaction.client
        settings = self.bot.get_guild_settings(interaction.guild.id); staff_role_id = settings.get('staff_role')
        if not staff_role_id: await send_embed_response(interaction, "Error", "Staff role not configured.", discord.Color.red()); return
        staff_role = interaction.guild.get_role(staff_role_id)
        if not staff_role: await send_embed_response(interaction, "Error", "Staff role not found.", discord.Color.red()); return
        is_staff = staff_role in interaction.user.roles; is_admin = interaction.user.guild_permissions.administrator
        if not is_staff and not is_admin: await send_embed_response(interaction, "Permission Denied", "", discord.Color.red()); return
        await interaction.response.defer()
        embed = create_embed("🗑️ Ticket Deletion", f"Marked by {interaction.user.mention}.\n**Deleting in 10s.**", discord.Color.dark_red())
        await interaction.followup.send(embed=embed, ephemeral=False)
        await asyncio.sleep(10)
        try: await interaction.channel.delete(reason=f"Deleted by {interaction.user.name}")
        except discord.NotFound: pass
        except discord.Forbidden:
             try: await interaction.followup.send(embed=create_embed("Error", "Lacking delete permissions.", discord.Color.red()), ephemeral=True)
             except Exception: pass
        except Exception as e: print(f"Error deleting ticket: {e}")

    # --- UPDATED close_ticket_logic TO ACCEPT REASON ---
    async def close_ticket_logic(self, channel: discord.TextChannel, user: discord.Member, reason: str = "No reason provided"):
        """The logic to close and archive a ticket."""
        guild = channel.guild
        settings = self.bot.get_guild_settings(guild.id)
        archive_category = guild.get_channel(settings['archive_category'])

        if not archive_category:
            await channel.send(embed=create_embed("Error", "Archive category not found.", discord.Color.red()))
            return

        transcript_file = await generate_transcript(channel)
        embed = discord.Embed(
            title="Ticket Closed",
            description=f"Closed by: {user.mention}\n**Reason:**\n```{reason}```", # Added reason
            color=discord.Color.orange()
        )
        transcript_file.seek(0)
        try:
            await channel.send(
                embed=embed,
                file=discord.File(transcript_file, filename=f"{channel.name}-transcript.txt")
            )
        except discord.HTTPException as e:
            if e.code == 40005: await channel.send(embed=create_embed("Transcript Too Large", "", discord.Color.orange()))
            else: await channel.send(embed=create_embed("Error", f"Could not upload transcript: {e}", discord.Color.red()))
        except Exception as e:
             await channel.send(embed=create_embed("Error", f"Error sending transcript: {e}", discord.Color.red()))

        await asyncio.sleep(5)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True)
        }
        staff_role = guild.get_role(settings['staff_role'])
        if staff_role: overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=False)

        try:
            closed_name = f"closed-{channel.name[:80]}-{channel.id}"[:100]
            await channel.edit(
                name=closed_name, category=archive_category, overwrites=overwrites,
                reason=f"Ticket closed by {user.name}. Reason: {reason}" # Added reason to audit log
            )
            async for msg in channel.history(limit=5):
                if msg.author == self.bot.user and msg.embeds:
                    try: await msg.edit(view=None)
                    except Exception: pass
                    break
            await channel.send(embed=create_embed("Archived", f"Moved to {archive_category.name}.", discord.Color.greyple()))
        except discord.Forbidden: await channel.send(embed=create_embed("Error", "Lacking permissions.", discord.Color.red()))
        except Exception as e: await channel.send(embed=create_embed("Error", f"Archival error: {e}", discord.Color.red()))


# --- SETUP COMMANDS ---
# (Setup commands remain largely the same, only descriptions updated slightly if needed)
@bot.hybrid_command(name="set_panel_channel", description="Sets channel for the ticket panel.")
@commands.has_permissions(administrator=True)
@app_commands.describe(channel="Channel for the ticket panel.")
async def set_panel_channel(ctx: commands.Context, channel: discord.TextChannel):
    bot.update_guild_setting(ctx.guild.id, "panel_channel", channel.id)
    await send_embed_response(ctx, "Setup", f"Panel channel: {channel.mention}", discord.Color.green())

@bot.hybrid_command(name="set_ticket_category", description="Sets category for new tickets.")
@commands.has_permissions(administrator=True)
@app_commands.describe(category="Category for new tickets.")
async def set_ticket_category(ctx: commands.Context, category: discord.CategoryChannel):
    bot.update_guild_setting(ctx.guild.id, "ticket_category", category.id)
    await send_embed_response(ctx, "Setup", f"Ticket category: `{category.name}`", discord.Color.green())

@bot.hybrid_command(name="set_archive_category", description="Sets category for closed tickets.")
@commands.has_permissions(administrator=True)
@app_commands.describe(category="Category for archived tickets.")
async def set_archive_category(ctx: commands.Context, category: discord.CategoryChannel):
    bot.update_guild_setting(ctx.guild.id, "archive_category", category.id)
    await send_embed_response(ctx, "Setup", f"Archive category: `{category.name}`", discord.Color.green())

@bot.hybrid_command(name="set_staff_role", description="Sets the main staff role.")
@commands.has_permissions(administrator=True)
@app_commands.describe(role="Your staff/support role.")
async def set_staff_role(ctx: commands.Context, role: discord.Role):
    bot.update_guild_setting(ctx.guild.id, "staff_role", role.id)
    await send_embed_response(ctx, "Setup", f"Staff role: {role.mention}", discord.Color.green())

@bot.hybrid_command(name="set_escalation_role", description="Sets role for !escalate.")
@commands.has_permissions(administrator=True)
@app_commands.describe(role="Senior staff/manager role.")
async def set_escalation_role(ctx: commands.Context, role: discord.Role):
    bot.update_guild_setting(ctx.guild.id, "escalation_role", role.id)
    await send_embed_response(ctx, "Setup", f"Escalation role: {role.mention}", discord.Color.green())

@bot.hybrid_command(name="set_prefix", description="Sets bot prefix for this server.")
@commands.has_permissions(administrator=True)
@app_commands.describe(prefix="New prefix (max 5 chars).")
async def set_prefix(ctx: commands.Context, prefix: str):
    if len(prefix) > 5: await send_embed_response(ctx, "Error", "Prefix max 5 chars.", discord.Color.red()); return
    bot.update_guild_setting(ctx.guild.id, "prefix", prefix)
    await send_embed_response(ctx, "Setup", f"Prefix: `{prefix}`", discord.Color.green())

@bot.hybrid_command(name="set_appeal_channel", description="Sets channel for blacklist appeals.")
@commands.has_permissions(administrator=True)
@app_commands.describe(channel="Channel for appeal reviews.")
async def set_appeal_channel(ctx: commands.Context, channel: discord.TextChannel):
    bot.update_guild_setting(ctx.guild.id, "appeal_channel", channel.id)
    await send_embed_response(ctx, "Setup", f"Appeal channel: {channel.mention}", discord.Color.green())


# --- PANEL CREATION COMMAND ---
@bot.hybrid_command(name="create_panel", description="Sends the ticket panel.")
@commands.has_permissions(administrator=True)
async def create_panel(ctx: commands.Context):
    if not await check_setup(ctx): return
    settings = bot.get_guild_settings(ctx.guild.id)
    panel_channel = bot.get_channel(settings['panel_channel'])
    if not panel_channel: await send_embed_response(ctx, "Error", "Panel channel not set.", discord.Color.red()); return
    embed = discord.Embed(title="Support & Tryouts", description="Select an option below.", color=0x2b2d31)
    if ctx.guild.icon: embed.set_thumbnail(url=ctx.guild.icon.url)
    embed.add_field(name="🎫 Standard Ticket", value="General help.", inline=False)
    embed.add_field(name="⚔️ Tryout", value="Apply to join.", inline=False)
    embed.add_field(name="🚨 Report a User", value="Report rule breakers.", inline=False)
    embed.set_footer(text=f"{ctx.guild.name}")
    try:
        await panel_channel.send(embed=embed, view=TicketPanelView(bot=bot))
        await send_embed_response(ctx, "Panel Created", f"Sent to {panel_channel.mention}", discord.Color.green())
    except discord.Forbidden: await send_embed_response(ctx, "Error", f"No permission in {panel_channel.mention}.", discord.Color.red())

# --- TICKET MANAGEMENT COMMANDS ---

# --- STAFF CHECKERS ---
def is_staff():
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.guild is None: return False
        settings = bot.get_guild_settings(ctx.guild.id); staff_role_id = settings.get('staff_role')
        if not staff_role_id: await send_embed_response(ctx, "Error", "Staff role not set.", discord.Color.red()); return False
        staff_role = ctx.guild.get_role(staff_role_id)
        if not isinstance(ctx.author, discord.Member): return False # Should not happen in guild commands
        if (staff_role and staff_role in ctx.author.roles) or ctx.author.guild_permissions.administrator: return True
        else: await send_embed_response(ctx, "Permission Denied", "Staff only.", discord.Color.red()); return False
    return commands.check(predicate)

async def is_staff_interaction(interaction: discord.Interaction) -> bool:
    settings = bot.get_guild_settings(interaction.guild.id); staff_role_id = settings.get('staff_role')
    if not staff_role_id: await send_embed_response(interaction, "Error", "Staff role not set.", discord.Color.red()); return False
    staff_role = interaction.guild.get_role(staff_role_id); is_admin = interaction.user.guild_permissions.administrator
    if (staff_role and staff_role in interaction.user.roles) or is_admin: return True
    else: await send_embed_response(interaction, "Permission Denied", "Staff only.", discord.Color.red()); return False

# --- TICKET CHANNEL CHECK ---
def in_ticket_channel():
    async def predicate(ctx: commands.Context) -> bool:
        settings = bot.get_guild_settings(ctx.guild.id)
        # Also allow in archive category for purging maybe? For now, only open.
        if ctx.channel.category_id == settings['ticket_category']: return True
        await send_embed_response(ctx, "Error", "Command only valid in open ticket channels.", discord.Color.red()); return False
    return commands.check(predicate)

# --- HELP COMMAND ---
@bot.command(name="help")
@commands.guild_only()
@is_staff()
async def help_command(ctx: commands.Context):
    settings = bot.get_guild_settings(ctx.guild.id); prefix = settings.get("prefix", "!")
    embed = discord.Embed(title="🛠️ Staff Help", description=f"Prefix: `{prefix}`", color=discord.Color.blue())
    embed.add_field(name="Setup (Admin)", value="`/set_panel_channel`\n`/set_ticket_category`\n`/set_archive_category`\n`/set_staff_role`\n`/set_escalation_role`\n`/set_appeal_channel`\n`/set_prefix`\n`/create_panel`", inline=False)
    embed.add_field(name="Tickets (Staff)", value=f"`{prefix}close`\n`{prefix}add @user`\n`{prefix}remove @user`\n`{prefix}rename <name>`\n`{prefix}claim`\n`{prefix}unclaim`\n`{prefix}escalate`\n`{prefix}purge <amount>` (NEW)\n`{prefix}help`", inline=False)
    embed.add_field(name="Moderation (Admin)", value=f"`{prefix}blacklist @user <reason>`\n`{prefix}unblacklist @user`\n`/announce <#channel> <message>` (NEW)\n`/ticket_stats`", inline=False)
    embed.set_footer(text="Staff can also use ticket buttons (Close/Delete) & appeal buttons (Approve/Reject)")
    await ctx.send(embed=embed, ephemeral=True)

# --- STANDARD TICKET COMMANDS ---
@bot.command(name="close")
@commands.guild_only()
async def close(ctx: commands.Context):
    """Closes the current ticket channel (opens reason modal)."""
    settings = bot.get_guild_settings(ctx.guild.id)
    if ctx.channel.category_id not in [settings['ticket_category'], settings['archive_category']]:
        await send_embed_response(ctx, "Error", "Only in ticket channels.", discord.Color.red()); return
    if ctx.channel.category_id == settings['archive_category']:
        await send_embed_response(ctx, "Error", "Already closed.", discord.Color.red()); return

    # --- OPEN MODAL ---
    modal = CloseReasonModal(bot_instance=bot, target_channel=ctx.channel, closer=ctx.author)
    # Need Interaction context for modal, using dummy interaction response here for prefix cmd
    # This part is a bit hacky for prefix commands, slash commands are cleaner for modals
    await ctx.send("Please provide a reason for closing (check pop-up):", delete_after=5, ephemeral=True) # Give feedback
    # We can't directly send a modal from a prefix command context easily.
    # Alternative: Just ask for reason in chat? Or make !close staff only and require reason as arg?
    # Let's make it staff only and require reason as arg for prefix, modal for button.

    # --- REVISED !close logic ---
    await send_embed_response(ctx, "Use Button", "Please use the 'Close Ticket' button to provide a reason.", discord.Color.blue())
    # --- END REVISED LOGIC ---


@bot.command(name="add")
@commands.guild_only() @is_staff() @in_ticket_channel()
async def add(ctx: commands.Context, user: discord.Member):
    await ctx.channel.set_permissions(user, read_messages=True, send_messages=True)
    await send_embed_response(ctx, "User Added", f"{user.mention} added by {ctx.author.mention}.", discord.Color.green(), ephemeral=False)

@bot.command(name="remove")
@commands.guild_only() @is_staff() @in_ticket_channel()
async def remove(ctx: commands.Context, user: discord.Member):
    await ctx.channel.set_permissions(user, overwrite=None) # Reset
    await send_embed_response(ctx, "User Removed", f"{user.mention} removed by {ctx.author.mention}.", discord.Color.orange(), ephemeral=False)

# --- TICKET TOOL COMMANDS ---
@bot.command(name="rename")
@commands.guild_only() @is_staff() @in_ticket_channel()
async def rename(ctx: commands.Context, *, new_name: str):
    try: clean_name = new_name.replace(" ", "-").lower()[:100]
    except Exception as e: await send_embed_response(ctx, "Error", f"Rename failed: {e}", discord.Color.red())

@bot.command(name="escalate")
@commands.guild_only() @is_staff() @in_ticket_channel()
async def escalate(ctx: commands.Context):
    settings = bot.get_guild_settings(ctx.guild.id); esc_role_id = settings.get("escalation_role")
    if not esc_role_id: await send_embed_response(ctx, "Error", "Escalation role not set.", discord.Color.red()); return
    esc_role = ctx.guild.get_role(esc_role_id)
    if not esc_role: await send_embed_response(ctx, "Error", "Escalation role not found.", discord.Color.red()); return
    embed = create_embed("Ticket Escalated", f"🚨 Escalated by {ctx.author.mention}. {esc_role.mention} notified.", discord.Color.red())
    await ctx.send(content=esc_role.mention, embed=embed)

@bot.command(name="claim")
@commands.guild_only() @is_staff() @in_ticket_channel()
async def claim(ctx: commands.Context):
    if ctx.channel.topic and "claimed-by" in ctx.channel.topic:
        claimer_id = int(ctx.channel.topic.split("claimed-by-")[-1]); claimer = ctx.guild.get_member(claimer_id) or f"ID: {claimer_id}"
        await send_embed_response(ctx, "Error", f"Already claimed by {claimer}.", discord.Color.orange()); return
    base_topic = (ctx.channel.topic or f"ticket-user-{ctx.channel.id}").split(" ")[0]
    new_topic = f"{base_topic} claimed-by-{ctx.author.id}"
    try:
        await ctx.channel.edit(topic=new_topic)
        await send_embed_response(ctx, "Ticket Claimed", f"🎫 Claimed by {ctx.author.mention}.", discord.Color.green(), ephemeral=False)
    except Exception as e: await send_embed_response(ctx, "Error", f"Failed claim: {e}", discord.Color.red())

@bot.command(name="unclaim")
@commands.guild_only() @is_staff() @in_ticket_channel()
async def unclaim(ctx: commands.Context):
    if not ctx.channel.topic or "claimed-by" not in ctx.channel.topic: await send_embed_response(ctx, "Error", "Not claimed.", discord.Color.orange()); return
    claimer_id = int(ctx.channel.topic.split("claimed-by-")[-1]); is_admin = ctx.author.guild_permissions.administrator
    if ctx.author.id != claimer_id and not is_admin:
        claimer = ctx.guild.get_member(claimer_id) or f"ID: {claimer_id}"
        await send_embed_response(ctx, "Permission Denied", f"Claimed by {claimer}.", discord.Color.red()); return
    base_topic = ctx.channel.topic.split(" ")[0]
    try:
        await ctx.channel.edit(topic=base_topic)
        await send_embed_response(ctx, "Ticket Unclaimed", "🔓 Unclaimed.", discord.Color.blue(), ephemeral=False)
    except Exception as e: await send_embed_response(ctx, "Error", f"Failed unclaim: {e}", discord.Color.red())

# --- NEW PURGE COMMAND ---
@bot.command(name="purge")
@commands.guild_only()
@is_staff()
@in_ticket_channel()
async def purge(ctx: commands.Context, amount: int):
    """Deletes a specified number of messages in the current ticket channel."""
    if amount <= 0:
        await send_embed_response(ctx, "Error", "Please provide a positive number of messages to delete.", discord.Color.orange())
        return
    if amount > 100:
         await send_embed_response(ctx, "Error", "You can only purge up to 100 messages at a time.", discord.Color.orange())
         return

    try:
        deleted = await ctx.channel.purge(limit=amount + 1) # +1 to include the command message
        await send_embed_response(ctx, "Purged", f"🗑️ Deleted {len(deleted) - 1} messages.", discord.Color.green(), ephemeral=True)
    except discord.Forbidden:
        await send_embed_response(ctx, "Error", "I don't have permission to delete messages here.", discord.Color.red())
    except Exception as e:
        await send_embed_response(ctx, "Error", f"Failed to purge messages: {e}", discord.Color.red())

# --- BLACKLIST COMMANDS ---
@bot.hybrid_command(name="blacklist", description="Blacklist a user.")
@commands.has_permissions(administrator=True)
@app_commands.describe(user="User to blacklist.", reason="Reason.")
async def blacklist(ctx: commands.Context, user: discord.Member, *, reason: str):
    settings = bot.get_guild_settings(ctx.guild.id); user_id_str = str(user.id)
    if user.id == ctx.author.id: await send_embed_response(ctx, "Error", "Cannot blacklist self.", discord.Color.orange()); return
    if user.bot: await send_embed_response(ctx, "Error", "Cannot blacklist bots.", discord.Color.orange()); return
    if user_id_str in settings["blacklist"]: await send_embed_response(ctx, "Error", "Already blacklisted.", discord.Color.orange()); return
    settings["blacklist"][user_id_str] = reason; save_settings(bot.settings)
    await send_embed_response(ctx, "User Blacklisted", f"{user.mention} blacklisted: `{reason}`.", discord.Color.red())

@bot.hybrid_command(name="unblacklist", description="Unblacklist a user.")
@commands.has_permissions(administrator=True)
@app_commands.describe(user="User to unblacklist.")
async def unblacklist(ctx: commands.Context, user: discord.Member):
    settings = bot.get_guild_settings(ctx.guild.id); user_id_str = str(user.id)
    if user_id_str not in settings["blacklist"]: await send_embed_response(ctx, "Error", "Not blacklisted.", discord.Color.orange()); return
    del settings["blacklist"][user_id_str]; save_settings(bot.settings)
    await send_embed_response(ctx, "User Unblacklisted", f"{user.mention} unblacklisted.", discord.Color.green())

# --- NEW ANNOUNCE COMMAND ---
@bot.hybrid_command(name="announce", description="Send an announcement to a channel.")
@is_staff() # Make it staff-only
@app_commands.describe(channel="Channel to announce in.", message="The announcement message.")
async def announce(ctx: commands.Context, channel: discord.TextChannel, *, message: str):
    """Sends an announcement embed to the specified channel."""
    embed = discord.Embed(
        title="📢 Announcement",
        description=message,
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Announced by {ctx.author.display_name}")

    try:
        await channel.send(embed=embed)
        await send_embed_response(ctx, "Announcement Sent", f"Message sent to {channel.mention}.", discord.Color.green(), ephemeral=True)
    except discord.Forbidden:
        await send_embed_response(ctx, "Error", f"I don't have permission to send messages in {channel.mention}.", discord.Color.red(), ephemeral=True)
    except Exception as e:
        await send_embed_response(ctx, "Error", f"Could not send announcement: {e}", discord.Color.red(), ephemeral=True)


# --- SLASH-ONLY COMMAND ---
@bot.tree.command(name="ticket_stats", description="Shows server ticket stats.")
async def ticket_stats(interaction: discord.Interaction):
    if not await is_staff_interaction(interaction): return
    await interaction.response.defer(ephemeral=True)
    settings = bot.get_guild_settings(interaction.guild.id)
    total_created = settings.get("ticket_counter", 1) - 1
    ticket_category_id = settings.get("ticket_category")
    open_tickets = 0
    if ticket_category_id:
        ticket_category = interaction.guild.get_channel(ticket_category_id)
        if ticket_category and isinstance(ticket_category, discord.CategoryChannel): open_tickets = len(ticket_category.text_channels)
        else: await interaction.followup.send(embed=create_embed("Warning", "Ticket category invalid.", discord.Color.orange()))
    embed = discord.Embed(title=f"Ticket Stats: {interaction.guild.name}", color=discord.Color.light_grey())
    embed.add_field(name="Total Created", value=f"**{total_created}**", inline=True)
    embed.add_field(name="Open Tickets", value=f"**{open_tickets}**", inline=True)
    await interaction.followup.send(embed=embed)


# --- RUN THE BOT ---
try:
    bot.run(TOKEN)
except discord.errors.LoginFailure: print("Login Failure: Improper token.")
except discord.errors.PrivilegedIntentsRequired: print("Privileged Intents Required.")
except Exception as e: print(f"Error during bot startup: {e}")