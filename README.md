# free-bandcamp-downloader

Download free and $0 minimum albums and tracks from Bandcamp

## Installation

Requires Firefox and [geckodriver](https://github.com/mozilla/geckodriver/releases)

Make sure geckodriver is in your PATH environment variable

Install with pip
```
py -m pip install git+https://github.com/7x11x13/free-bandcamp-downloader
```

## Usage

```Usage:
    bcdl-free (-a <URL> | -l <URL>)[--force][-d | --dir <dir>][-e | --email <email>]
        [-z | --zipcode <zipcode>][-c | --country <country>][-f | --format <format>]
    bcdl-free setdefault [-d | --dir <dir][-e | --email <email>][-z | --zipcode <zipcode>]
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
    setdefault                  Set default options
    defaults                    List the default options
    clear                       Clear download history
    -d --dir <dir>              Set download directory
    -c --country <country>      Set country
    -z --zipcode <zipcode>      Set zipcode
    -e --email <email>          Set email
    -f --format <format>        Set format
Formats:
    - FLAC
    - V0MP3
    - 320MP3
    - AAC
    - Ogg
    - ALAC
    - WAV
    - AIFF```
