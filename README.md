# free-bandcamp-downloader

Download free and $0 minimum name-your-price albums and tracks from Bandcamp (including ones that are sent to email),
and tag them with data from the Bandcamp page. Also able to download items in your collection, if login cookies are
supplied using the `--cookies` or `--identity` argument.

## Installation

With pip:

```
$ pip install free-bandcamp-downloader
$ bcdl-free
```

With [uv](https://docs.astral.sh/uv/getting-started/installation/):

```
$ uvx --from free-bandcamp-downloader bcdl-free
```

## Note on passing cookies

Only one cookie is needed to login, which has the name "identity". You can pass this cookie to `bcdl-free` using the
`--cookies` argument which you must supply a path to a Netscape cookies.txt formatted file, or using the `--identity`
argument which you must supply the value of your "identity" cookie.

## Usage

```
bcdl-free

Usage:
  bcdl-free setdefault [options]
  bcdl-free defaults
  bcdl-free clear
  bcdl-free [options] [--] <URL>...
  bcdl-free -h | --help
  bcdl-free --version

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
    - FLAC
    - V0MP3
    - 320MP3
    - AAC
    - Ogg
    - ALAC
    - WAV
    - AIFF
```
