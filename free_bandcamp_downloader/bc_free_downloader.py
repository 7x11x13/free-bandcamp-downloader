import glob
import html
import json
import os
import re
import time
import zipfile
import mutagen
import pyrfc6266
import requests

from bs4 import BeautifulSoup
from tqdm import tqdm
from dataclasses import dataclass
from http.cookiejar import MozillaCookieJar
from typing import Dict, List, Literal, Optional, Tuple, TypedDict, Union
from urllib.parse import urljoin
from guerrillamail import GuerrillaMailSession
from urllib3 import Retry

from free_bandcamp_downloader import logger
from free_bandcamp_downloader.bandcamp_http_adapter import BandcampHTTPAdapter

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


class BCFreeDownloadError(Exception):
    pass


class BCFreeDownloader:
    CHUNK_SIZE = 1024 * 1024
    LINK_REGEX = re.compile(r'<a href="(?P<url>[^"]*)">')
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
        self.queued_emails: Dict[TralbumId, AlbumInfo] = {}
        self.session = None
        self.email = None
        self._init_session()

    def _init_email(self):
        logger.info("Starting mail session...")
        if not self.options.email:
            self.options.email = "auto"
        if self.options.email == "auto":
            self.mail_session = GuerrillaMailSession()
            self.options.email = self.mail_session.get_session_state()["email_address"]

    def _init_session(self):
        self.session = requests.Session()
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

    def _download_file(self, download_page_url: str, format: str) -> DownloadRet:
        soup = self.get_url_soup(download_page_url)

        data = json.loads(soup.find("div", {"id": "pagedata"}).attrs["data-blob"])[
            "digital_items"
        ][0]
        download_url = data["downloads"][self.FORMATS[format]]["url"]
        id = (data["type"], int(data["item_id"]))

        def download(download_url: str) -> str:
            with self.get_url(download_url, stream=True) as r:
                size = int(r.headers["content-length"])
                name = pyrfc6266.requests_response_to_filename(r)
                file_name = os.path.join(self.options.dir, name)
                with tqdm(total=size, unit="iB", unit_scale=True) as pbar:
                    with open(file_name, "wb") as f:
                        for chunk in r.iter_content(chunk_size=self.CHUNK_SIZE):
                            f.write(chunk)
                            pbar.update(len(chunk))
                return file_name

        try:
            file_name = download(download_url)
        except Exception:
            statdownload_url = download_url.replace("/download/", "/statdownload/")
            with self.get_url(statdownload_url) as r:
                download_url = self.RETRY_URL_REGEX.search(r.text).group("retry_url")
            if download_url:
                file_name = download(download_url)
            else:
                # retry requires email address
                raise BCFreeDownloadError(
                    "Download expired. Make sure your payment email is linked "
                    "to your fan account (Settings > Fan > Payment email addresses)"
                )

        logger.info(f"Downloaded {file_name}")

        return {"id": id, "file_name": file_name}

    # unzip the provided file and return all file paths
    @staticmethod
    def unzip_album(file_name: str) -> List[str]:
        dir_name = file_name[:-4]
        with zipfile.ZipFile(file_name, "r") as f:
            f.extractall(dir_name)
        logger.info(f"Unzipped {file_name}.")
        os.remove(file_name)
        return glob.glob(os.path.join(dir_name, "*"))

    # Tag downloaded audio file with url & comment
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
            # only should happen if the file doesn't support tags
            pass

    def _download_purchased_album(
        self, user_id: int, tralbum_data: Dict
    ) -> DownloadRet:
        logger.info("Downloading album from collection...")
        logger.debug(f"Searching for album: '{tralbum_data['current']['title']}'")
        data = {
            "fan_id": user_id,
            "search_key": tralbum_data["current"]["title"],
            "search_type": "collection",
        }
        results = self.post_url_json(
            "https://bandcamp.com/api/fancollection/1/search_items", json=data
        )
        tralbums = results["tralbums"]
        redownload_urls = results["redownload_urls"]
        wanted_id = f"{tralbum_data['item_type'][0]}:{tralbum_data['id']}"
        try:
            tralbum = next(
                filter(
                    lambda tralbum: f"{tralbum['tralbum_type']}:{tralbum['tralbum_id']}"
                    == wanted_id,
                    tralbums,
                )
            )
        except StopIteration:
            raise BCFreeDownloadError("Could not find album in collection")
        sale_id = f"{tralbum['sale_item_type']}{tralbum['sale_item_id']}"
        if sale_id not in redownload_urls:
            raise BCFreeDownloadError("Could not find album download URL in collection")
        download_url = redownload_urls[sale_id]
        logger.debug(f"Got download URL: {download_url}")
        return self._download_file(download_url, self.options.format)

    # download from release page
    def download_album(self, soup: BeautifulSoup) -> AlbumInfo:
        album_data = BCFreeDownloader.get_album_info(soup)
        tralbum_data = album_data["tralbum_data"]
        head_data = album_data["head_data"]
        album_data["is_downloaded"] = False
        album_data["email_queued"] = False
        url = tralbum_data["url"]

        logger.debug(f"tralbum data: {tralbum_data}")
        logger.debug(f"album head data: {head_data}")

        if not tralbum_data["hasAudio"]:
            logger.error(f"{url} has no audio.")
            return album_data

        head_id = head_data.get("@id")
        # fallback if a track link was provided
        # track releases have this inAlbum key even if they're standalone
        album_release = head_data.get("inAlbum", head_data)["albumRelease"]
        # find the albumRelease object that matches the overall album @id link
        # this will ensure that strictly the page release is downloaded
        album_release = next(obj for obj in album_release if obj["@id"] == head_id)

        if "offers" not in album_release:
            logger.error(f"{url} has no available offers.")

        if tralbum_data["freeDownloadPage"]:
            logger.info(f"{url} does not require email")
            dlret = self._download_file(
                tralbum_data["freeDownloadPage"], self.options.format
            )
        elif "offers" in album_release and album_release["offers"]["price"] == 0.0:
            logger.info(f"{url} requires email")
            if self.mail_session is None:
                self._init_email()
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

            if not r["ok"]:
                raise ValueError(f"Bad response when sending email address: {r}")
            type = tralbum_data["current"]["type"]
            id = tralbum_data["current"]["id"]
            album_data["email_queued"] = True
            self.queued_emails[(type, id)] = album_data
            return album_data
        elif tralbum_data["is_purchased"]:
            collection_info = soup.find(
                "script", {"data-tralbum-collect-info": True}
            ).attrs["data-tralbum-collect-info"]
            collection_info = json.loads(collection_info)
            dlret = self._download_purchased_album(
                collection_info["fan_id"], tralbum_data
            )
        else:
            logger.error(
                f"{url} is not free. If you have purchased this album, "
                "use the --cookies flag or --identity flag to pass your login cookie."
            )
            return album_data

        album_data["is_downloaded"] = True
        album_data["file_name"] = dlret["file_name"]

        return album_data

    # unconditionally download from release page
    def download_label(self, soup: BeautifulSoup) -> LabelInfo:
        info = BCFreeDownloader.get_label_info(soup)

        for release in info["releases"]:
            logger.info(f"Downloading {release['url']}")

            soup = self.get_url_soup(release["url"])
            try:
                ret = self.download_album(soup)
                release["release_info"] = ret
            except BCFreeDownloadError as ex:
                logger.info(ex)

        return info

    # unconditionally downloads the provided url
    # returns either the result of download_album or download_label
    # with the `page_type` set to album|song|band
    # exception if download error
    def download_url(self, url: str):
        soup = self.get_url_soup(url)

        page_info = self.get_page_info(soup)
        page_type = page_info.get("type")
        if page_type == "album" or page_type == "song":
            ret = self.download_album(soup)
        else:
            ret = self.download_label(soup)

        ret["page_type"] = page_type

        return ret

    def flush_email_downloads(self) -> List[AlbumInfo]:
        checked_ids = set()
        downloaded = []
        while len(self.queued_emails) > 0:
            logger.info(
                f"Waiting for {len(self.queued_emails)} emails from Bandcamp..."
            )
            time.sleep(5)
            for email in self.mail_session.get_email_list():
                email_id = email.guid
                if email_id in checked_ids:
                    continue

                checked_ids.add(email_id)
                if (
                    email.sender == "noreply@bandcamp.com"
                    and "download" in email.subject
                ):
                    logger.info(f'Received email "{email.subject}"')
                    content = self.mail_session.get_email(email_id).body
                    match = self.LINK_REGEX.search(content)
                    if match:
                        download_url = match.group("url")
                        dlret = self._download_file(download_url, self.options.format)
                        self.queued_emails[dlret["id"]]["file_name"] = dlret[
                            "file_name"
                        ]
                        downloaded.append(self.queued_emails[dlret["id"]])
                        self.queued_emails.pop(dlret["id"])
                    else:
                        logger.error(f"Could not find download URL in body: {content}")
        return downloaded

    # get_url_x can't be staticmethods because of special session context
    def get_url(self, url: str, **kwargs) -> requests.Response:
        r = self.session.get(url, **kwargs)
        r.raise_for_status()
        return r

    def get_url_soup(self, url: str, **kwargs) -> BeautifulSoup:
        return BeautifulSoup(self.get_url(url, **kwargs).text, "html.parser")

    def get_url_info(self, url: str, **kwargs) -> PageInfo:
        soup = self.get_url_soup(url, **kwargs)
        try:
            return self.get_page_info(soup)
        except Exception:
            raise BCFreeDownloadError(f"Could not get page info for {url}")

    def post_url(self, url: str, **kwargs) -> requests.Response:
        r = self.session.post(url, **kwargs)
        r.raise_for_status()
        return r

    def post_url_json(self, url: str, **kwargs) -> Dict:
        return self.post_url(url, **kwargs).json()

    # get the album/label info of a bandcamp page
    @staticmethod
    def get_page_info(soup: BeautifulSoup) -> PageInfo:
        page_type = soup.head.find("meta", attrs={"property": "og:type"}).get("content")

        if page_type == "album" or page_type == "song":
            return {"type": page_type, "info": BCFreeDownloader.get_album_info(soup)}
        if page_type == "band":
            return {"type": page_type, "info": BCFreeDownloader.get_label_info(soup)}
        else:
            # only bandcamp pages are supported
            raise BCFreeDownloadError("Page does not have a valid og:type value")

    @staticmethod
    def get_label_info(soup: BeautifulSoup) -> LabelInfo:
        label_info = soup.find("script", attrs={"data-band": True})
        if label_info is None:
            raise BCFreeDownloadError("Page has no data-band script.")
        label_info = json.loads(label_info["data-band"])

        releases = []
        # needed for releases
        local_url = label_info["local_url"]

        # bandcamp splits the release between this music-grid html and some json blob
        grid = soup.find("ol", id="music-grid")
        for li in grid.find_all("li"):
            if "display:none" in li.get("style", ""):
                continue

            data = li["data-item-id"].split("-")
            # most important fields
            releases.append(
                {
                    "type": data[0],
                    "id": int(data[1]),
                    "url": li.a["href"],
                    "band_id": int(li["data-band-id"]),
                }
            )
        for obj in json.loads(html.unescape(grid.get("data-client-items", {}))):
            if obj.get("filtered"):
                continue
            # normalize to fit the other half
            obj["url"] = obj.pop("page_url")
            releases.append(obj)

        # fixup local urls into global ones
        for release in releases:
            if release["url"][0] == "/":
                release["url"] = urljoin(local_url, release["url"])

        return {"label_info": label_info, "releases": releases}

    @staticmethod
    def get_album_info(soup: BeautifulSoup) -> AlbumInfo:
        tralbum_data = soup.find("script", {"data-tralbum": True}).attrs["data-tralbum"]
        tralbum_data = json.loads(tralbum_data)
        head_data = soup.head.find(
            "script", {"type": "application/ld+json"}, recursive=False
        ).string
        head_data = json.loads(head_data)

        return {"tralbum_data": tralbum_data, "head_data": head_data}
