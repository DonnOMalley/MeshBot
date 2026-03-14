# Coding Standards

The following rules apply to all code in this repository.

## 1. Variable Declaration

All variables must be declared with a type annotation before they are assigned or referenced.

```python
# correct
name: str = ""
name = "Alice"

# incorrect
name = "Alice"
```

## 2. Return Types

All functions must have an explicit return type annotation. Use `-> None` when the function does not return a value.

```python
# correct
def connect(self, iface) -> None: ...
def get_channel(self, index: int) -> Optional[Channel]: ...

# incorrect
def connect(self, iface): ...
```

## 3. No Hard Coding

Literal values must not appear inline. Define a named constant and reference it instead.

```python
# correct
WELCOME_MESSAGE: str = "Hello Mesh - Good to see you"
iface.sendText(WELCOME_MESSAGE)

# incorrect
iface.sendText("Hello Mesh - Good to see you")
```

Constants that are used in only one module are declared at the top of that module as private (leading `_`).
Constants that are used in more than one module must be moved to `Common/constants.py` and imported from there. They are declared without a leading underscore because they are intentionally exported.

**All application-level constants — strings, numbers, formats, delays, command names, and message templates — must be declared in `common/constants.py` regardless of where they are used.** Module-level constant declarations outside of `common/constants.py` are not permitted for application logic. The only exception is narrow implementation internals scoped to a single class (e.g. JSON key names inside a serialiser, cryptographic iteration counts inside an encryption helper) that have no meaning outside that file.

```python
# Common/constants.py
# Bot command names
CMD_HELLO: str = "hello"          # shared — used in command_register and channel_monitor
CMD_PING: str = "ping"            # shared — used in command_register and channel_monitor
CMD_TEST: str = "test"            # shared — used in command_register and channel_monitor

# Bot identity
BOT_PREFIX: str = "@DAMNbot"      # shared — used in channel_monitor, message_broadcaster, command_register

# module-level private constant — only used in this file
_MONITOR_POLL_INTERVAL: float = 0.5
```

When adding a new constant, check `Common/constants.py` first. If an equivalent value already exists there, import and reuse it rather than declaring a duplicate.

## 4. Minimum Scope

Functions and variables should be scoped as narrowly as possible.

- Private helper methods that are only used within a class must be prefixed with `_` (single underscore).
- Module-level helpers that are only used within a single module should not be exported.
- Avoid exposing internals beyond the boundary where they are needed.

## 5. Class Variable Declaration

All instance variables must be declared as class-level annotations before any method. Never annotate `self._variable` inside a method — declare the type at the class level and assign without annotation inside `__init__`.

```python
# correct
class MyClass:
    _name: str
    _count: int

    def __init__(self) -> None:
        self._name = ""
        self._count = 0

# incorrect
class MyClass:
    def __init__(self) -> None:
        self._name: str = ""
        self._count: int = 0
```

## 6. Documentation (Google-Style Docstrings)

All classes and all public or protected functions/methods must have a Google-style docstring. This is the Python industry standard and is compatible with documentation generators such as Sphinx and pdoc.

### Classes

Every class must have a docstring immediately after the `class` line that describes its purpose and responsibility.

```python
# correct
class ChannelMonitor:
    """Monitors a single Meshtastic channel and dispatches incoming text commands.

    Subscribes to the meshtastic pubsub events for the given channel and routes
    recognised bot commands to the registered command handlers.
    """
```

### `__init__`

Document `__init__` when the constructor has parameters beyond `self`. List every parameter in an `Args:` block.

```python
# correct
def __init__(self, iface: MeshInterface, channel: channel_pb2.Channel) -> None:
    """Initialises the monitor for the specified interface and channel.

    Args:
        iface: The active MeshInterface connection to the Meshtastic device.
        channel: The channel object to monitor for incoming messages.
    """
```

### Methods and functions

Document every public and protected method. Use the following sections as applicable — omit sections that do not apply rather than leaving them empty.

- **Args:** — one line per parameter (omit `self`).
- **Returns:** — what the function returns; omit for `-> None`.
- **Raises:** — exceptions the caller should expect.

```python
# correct
def get_channel_by_name(self, channel_name: str) -> Optional[channel_pb2.Channel]:
    """Looks up a channel by its display name.

    A name of 'primary' (case-insensitive, with or without parentheses) is
    treated as an alias for the channel at index 0.

    Args:
        channel_name: The channel name to search for.

    Returns:
        The matching Channel object, or None if no match is found.
    """
```

### Private methods

Private methods (prefixed with `_`) must still have a docstring that describes their purpose, but the `Args:` and `Returns:` sections may be abbreviated or omitted when the signature and type annotations already make the meaning obvious.

### Properties

Properties must have a one-line docstring describing the value they expose.

```python
@property
def case_sensitive(self) -> bool:
    """Whether prefix and command matching is case-sensitive."""
    return self._case_sensitive
```

### What NOT to do

- Do not use `#` inline comments as a substitute for a docstring.
- Do not repeat the type annotation in the docstring text (the type is already in the signature).
- Do not leave docstrings as `pass` or blank.

## 7. Regions

Use `# region <Name>` / `# endregion <Name>` comment pairs to visually group members inside every class body. The `# endregion` tag must always repeat the same descriptive text used in the matching `# region` tag. Regions must appear in the following order — omit any section that has no members:

1. Private Variables
2. Protected Variables
3. Public Variables
4. Private Properties
5. Protected Properties
6. Public Properties
7. Constructor
8. Private Functions
9. Protected Functions
10. Public Functions

The `Constructor` region contains only `__init__`. It sits between the properties and the function regions so that initialisation is clearly separated from behaviour.

```python
class MyClass:
    # region Private Variables
    __id: int
    # endregion Private Variables

    # region Protected Variables
    _name: str
    # endregion Protected Variables

    # region Public Variables
    label: str
    # endregion Public Variables

    # region Public Properties
    @property
    def name(self) -> str:
        """The display name."""
        return self._name
    # endregion Public Properties

    # region Constructor
    def __init__(self, name: str) -> None:
        """Initialises with a name.

        Args:
            name: The display name.
        """
        self._name = name
    # endregion Constructor

    # region Protected Functions
    def _validate(self) -> bool:
        """Checks internal state."""
        ...
    # endregion Protected Functions

    # region Public Functions
    def reset(self) -> None:
        """Resets the instance to its default state."""
        self._name = ""
    # endregion Public Functions
```

**Classification rules**

| Prefix                   | Category  |
| ------------------------ | --------- |
| `__` (double underscore) | Private   |
| `_` (single underscore)  | Protected |
| No underscore            | Public    |

`__init__` always lives in the `Constructor` region, not in `Public Functions`.

## 8. Abstract Base Classes

Use Python's `abc.ABC` and `@abstractmethod` / `@abstractmethod @property` to define shared framework logic that subclasses must specialise.

### Abstract methods

Declare abstract methods in the appropriate Functions region (`Protected Functions` or `Public Functions`), with a docstring describing the contract the subclass must fulfil. The body is `...`.

```python
# region Protected Functions
@abstractmethod
def _is_message_relevant(self, packet: dict) -> bool:
    """Returns True if the packet should be processed by this monitor."""
    ...
# endregion Protected Functions
```

### Abstract properties

Declare abstract properties in the appropriate Properties region (`Protected Properties` or `Public Properties`). Stack `@property` above `@abstractmethod` (this order is required by Python). The body is `...`.

```python
# region Protected Properties
@property
@abstractmethod
def _msg_started(self) -> str:
    """Format string printed when the monitor starts.

    Must accept ``channel_name`` and ``index`` keyword arguments.
    """
    ...
# endregion Protected Properties
```

### Concrete subclasses

A subclass that only provides implementations of inherited abstract members is a **thin subclass**. Omit any region that has no members of its own. In particular:

- Do **not** add a `Constructor` region if the subclass does not define its own `__init__` — the base class constructor is inherited automatically.
- Do **not** repeat class-level variable declarations from the base class.
- Only include regions for the members the subclass actually defines.

```python
class ChannelMonitor(BaseMonitor):
    """Monitors a single Meshtastic channel and dispatches incoming text commands."""

    # region Protected Properties
    @property
    def _msg_started(self) -> str:
        return _MSG_MONITORING

    @property
    def _msg_stopped(self) -> str:
        return _MSG_MONITOR_STOPPED
    # endregion Protected Properties

    # region Protected Functions
    def _is_message_relevant(self, packet: dict) -> bool:
        """Returns True if the packet is on the monitored channel."""
        return packet.get(_PACKET_KEY_CHANNEL, 0) == self._channel.index
    # endregion Protected Functions
```

Concrete property implementations that simply return a constant do **not** require a docstring — the abstract declaration in the base class already documents the contract.

## 9. Single Return Statement

Every function or method must have **exactly one** `return` statement, located at the end of the function body. Early returns are not permitted.

Use a result variable to accumulate the value to be returned, and guard conditional logic with `if`/`elif`/`else` blocks instead of returning from within them.

```python
# correct
def get_node_id(self, node_num: int | None) -> str:
    node_id: str = _NODE_ID_UNKNOWN if node_num is None else f"!{node_num:08x}"
    return node_id

# correct — void functions: let Python return implicitly; no explicit return needed
def load(self) -> None:
    if not os.path.isfile(self._path):
        self._save()
    else:
        self._parse()

# incorrect — early return
def get_node_id(self, node_num: int | None) -> str:
    if node_num is None:
        return _NODE_ID_UNKNOWN
    return f"!{node_num:08x}"
```

For `-> None` functions, omit the `return` statement entirely — Python's implicit return at the end of the function body is sufficient. Do not add a bare `return` at the bottom of a `-> None` function, and do not use early `return` to exit early; restructure the logic with `else` instead.

```python
# correct
def on_message(self, packet: dict) -> None:
    if self._is_relevant(packet):
        self._handle(packet)

# incorrect — early return
def on_message(self, packet: dict) -> None:
    if not self._is_relevant(packet):
        return
    self._handle(packet)
```
