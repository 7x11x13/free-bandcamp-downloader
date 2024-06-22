# free-bandcamp-downloader

Download free and $0 minimum name-your-price albums and tracks from Bandcamp (including ones that are sent to email), 
and tag them with data from the Bandcamp page. Also able to download items in your collection, if login cookies are
supplied using the `--cookies` or `--identity` argument.

## Installation

Install with pip
```
pip install free-bandcamp-downloader
```

## Note on passing cookies

Only one cookie is needed to login, which has the name "identity". You can pass this cookie to `bcdl-free` using the
`--cookies` argument which you must supply a path to a Netscape cookies.txt formatted file, or using the `--identity`
argument which you must supply the value of your "identity" cookie.

## Usage

```
Usage:
    bcdl-free (-a <URL> | -l <URL>)[--force][--no-unzip][-d | --dir <dir>][-e | --email <email>]
        [-z | --zipcode <zipcode>][-c | --country <country>][-f | --format <format>]
        [--cookies <file>][--identity <value>][--debug]
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
    --cookies <file>            Path to cookies.txt file so albums in your collection can be downloaded
    --identity <value>          Value of identity cookie so albums in your collection can be downloaded
    --debug                     Set loglevel to debug
Formats:
    - FLAC
    - V0MP3
    - 320MP3
    - AAC
    - Ogg
    - ALAC
    - WAV
    - AIFF
```
