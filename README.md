# YouTube Downloader

A Python CLI application for downloading audio from YouTube playlists and individual videos using the YouTube Data API v3.

## Features

- Download audio from entire YouTube playlists
- Download audio from individual videos
- Multiple audio format support (mp3, m4a, webm, opus)
- Configurable audio quality/bitrate
- View playlist contents and video metadata
- Check available audio formats for videos
- Interactive and CLI modes
- Progress tracking and detailed error reporting

## Prerequisites

- Python 3.7+
- YouTube Data API v3 key
- FFmpeg (for audio conversion)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/youtube-downloader.git
cd youtube-downloader
```

2. Install dependencies:
```bash
pip install requests yt-dlp
```

3. Configure your YouTube API key (see [creds.py](creds.py))

## Usage

### Interactive Mode

Run without arguments to enter interactive mode:
```bash
python main.py
```

### CLI Mode

**Download a playlist:**
```bash
python main.py download "https://youtube.com/playlist?list=PLxxx..."
```

**Download with custom options:**
```bash
python main.py download "PLxxx..." -o ./music -f m4a -q 256
```

**Download a single video:**
```bash
python main.py single "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

**List videos in a playlist:**
```bash
python main.py list "https://youtube.com/playlist?list=PLxxx..."
```

**Get available audio formats:**
```bash
python main.py formats dQw4w9WgXcQ
```

## Command Options

- `-o, --output`: Output folder path (default: ./downloads)
- `-f, --format`: Audio format (default: mp3)
- `-q, --quality`: Audio quality/bitrate (default: 192)
- `--quiet`: Suppress progress output
- `-d, --details`: Show detailed video information (list command)
- `-m, --max`: Maximum number of videos to fetch (list command)

## License

This project is provided as-is for educational purposes.

## Disclaimer

Please respect YouTube's Terms of Service and copyright laws when using this tool.
