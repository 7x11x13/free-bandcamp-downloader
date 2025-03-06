"""Download free albums and tracks from Bandcamp
Usage:
    bcdl-free [--debug] [--force] [--no-unzip] [-al]
        [-d <dir>] [-e <email>] [-z <zipcode>] [-c <country>] [-f <format>]
        [--cookies <file>] [--identity <value>] URL...
    bcdl-free setdefault [-d <dir>] [-e <email>] [-z <zipcode>]
        [-c <country>] [-f <format>]
    bcdl-free defaults
    bcdl-free clear
    bcdl-free -h | --help | --version

Arguments:
    URL            URL to download. Can be a link to a label or release page

Subcommands:
    defaults       list default configuration options
    setdefaults    set default configuration options
    clear          clear default configuration options

Options:
    -h --help                            Show this screen
    --version                            Show version
    --force                              Download even if album has been downloaded before
    --no-unzip                           Don't unzip downloaded albums
    --debug                              Set loglevel to debug
    -a -l                                Dummy options, for backwards compatibility
    -d <dir> --dir <dir>                 Set download directory
    -c <country> --country <country>     Set country
    -z <zipcode> --zipcode <zipcode>     Set zipcode
    -e <email> --email <email>           Set email (set to 'auto' to automatically download from a disposable email)
    -f <format> --format <format>        Set format
    --cookies <file>                     Path to cookies.txt file so albums in your collection can be downloaded
    --identity <value>                   Value of identity cookie so albums in your collection can be downloaded

Formats:
    - FLAC
    - V0MP3
    - 320MP3
    - AAC
    - Ogg
    - ALAC
    - WAV
    - AIFF
"""

import atexit
import dataclasses
import glob
import html
import json
import logging
import os
import pprint
import re
import sys
import time
import zipfile
from configparser import ConfigParser
from dataclasses import dataclass
from http.cookiejar import MozillaCookieJar
from typing import Dict, Optional, Set
from urllib.parse import urljoin, urlsplit

import mutagen
import pyrfc6266
import requests
import secmail
from bs4 import BeautifulSoup
from docopt import docopt
from tqdm import tqdm

from free_bandcamp_downloader import __version__, logger
from free_bandcamp_downloader.bandcamp_http_adapter import BandcampHTTPAdapter


@dataclass
class BCFreeDownloaderOptions:
    country: str = None
    zipcode: str = None
    email: str = None
    format: str = None
    dir: str = None


@dataclass
class BCFreeDownloaderAlbumData:
    about: str = None
    credits: str = None
    tags: str = None
    id: str = None
    title: str = None


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

    def __init__(
        self,
        options: BCFreeDownloaderOptions,
        config_dir: str,
        download_history_file: str,
        unzip: bool = True,
        cookies_file: Optional[str] = None,
        identity: Optional[str] = None,
    ):
        self.options = options
        self.config_dir = config_dir
        self.download_history_file = download_history_file
        self.downloaded: Set[str] = set()  # can be URL or ID
        self.mail_session = None
        self.mail_album_data: Dict[str, BCFreeDownloaderAlbumData] = {}
        self.unzip = unzip
        self.session = None
        self._init_downloaded()
        self._init_session(cookies_file, identity)

    def _init_email(self):
        self.mail_session = secmail.Client(self.config_dir)
        self.options.email = self.mail_session.random_email(1, "1secmail.com")[0]

    def _init_downloaded(self):
        if self.download_history_file:
            with open(self.download_history_file, "r") as f:
                for line in f:
                    self.downloaded.add(line.strip())

    def _init_session(self, cookies_file: Optional[str], identity: Optional[str]):
        self.session = requests.Session()
        self.session.mount("https://", BandcampHTTPAdapter())
        if cookies_file:
            cj = MozillaCookieJar(cookies_file)
            cj.load()
            self.session.cookies = cj
        if identity:
            self.session.cookies.set("identity", identity)

    def _download_file(
        self,
        download_page_url: str,
        format: str,
        album_data: Optional[BCFreeDownloaderAlbumData] = None,
    ) -> str:
        r = self.session.get(download_page_url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        album_url = soup.find("div", class_="download-artwork").find("a").attrs["href"]
        if album_data is None:
            r = self.session.get(album_url)
            r.raise_for_status()
            id = self._get_album_data_from_soup(BeautifulSoup(r.text, "html.parser")).id
            album_data = self.mail_album_data[id]

        data = json.loads(soup.find("div", {"id": "pagedata"}).attrs["data-blob"])
        download_url = data["digital_items"][0]["downloads"][self.FORMATS[format]][
            "url"
        ]

        def download(download_url: str) -> str:
            with self.session.get(download_url, stream=True) as r:
                r.raise_for_status()
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
            with self.session.get(statdownload_url) as r:
                r.raise_for_status()
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

        if file_name.endswith("zip") and self.unzip:
            # Unzip archive
            dir_name = file_name[:-4]
            with zipfile.ZipFile(file_name, "r") as f:
                f.extractall(dir_name)
            logger.info(f"Unzipped to {dir_name}. Use --no-unzip to prevent this")
            os.remove(file_name)
            files = glob.glob(os.path.join(dir_name, "*"))
        else:
            files = [file_name]
        # Tag downloaded audio files with url & comment
        logger.info("Setting tags...")
        for file in files:
            f = mutagen.File(file)
            if f is None:
                continue
            f["website"] = album_url
            if album_data.tags:
                f["genre"] = album_data.tags
            comment = ""
            if album_data.about:
                comment += album_data.about
            if album_data.about and album_data.credits:
                comment += "\n\n"
            if album_data.credits:
                comment += album_data.credits
            f["comment"] = comment
            f.save()
        # successfully downloaded file, add to download history
        self.downloaded.add(album_data.id)
        if self.download_history_file:
            with open(self.download_history_file, "a") as f:
                f.write(f"{album_data.id}\n")

        return album_data.id

    @staticmethod
    def _get_album_data_from_soup(soup: BeautifulSoup) -> BCFreeDownloaderAlbumData:
        album_data = BCFreeDownloaderAlbumData()
        about = soup.find("div", class_="tralbum-about")
        credits = soup.find("div", class_="tralbum-credits")
        tags = [tag.get_text() for tag in soup.find_all("a", class_="tag")]
        properties = json.loads(
            soup.find("meta", attrs={"name": "bc-page-properties"})["content"]
        )
        id = f"{properties['item_type']}:{properties['item_id']}"

        album_data.about = about.get_text("\n") if about else None
        album_data.credits = credits.get_text("\n") if credits else None
        album_data.tags = ",".join(sorted(tags))
        album_data.id = id

        return album_data

    def _download_purchased_album(
        self, user_id: int, album_data: BCFreeDownloaderAlbumData
    ):
        logger.info("Downloading album from collection...")
        logger.debug(f"Searching for album: '{album_data.title}'")
        data = {
            "fan_id": user_id,
            "search_key": album_data.title,
            "search_type": "collection",
        }
        r = self.session.post(
            "https://bandcamp.com/api/fancollection/1/search_items", json=data
        )
        r.raise_for_status()
        results = r.json()
        tralbums = results["tralbums"]
        redownload_urls = results["redownload_urls"]
        try:
            tralbum = next(
                filter(
                    lambda tralbum: f"{tralbum['tralbum_type']}:{tralbum['tralbum_id']}"
                    == album_data.id,
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
        self._download_file(download_url, self.options.format, album_data)

    # check if the album was already downloaded given an id and url
    # format of id is [at]:<id>
    def is_downloaded(self, id: str, url: str = ""):
        return url in self.downloaded or id in self.downloaded

    def _download_album(self, soup: BeautifulSoup, force: bool = False):
        album_data = self._get_album_data_from_soup(soup)
        url = soup.head.find("meta", attrs={"property": "og:url"})["content"]
        if not force and self.is_downloaded(album_data.id, url):
            raise BCFreeDownloadError(
                f"{url} already downloaded. To download anyways, use option --force"
            )

        logger.debug(f"Album data: {album_data}")

        tralbum_data = soup.find("script", {"data-tralbum": True}).attrs["data-tralbum"]
        tralbum_data = json.loads(tralbum_data)

        if not tralbum_data["hasAudio"]:
            raise BCFreeDownloadError(f"{url} has no audio. Skipping...")

        head_data = soup.head.find(
            "script", {"type": "application/ld+json"}, recursive=False
        ).string

        head_data = json.loads(head_data)
        head_id = head_data.get("@id")
        # fallback if a track link was provided
        # track releases have this inAlbum key even if they're standalone
        head_data = head_data.get("inAlbum", head_data)["albumRelease"]
        # find the albumRelease object that matches the overall album @id link
        # this will ensure that strictly the page release is downloaded
        head_data = next(obj for obj in head_data if obj["@id"] == head_id)
        if "offers" not in head_data:
            raise BCFreeDownloadError(f"{url} has no digital download. Skipping...")

        album_data.title = head_data["name"]

        if head_data["offers"]["price"] == 0.0:
            if tralbum_data["current"]["require_email"]:
                raise BCFreeDownloadError(f"{url} requires email. Skipping...")
                if not self.options.email or self.options.email == "auto":
                    self._init_email()
                logger.info(f"{url} requires email")
                email_post_url = urljoin(url, "/email_download")
                r = self.session.post(
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
                r.raise_for_status()
                r = r.json()
                if not r["ok"]:
                    raise ValueError(f"Bad response when sending email address: {r}")
                self.mail_album_data[album_data.id] = album_data
            else:
                logger.info(f"{url} does not require email")
                self._download_file(
                    tralbum_data["freeDownloadPage"], self.options.format, album_data
                )
        else:
            if tralbum_data["is_purchased"]:
                collection_info = soup.find(
                    "script", {"data-tralbum-collect-info": True}
                ).attrs["data-tralbum-collect-info"]
                collection_info = json.loads(collection_info)
                self._download_purchased_album(collection_info["fan_id"], album_data)
            else:
                raise BCFreeDownloadError(
                    f"{url} is not free. If you have purchased this album, "
                    "use the --cookies flag or --identity flag to pass your login cookie."
                )

    def _download_label(self, soup: BeautifulSoup, force: bool = False):
        albums = []
        baseurl = soup.head.find("meta", attrs={"property": "og:url"})["content"]

        # bandcamp splits the album between this music-grid html and some json blob
        grid = soup.find("ol", id="music-grid")
        for li in grid.find_all("li"):
            if "display:none" in li.get("style", ""):
                continue
            data = li["data-item-id"].split("-")
            albums += [{"url": li.a["href"], "id": f"{data[0][0]}:{data[1]}"}]
        for obj in json.loads(html.unescape(grid.get("data-client-items", {}))):
            if obj.get("filtered"):
                continue
            albums += [{"url": obj["page_url"], "id": f"{obj['type'][0]}:{obj['id']}"}]

        for album in albums:
            if album["url"][0] == "/":
                album["url"] = urljoin(baseurl, album["url"])

            # perform a check here for already-downloaded album to prevent mass requests
            # to bandcamp for large labels and getting rate limited as a result
            if not force and self.is_downloaded(album["id"], album["url"]):
                logger.info(
                    f"{album['url']} already downloaded. To download anyways, use option --force"
                )
                continue

            logger.info(f"Downloading {album['url']}")
            r = self.session.get(album["url"])
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            try:
                self._download_album(soup, force)
            except BCFreeDownloadError as ex:
                logger.info(ex)

    def download_url(self, url: str, force: bool = False):
        # detect whether it's a release or label page
        r = self.session.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        try:
            url_type = soup.head.find("meta", attrs={"property": "og:type"})["content"]
        except:
            raise BCFreeDownloadError(f"{url} does not have an og:type property.")

        if url_type == "album" or url_type == "song":
            self._download_album(soup, force)
        elif url_type == "band":
            self._download_label(soup, force)
        else:
            raise BCFreeDownloadError(f"{url} does not have a valid og:type value")

    def wait_for_email_downloads(self):
        checked_ids = set()
        while (expected_emails := len(self.mail_album_data)) > 0:
            logger.info(f"Waiting for {expected_emails} emails from Bandcamp...")
            time.sleep(5)
            for email in self.mail_session.get_inbox(self.options.email):
                if email.id not in checked_ids:
                    checked_ids.add(email.id)
                    if (
                        email.from_address.endswith("@email.bandcamp.com")
                        and "download" in email.subject
                    ):
                        logger.info(f'Received email "{email.subject}"')
                        email = self.mail_session.get_message(
                            self.options.email, email.id
                        )
                        match = self.LINK_REGEX.search(email.html_body)
                        if match:
                            download_url = match.group("url")
                            album_id = self._download_file(
                                download_url, self.options.format
                            )
                            self.mail_album_data.pop(album_id)


class BCFreeDownloaderConfig:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.parser = ConfigParser()
        self.parser.read(config_path)
        atexit.register(self.save)

    def get(self, key):
        return self.parser["free-bandcamp-downloader"].get(key, None)

    def set(self, key, value):
        self.parser["free-bandcamp-downloader"][key] = value

    def save(self):
        with open(self.config_path, "w") as f:
            self.parser.write(f)

    def __str__(self):
        return pprint.pformat(dict(self.parser["free-bandcamp-downloader"]), indent=2)


def get_config_dir():
    if "XDG_CONFIG_HOME" in os.environ:
        config_dir = os.path.join(
            os.environ["XDG_CONFIG_HOME"], "free-bandcamp-downloader"
        )
    else:
        config_dir = os.path.join(
            os.path.expanduser("~"), ".config", "free-bandcamp-downloader"
        )
    return config_dir


def get_data_dir():
    if "XDG_DATA_HOME" in os.environ:
        data_dir = os.path.join(os.environ["XDG_DATA_HOME"], "free-bandcamp-downloader")
    else:
        data_dir = os.path.join(
            os.path.expanduser("~"), ".local", "share", "free-bandcamp-downloader"
        )
    return data_dir


def get_config(data_dir: str, config_dir: str):
    download_history_file = os.path.join(data_dir, "downloaded.txt")
    default_config = f"""[free-bandcamp-downloader]
        country = United States
        zipcode = 00000
        email = auto
        format = FLAC
        dir = .
        download_history_file = {download_history_file}"""
    config_file = os.path.join(config_dir, "free-bandcamp-downloader.cfg")
    if not os.path.exists(config_file):
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        with open(config_file, "w") as f:
            f.write(default_config)
    if not os.path.exists(download_history_file):
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        with open(download_history_file, "w") as f:
            pass
    config = BCFreeDownloaderConfig(config_file)
    return config


def main():
    data_dir = get_data_dir()
    config_dir = get_config_dir()
    config = get_config(data_dir, config_dir)
    options = BCFreeDownloaderOptions()
    arguments = docopt(__doc__, version=__version__)

    if arguments["--debug"]:
        logger.setLevel(logging.DEBUG)

    # set options if needed
    if arguments["URL"] or arguments["setdefault"]:
        for field in dataclasses.fields(options):
            option = field.name
            arg = f"--{option}"
            if arguments[arg]:
                setattr(options, option, arguments[arg])
            else:
                setattr(options, option, config.get(option))
            if not getattr(options, option):
                logger.error(
                    f'{option} is not set, use "bcdl-free setdefault {arg} <{option}>"'
                )
                sys.exit(1)
        if options.format not in BCFreeDownloader.FORMATS:
            logger.error(
                f'{options["format"]} is not a valid format. See "bcdl-free -h" for valid formats'
            )
            sys.exit(1)

    if arguments["setdefault"]:
        # write arguments to config
        for field in dataclasses.fields(options):
            option = field.name
            arg = f"--{option}"
            if arguments[arg]:
                config.set(option, arguments[arg])
        sys.exit(0)

    if arguments["clear"]:
        with open(config.get("download_history_file"), "w"):
            pass
        sys.exit(0)

    if arguments["defaults"]:
        print(str(config))
        sys.exit(0)

    if arguments["URL"]:
        # init downloader
        downloader = BCFreeDownloader(
            options,
            config_dir,
            config.get("download_history_file"),
            not arguments["--no-unzip"],
            arguments["--cookies"],
            arguments["--identity"],
        )

        for url in arguments["URL"]:
            try:
                downloader.download_url(url)
            except BCFreeDownloadError as ex:
                logger.info(ex)

        # finish up downloading
        downloader.wait_for_email_downloads()


if __name__ == "__main__":
    main()
