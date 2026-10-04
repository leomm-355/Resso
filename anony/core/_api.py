# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic

import asyncio
import os
import urllib.parse
from pathlib import Path
import aiohttp
import aiofiles

from anony import config, logger


class FallenApi:
    def __init__(self, retries: int = 3, timeout: int = 25):
        self.primary_url = "https://Music.yukiapi.site".rstrip("/")
        self.fallback_url = "https://Play.yukiapi.site".rstrip("/")
        self.api_key = getattr(config, "API_KEY", "yuki_766da48bba725e5d13355c4a1285a019")
        self.retries = retries
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.download_dir = Path("downloads")
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def _get_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": "AnonXMusic-Bot",
        }

    async def get_session(self) -> None:
        """__main__.py မှ ခေါ်ဆိုသော session initialize လုပ်ရန် method"""
        pass

    async def _make_request(self, session: aiohttp.ClientSession, endpoint: str) -> str | None:
        urls = [f"{self.primary_url}{endpoint}", f"{self.fallback_url}{endpoint}"]
        
        for base_url in urls:
            if "?" in base_url:
                url = f"{base_url}&key={self.api_key}"
            else:
                url = f"{base_url}?key={self.api_key}"

            for attempt in range(1, self.retries + 1):
                try:
                    async with session.get(url, headers=self._get_headers()) as resp:
                        if resp.status == 200:
                            try:
                                data = await resp.json()
                                if isinstance(data, dict):
                                    return data.get("url") or data.get("cdnurl") or data.get("stream")
                            except Exception:
                                pass
                            return str(resp.url)
                        
                        logger.warning(f"[API ERROR] {base_url} returned status {resp.status}")
                        break
                except asyncio.TimeoutError:
                    logger.warning(f"[TIMEOUT] Attempt {attempt} for {base_url} timed out.")
                except Exception as e:
                    logger.warning(f"[NETWORK ERROR] Attempt {attempt} for {base_url} failed: {e}")
                
                await asyncio.sleep(2)
        return None

    async def download_track(self, video_id: str, url: str = None, video: bool = False, format_quality: str = "360") -> str | None:
        if video:
            endpoint = f"/stream/{video_id}?format={format_quality}"
        else:
            endpoint = f"/stream/{video_id}"

        ext = "mp4" if video else "webm"
        save_path = self.download_dir / f"{video_id}_{format_quality if video else 'audio'}.{ext}"

        if save_path.exists() and save_path.stat().st_size > 0:
            return str(save_path)

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            stream_url = await self._make_request(session, endpoint)
            if not stream_url:
                logger.warning(f"[{video_id}]: All Meow API endpoints failed to fetch stream URL.")
                return None

            try:
                async with session.get(stream_url) as resp:
                    if resp.status != 200:
                        logger.warning(f"Failed to download stream content: [HTTP {resp.status}]")
                        return None
                    
                    async with aiofiles.open(save_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(16 * 1024):
                            if chunk:
                                await f.write(chunk)
                                
                    if save_path.stat().st_size == 0:
                        save_path.unlink(missing_ok=True)
                        return None
                        
                    return str(save_path)
            except Exception as e:
                logger.warning(f"[DOWNLOAD ERROR] {video_id}: {e}")
                if save_path.exists():
                    save_path.unlink(missing_ok=True)
                return None
