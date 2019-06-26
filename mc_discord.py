# coding=utf-8
from __future__ import print_function
from typing import List, Dict, Tuple, Callable
import mcrcon
import socket
import discord
from enum import Enum
import traceback


class Permission(Enum):
    """
    Pre-defined permission levels
    """
    Default = 0
    Moderator = 25
    Admin = 50
    Owner = 900

    def __lt__(self, other):
        if self.__class__ is other.__class__:
            return self.value < other.value
        return NotImplemented

    def __le__(self, other):
        if self.__class__ is other.__class__:
            return self.value <= other.value
        return NotImplemented


class Command:
    """
    Command struct
    """
    name: str
    permission: Permission
    func: Callable
    help: str

    def __init__(self, name: str, level: Permission, func: Callable, help=""):
        self.name = name
        self.permission = level
        self.func = func
        self.help = help


class MCLink:
    """
    Minecraft: Java Edition RCON -> Discord Link
    """
    _DEBUG: bool = False

    # RCON socket
    _rcon_socket = None

    # Discord
    _link = None  # type: _DiscordLink
    _guild_id = None  # type: int

    """
    List of admins
    """
    _bot_admins = []  # type: List[int]
    _commands = {}  # type: Dict[str, Command]
    _role_permissions = {}  # type: Dict[int, Permission]
    _output_channels = {}

    class _DiscordLink(discord.Client):
        """
        Custom Discord Client
        """
        _parent: "MCLink"
        _DEBUG: bool = False

        def __init__(self, parent: "MCLink", *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._parent = parent

        async def on_ready(self):
            print('[!] Logged on as {0}!'.format(self.user))
            await self.change_presence(activity=discord.Game("Minecraft: Java Edition"), status=discord.Status.online)

        async def on_connect(self):
            print("[!] Connected to discord")

        async def on_disconnect(self):
            print("[!] Lost connection to Discord")

        async def on_message(self, message):
            if self._DEBUG:
                print('Message from {0.author}: {0.content}'.format(message))

            # Ignore messages from self, or other bots
            if (message.author == self.user) or message.author.bot:
                return

            if message.content.startswith('!'):
                try:
                    response = await self._parent.call(message.content[1:], message.author)

                    if response is not None:
                        await message.channel.send(("[FAIL] " if not response[0] else "") + response[1])

                except Exception as e:
                    response = ":exclamation: An error occurred while trying to run the command '{:s}'.\nPlease notify the development team.\n\nException: {:s}".format(message.content[1:], str(e))
                    print(response)
                    traceback.print_tb(e.__traceback__)
                    await message.channel.send(content=response)

    def __init__(self):
        super().__init__()
        self.register_command("help", Permission.Default, self.help, "Show this help menu")

    def connect(self, bot_token: str, guild_id: int, rcon_host: str, rcon_port: int, rcon_password: str):
        """
        Open a connection to a Minecraft: Java Edition RCON
        :param bot_token: Discord Bot token
        :param guild_id: Discord Server ID
        :param rcon_host: Host address
        :param rcon_port: RCON port
        :param rcon_password: RCON password
        :return: Successful
        """
        # Set parameters
        self._guild_id = guild_id

        # Connect to RCON
        self._rcon_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._rcon_socket.connect((rcon_host, rcon_port))

            # Log in
            result = mcrcon.login(self._rcon_socket, rcon_password)
            if not result:
                print("Incorrect rcon password")
                self.close()
                raise ConnectionError("Incorrect rcon password")

        except Exception as e:
            print("Failed to connect to the Minecraft RCON server")
            print(e)
            self.close()
            raise e

        # Connect to discord
        self._link = self._DiscordLink(self)
        self._link.run(bot_token)

    def close(self):
        """
        Closes the RCON connection
        :return: None
        """
        if self.is_connected():
            self._rcon_socket.close()
            self._rcon_socket = None

    def is_connected(self):
        """
        :return: Whether the RCON connection is open
        """
        return self._rcon_socket is not None

    def log(self, message: str):
        print(message)

    def register_admin(self, user_id: int):
        """
        Register a Discord user as an admin for this bot. Admins have access to advanced functionality such as !stop
        :param user_id: Discord UserID
        :return:
        """
        self._bot_admins.append(user_id)

    def register_role(self, role_id: int, level: Permission):
        """
        Set the permission level for a role
        :param role_id: Discord RoleId
        :param level: Permission level this role grants for commands
        :return:
        """
        self._role_permissions[role_id] = level

    def register_command(self, name: str, level: Permission, func: Callable, help: str = ""):
        """
        Register a bot command
        :param name: Name of the command
        :param level: Permission level required to run this command
        :param func: Function to execute. MUST take these parameters:
            <Minecraft Execute Handle>: Callable[str], <Arguments List>: List[str], <Discord Member>: discord.Member
        :return:
        """
        self._commands[name] = Command(name, level, func, help)

    def get_member_permission_level(self, user: discord.User) -> Permission:
        """
        Get the permission level for a given member
        :param member: MemberId
        :return: Permission level
        """
        guild = self._link.get_guild(self._guild_id)  # type: discord.Guild

        # Get the member object for this user
        try:
            member_index = guild.members.index(user)  # type: discord.Member
            member = guild.members[member_index]
        except ValueError:
            return Permission.Default

        # Go through their roles and find their highest level permission
        permission_level: Permission = Permission.Default
        role: discord.Role
        for role in member.roles:
            if role in self._role_permissions:
                permission_level = max(permission_level, self._role_permissions[role.id])

        return permission_level

    async def call(self, input: str, user: discord.User) -> Tuple[bool, str]:
        """
        Call a command
        :param input: String input
        :param member: Member who is running this command
        :return: Tuple[Success, Response Message]
        """
        cmd_args = input.split(" ")
        cmd_name = cmd_args[0]  # type: str
        cmd_args = cmd_args[1:]  # type: List[str]

        # Get the command object
        try:
            cmd = self._commands[cmd_name]  # type: Command
        except KeyError:
            return False, "Error: Unknown command '{:s}'".format(cmd_name)

        # Check the user has permission to run the command
        if self.get_member_permission_level(user) < cmd.permission:
            return False, "You don't have permission for that command."

        # Run the command
        else:
            if self._DEBUG:
                self.log("Running '{:s}'".format(input))
            response = await cmd.func(link=self, args=cmd_args, user=user)

            if response is None:
                # Send response the user
                return True, "No response for command"
            else:
                return response

    async def execute(self, command: str) -> str:
        """
        Run a command on the Minecraft RCON
        :param command: command to send to Minecraft
        :return: String response
        """
        if not self.is_connected():
            return "RCON is not connected"

        return await mcrcon.command(self._rcon_socket, command)

    async def help(self, link: "MCLink", args: List[str], user: discord.User):
        """
        Provides the user with information about the bot and the commands accessible to them
        :param link:
        :param args:
        :param user:
        :return:
        """
        message = "Hello! I am a Discord -> Minecraft: Java Edition server link!\nHere are the commands available to you:\n\n"
        user_permission = self.get_member_permission_level(user)

        for x in self._commands.values():
            if user_permission >= x.permission:
                message += "* `{:s}` - {:s}\n".format(x.name, x.help)

        return True, message
