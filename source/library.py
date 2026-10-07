"""The audio library: Studio's own copies of clips in <data>/Audio, where pads use them, and safe changes."""

import hashlib
import os
from pathlib import Path
import re

from store import AUDIO_EXTS, iter_clips

# Library files are named <32 hex characters>-<original name> so imports never collide.
PREFIX = re.compile(r'^[0-9a-f]{32}-')


def display_name(path):
    """The name shown for a library file: its original name, without the unique prefix."""
    return PREFIX.sub('', Path(path).name)


def path_key(path):
    """Compare paths the way Windows does: fully resolved and case-insensitive. realpath also turns
    8.3 short names (C:\\Users\\RUNNER~1) into long ones, and works for a file that no longer exists."""
    return os.path.normcase(os.path.realpath(path))


def same_file(a, b):
    return path_key(a) == path_key(b)


def clean_name(name, suffix):
    """A file name typed by the person, without characters Windows rejects or a repeated extension."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', str(name or '')).strip(' .')
    if name.lower().endswith(suffix.lower()):
        name = name[: -len(suffix)].rstrip(' .')
    if not name:
        raise ValueError('Type a name for the clip')
    return name[:120]


class Library:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.hashes = {}  # (path, size, mtime) -> SHA-256, so a file is hashed once

    def files(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        return [p for p in self.folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS]

    def resolve(self, value):
        """A library file named by the interface. Anything outside the library folder is refused."""
        path = Path(str(value or '')).resolve(strict=True)
        if not same_file(path.parent, self.folder.resolve()) or path.suffix.lower() not in AUDIO_EXTS:
            raise ValueError('Only clips in the Studio library can be changed')
        return path

    def digest(self, path):
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        if key not in self.hashes:
            sha = hashlib.sha256()
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(1 << 20), b''):
                    sha.update(chunk)
            self.hashes[key] = sha.hexdigest()
        return self.hashes[key]

    def duplicate(self, source):
        """A library file with the same content as source, or None. Only files of the same size are hashed."""
        size = source.stat().st_size
        same = [p for p in self.files() if p.stat().st_size == size]
        if not same:
            return None
        digest = self.digest(source)
        return next((p for p in same if self.digest(p) == digest), None)

    @staticmethod
    def usage(profiles):
        """Where each clip is used, by normalized path: [{profile, page, bank, id, control, step}]."""
        used = {}
        for p in profiles:
            for pg, bank, cid, holder in iter_clips(p):
                if holder['value']:
                    control = pg['banks'][bank][cid]
                    used.setdefault(path_key(holder['value']), []).append(
                        {
                            'profile': p['name'],
                            'page': pg['name'],
                            'bank': bank,
                            'id': cid,
                            'control': control['label'],
                            'step': holder is not control,
                        }
                    )
        return used

    def rename(self, path, name, documents):
        """Rename a clip, keeping its unique prefix and type, and point every reference at the new path.

        documents are the store data and its Undo snapshots, so Undo never brings back a path that
        no longer exists."""
        prefix = PREFIX.match(path.name)
        new = path.with_name((prefix.group(0) if prefix else '') + clean_name(name, path.suffix) + path.suffix)
        if new.name == path.name:
            return path
        if new.exists() and not same_file(new, path):
            raise ValueError('Another clip already has that name')
        old = path_key(path)
        path.rename(new)
        for data in documents:
            for p in data['profiles']:
                for pg, bank, cid, holder in iter_clips(p):
                    if holder['value'] and path_key(holder['value']) == old:
                        holder['value'] = str(new)
                        if holder is pg['banks'][bank][cid]:
                            holder['audioName'] = display_name(new)
        return new
