__doc__ = """
free-bandcamp-downloader

Usage:
  free-bandcamp-downloader setdefault [options]
  free-bandcamp-downloader defaults
  free-bandcamp-downloader clear
  free-bandcamp-downloader [options] [--] <URL>...
  free-bandcamp-downloader -h | --help
  free-bandcamp-downloader --version

Options:
  -h --help                         Show this screen.
  --version                         Show version.
  --dir=<dir>                       The directory to save downloads to.
  --country=<country>               The country to use for downloads that require one.
  --zipcode=<zipcode>               The zipcode to use for downloads that require one.
  --email=<email>                   The email to use for downloads that require one. Use "auto" for a temporary email.
  --format=<format>                 The audio format to download.
  --force                           Force download, even if it's in the download history.
  --no-unzip                        Don't unzip albums.
  --cookies=<file>                  Path to a netscape cookies file to use for authentication.
  --identity=<cookie>               The value of the identity cookie to use for authentication.
  --download-history-file=<file>    The file to use for download history.
  --failure-log-file=<file>         The file to log failed downloads to.

Available Formats:
{available_formats}
"""
import dataclasses
import sys
import os
import pprint
import time
import shutil
from datetime import datetime
from typing import List, Set
from docopt import docopt
from configparser import ConfigParser
from . import __version__
from .bc_free_downloader import (
    AlbumInfo,
    BCFreeDownloader,
    BCFreeDownloaderOptions,
    TralbumId,
)
available_formats = "\n".join([f"    - {f}" for f in BCFreeDownloader.FORMATS.keys()])
__doc__ = __doc__.format(available_formats=available_formats)
class Config:
    def __init__(self):
        config_dir = get_config_dir()
        self.parser = ConfigParser(allow_no_value=True)
        self.parser["free-bandcamp-downloader"] = {}
        for field in dataclasses.fields(BCFreeDownloaderOptions):
            self.parser["free-bandcamp-downloader"][field.name] = field.default
        self.parser["free-bandcamp-downloader"]["force"] = "false"
        self.parser["free-bandcamp-downloader"]["no-unzip"] = "false"
        self.parser["free-bandcamp-downloader"]["download-history-file"] = (
            get_data_dir() + "/downloaded.txt"
        )
        self.parser["free-bandcamp-downloader"]["failure-log-file"] = (
            get_data_dir() + "/failed_downloads.log"
        )
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
def get_total_size(path: str) -> int:
    if os.path.isfile(path):
        return os.path.getsize(path)
    if os.path.isdir(path):
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
        return total_size
    return 0
def update_status(message: str, finalize=False):
    terminal_width = shutil.get_terminal_size((80, 20)).columns
    line = f" -> {message}"
    padding = " " * (terminal_width - len(line) - 1)
    full_line = "\r" + line + padding
    if finalize:
        full_line += "\n"
    sys.stdout.write(full_line)
    sys.stdout.flush()
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
def update_history_entry(config: Config, id: TralbumId, new_name: str, new_bytes: int, new_state: str, downloaded_dict: dict):
    history_file = config.get("download-history-file")
    if not os.path.exists(history_file):
        return
    id_str_to_find = f"{id[0][0]}:{id[1]}"
    updated_lines = []
    found = False
    with open(history_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith(id_str_to_find + ';'):
                updated_lines.append(f"{id_str_to_find};{new_name};{new_bytes};{new_state}\n")
                found = True
            else:
                updated_lines.append(line)
    if found:
        with open(history_file, "w", encoding="utf-8") as f:
            f.writelines(updated_lines)
    downloaded_dict[id] = (new_name, new_bytes, new_state)
def is_downloaded_and_exists(config: Config, downloaded_dict: dict, id: TralbumId, desired_state: str) -> bool:
    if id not in downloaded_dict:
        return False
    name, expected_bytes, stored_state = downloaded_dict[id]
    if stored_state != desired_state:
        return False
    expected_path = os.path.join(config.get("dir"), name)
    if not os.path.exists(expected_path):
        return False
    actual_bytes = get_total_size(expected_path)
    return actual_bytes == expected_bytes
def add_to_dl_file(config: Config, id: TralbumId, file_path: str, downloaded_dict: dict, state: str):
    history_file = config.get("download-history-file")
    item_name = os.path.basename(file_path)
    total_bytes = get_total_size(file_path)
    with open(history_file, "a", encoding="utf-8") as f:
        f.write(f"{id[0][0]}:{id[1]};{item_name};{total_bytes};{state}\n")
    downloaded_dict[id] = (item_name, total_bytes, state)
def add_to_failure_log(config: Config, album_url: str, attempt: int, error: str):
    failure_log_file = config.get("failure-log-file")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] - URL: {album_url} - Attempt: {attempt} - Error: {error}\n"
    with open(failure_log_file, "a", encoding="utf-8") as f:
        f.write(log_entry)
def cleanup_failed_download(file_path: str):
    if not file_path:
        return
    tmp_file_path = file_path + ".tmp"
    if os.path.exists(tmp_file_path):
        try:
            os.remove(tmp_file_path)
        except OSError:
            pass
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            dir_name = file_path[:-4]
            if os.path.isdir(dir_name):
                shutil.rmtree(dir_name)
        except OSError:
            pass
def get_downloaded(config: Config) -> dict:
    history_file = config.get("download-history-file")
    if not os.path.exists(history_file):
        return {}
    downloaded = {}
    with open(history_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                parts = line.strip().split(';', 3)
                if len(parts) < 3: continue
                state = "unzipped"
                if len(parts) == 4:
                    id_part, name_part, bytes_part, state_part = parts
                    state = state_part if state_part in ["zipped", "unzipped"] else "unzipped"
                else:
                    id_part, name_part, bytes_part = parts
                type_str, _, data_str = id_part.partition(":")
                if type_str == "a":
                    item_type, data = "album", int(data_str)
                elif type_str == "t":
                    item_type, data = "track", int(data_str)
                else:
                    continue
                downloaded[(item_type, data)] = (name_part, int(bytes_part), state)
            except (ValueError, IndexError):
                continue
    return downloaded
def process_album(url: str, config: Config, downloader: BCFreeDownloader, downloaded: dict):
    slug = os.path.basename(url)
    print(f"Processing: {url}")
    force = config.parser.getboolean("free-bandcamp-downloader", "force")
    no_unzip_flag = config.parser.getboolean("free-bandcamp-downloader", "no-unzip")
    desired_state = "zipped" if no_unzip_flag else "unzipped"
    max_retries = 10
    album_url = url
    try:
        update_status(f"{slug} - Status: Getting info...")
        page_info = downloader.get_url_info(url)
        if not page_info:
            update_status(f"{slug} - Error: Could not get page info", finalize=True)
            add_to_failure_log(config, url, 1, "Could not get page info")
            return
        album_info = page_info["info"]
        tralbum_data = album_info.get("tralbum_data", {})
        type = tralbum_data.get("current", {}).get("type")
        id = tralbum_data.get("current", {}).get("id")
        album_url = tralbum_data.get("url", url)
        if not type or not id:
            raise ValueError("Essential album metadata (type, id) not found.")
        tralbum_id = (type, id)
        if not force:
            if tralbum_id in downloaded:
                stored_name, stored_bytes, stored_state = downloaded[tralbum_id]
                if stored_state == desired_state:
                    if is_downloaded_and_exists(config, downloaded, tralbum_id, desired_state):
                        update_status(f"{slug} - Skipped: Already downloaded and verified. Use --force to override.", finalize=True)
                        return
                elif desired_state == "unzipped" and stored_state == "zipped":
                    zip_path = os.path.join(config.get("dir"), stored_name)
                    if os.path.exists(zip_path) and os.path.getsize(zip_path) == stored_bytes:
                        update_status(f"{slug} - Status: Found local ZIP. Unzipping...")
                        files = BCFreeDownloader.unzip_album(zip_path)
                        update_status(f"{slug} - Status: Setting tags...")
                        for file in files:
                            BCFreeDownloader.tag_file(file, album_info["head_data"])
                        unzipped_dir_path = zip_path[:-4]
                        new_bytes = get_total_size(unzipped_dir_path)
                        new_name = os.path.basename(unzipped_dir_path)
                        update_history_entry(config, tralbum_id, new_name, new_bytes, "unzipped", downloaded)
                        update_status(f"{slug} - Success: Unzipped local file.", finalize=True)
                        return
    except Exception as e:
        error_text = str(e).splitlines()[0]
        update_status(f"{slug} - Error during info fetch: {error_text}", finalize=True)
        add_to_failure_log(config, url, 1, str(e))
        return
    for attempt in range(max_retries):
        downloaded_zip_path = None
        try:
            def progress_bar_callback(name, downloaded_bytes, total_size):
                bar_length = 40
                if total_size > 0:
                    percentage = (downloaded_bytes / total_size) * 100
                    filled_len = int(bar_length * downloaded_bytes // total_size)
                    downloaded_mb = downloaded_bytes / (1024 * 1024)
                    total_mb = total_size / (1024 * 1024)
                    bar = f"[{'█' * filled_len}{'-' * (bar_length - filled_len)}]"
                    progress_line = f"{slug} - {percentage:.2f}% {bar} {downloaded_mb:.2f}/{total_mb:.2f} MB"
                    update_status(progress_line)
            update_status(f"{slug} - Status: Attempt {attempt + 1}/{max_retries}...")
            album_info = downloader.download_album(album_url, progress_bar_callback)
            error_message = album_info.get("error")
            if error_message:
                update_status(f"{slug} - Failed: {error_message}", finalize=True)
                add_to_failure_log(config, album_url, 0, error_message)
                return
            if album_info.get("is_downloaded"):
                downloaded_zip_path = album_info["file_name"]
            elif album_info.get("email_queued"):
                if not downloader.request_email_download(album_info):
                    raise IOError("Failed to send email request.")
                download_page_url = downloader.await_download_email(
                    time.time(), status_callback=lambda msg: update_status(f"{slug} - {msg}")
                )
                if not download_page_url:
                    raise TimeoutError("Did not receive download email in time.")
                dl_ret = downloader._download_file(download_page_url, downloader.options.format, progress_bar_callback)
                if not dl_ret:
                    raise IOError("Failed to download file from email link.")
                downloaded_zip_path = dl_ret["file_name"]
            if not downloaded_zip_path:
                update_status(f"{slug} - Error: Download path not found.", finalize=True)
                return
            files = [downloaded_zip_path]
            unzip = not config.parser.getboolean("free-bandcamp-downloader", "no-unzip")
            if unzip and downloaded_zip_path.endswith(".zip"):
                update_status(f"{slug} - Status: Unzipping...")
                files = BCFreeDownloader.unzip_album(downloaded_zip_path)
            update_status(f"{slug} - Status: Setting tags...")
            final_state = "unzipped" if unzip and downloaded_zip_path.endswith(".zip") else "zipped"
            item_path_for_history = downloaded_zip_path[:-4] if final_state == "unzipped" else downloaded_zip_path
            for file in files:
                BCFreeDownloader.tag_file(file, album_info["head_data"])
            add_to_dl_file(config, (type, id), item_path_for_history, downloaded, final_state)
            update_status(f"{slug} - Success", finalize=True)
            return
        except Exception as e:
            cleanup_failed_download(downloaded_zip_path)
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 10
                update_status(f"{slug} - Error: Attempt {attempt + 1} failed. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                update_status(f"{slug} - Error: Failed after {max_retries} attempts.", finalize=True)
                add_to_failure_log(config, album_url, max_retries, str(e))
                return
def download_urls(urls: List[str], config: Config):
    downloader = BCFreeDownloader(options_from_config(config))
    downloaded = get_downloaded(config)
    for url in urls:
        page_info = downloader.get_url_info(url)
        slug = os.path.basename(url)
        if not page_info:
            print(f"Processing: {url}")
            update_status(f"{slug} - Error: Could not get page info", finalize=True)
            add_to_failure_log(config, url, 0, "Could not get page info")
            continue
        page_type = page_info.get("type")
        if page_type in ("album", "song"):
            process_album(url, config, downloader, downloaded)
        elif page_type == "band":
            releases = page_info.get("info", {}).get("releases", [])
            print(f"Processing Label: {url}")
            update_status(f"Found {len(releases)} releases. Starting batch download.", finalize=True)
            for i, rel in enumerate(releases):
                process_album(rel["url"], config, downloader, downloaded)
                if i < len(releases) - 1:
                    time.sleep(1)
        else:
            print(f"Processing: {url}")
            update_status(f"{slug} - Error: Unsupported page type '{page_type}'", finalize=True)
            add_to_failure_log(config, url, 0, f"Unsupported page type: {page_type}")
def main():
    config = Config()
    arguments = docopt(__doc__, version=__version__)
    if arguments["<URL>"] or arguments["setdefault"]:
        for option in config.parser["free-bandcamp-downloader"].keys():
            arg = f"--{option}"
            if arguments.get(arg):
                config.set(option, arguments[arg])
        if (
            config.get("format")
            not in BCFreeDownloader.FORMATS
        ):
            print(f'Error: {config.get("format")} is not a valid format.', file=sys.stderr)
            sys.exit(1)
    if arguments["setdefault"]:
        config.save()
        sys.exit(0)
    elif arguments["clear"]:
        if os.path.exists(config.config_path):
            try:
                os.remove(config.config_path)
            except OSError:
                print(f"Error: Could not clear configuration file.", file=sys.stderr)
                sys.exit(1)
            sys.exit(0)
    elif arguments["defaults"]:
        print(str(config))
        sys.exit(0)
    elif arguments["<URL>"]:
        download_urls(arguments["<URL>"], config)
if __name__ == "__main__":
    main()
