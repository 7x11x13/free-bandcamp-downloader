import atexit
import logging
import os
from configparser import ConfigParser

logging.basicConfig(level=os.environ.get('LOGLEVEL', 'INFO'))
logger = logging.getLogger(__name__)

__version__ = 'v0.0.7'

if 'XDG_CONFIG_HOME' in os.environ:
    config_dir = os.path.join(
        os.environ['XDG_CONFIG_HOME'], 'free-bandcamp-downloader')
else:
    config_dir = os.path.join(os.path.expanduser(
        '~'), '.config', 'free-bandcamp-downloader')

if 'XDG_DATA_HOME' in os.environ:
    data_dir = os.path.join(
        os.environ['XDG_DATA_HOME'], 'free-bandcamp-downloader')
else:
    data_dir = os.path.join(os.path.expanduser(
        '~'), '.local', 'share', 'free-bandcamp-downloader')

download_history_file = os.path.join(data_dir, 'downloaded.txt')

default_config = \
    f"""[free-bandcamp-downloader]
    country = United States
    zipcode = 00000
    email = auto
    format = FLAC
    dir = .
    download_history_file = {download_history_file}"""

config_file = os.path.join(config_dir, 'free-bandcamp-downloader.cfg')

if not os.path.exists(config_file):
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
    with open(config_file, 'w') as f:
        f.write(default_config)

if not os.path.exists(download_history_file):
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    with open(download_history_file, 'w') as f:
        pass

parser = ConfigParser()
parser.read(config_file)


class Config:
    def __init__(self, parser: ConfigParser):
        self.parser = parser
        atexit.register(self.save)

    def get(self, key):
        return self.parser['free-bandcamp-downloader'].get(key, None)

    def set(self, key, value):
        self.parser['free-bandcamp-downloader'][key] = value

    def save(self):
        with open(config_file, 'w') as f:
            self.parser.write(f)

    def __str__(self):
        return str(dict(self.parser['free-bandcamp-downloader']))


config = Config(parser)
