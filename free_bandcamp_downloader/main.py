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
    - AIFF
"""

import atexit, time, sys, urllib.request, os
from docopt import docopt
from guerrillamail import GuerrillaMailSession
from selenium import webdriver
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.firefox.options import Options

from free_bandcamp_downloader import __version__, config, logger

# Global variables
arguments = None
driver = None
downloaded = set()
options = {
    'country': None,
    'zipcode': None,
    'email': None,
    'format': None,
    'dir': None
}

# Constants
xpath = {
    'buy': '//*[@class="ft compound-button main-button"]/button[@class="download-link buy-link"]',
    'price': '//input[@id="userPrice"]',
    'download-nyp': '//a[@class="download-panel-free-download-link"]',
    'checkout': '//button[@class="download-panel-checkout-button" and not(ancestor::div[contains(@style,"display:none")])]',
    'email': '//input[@id="fan_email_address"]',
    'country': '//select[@id="fan_email_country"]',
    'zipcode': '//input[@id="fan_email_postalcode"]',
    'preparing': '//span[@class="preparing-title"]',
    'formats': '//div[@class="item-format button"]',
    'download': '//a[@class="item-button"]',
    'albums': '//a[./p[@class="title"]]'
}

formats = {
    'FLAC': 'FLAC',
    'V0MP3': 'MP3 V0',
    '320MP3': 'MP3 320',
    'AAC': 'AAC',
    'Ogg': 'Ogg Vorbis',
    'ALAC': 'ALAC',
    'WAV': 'WAV',
    'AIFF': 'AIFF'
}

def wait():
    time.sleep(1)

def init_driver():
    global driver
    if not driver:
        options = Options()
        options.add_argument('--headless')
        driver = webdriver.Firefox(firefox_options=options, service_log_path=os.devnull)
        atexit.register(driver.quit)
        driver.implicitly_wait(10)

def init_downloaded():
    with open(config.get('download_history_file'), 'r') as f:
        for line in f:
            downloaded.add(line.strip())

def download_file(page_url):
    logger.info('On download page')
    driver.find_element_by_xpath(xpath['formats']).click()
    wait()
    driver.find_element_by_xpath(f'//*[text() = "{formats[options["format"]]}"]').click()
    logger.info(f'Set format to {formats[options["format"]]}')
    wait()
    button = driver.find_element_by_xpath(xpath['download'])
    WebDriverWait(driver, 60).until(EC.visibility_of(button))
    url = button.get_attribute('href')
    response = urllib.request.urlopen(url)
    name = os.path.basename(response.headers.get_filename().encode('latin-1').decode('utf-8'))
    length = int(response.getheader('content-length'))
    block_size = length // 10
    with open(os.path.join(options['dir'], name), 'wb') as f:
        size = 0
        while True:
            buf = response.read(block_size)
            if not buf:
                break
            f.write(buf)
            size += len(buf)
            logger.info(f'Downloading {name}, {size / length * 100: .1f}%')
    response.close()
    logger.info(f'Downloaded {os.path.join(options["dir"], name)}')
    # successfully downloaded file, add to download history
    downloaded.add(page_url)
    with open(config.get('download_history_file'), 'a') as f:
        f.write(f'{page_url}\n')

def download_album(url):
    if url in downloaded and not arguments['--force']:
        return f'{url} already downloaded. To download anyways, use option --force'
    init_driver()
    driver.get(url)
    wait()
    try:
        button = driver.find_element_by_xpath(xpath['buy'])
        if button.text == 'Free Download':
            logger.info('Album is Free Download')
            button.click()
            wait()
            return download_file(url)
        else:
            # name your price download
            logger.info('Album is not Free Download')
            button.click()
            wait()
            price_input = driver.find_element_by_xpath(xpath['price'])
            price_input.click()
            price_input.send_keys('0')
            logger.info('Set payment to 0')
            wait()
            try:
                driver.find_element_by_xpath(xpath['download-nyp']).click()
            except:
                return f'Album {url} is not free'
            checkout = driver.find_element_by_xpath(xpath['checkout'])
            if checkout.text == 'Download Now':
                checkout.click()
                wait()
                return download_file(url)
            else:
                logger.info('Album requires email')
                # fill out info
                driver.find_element_by_xpath(xpath['email']).send_keys(options['email'])
                wait()
                driver.find_element_by_xpath(xpath['zipcode']).send_keys(options['zipcode'])
                wait()
                Select(driver.find_element_by_xpath(xpath['country'])).select_by_visible_text(options['country'])
                wait()
                checkout.click()
                logger.info(f'Download link sent to {options["email"]}')
    except Exception as e:
        return e


def download_label(url):
    init_driver()
    driver.get(url)
    links = []
    for album in driver.find_elements_by_xpath(xpath['albums']):
        links.append(album.get_attribute('href'))
    for link in links:
        logger.info(f'Downloading album at {link}')
        err = download_album(link)
        if err:
            logger.info(err)

def main():
    global arguments
    arguments = docopt(__doc__, version=__version__)
    if arguments['-a'] or arguments['-l']:
        init_downloaded()
        # set options
        for option in options:
            arg = f'--{option}'
            if arguments[arg]:
                options[option] = arguments[arg][0]
            else:
                options[option] = config.get(option)
            if not options[option]:
                logger.error(f'{option} is not set, use "bcdl-free setdefault {arg} <{option}>"')
                sys.exit(1)
        if options['format'] not in formats:
            logger.error(f'{options["format"]} is not a valid format. See "bcdl-free -h" for valid formats')
            sys.exit(1)
    if arguments['-a']:
        err = download_album(arguments['-a'])
        if err:
            logger.error(err)
            sys.exit(1)
    elif arguments['-l']:
        download_label(arguments['-l'])
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
    

if __name__ == '__main__':
    main()
