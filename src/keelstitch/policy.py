"""Load operator policy once, explicitly and fail closed."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType


class PolicyError(ValueError):
    pass


ALIAS = re.compile(r'[a-z0-9][a-z0-9_-]{0,63}')
HOST = re.compile(r'[a-zA-Z0-9.:-]{1,253}')
USER = re.compile(r'[a-zA-Z_][a-zA-Z0-9_-]{0,63}')
COMMAND = re.compile(r'(?:/[a-zA-Z0-9_][a-zA-Z0-9_.-]*)+')
MAX_POLICY_BYTES = 256 * 1024


def _unique_pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise PolicyError('duplicate key in policy')
        obj[key] = value
    return obj


def _shape(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() <= set(required) | set(optional):
        raise PolicyError('missing or unexpected policy fields')


def _text(value, name, limit):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or not value.isprintable()):
        raise PolicyError(f'invalid {name}')
    return value


def _match(value, name, pattern, limit=256):
    value = _text(value, name, limit)
    if not pattern.fullmatch(value):
        raise PolicyError(f'invalid {name}')
    return value


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise PolicyError(f'invalid {name}: expected integer from {low} to {high}')
    return value


def _entries(value, name):
    if not isinstance(value, dict) or not 1 <= len(value) <= 64:
        raise PolicyError(f'{name} must contain 1 to 64 entries')
    for alias, item in value.items():
        yield _match(alias, 'alias', ALIAS), item


@dataclass(frozen=True)
class Action:
    command: str
    description: str
    timeout_seconds: int
    max_output_bytes: int


@dataclass(frozen=True)
class Target:
    host: str
    username: str
    port: int
    host_key: str
    identity_file: str
    actions: Mapping[str, Action]


@dataclass(frozen=True)
class Policy:
    targets: Mapping[str, Target]

    @classmethod
    def load(cls, path: Path) -> 'Policy':
        try:
            with path.open('rb') as file:
                data = file.read(MAX_POLICY_BYTES + 1)
            if len(data) > MAX_POLICY_BYTES:
                raise PolicyError('policy exceeds the size limit')
            config = json.loads(data.decode('utf-8'), object_pairs_hook=_unique_pairs)
        except PolicyError:
            raise
        except (OSError, ValueError, RecursionError) as exc:
            raise PolicyError('cannot read policy as UTF-8 JSON') from exc
        _shape(config, ('targets',))
        targets = {}
        for alias, item in _entries(config['targets'], 'targets'):
            _shape(item, ('host', 'username', 'host_key', 'identity_file', 'actions'), ('port',))
            actions = {}
            for name, action in _entries(item['actions'], 'actions'):
                _shape(action, ('command', 'description'), ('timeout_seconds', 'max_output_bytes'))
                actions[name] = Action(
                    _match(action['command'], 'command (absolute executable path)', COMMAND, 512),
                    _text(action['description'], 'description', 256),
                    _integer(action.get('timeout_seconds', 15), 'timeout_seconds', 1, 120),
                    _integer(action.get('max_output_bytes', 16384), 'max_output_bytes', 1, 65536),
                )
            identity = _text(item['identity_file'], 'identity_file', 4096)
            if not Path(identity).is_absolute():
                raise PolicyError('identity_file must be an absolute path')
            targets[alias] = Target(
                _match(item['host'], 'host', HOST),
                _match(item['username'], 'username', USER),
                _integer(item.get('port', 22), 'port', 1, 65535),
                _text(item['host_key'], 'host_key', 4096),
                identity,
                MappingProxyType(actions),
            )
        return cls(MappingProxyType(targets))

    def catalog(self) -> dict[str, dict[str, str]]:
        return {alias: {name: action.description for name, action in target.actions.items()}
                for alias, target in self.targets.items()}

    def select(self, target: str, action: str) -> tuple[Target, Action]:
        try:
            selected = self.targets[target]
            return selected, selected.actions[action]
        except KeyError as exc:
            raise PolicyError('unknown target or action; consult the catalog') from exc
