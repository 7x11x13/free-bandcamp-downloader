from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context


# https://github.com/urllib3/urllib3/issues/3439#issuecomment-2306400349
class BandcampHTTPAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        ctx = create_urllib3_context()
        ctx.load_default_certs()
        DEFAULT_CIPHERS = ":".join(
            [
                "ECDHE+AESGCM",
                "ECDHE+CHACHA20",
                "DHE+AESGCM",
                "DHE+CHACHA20",
                "ECDH+AESGCM",
                "DH+AESGCM",
                "ECDH+AES",
                "DH+AES",
                "RSA+AESGCM",
                "RSA+AES",
                "!aNULL",
                "!eNULL",
                "!MD5",
                "!DSS",
                "!AESCCM",
            ]
        )
        ctx.set_ciphers(DEFAULT_CIPHERS)
        return super().init_poolmanager(
            connections, maxsize, block, **pool_kwargs, ssl_context=ctx
        )
