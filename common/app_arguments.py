from __future__ import annotations
import argparse
import configparser
import os
import sys
from typing import NoReturn, Optional
from common.constants import (
    _ARG_BOT_NAME,
    _ARG_CASE_SENSITIVE,
    _ARG_CHANNEL,
    _ARG_CONFIG,
    _ARG_ENCRYPTION_KEY,
    _ARG_EXCLUDE_OOTB,
    _ARG_NODE_RETENTION_DAYS,
    _ARG_VERBOSE,
    _APP_DESCRIPTION,
    _APP_EPILOG,
    _CONFIG_SECTION,
    _DEFAULT_CONFIG_FILE,
    _HELP_BOT_NAME,
    _HELP_CASE_SENSITIVE,
    _HELP_CHANNEL,
    _HELP_CONFIG,
    _HELP_ENCRYPTION_KEY,
    _HELP_EXCLUDE_OOTB,
    _HELP_NODE_RETENTION_DAYS,
    _HELP_VERBOSE,
)


class _HelpOnErrorParser(argparse.ArgumentParser):
    """ArgumentParser subclass that prints full help text on any argument error."""

    # region Public Functions
    def error(self, message: str) -> NoReturn:
        """Overrides the default error handler to print full help before exiting.

        Args:
            message: The error message produced by argparse.
        """
        self.print_help(sys.stderr)
        self.exit(2, f"\nerror: {message}\n")
    # endregion Public Functions


class AppArguments:
    """Parses and exposes command-line arguments for the DAMNBot application.

    Wraps argparse to provide typed, read-only access to each supported argument.
    Call parse() once at startup before accessing any properties.
    """

    # region Protected Variables
    _bot_name: str
    _case_sensitive: bool
    _channel: Optional[str]
    _encryption_key: Optional[str]
    _exclude_ootb: bool
    _node_retention_days: int
    _verbose: bool
    # endregion Protected Variables

    # region Public Properties
    @property
    def bot_name(self) -> str:
        """The display name of the bot, used to derive the command prefix."""
        return self._bot_name

    @property
    def case_sensitive(self) -> bool:
        """Whether prefix and command matching must respect letter case."""
        return self._case_sensitive

    @property
    def channel(self) -> Optional[str]:
        """The channel name supplied via --Channel, or None if not provided."""
        return self._channel

    @property
    def encryption_key(self) -> Optional[str]:
        """The passphrase used to encrypt and decrypt local data files, or None if not set."""
        return self._encryption_key

    @property
    def exclude_ootb(self) -> bool:
        """Whether out-of-the-box default commands (ping, test) are suppressed."""
        return self._exclude_ootb

    @property
    def node_retention_days(self) -> int:
        """Number of days without activity before a node is removed from the local database."""
        return self._node_retention_days

    @property
    def verbose(self) -> bool:
        """Whether verbose console output is enabled."""
        return self._verbose
    # endregion Public Properties

    # region Constructor
    def __init__(self) -> None:
        self._bot_name = ""
        self._case_sensitive = False
        self._channel = None
        self._encryption_key = None
        self._exclude_ootb = False
        self._node_retention_days = 30
        self._verbose = False
    # endregion Constructor

    # region Public Functions
    def parse(self) -> None:
        """Parses sys.argv and populates the argument properties.

        If a config file is found (via --Config or the default 'meshbot.config' in
        the current directory), its values are applied as defaults before parsing
        command-line arguments. Explicit command-line arguments always take precedence.

        Prints full usage help and exits with code 2 if unrecognised arguments
        are supplied, a required argument value is missing, or the specified
        config file does not exist.
        """
        parser: _HelpOnErrorParser = _HelpOnErrorParser(
            description=_APP_DESCRIPTION,
            epilog=_APP_EPILOG,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument(_ARG_CONFIG, type=str, default=None, metavar="FILE", help=_HELP_CONFIG)
        parser.add_argument(_ARG_BOT_NAME, nargs="?", default=None, type=str, help=_HELP_BOT_NAME)
        parser.add_argument(_ARG_CASE_SENSITIVE, action="store_true", help=_HELP_CASE_SENSITIVE)
        parser.add_argument(_ARG_CHANNEL, type=str, default=None, help=_HELP_CHANNEL)
        parser.add_argument(_ARG_ENCRYPTION_KEY, type=str, default=None, metavar="PASSPHRASE", help=_HELP_ENCRYPTION_KEY)
        parser.add_argument(_ARG_EXCLUDE_OOTB, action="store_true", help=_HELP_EXCLUDE_OOTB)
        parser.add_argument(_ARG_NODE_RETENTION_DAYS, type=int, default=None, metavar="DAYS", help=_HELP_NODE_RETENTION_DAYS)
        parser.add_argument(_ARG_VERBOSE, action="store_true", help=_HELP_VERBOSE)

        # Locate the config file before the full parse so its values can be applied
        # as defaults (command-line arguments will still override them).
        explicit_config: Optional[str] = None
        argv: list[str] = sys.argv[1:]
        for i, arg in enumerate(argv):
            if arg == _ARG_CONFIG and i + 1 < len(argv):
                explicit_config = argv[i + 1]
                break

        config_path: str = explicit_config or _DEFAULT_CONFIG_FILE
        config_exists: bool = os.path.isfile(config_path)

        # Nothing to work with — show help and exit cleanly (no scary error message).
        if not argv and not config_exists:
            parser.print_help()
            parser.exit(0)

        if explicit_config and not config_exists:
            parser.error(f"Config file not found: {config_path}")
        elif config_exists:
            parser.set_defaults(**_load_config_file(config_path))

        args: argparse.Namespace = parser.parse_args()

        if not args.bot_name:
            parser.error(
                "the following arguments are required: bot_name "
                f"(provide it on the command line or set bot_name in {config_path})"
            )

        self._bot_name = args.bot_name
        self._case_sensitive = args.CaseSensitive
        self._channel = args.Channel
        self._encryption_key = args.EncryptionKey
        self._exclude_ootb = args.ExcludeOOTB
        self._node_retention_days = args.NodeRetentionDays if args.NodeRetentionDays is not None else 30
        self._verbose = args.Verbose
    # endregion Public Functions


def _load_config_file(path: str) -> dict:
    """Reads an INI-format config file and returns argparse-compatible defaults.

    Keys in the ``[meshbot]`` section are mapped to their corresponding argparse
    dest names. Boolean flags (``CaseSensitive``, ``ExcludeOOTB``, ``Verbose``)
    accept ``true``/``false`` (case-insensitive). Unrecognised keys are ignored.

    Args:
        path: Path to the config file.

    Returns:
        A dict mapping argparse dest names to their configured values.
    """
    cp: configparser.ConfigParser = configparser.ConfigParser()
    cp.optionxform = lambda optionstr: optionstr  # preserve key capitalisation (e.g. CaseSensitive)
    cp.read(path)
    defaults: dict = {}
    if _CONFIG_SECTION in cp:
        section = cp[_CONFIG_SECTION]
        if "bot_name" in section:
            defaults["bot_name"] = section["bot_name"]
        if "Channel" in section:
            defaults["Channel"] = section["Channel"]
        if "CaseSensitive" in section:
            defaults["CaseSensitive"] = section.getboolean("CaseSensitive")
        if "EncryptionKey" in section:
            defaults["EncryptionKey"] = section["EncryptionKey"]
        if "ExcludeOOTB" in section:
            defaults["ExcludeOOTB"] = section.getboolean("ExcludeOOTB")
        if "NodeRetentionDays" in section:
            defaults["NodeRetentionDays"] = section.getint("NodeRetentionDays")
        if "Verbose" in section:
            defaults["Verbose"] = section.getboolean("Verbose")
    return defaults
