from setuptools import setup, find_packages

import free_bandcamp_downloader

setup(
    name='free-bandcamp-downloader',
    version=free_bandcamp_downloader.__version__,
    packaged=find_packages(),
    author='7x11x13',
    install_requires=[
        'selenium',
        'docopt',
        'rfc6266'
    ],
    entry_points={
        'console_scripts': [
            'bcdl-free = free_bandcamp_downloader.main:main'
        ]
    }
)
