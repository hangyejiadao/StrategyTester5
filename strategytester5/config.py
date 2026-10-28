
"""
Module containing constants and configuration validators for the strategy tester
"""

MAX_WORKERS = 4
"""Maximum number of parallel workers for testing. Adjust based on your CPU capabilities."""


DEFAULT_BROKER_DATA_PATH = "Default-Broker"
"""Default path where broker data (like ticks and symbol info) is stored."""

DEFAULT_SYMBOL_INFO_JSON = "SymbolInfo.json"
"""Default filename for symbol information JSON file."""
DEFAULT_ACCOUNT_INFO_JSON = "AccountInfo.json"
"""Default filename for account information JSON file."""
DEFAULT_TERMINAL_INFO_JSON = "TerminalInfo.json"
"""Default filename for terminal information JSON file."""

SUPPORTED_TESTER_MODELLING = \
    {
        0: "Every tick",
        1: "1 minute OHLC",
        2: "Open price only",
        # 3: "Math calculations",
        4: "Every tick based on real ticks"
    }
"""Mapping of supported tester modelling modes. The keys are the integer codes used in MetaTrader5, and the values are human-readable descriptions.
"""

REQUIRED_TESTER_CONFIG_KEYS = {
            "bot_name",
            "symbols",
            "timeframe",
            "start_date",
            "end_date",
            "modelling",
            "deposit",
            "leverage"
        }
"""Set of required keys that must be present in the tester configuration dictionary.
"""

SUPPORTED_TESTER_MODELLING_REVERSE = {
    v.lower(): k for k, v in SUPPORTED_TESTER_MODELLING.items()
}

"""Reverse mapping of supported tester modelling modes, where the keys are the lowercase human-readable descriptions and the values are the integer codes. This allows users to specify the modelling mode using either the integer code or a case-insensitive string.
"""