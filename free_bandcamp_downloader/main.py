"""Download free albums and tracks from Bandcamp
Usage:
    bcdl-free (-a <URL> | -l <URL>)[--force][-d | --dir <dir>][-e | --email <email>]
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
import glob
import os
import re
import sys
import time
import urllib.request
import zipfile
from urllib.parse import urlsplit

import bs4
import mutagen
from bs4 import BeautifulSoup, SoupStrainer
from docopt import docopt
from guerrillamail import GuerrillaMailSession
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.wait import WebDriverWait

from free_bandcamp_downloader import __version__, config, logger

# Global variables
arguments = None
mail_session = None
expected_emails = 0
mail_album_data = {}
downloaded = set()
options = {
    'country': None,
    'zipcode': None,
    'email': None,
    'format': None,
    'dir': None
}

# Constants

link_regex = re.compile('<a href="(?P<url>http[^"]*)">')

xpath = {
    'buy': '//*[@class="ft compound-button main-button"]/button[@class="download-link buy-link"]',
    'price': '//input[@id="userPrice"]',
    'download-nyp': '//a[@class="download-panel-free-download-link"]',
    'checkout': '//button[@class="download-panel-checkout-button" and not(ancestor::div[contains(@style,"display:none")])]',
    'email': '//input[@id="fan_email_address"]',
    'country': '//select[@id="fan_email_country"]',
    'zipcode': '//input[@id="fan_email_postalcode"]',
    'preparing': '//span[@class="preparing-title"]',
    'formats': '//select[@id="format-type"]',
    'download': '//div[@class="download-format-tmp"]/a[1]',
    'albums': '//a[./p[@class="title"]]',
    'album-link': '//div[@class="download-artwork"]/a',
    'album-tags': '//div[contains(@class, "tralbum-tags-nu")]',
    'album-credits': '//div[@class="tralbumData tralbum-credits"]',
    'album-about': '//div[@class="tralbumData tralbum-about"]',
}

formats = {
    'FLAC': 'flac',
    'V0MP3': 'mp3-v0',
    '320MP3': 'mp3-320',
    'AAC': 'aac-hi',
    'Ogg': 'vorbis',
    'ALAC': 'alac',
    'WAV': 'wav',
    'AIFF': 'aiff-lossless'
}


def wait():
    time.sleep(1)


def init_email():
    global mail_session
    if not mail_session and (not options['email'] or options['email'] == 'auto'):
        mail_session = GuerrillaMailSession()
        options['email'] = mail_session.get_session_state()['email_address']


def get_driver():
    options = Options()
    options.add_argument('--headless')
    driver = webdriver.Firefox(
        options=options, service_log_path=os.devnull)
    driver.implicitly_wait(10)
    return driver


def init_downloaded():
    with open(config.get('download_history_file'), 'r') as f:
        for line in f:
            downloaded.add(line.strip())


def download_file(driver, album_data=None):
    logger.info('On download page')
    page_url = driver.find_element("xpath", 
        xpath['album-link']).get_attribute('href')
    page_url = 'https://' + BASE_URL + urlsplit(page_url).path
    if album_data is None:
        album_data = mail_album_data[page_url]
    driver.find_element("xpath", xpath['formats']).click()
    wait()
    driver.find_element("xpath", 
        f'//option[@value="{formats[options["format"]]}"]').click()
    logger.info(f'Set format to {formats[options["format"]]}')
    wait()
    button = driver.find_element("xpath", xpath['download'])
    WebDriverWait(driver, 60).until(EC.visibility_of(button))
    url = button.get_attribute('href')
    response = urllib.request.urlopen(url)
    name = os.path.basename(
        response.headers.get_filename().encode('latin-1').decode('utf-8'))
    length = int(response.getheader('content-length'))
    block_size = length // 10
    file_name = os.path.join(options['dir'], name)
    with open(file_name, 'wb') as f:
        size = 0
        while True:
            buf = response.read(block_size)
            if not buf:
                break
            f.write(buf)
            size += len(buf)
            logger.info(f'Downloading {name}, {size / length * 100: .1f}%')
    response.close()
    logger.info(f'Downloaded {file_name}')
    if file_name.endswith('zip'):
        # Unzip archive
        dir_name = file_name[:-4]
        with zipfile.ZipFile(file_name, 'r') as f:
            f.extractall(dir_name)
        logger.info(f'Unzipped to {dir_name}')
        os.remove(file_name)
        files = glob.glob(os.path.join(dir_name, "*"))
    else:
        files = [file_name]
    # Tag downloaded audio files with url & comment
    logger.info("Setting tags...")
    for file in files:
        try:
            f = mutagen.File(file)
            if f is None:
                continue
            f['website'] = page_url
            if album_data['tags']:
                f['genre'] = album_data['tags']
            if album_data['about'] or album_data['credits']:
                comment = ''
                if album_data['about']:
                    comment += album_data['about']
                if album_data['about'] and album_data['credits']:
                    comment += '\n\n'
                if album_data['credits']:
                    comment += album_data['credits']
                f['comment'] = comment
            f.save()
        except Exception as e:
            logger.info(f"Could not tag {file} - {e.__class__}: {e}")
    # successfully downloaded file, add to download history
    downloaded.add(page_url)
    with open(config.get('download_history_file'), 'a') as f:
        f.write(f'{page_url}\n')


def download_files(driver, urls):
    for url in urls:
        driver.get(url)
        download_file(driver)


def get_text(text):
    text = ''.join(line.strip() for line in text.split('\n'))
    text = text.replace('<br>', '\n')
    return BeautifulSoup(text, features='html.parser').get_text()


def download_album(driver, url):
    # Remove url params
    url = urlsplit(url).geturl()
    if url in downloaded and not arguments['--force']:
        logger.error(
            f'{url} already downloaded. To download anyways, use option --force')
        return f'{url} already downloaded. To download anyways, use option --force'
    driver.get(url)
    wait()
    try:
        # Get album data
        album_data = {
            'about': None,
            'credits': None,
            'tags': None
        }
        try:
            s = driver.find_element("xpath", 
                xpath['album-about']).get_attribute('innerHTML')
            s = get_text(s)
            album_data['about'] = s
        except Exception as e:
            logger.info(f"Could not get album about - {e.__class__}: {e}")
        try:
            s = driver.find_element("xpath", 
                xpath['album-credits']).get_attribute('innerHTML')
            s = get_text(s)
            album_data['credits'] = s
        except Exception as e:
            logger.info(f"Could not get album credits - {e.__class__}: {e}")
        try:
            s = driver.find_element("xpath", 
                xpath['album-tags']).get_attribute('innerHTML')
            tags = {a.text for a in BeautifulSoup(
                s, features='html.parser', parse_only=SoupStrainer('a'))}
            album_data['tags'] = ','.join(sorted(tags))
        except Exception as e:
            logger.info(f"Could not get album tags - {e.__class__}: {e}")

        logger.info(f"Album data: {album_data}")

        button = driver.find_element("xpath", xpath['buy'])
        if button.text == 'Free Download':
            logger.info(f'{url} is Free Download')
            button.click()
            wait()
            return download_file(driver, album_data)
        else:
            # name your price download
            logger.info(f'{url} is not Free Download')
            button.click()
            wait()
            price_input = driver.find_element("xpath", xpath['price'])
            price_input.click()
            price_input.send_keys('0')
            wait()
            try:
                driver.find_element("xpath", xpath['download-nyp']).click()
            except:
                logger.error(f'{url} is not free')
                return f'{url} is not free'
            checkout = driver.find_element("xpath", xpath['checkout'])
            if checkout.text == 'Download Now':
                checkout.click()
                wait()
                return download_file(driver, album_data)
            else:
                init_email()
                logger.info(f'{url} requires email')
                # fill out info
                driver.find_element("xpath", 
                    xpath['email']).send_keys(options['email'])
                wait()
                driver.find_element("xpath", 
                    xpath['zipcode']).send_keys(options['zipcode'])
                wait()
                Select(driver.find_element("xpath", 
                    xpath['country'])).select_by_visible_text(options['country'])
                wait()
                checkout.click()
                global expected_emails
                expected_emails += 1
                mail_album_data[url] = album_data
    except Exception as e:
        logger.error(f"Error downloading {url} - {e.__class__}: {e}")
        return e


def download_albums(driver, urls):
    for link in urls:
        logger.info(f'Downloading {link}')
        download_album(driver, link)


def download_label(driver, url):
    driver.get(url)
    global BASE_URL
    BASE_URL = urlsplit(url).netloc
    links = []
    for album in driver.find_elements("xpath", xpath['albums']):
        links.append(album.get_attribute('href'))
    download_albums(driver, links)


def main():
    global arguments
    arguments = docopt(__doc__, version=__version__)
    if arguments['-a'] or arguments['-l']:
        # set options
        for option in options:
            arg = f'--{option}'
            if arguments[arg]:
                options[option] = arguments[arg][0]
            else:
                options[option] = config.get(option)
            if not options[option]:
                logger.error(
                    f'{option} is not set, use "bcdl-free setdefault {arg} <{option}>"')
                sys.exit(1)
        if options['format'] not in formats:
            logger.error(
                f'{options["format"]} is not a valid format. See "bcdl-free -h" for valid formats')
            sys.exit(1)
        init_downloaded()
    driver = get_driver()
    try:
        if arguments['-a']:
            err = download_album(driver, arguments['-a'])
            if err:
                sys.exit(1)
        elif arguments['-l']:
            download_label(driver, arguments['-l'])
        elif arguments['setdefault']:
            # write arguments to config
            for option in options:
                arg = f'--{option}'
                if arguments[arg]:
                    config.set(option, arguments[arg][0])
        elif arguments['defaults']:
            print(str(config))
        elif arguments['clear']:
            with open(config.get('download_history_file'), 'w'):
                pass
        # download emailed albums
        checked_ids = set()
        album_urls = set()
        global expected_emails
        logger.info(f'Waiting for {expected_emails} emails from bandcamp')
        while expected_emails > 0:
            time.sleep(10)
            try:
                for email in mail_session.get_email_list():
                    if email.guid not in checked_ids:
                        checked_ids.add(email.guid)
                        if email.sender == 'noreply@bandcamp.com' and 'download' in email.subject:
                            logger.info(f'Received email "{email.subject}"')
                            email = mail_session.get_email(email.guid)
                            match = link_regex.search(email.body)
                            if match:
                                download_url = match.group('url')
                                album_urls.add(download_url)
                                expected_emails -= 1
            except Exception as e:
                logger.error(e)
        logger.info(f'Downloading {len(album_urls)} albums...')
        download_files(driver, album_urls)
    except:
        raise
    finally:
        driver.quit()


if __name__ == '__main__':
    main()
