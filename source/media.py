"""YouTube audio import, waveform peaks and clip cropping through a bundled ffmpeg."""

from array import array
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlparse
import uuid

YOUTUBE_HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be', 'www.youtu.be'}
MAX_SECONDS = 3 * 3600
MAX_BYTES = 200_000_000
PEAK_RATE = 2000
PEAK_BLOCK = 20  # 100 fine peaks per second before resampling to the requested width
NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0


class Cancelled(Exception):
    pass


def ffmpeg():
    """The imageio-ffmpeg binary bundled with Studio, else one on PATH."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        found = shutil.which('ffmpeg')
        if found:
            return found
    raise RuntimeError('ffmpeg is unavailable, so Studio cannot convert or crop audio')


def youtube_url(value):
    """Accept only a single http(s) YouTube video link."""
    value = str(value or '').strip()
    if not value:
        raise ValueError('Paste a YouTube link first')
    if '://' not in value:
        value = 'https://' + value
    parsed = urlparse(value)
    if parsed.scheme not in ['http', 'https'] or (parsed.hostname or '').lower() not in YOUTUBE_HOSTS:
        raise ValueError('Only youtube.com and youtu.be links are supported')
    return value


def clean_name(title):
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', str(title or '')).strip(' .')
    return (title or 'YouTube audio')[:120]


def probe_duration(path):
    """A clip's length in seconds from its header (ffmpeg -i reads it without decoding), or None."""
    result = subprocess.run(
        [ffmpeg(), '-hide_banner', '-nostdin', '-i', str(path)],
        capture_output=True,
        timeout=30,
        creationflags=NO_WINDOW,
    )
    match = re.search(rb'Duration: (\d+):(\d{2}):(\d{2}(?:\.\d+)?)', result.stderr)
    return int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3]) if match else None


def waveform(path, width=1000, cancel=None):
    """Peak amplitude (0-1) for `width` equal slices of the clip, plus its decoded duration."""
    path = Path(path).resolve(strict=True)
    width = max(50, min(4000, int(width)))
    process = subprocess.Popen(
        [
            ffmpeg(),
            '-hide_banner',
            '-nostdin',
            '-loglevel',
            'error',
            '-i',
            str(path),
            '-vn',
            '-ac',
            '1',
            '-ar',
            str(PEAK_RATE),
            '-f',
            's16le',
            '-',
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=NO_WINDOW,
    )
    fine = array('H')
    samples = 0
    rest = b''
    try:
        while True:
            chunk = process.stdout.read(PEAK_BLOCK * 2 * 512)
            if not chunk:
                break
            if cancel is not None and cancel.is_set():
                raise Cancelled('Waveform cancelled')
            chunk = rest + chunk
            usable = len(chunk) - len(chunk) % (PEAK_BLOCK * 2)
            rest = chunk[usable:]
            values = array('h', chunk[:usable])
            samples += len(values)
            for i in range(0, len(values), PEAK_BLOCK):
                block = values[i : i + PEAK_BLOCK]
                fine.append(min(32767, max(max(block), -min(block))))
        if rest:
            values = array('h', rest[: len(rest) // 2 * 2])
            samples += len(values)
            if values:
                fine.append(min(32767, max(max(values), -min(values))))
        error = process.stderr.read().decode('utf8', 'replace').strip()
        if process.wait(30) or not samples:
            raise RuntimeError('Could not decode ' + path.name + (': ' + error.splitlines()[-1] if error else ''))
    finally:
        if process.poll() is None:
            process.kill()
        process.stdout.close()
        process.stderr.close()
    peaks = []
    for i in range(width):
        a = i * len(fine) // width
        b = max(a + 1, (i + 1) * len(fine) // width)
        peaks.append(round(max(fine[a:b]) / 32767, 3) if a < len(fine) else 0)
    return {'peaks': peaks, 'duration': samples / PEAK_RATE}


def crop(source, folder, start, end, name=None):
    """Write the start-end portion of a clip as a new managed library file."""
    source = Path(source).resolve(strict=True)
    start = max(0.0, float(start))
    end = float(end)
    if not end > start:
        raise ValueError('Crop end must be after crop start')
    suffix = source.suffix.lower()
    suffix = suffix if suffix in ['.wav', '.flac', '.mp3'] else '.mp3'
    codec = {'.wav': ['-c:a', 'pcm_s16le'], '.flac': ['-c:a', 'flac'], '.mp3': ['-c:a', 'libmp3lame', '-q:a', '2']}[
        suffix
    ]
    stem = clean_name(
        name
        or (source.stem.split('-', 1)[-1] if len(source.stem.split('-', 1)[0]) == 32 else source.stem) + ' (cropped)'
    )
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (uuid.uuid4().hex + '-' + stem + suffix)
    temp = target.with_suffix('.part' + suffix)
    try:
        result = subprocess.run(
            [
                ffmpeg(),
                '-hide_banner',
                '-nostdin',
                '-loglevel',
                'error',
                '-y',
                '-ss',
                f'{start:.3f}',
                '-i',
                str(source),
                '-t',
                f'{end - start:.3f}',
                '-vn',
                '-map_metadata',
                '-1',
                *codec,
                str(temp),
            ],
            capture_output=True,
            timeout=600,
            creationflags=NO_WINDOW,
        )
        if result.returncode or not temp.is_file() or not temp.stat().st_size:
            raise RuntimeError(
                'Crop failed: ' + (result.stderr.decode('utf8', 'replace').strip().splitlines() or ['ffmpeg error'])[-1]
            )
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return {'path': str(target), 'name': target.name.split('-', 1)[1]}


class YoutubeLogger:
    def debug(self, message):
        pass

    def info(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        pass


def youtube_mp3(url, folder, progress=lambda **state: None, cancel=None):
    """Download one YouTube video's audio and convert it to MP3 in the library folder."""
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled

    url = youtube_url(url)
    cancel = cancel or threading.Event()
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)

    def hook(status):
        if cancel.is_set():
            raise DownloadCancelled('Download cancelled')
        if status.get('status') == 'downloading':
            total = status.get('total_bytes') or status.get('total_bytes_estimate')
            progress(
                state='downloading',
                percent=round(min(99, status.get('downloaded_bytes', 0) * 100 / total)) if total else None,
            )
        elif status.get('status') == 'finished':
            progress(state='converting', percent=100)

    def postprocessing(status):
        if cancel.is_set():
            raise DownloadCancelled('Download cancelled')
        if status.get('status') == 'started':
            progress(state='converting', percent=100)

    with tempfile.TemporaryDirectory(dir=folder.parent, prefix='youtube-') as work:
        options = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'outtmpl': str(Path(work) / '%(id)s.%(ext)s'),
            'ffmpeg_location': ffmpeg(),
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
            'max_filesize': MAX_BYTES,
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'logger': YoutubeLogger(),
            'progress_hooks': [hook],
            'postprocessor_hooks': [postprocessing],
            # YouTube requires a JavaScript runtime; use whichever one is installed.
            'js_runtimes': {'deno': {}, 'node': {}, 'bun': {}, 'quickjs': {}},
        }
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                progress(state='fetching', percent=None)
                info = ydl.extract_info(url, download=False)
                if info.get('_type') in ['playlist', 'multi_video']:
                    raise ValueError('Paste a link to a single video, not a playlist')
                if info.get('is_live'):
                    raise ValueError('Live streams cannot be downloaded')
                if (info.get('duration') or 0) > MAX_SECONDS:
                    raise ValueError('Videos longer than 3 hours are not supported')
                title = clean_name(info.get('title'))
                progress(state='downloading', percent=0, title=title)
                if cancel.is_set():
                    raise DownloadCancelled('Download cancelled')
                ydl.process_ie_result(info, download=True)
        except DownloadCancelled as exc:
            raise Cancelled('Download cancelled') from exc
        except yt_dlp.utils.DownloadError as exc:
            message = re.sub(r'^ERROR:\s*(\[[^\]]+\]\s*)?([\w-]+:\s*)?', '', str(exc)).strip()
            if re.search(r'javascript|format is not available|n challenge|signature', message, re.I):
                message += '. YouTube may need a JavaScript runtime: install Deno (winget install DenoLand.Deno) or Node.js, then restart Studio'
            raise RuntimeError('YouTube download failed: ' + (message or 'unknown error')) from exc
        if cancel.is_set():
            raise Cancelled('Download cancelled')
        produced = next(Path(work).glob('*.mp3'), None)
        if produced is None:
            raise RuntimeError('YouTube download finished without an MP3 (the file may exceed 200 MB)')
        target = folder / (uuid.uuid4().hex + '-' + title + '.mp3')
        shutil.move(str(produced), target)
    return {'path': str(target), 'name': title + '.mp3', 'title': title, 'duration': info.get('duration')}
