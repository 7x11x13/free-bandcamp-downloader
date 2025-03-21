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
    bcdl-free setdefault [-d <dir>] [-e <email>] [-z <zipcode>]
        [-c <country>] [-f <format>]
    bcdl-free defaults
    bcdl-free clear
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
```
