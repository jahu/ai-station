"""Closed tensor state metadata. No unpickler, imports, reducers or model code.

Only primitive protocol-2 dictionaries and symbolic tensor/storage records are
recognized. GLOBAL/REDUCE/BUILD are validated data tokens, never dispatched to
Python. This is deliberately not a general pickle or PyTorch checkpoint loader.
"""

import math
import pickletools
import re
from dataclasses import dataclass

MAX_METADATA = 2 * 1024**2
MAX_OPS = 150000
MAX_MEMO = 65536
MAX_STACK = 8192
MAX_TENSORS = 4096
STORAGE = {"FloatStorage": ("F32", 4), "HalfStorage": ("F16", 2)}
_GLOBALS = {
    "collections OrderedDict",
    "torch._utils _rebuild_tensor_v2",
    *("torch " + name for name in STORAGE),
}
_KEY = re.compile(r"(?:0|[1-9][0-9]{0,5})\Z")


@dataclass(frozen=True)
class Symbol:
    name: str


@dataclass(frozen=True)
class StorageRef:
    key: str
    dtype: str
    width: int
    elements: int


@dataclass(frozen=True)
class TensorRef:
    storage: StorageRef
    shape: tuple


def _text(value):
    if type(value) is not str or not value or len(value) > 512 or "\0" in value:
        raise ValueError("State keys must be bounded text")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Invalid state text") from exc
    return value


def _storage(value):
    if (
        type(value) is not tuple
        or len(value) != 5
        or value[0] != "storage"
        or not isinstance(value[1], Symbol)
        or value[1].name not in {"torch " + name for name in STORAGE}
        or type(value[2]) is not str
        or not _KEY.fullmatch(value[2])
        or type(value[3]) is not str
        or not re.fullmatch(r"cpu|cuda:[0-9]{1,6}", value[3])
        or type(value[4]) is not int
        or not 0 < value[4] <= 8 * 1024**3
    ):
        raise ValueError("Unsupported tensor storage record")
    dtype, width = STORAGE[value[1].name.split(" ")[1]]
    return StorageRef(value[2], dtype, width, value[4])


def _tensor(arguments):
    if (
        type(arguments) is not tuple
        or len(arguments) != 6
        or not isinstance(arguments[0], StorageRef)
        or type(arguments[1]) is not int
        or arguments[1] != 0
        or arguments[4] is not False
        or type(arguments[5]) is not dict
        or arguments[5]
    ):
        raise ValueError("Only detached complete tensors without hooks are supported")
    storage, _, shape, stride, _, _ = arguments
    if (
        type(shape) is not tuple
        or type(stride) is not tuple
        or len(shape) > 8
        or len(shape) != len(stride)
        or any(type(v) is not int or not 0 < v <= 1_000_000 for v in shape)
        or any(type(v) is not int for v in stride)
        or math.prod(shape) != storage.elements
    ):
        raise ValueError("Tensor shape differs from its bounded storage")
    expected, current = [], 1
    for size in reversed(shape):
        expected.append(current)
        current *= size
    if stride != tuple(reversed(expected)):
        raise ValueError("Only contiguous tensor storage is supported")
    return TensorRef(storage, shape)


def _versions(value):
    if type(value) is not dict or set(value) != {"_metadata"}:
        raise ValueError("Only fixed module-version metadata is supported")
    versions = value["_metadata"]
    if type(versions) is not dict or len(versions) > MAX_TENSORS:
        raise ValueError("Module-version metadata exceeds its bound")
    for name, version in versions.items():
        if name != "":
            _text(name)
        if (
            type(version) is not dict
            or set(version) != {"version"}
            or type(version["version"]) is not int
            or not 0 <= version["version"] <= 32
        ):
            raise ValueError("Unsupported module-version data")
    return versions


def parse(raw):
    """Return symbolic plain tensors and versions; never execute an input token."""
    if type(raw) is not bytes or not 2 <= len(raw) <= MAX_METADATA:
        raise ValueError("Tensor metadata exceeds its bound")
    stack, memo, marker = [], {}, object()
    root, versions, built, stopped = None, {}, False, False

    def pop():
        if not stack:
            raise ValueError("Truncated tensor metadata stack")
        return stack.pop()

    def marked():
        values = []
        while stack and stack[-1] is not marker:
            values.append(pop())
        if not stack:
            raise ValueError("Unbalanced tensor metadata marker")
        pop()
        return list(reversed(values))

    def assign(target, values):
        if type(target) is not dict or len(values) % 2:
            raise ValueError("Invalid state dictionary record")
        for key, value in zip(values[::2], values[1::2]):
            if key != "":
                _text(key)
            if type(key) is not str or key in target or len(target) >= MAX_TENSORS:
                raise ValueError("Duplicate or excessive state dictionary keys")
            target[key] = value

    try:
        for count, (opcode, value, position) in enumerate(pickletools.genops(raw)):
            name = opcode.name
            if count >= MAX_OPS or len(stack) > MAX_STACK:
                raise ValueError("Tensor metadata operation budget exceeded")
            if count == 0:
                if name != "PROTO" or value != 2:
                    raise ValueError("Use the closed protocol-2 tensor state format")
                continue
            if name == "GLOBAL":
                if value not in _GLOBALS:
                    raise ValueError("Executable or unknown state globals are forbidden")
                stack.append(Symbol(value))
            elif name in {"BININT", "BININT1", "BININT2"}:
                if type(value) is not int or not 0 <= value <= 8 * 1024**3:
                    raise ValueError("Invalid state integer")
                stack.append(value)
            elif name == "BINUNICODE":
                if value != "":
                    _text(value)
                stack.append(value)
            elif name == "NEWFALSE":
                stack.append(False)
            elif name == "EMPTY_TUPLE":
                stack.append(())
            elif name == "EMPTY_DICT":
                value = {}
                if not stack and root is None:
                    root = value
                stack.append(value)
            elif name == "MARK":
                stack.append(marker)
            elif name == "TUPLE":
                stack.append(tuple(marked()))
            elif name in {"TUPLE1", "TUPLE2"}:
                values = [pop() for _ in range(int(name[-1]))]
                stack.append(tuple(reversed(values)))
            elif name in {"BINPUT", "LONG_BINPUT"}:
                if not stack or not 0 <= value < MAX_MEMO or value in memo:
                    raise ValueError("Invalid tensor metadata memo")
                memo[value] = stack[-1]
            elif name in {"BINGET", "LONG_BINGET"}:
                if value not in memo:
                    raise ValueError("Unknown tensor metadata reference")
                stack.append(memo[value])
            elif name == "BINPERSID":
                stack.append(_storage(pop()))
            elif name == "REDUCE":
                arguments, symbol = pop(), pop()
                if not isinstance(symbol, Symbol):
                    raise ValueError("Only symbolic tensor data constructors are supported")
                if symbol.name == "collections OrderedDict" and arguments == ():
                    value = {}
                    if not stack and root is None:
                        root = value
                elif symbol.name == "torch._utils _rebuild_tensor_v2":
                    value = _tensor(arguments)
                else:
                    raise ValueError("Executable state reducers are forbidden")
                stack.append(value)
            elif name == "SETITEM":
                value, key = pop(), pop()
                if not stack:
                    raise ValueError("Missing state dictionary")
                assign(stack[-1], [key, value])
            elif name == "SETITEMS":
                values = marked()
                if not stack:
                    raise ValueError("Missing state dictionary")
                assign(stack[-1], values)
            elif name == "BUILD":
                state = pop()
                if built or not stack or stack[-1] is not root:
                    raise ValueError("Executable state object construction is forbidden")
                versions, built = _versions(state), True
            elif name == "STOP":
                if position + 1 != len(raw) or len(stack) != 1 or stack[0] is not root:
                    raise ValueError("Trailing or unbalanced tensor metadata")
                stopped = True
            else:
                raise ValueError("Unsupported tensor metadata instruction: " + name)
    except (IndexError, KeyError, OverflowError, UnicodeError, TypeError) as exc:
        raise ValueError("Invalid closed tensor metadata") from exc
    if not stopped or type(root) is not dict or not 1 <= len(root) <= MAX_TENSORS:
        raise ValueError("The checkpoint must contain a plain bounded tensor state")
    if any(not name or not isinstance(value, TensorRef) for name, value in root.items()):
        raise ValueError("The checkpoint contains non-tensor state")
    if len({value.storage.key for value in root.values()}) != len(root):
        raise ValueError("Aliased tensor storages require a separate supported profile")
    return root, versions
