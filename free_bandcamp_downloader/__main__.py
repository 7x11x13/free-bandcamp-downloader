"""Download free albums and tracks from Bandcamp
Usage:
    bcdl-free (-a <URL> | -l <URL>)[--force][--no-unzip][-d | --dir <dir>][-e | --email <email>]
        [-z | --zipcode <zipcode>][-c | --country <country>][-f | --format <format>]
    bcdl-free setdefault [-d | --dir <dir>][-e | --email <email>][-z | --zipcode <zipcode>]
        [-c | --country <country>][-f | --format <format>]
    bcdl-free defaults
    bcdl-free clear
    bcdl-free (-h | --help)
    bcdl-free --version
Options:
    -h --help                   Show this screen
    --version                   Show version
    -a <URL>                    Download the album at URL
    -l <URL>                    Download all free albums of the label at URL
    --force                     Download even if album has been downloaded before
    --no-unzip                  Don't unzip downloaded albums
    setdefault                  Set default options
    defaults                    List the default options
    clear                       Clear download history
    -d --dir <dir>              Set download directory
    -c --country <country>      Set country
    -z --zipcode <zipcode>      Set zipcode
    -e --email <email>          Set email (set to 'auto' to automatically download from a disposable email)
    -f --format <format>        Set format
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
import json
import os
import pprint
import re
import sys
import time
import zipfile
from configparser import ConfigParser
from dataclasses import dataclass
from typing import Dict, Set
from urllib.parse import urljoin, urlsplit

import mutagen
import pyrfc6266
import requests
import secmail
from bs4 import BeautifulSoup
from docopt import docopt
from tqdm import tqdm

from free_bandcamp_downloader import __version__, logger


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
    ):
        self.options = options
        self.config_dir = config_dir
        self.download_history_file = download_history_file
        self.downloaded: Set[str] = set()
        self.mail_session = None
        self.mail_album_data: Dict[str, BCFreeDownloaderAlbumData] = {}
        self.unzip = unzip
        self.session = None
        self._init_email()
        self._init_downloaded()
        self._init_session()

    def _init_email(self):
        if not self.options.email or self.options.email == "auto":
            self.mail_session = secmail.Client(self.config_dir)
            self.options.email = self.mail_session.random_email(1, "1secmail.com")[0]

    def _init_downloaded(self):
        if self.download_history_file:
            with open(self.download_history_file, "r") as f:
                for line in f:
                    self.downloaded.add(line.strip())

    def _init_session(self):
        self.session = requests.Session()

    def _download_file(
        self,
        download_page_url: str,
        format: str,
        album_data: BCFreeDownloaderAlbumData = None,
    ) -> str:
        r = self.session.get(download_page_url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        album_url = soup.find("div", class_="download-artwork").find("a").attrs["href"]
        if album_data is None:
            album_data = self.mail_album_data[album_url]

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
        except:
            statdownload_url = download_url.replace("/download/", "/statdownload/")
            with self.session.get(statdownload_url) as r:
                r.raise_for_status()
                download_url = self.RETRY_URL_REGEX.search(r.text).group("retry_url")
            file_name = download(download_url)

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
        self.downloaded.add(album_url)
        if self.download_history_file:
            with open(self.download_history_file, "a") as f:
                f.write(f"{album_url}\n")

        return album_url

    @staticmethod
    def _get_album_data_from_soup(soup: BeautifulSoup) -> BCFreeDownloaderAlbumData:
        album_data = BCFreeDownloaderAlbumData()
        album_data.about = soup.find("div", class_="tralbum-about").get_text("\n")
        album_data.credits = soup.find("div", class_="tralbum-credits").get_text("\n")
        tags = [tag.get_text() for tag in soup.find_all("a", class_="tag")]
        album_data.tags = ",".join(sorted(tags))
        return album_data

    def download_album(self, url: str, force: bool = False):
        # Remove url params
        url = urlsplit(url).geturl()
        if url in self.downloaded and not force:
            raise BCFreeDownloadError(
                f"{url} already downloaded. To download anyways, use option --force"
            )
        r = self.session.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        album_data = self._get_album_data_from_soup(soup)

        logger.debug(f"Album data: {album_data}")

        tralbum_data = soup.find("script", {"data-tralbum": True}).attrs["data-tralbum"]
        tralbum_data = json.loads(tralbum_data)

        if tralbum_data["current"]["minimum_price"] == 0:
            if tralbum_data["current"]["require_email"]:
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
                self.mail_album_data[url] = album_data
            else:
                logger.info(f"{url} does not require email")
                self._download_file(
                    tralbum_data["freeDownloadPage"], self.options.format, album_data
                )
        else:
            raise BCFreeDownloadError(f"{url} is not free")

    def download_label(self, url: str, force: bool = False):
        r = self.session.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text)
        for album_title in soup.find_all("p", class_="title"):
            album_link = album_title.parent.attrs["href"]
            logger.info(f"Downloading {album_link}")
            try:
                self.download_album(album_link, force)
            except BCFreeDownloadError as ex:
                logger.info(ex)

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
                            album_url = self._download_file(
                                download_url, self.options.format
                            )
                            self.mail_album_data.pop(album_url)


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
    if arguments["-a"] or arguments["-l"] or arguments["setdefault"]:
        # set options
        for field in dataclasses.fields(options):
            option = field.name
            arg = f"--{option}"
            if arguments[arg]:
                setattr(options, option, arguments[arg][0])
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
    if arguments["-a"] or arguments["-l"]:
        # init downloader
        downloader = BCFreeDownloader(
            options,
            config_dir,
            config.get("download_history_file"),
            not arguments["--no-unzip"],
        )
        if arguments["-a"]:
            downloader.download_album(arguments["-a"], arguments["--force"])
        elif arguments["-l"]:
            downloader.download_label(arguments["-l"], arguments["--force"])
        # finish up downloading
        downloader.wait_for_email_downloads()
    elif arguments["setdefault"]:
        # write arguments to config
        for field in dataclasses.fields(options):
            option = field.name
            arg = f"--{option}"
            if arguments[arg]:
                config.set(option, arguments[arg][0])
    elif arguments["defaults"]:
        print(str(config))
    elif arguments["clear"]:
        with open(config.get("download_history_file"), "w"):
            pass


if __name__ == "__main__":
    main()
