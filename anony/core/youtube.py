# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic

import asyncio
import os
import random
import re
from pathlib import Path

import aiohttp
import yt_dlp
from py_yt import Playlist, VideosSearch

from anony import config, logger
from anony.helpers import cache, Track, utils
from ._api import FallenApi


class DummyLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.cookies = []
        self.checked = False
        self.cookie_dir = "anony/cookies"
        self.fallen = FallenApi()
        self.warned = False
        self.regex = re.compile(
            r"(https?://)?(www\.|m\.|music\.)?"
            r"(youtube\.com/(watch\?v=|shorts/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )

    def get_cookies(self):
        if not self.checked:
            if os.path.exists(self.cookie_dir):
                for file in os.listdir(self.cookie_dir):
                    if file.endswith(".txt"):
                        self.cookies.append(f"{self.cookie_dir}/{file}")
            self.checked = True
        if not self.cookies:
            if not self.warned:
                self.warned = True
                logger.warning("Cookies are missing; downloads might fail.")
            return None
        return random.choice(self.cookies)

    async def save_cookies(self, urls: list[str]) -> None:
        logger.info("Saving cookies from urls...")
        os.makedirs(self.cookie_dir, exist_ok=True)
        async with aiohttp.ClientSession() as session:
            for url in urls:
                name = url.split("/")[-1]
                link = "https://batbin.me/raw/" + name
                async with session.get(link) as resp:
                    resp.raise_for_status()
                    with open(f"{self.cookie_dir}/{name}.txt", "wb") as fw:
                        fw.write(await resp.read())
        logger.info(f"Cookies saved in {self.cookie_dir}.")

    def valid(self, url: str) -> bool:
        return bool(re.match(self.regex, url))

    async def search(self, query: str, m_id: int, video: bool = False, retries: int = 5) -> Track | None:
        for attempt in range(1, retries + 1):
            try:
                _search = VideosSearch(query, limit=1, with_live=False)
                results = await _search.next()
            except Exception:
                continue

            try:
                if results and results["result"]:
                    data = results["result"][0]
                    return Track(
                        id=data.get("id"),
                        channel_name=data.get("channel", {}).get("name"),
                        duration=data.get("duration"),
                        duration_sec=utils.to_seconds(data.get("duration")),
                        message_id=m_id,
                        title=data.get("title")[:25],
                        thumbnail=data.get("thumbnails", [{}])[-1].get("url").split("?")[0],
                        url=data.get("link"),
                        view_count=data.get("viewCount", {}).get("short"),
                        video=video,
                    )
            except Exception as ex:
                logger.warning(f"Search attempt failed: {attempt}/{retries}: {ex}")
        return None

    async def get_next(self, id: str) -> Track | None:
        url = f"{self.base}{id}&list=RD{id}"
        try:
            _result = await Playlist.get(url)
            if not _result or not _result.get("videos"):
                return None
            videos = _result.get("videos")
            random.shuffle(videos)
            data = videos[0]
            track = Track(
                id=data.get("id"),
                channel_name=data.get("channel", {}).get("name", ""),
                duration=data.get("duration"),
                duration_sec=utils.to_seconds(data.get("duration")),
                title=data.get("title")[:25],
                thumbnail=data.get("thumbnails")[-1].get("url").split("?")[0],
                url=data.get("link"),
                view_count="",
                video=False,
            )
            return track
        except Exception:
            return None

    async def playlist(self, limit: int, user: str, url: str, video: bool) -> list[Track | None]:
        tracks = []
        try:
            plist = await Playlist.get(url)
            for data in plist["videos"][:limit]:
                track = Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name", ""),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")),
                    title=data.get("title")[:25],
                    thumbnail=data.get("thumbnails")[-1].get("url").split("?")[0],
                    url=data.get("link").split("&list=")[0],
                    user=user,
                    view_count="",
                    video=video,
                )
                tracks.append(track)
        except Exception:
            pass
        return tracks

    async def download(self, video_id: str, video: bool = False, format_quality: str = "360") -> str | None:
        if cached := await cache.fetch_song(video_id):
            return cached

        url = self.base + video_id
        
        # 1. Meow API (FallenApi) ကို ဦးစားပေးအသုံးပြုခြင်း
        if getattr(config, "API_KEY", None):
            if file_path := await self.fallen.download_track(video_id, url, video=video, format_quality=format_quality):
                await cache.handle_dl(file_path, video_id)
                return file_path

        # 2. API အလုပ်မလုပ်ပါက yt_dlp သို့ ဆင်းရန် (Failback)
        ext = "mp4" if video else "webm"
        filename = f"downloads/{video_id}.{ext}"

        if Path(filename).exists():
            return filename

        cookie = self.get_cookies()
        base_opts = {
            "outtmpl": "downloads/%(id)s.%(ext)s",
            "quiet": True,
            "noplaylist": True,
            "geo_bypass": True,
            "no_warnings": True,
            "overwrites": False,
            "logger": DummyLogger(),
            "nocheckcertificate": True,
            "cookiefile": cookie,
            "remote_components": ["ejs:github"],
        }

        if video:
            ydl_opts = {
                **base_opts,
                "format": "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio)",
                "merge_output_format": "mp4",
            }
        else:
            ydl_opts = {
                **base_opts,
                "format": "bestaudio[ext=webm][acodec=opus]",
            }

        def _download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    ydl.download([url])
                except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError):
                    return None
                except Exception as ex:
                    logger.warning("Download failed: %s", ex)
                    return None
            return filename

        filename = await asyncio.to_thread(_download)
        if not filename:
            return None

        try:
            await cache.handle_dl(filename, video_id)
        except Exception:
            pass
        return filename
