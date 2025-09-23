import glob
import html
import json
import os
import re
import sys
import time
import zipfile
import mutagen
import pyrfc6266
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass
from datetime import datetime
from http.cookiejar import MozillaCookieJar
from typing import Dict, List, Literal, Optional, Tuple, TypedDict, Union
from urllib.parse import urljoin
from guerrillamail import GuerrillaMailSession
from urllib3 import Retry
from .bandcamp_http_adapter import BandcampHTTPAdapter
TralbumId = Tuple[Literal["album", "track", "url"], Union[int, str]]
class DownloadRet(TypedDict):
    id: TralbumId
    file_name: str
class AlbumInfo(TypedDict):
    tralbum_data: Dict
    head_data: Dict
    is_downloaded: Optional[bool]
    email_queued: Optional[bool]
    file_name: Optional[str]
    error: Optional[str]
class LabelReleaseInfo(TypedDict):
    type: str
    id: TralbumId
    band_id: int
    url: str
    release_info: Optional[AlbumInfo]
class LabelInfo(TypedDict):
    label_info: Dict
    releases: List[LabelReleaseInfo]
class PageInfo(TypedDict):
    type: Literal["album", "song", "band"]
    info: LabelInfo | AlbumInfo
@dataclass
class BCFreeDownloaderOptions:
    country: str = "United States"
    zipcode: str = "00000"
    email: str = "auto"
    format: str = "FLAC"
    dir: str = "."
    cookies: Optional[str] = None
    identity: Optional[str] = None
class BCFreeDownloader:
    CHUNK_SIZE = 1024 * 1024
    LINK_REGEX = re.compile(r'<a href="(?P<url>https://bandcamp.com/download[^"]*)">')
    STAT_DL_REGEX = re.compile(r'var _statDL_result = (.+);')
    RETRY_URL_REGEX = re.compile(r'"retry_url":"(?P<retry_url>[^"]*)"')
    FORMATS = {
        "FLAC": "flac",
        "V0MP3": "mp3-v0",
        "320MP3": "mp3-320",
        "AAC": "aac-hi",
        "Ogg": "vorbis",
        "ALAC": "alac",
        "WAV": "wav",
        "AIFF": "aiff-lossless",
    }
    def __init__(self, options: BCFreeDownloaderOptions):
        self.options = options
        self.mail_session = None
        self.session = None
        self.email = None
        self._init_session()
    def _init_email(self):
        if not self.options.email:
            self.options.email = "auto"
        if self.options.email == "auto":
            self.mail_session = GuerrillaMailSession()
            self.options.email = self.mail_session.get_session_state()["email_address"]
    def _init_session(self):
        self.session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        self.session.headers.update(headers)
        retries = Retry(
            total=10, backoff_factor=10, backoff_max=60, allowed_methods={"POST", "GET"}
        )
        self.session.mount("https://", BandcampHTTPAdapter(max_retries=retries))
        if self.options.cookies:
            cj = MozillaCookieJar(self.options.cookies)
            cj.load()
            self.session.cookies = cj
        if self.options.identity:
            self.session.cookies.set("identity", self.options.identity)
    def _get_fresh_retry_url(self, initial_download_url: str) -> Optional[str]:
        stat_url = initial_download_url.replace("/download/", "/statdownload/")
        try:
            stat_response = self.get_url(stat_url)
            if not stat_response:
                return None
            match = self.STAT_DL_REGEX.search(stat_response.text)
            if not match:
                return None
            stat_data = json.loads(match.group(1))
            retry_url = stat_data.get("retry_url")
            if not retry_url:
                return None
            return retry_url
        except Exception:
            return None
    def _download_file(self, download_page_url: str, format: str, progress_callback=None) -> Optional[DownloadRet]:
        try:
            soup = self.get_url_soup(download_page_url)
            if not soup:
                return None
            pagedata_div = soup.find("div", {"id": "pagedata"})
            if not pagedata_div:
                return None
            data = json.loads(pagedata_div["data-blob"])["digital_items"][0]
            initial_download_url = data["downloads"][self.FORMATS[format]]["url"]
            item_id = (data["type"], int(data["item_id"]))
            headers = {"Referer": download_page_url}
            download_url = self._get_fresh_retry_url(initial_download_url)
            if not download_url:
                download_url = initial_download_url
            name_response = requests.get(download_url, headers=headers, stream=True, timeout=30)
            name_response.raise_for_status()
            name = pyrfc6266.requests_response_to_filename(name_response)
            name_response.close()
            file_name = os.path.join(self.options.dir, name)
            tmp_file_name = file_name + ".tmp"
            downloaded_bytes = 0
            mode = 'wb'
            if os.path.exists(tmp_file_name):
                downloaded_bytes = os.path.getsize(tmp_file_name)
                headers['Range'] = f'bytes={downloaded_bytes}-'
                mode = 'ab'
            response = self.session.get(download_url, stream=True, allow_redirects=True, headers=headers, timeout=30)
            response.raise_for_status()
            with response:
                total_size = int(response.headers.get("content-length", 0)) + downloaded_bytes
                with open(tmp_file_name, mode) as f:
                    if progress_callback and downloaded_bytes == 0:
                        progress_callback(name, downloaded_bytes, total_size)
                    for chunk in response.iter_content(chunk_size=self.CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                            downloaded_bytes += len(chunk)
                            if progress_callback:
                                progress_callback(name, downloaded_bytes, total_size)
            if total_size != 0 and downloaded_bytes != total_size:
                try:
                    os.remove(tmp_file_name)
                except OSError:
                    pass
                return None
            if os.path.exists(file_name):
                os.remove(file_name)
            os.rename(tmp_file_name, file_name)
            return {"id": item_id, "file_name": file_name}
        except Exception as e:
            return None
    @staticmethod
    def unzip_album(file_name: str) -> List[str]:
        dir_name = file_name[:-4]
        with zipfile.ZipFile(file_name, "r") as f:
            f.extractall(dir_name)
        os.remove(file_name)
        return glob.glob(os.path.join(dir_name, "*"))
    @staticmethod
    def tag_file(file_name: str, head_data: Dict):
        try:
            f = mutagen.File(file_name)
            if f is None:
                return
            f["website"] = head_data["@id"]
            if head_data.get("keywords"):
                f["genre"] = head_data["keywords"]
            comment = ""
            comment += head_data.get("description", "").strip()
            comment += "\n\n" + head_data.get("creditText", "")
            f["comment"] = comment.strip()
            f.save()
        except Exception:
            pass
    def _download_purchased_album(self, user_id: int, tralbum_data: Dict, progress_callback=None) -> Optional[DownloadRet]:
        data = {
            "fan_id": user_id,
            "search_key": tralbum_data["current"]["title"],
            "search_type": "collection",
        }
        results = self.post_url_json("https://bandcamp.com/api/fancollection/1/search_items", json=data)
        if not results:
            return None
        tralbums = results.get("tralbums", [])
        redownload_urls = results.get("redownload_urls", {})
        wanted_id = f"{tralbum_data['item_type'][0]}:{tralbum_data['id']}"
        tralbum = next((t for t in tralbums if f"{t.get('tralbum_type')}:{t.get('tralbum_id')}" == wanted_id), None)
        if not tralbum:
            return None
        sale_id = f"{tralbum.get('sale_item_type')}{tralbum.get('sale_item_id')}"
        download_url = redownload_urls.get(sale_id)
        if not download_url:
            return None
        return self._download_file(download_url, self.options.format, progress_callback)
    def download_album(self, album_url: str, progress_callback=None) -> AlbumInfo:
        soup = self.get_url_soup(album_url)
        if not soup:
            return {"error": "Could not fetch album page soup"}
        album_info = self.get_album_info(soup)
        if not album_info:
            return {"error": "Could not parse album info"}
        tralbum_data = album_info.get("tralbum_data", {})
        album_info["is_downloaded"] = False
        album_info["email_queued"] = False
        if not tralbum_data.get("hasAudio"):
            album_info["error"] = "Track has no audio"
            return album_info
        head_id = album_info.get("head_data", {}).get("@id")
        album_release_parent = album_info.get("head_data", {}).get("inAlbum", album_info.get("head_data", {}))
        album_release_list = album_release_parent.get("albumRelease", [])
        album_release = next((obj for obj in album_release_list if obj.get("@id") == head_id), None)
        if tralbum_data.get("freeDownloadPage"):
            download_page_url = tralbum_data.get("freeDownloadPage")
            dl_ret = self._download_file(download_page_url, self.options.format, progress_callback)
            if dl_ret:
                album_info["is_downloaded"] = True
                album_info["file_name"] = dl_ret["file_name"]
            else:
                album_info["error"] = "Download failed"
        elif tralbum_data.get("is_purchased"):
            collection_info_json = soup.find("script", {"data-tralbum-collect-info": True}).attrs["data-tralbum-collect-info"]
            collection_info = json.loads(collection_info_json)
            dl_ret = self._download_purchased_album(collection_info["fan_id"], tralbum_data, progress_callback)
            if dl_ret:
                album_info["is_downloaded"] = True
                album_info["file_name"] = dl_ret["file_name"]
            else:
                album_info["error"] = "Failed to download from collection"
        elif album_release and album_release.get("offers", {}).get("price") == 0.0:
            if self.mail_session is None:
                self._init_email()
            album_info["email_queued"] = True
        else:
            album_info["error"] = "Not free and not in collection. Use --cookies/--identity if purchased"
        return album_info
    def request_email_download(self, album_info: AlbumInfo) -> bool:
        tralbum_data = album_info["tralbum_data"]
        url = tralbum_data["url"]
        email_post_url = urljoin(url, "/email_download")
        r = self.post_url_json(
            email_post_url,
            data={
                "encoding_name": "none",
                "item_id": tralbum_data["current"]["id"],
                "item_type": tralbum_data["current"]["type"],
                "address": self.options.email,
                "country": self.options.country,
                "postcode": self.options.zipcode,
            },
        )
        return r and r.get("ok")
    def await_download_email(self, request_timestamp: float, wait_timeout: int = 30, status_callback=None) -> Optional[str]:
        checked_ids = set()
        start_time = time.time()
        if status_callback:
            status_callback("Status: Waiting for download email...")
        while time.time() - start_time < wait_timeout:
            offset = 0
            while True:
                emails = self.mail_session.get_email_list(offset=offset)
                if not emails:
                    break
                for email in emails:
                    email_id = email.guid
                    if email_id in checked_ids:
                        continue
                    checked_ids.add(email_id)
                    if (
                        email.sender == "noreply@bandcamp.com"
                        and "download" in email.subject
                        and email.datetime.timestamp() >= request_timestamp
                    ):
                        content = self.mail_session.get_email(email_id).body
                        match = self.LINK_REGEX.search(content)
                        if match:
                            return match.group("url")
                if len(emails) >= 20:
                    offset += 20
                else:
                    break
            time.sleep(3)
        return None
    def get_url(self, url: str, **kwargs) -> Optional[requests.Response]:
        try:
            r = self.session.get(url, **kwargs, timeout=30)
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            return None
    def get_url_soup(self, url: str, **kwargs) -> Optional[BeautifulSoup]:
        response = self.get_url(url, **kwargs)
        if response:
            return BeautifulSoup(response.text, "html.parser")
        return None
    def get_url_info(self, url: str, **kwargs) -> Optional[PageInfo]:
        soup = self.get_url_soup(url, **kwargs)
        if soup:
            return self.get_page_info(soup)
        return None
    def post_url(self, url: str, **kwargs) -> Optional[requests.Response]:
        try:
            r = self.session.post(url, **kwargs, timeout=30)
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            return None
    def post_url_json(self, url: str, **kwargs) -> Optional[Dict]:
        response = self.post_url(url, **kwargs)
        if response:
            try:
                return response.json()
            except json.JSONDecodeError as e:
                return None
        return None
    @staticmethod
    def get_page_info(soup: BeautifulSoup) -> Optional[PageInfo]:
        page_type_tag = soup.head.find("meta", attrs={"property": "og:type"})
        if not page_type_tag:
            return None
        page_type = page_type_tag.get("content")
        if page_type in ("album", "song"):
            info = BCFreeDownloader.get_album_info(soup)
            if info:
                return {"type": page_type, "info": info}
        elif page_type == "band":
            info = BCFreeDownloader.get_label_info(soup)
            if info:
                return {"type": page_type, "info": info}
        return None
    @staticmethod
    def get_label_info(soup: BeautifulSoup) -> Optional[LabelInfo]:
        label_info_tag = soup.find("script", attrs={"data-band": True})
        if label_info_tag is None:
            return None
        label_info = json.loads(label_info_tag["data-band"])
        releases = []
        local_url = label_info["local_url"]
        grid = soup.find("ol", id="music-grid")
        if not grid:
            return {"label_info": label_info, "releases": []}
        for li in grid.find_all("li"):
            if "display:none" in li.get("style", ""):
                continue
            data = li.get("data-item-id", "").split("-")
            if len(data) < 2:
                continue
            releases.append(
                {
                    "type": data[0],
                    "id": int(data[1]),
                    "url": li.a["href"],
                    "band_id": int(li["data-band-id"]),
                }
            )
        client_items = grid.get("data-client-items")
        if client_items:
            for obj in json.loads(html.unescape(client_items)):
                if obj.get("filtered"):
                    continue
                obj["url"] = obj.pop("page_url")
                releases.append(obj)
        for release in releases:
            if release["url"].startswith("/"):
                release["url"] = urljoin(local_url, release["url"])
        return {"label_info": label_info, "releases": releases}
    @staticmethod
    def get_album_info(soup: BeautifulSoup) -> Optional[AlbumInfo]:
        try:
            tralbum_data_tag = soup.find("script", {"data-tralbum": True})
            head_data_tag = soup.head.find("script", {"type": "application/ld+json"}, recursive=False)
            if not tralbum_data_tag or not head_data_tag:
                return None
            tralbum_data = json.loads(tralbum_data_tag.attrs["data-tralbum"])
            head_data = json.loads(head_data_tag.string)
            return {"tralbum_data": tralbum_data, "head_data": head_data}
        except (json.JSONDecodeError, AttributeError):
            return None
