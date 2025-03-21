"""Download free albums and tracks from Bandcamp

Usage:
    bcdl-free setdefault [-d <dir>] [-e <email>] [-z <zipcode>]
        [-c <country>] [-f <format>]
    bcdl-free defaults
    bcdl-free clear
    bcdl-free [--debug] [--force] [--no-unzip] [-al]
        [-d <dir>] [-e <email>] [-z <zipcode>] [-c <country>] [-f <format>]
        [--cookies <file>] [--identity <value>] URL...
    bcdl-free -h | --help | --version
    bcdl-free [--debug] [--force] [--no-unzip] [-al]
        [-d <dir>] [-e <email>] [-z <zipcode>] [-c <country>] [-f <format>]
        [--cookies <file>] [--identity <value>] [--download-history-file <file>]
        URL...

Arguments:
    URL            URL to download. Can be a link to a label or release page

Subcommands:
    setdefaults    set default configuration options
    defaults       list default configuration options
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
    --download-history-file <file>       Path to history file containing downloaded albums

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

import dataclasses
import logging
import sys
import os
import pprint
from typing import List, Set, Tuple
from docopt import docopt
from configparser import ConfigParser

from free_bandcamp_downloader import __version__
from free_bandcamp_downloader.bc_free_downloader import (
    AlbumInfo,
    BCFreeDownloader,
    BCFreeDownloaderOptions,
)
from free_bandcamp_downloader import logger


class Config:
    def __init__(self):
        config_dir = get_config_dir()
        # initialize with default config first
        # this is combined from the dataclass and CLI params
        self.parser = ConfigParser(allow_no_value=True)
        self.parser["free-bandcamp-downloader"] = {}
        for field in dataclasses.fields(BCFreeDownloaderOptions):
            self.parser["free-bandcamp-downloader"][field.name] = field.default
        self.parser["free-bandcamp-downloader"]["force"] = "false"
        self.parser["free-bandcamp-downloader"]["no-unzip"] = "false"
        self.parser["free-bandcamp-downloader"]["download-history-file"] = (
            get_data_dir() + "/downloaded.txt"
        )

        # read config file
        self.config_path = os.path.join(config_dir, "free-bandcamp-downloader.cfg")
        if not os.path.exists(self.config_path):
            with open(self.config_path, "w") as f:
                self.parser.write(f)
            return
        self.parser.read(self.config_path)

    def get(self, key):
        return self.parser["free-bandcamp-downloader"].get(key)

    def set(self, key, value):
        if value is not None:
            value = str(value)
        self.parser["free-bandcamp-downloader"][key] = value

    def save(self):
        with open(self.config_path, "w") as f:
            self.parser.write(f)

    def __str__(self):
        return pprint.pformat(dict(self.parser["free-bandcamp-downloader"]), indent=2)


def options_from_config(config: Config):
    options = BCFreeDownloaderOptions()
    for field in dataclasses.fields(options):
        setattr(
            options, field.name, config.parser["free-bandcamp-downloader"][field.name]
        )
    return options


def get_config_dir() -> str:
    if "XDG_CONFIG_HOME" in os.environ:
        config_dir = os.path.join(
            os.environ["XDG_CONFIG_HOME"], "free-bandcamp-downloader"
        )
    else:
        config_dir = os.path.join(
            os.path.expanduser("~"), ".config", "free-bandcamp-downloader"
        )
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
    return config_dir


def get_data_dir() -> str:
    if "XDG_DATA_HOME" in os.environ:
        data_dir = os.path.join(os.environ["XDG_DATA_HOME"], "free-bandcamp-downloader")
    else:
        data_dir = os.path.join(
            os.path.expanduser("~"), ".local", "share", "free-bandcamp-downloader"
        )
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    return data_dir


def is_downloaded(downloaded_set, id: Tuple[str, int], url: str = None) -> bool:
    return id in downloaded_set or url in downloaded_set


def add_to_dl_file(config: Config, id: Tuple[str, int]):
    history_file = config.parser["free-bandcamp-downloader"]["download-history-file"]
    with open(history_file, "a") as f:
        f.write(f"{id[0][0]}:{id[1]}\n")


def get_downloaded(config: Config) -> Set[Tuple[str, int | str]]:
    history_file = config.parser["free-bandcamp-downloader"]["download-history-file"]
    if not os.path.exists(history_file):
        with open(history_file, "w") as f:
            pass

    downloaded = set()
    with open(history_file, "r") as f:
        for line in f:
            type = line.strip()[:2]
            if type == "a:":
                type = "album"
                data = int(line[2:])
            elif type == "t:":
                type = "track"
                data = int(line[2:])
            else:
                type = "url"
                data = line.strip()
            downloaded.add((type, data))
    return downloaded


def post_download(album_info: AlbumInfo, config: Config):
    file_name = album_info["file_name"]
    # file list for setting tags
    files = [file_name]
    unzip = not config.parser.getboolean("free-bandcamp-downloader", "no-unzip")

    # unzip if needed
    if unzip and file_name.endswith(".zip"):
        files = BCFreeDownloader.unzip_album(file_name)

    logger.info("Setting tags...")
    for file in files:
        BCFreeDownloader.tag_file(file, album_info["head_data"])


def download_urls(urls: List[str], config: Config):
    downloader = BCFreeDownloader(options_from_config(config))
    downloaded = get_downloaded(config)
    force = config.parser.getboolean("free-bandcamp-downloader", "force")

    for url in urls:
        soup = downloader.get_url_soup(url)
        url_info = downloader.get_page_info(soup)

        urltype = url_info and url_info.get("type")
        if urltype == "album" or urltype == "song":
            tralbum = url_info["info"]["tralbum_data"]
            type = tralbum["current"]["type"]
            id = tralbum["current"]["id"]
            url = tralbum["url"]
            if not force and is_downloaded(downloaded, (type, id), url):
                logger.error(
                    f"{url} already downloaded. To download anyways, use --force."
                )
                continue
            ret = downloader.download_album(soup)
            if ret["is_downloaded"]:
                add_to_dl_file(config, (type, id))
                downloaded.add((type, id))
                post_download(ret, config)
        elif urltype == "band":
            for rel in url_info["info"]["releases"]:
                type = rel["type"]
                id = rel["id"]
                url = rel["url"]
                if not force and is_downloaded(downloaded, (type, id), url):
                    logger.error(
                        f"{url} already downloaded. To download anyways, use --force."
                    )
                    continue
                soup = downloader.get_url_soup(url)
                ret = downloader.download_album(soup)
                if ret["is_downloaded"]:
                    add_to_dl_file(config, (type, id))
                    downloaded.add((type, id))
                    post_download(ret, config)
        else:
            continue

    # finish up downloading
    ret = downloader.flush_email_downloads()
    for album_info in ret:
        type = album_info["tralbum_data"]["current"]["type"]
        id = album_info["tralbum_data"]["current"]["id"]
        add_to_dl_file(config, (type, id))
        downloaded.add((type, id))
        post_download(album_info, config)


def main():
    config = Config()
    arguments = docopt(__doc__, version=__version__)

    if arguments["--debug"]:
        logger.setLevel(logging.DEBUG)

    # set config if needed
    if arguments["URL"] or arguments["setdefault"]:
        for option in config.parser["free-bandcamp-downloader"].keys():
            arg = f"--{option}"
            if arguments.get(arg):
                config.set(option, arguments[arg])
        if (
            config.parser["free-bandcamp-downloader"]["format"]
            not in BCFreeDownloader.FORMATS
        ):
            logger.error(
                f'{config.parser.get("format")} is not a valid format. See "bcdl-free -h" for valid formats'
            )
            sys.exit(1)

    # write to config file
    if arguments["setdefault"]:
        config.save()
        sys.exit(0)

    if arguments["clear"]:
        with open(config.config_path, "w"):
            pass
        sys.exit(0)

    if arguments["defaults"]:
        print(str(config))
        sys.exit(0)

    if arguments["URL"]:
        download_urls(arguments["URL"], config)


if __name__ == "__main__":
    main()
