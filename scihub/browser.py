# -*- coding: utf-8 -*-

"""
Fetch Sci-Hub pages and PDFs through a Camoufox (Firefox) browser.

Sci-Hub shows an "Are you a robot?" page backed by an ALTCHA proof-of-work
widget. The widget only starts when the "No" button is clicked; on success the
page posts the solution and reloads itself. A real browser handles this, and
the cookies it earns are reused to download the PDF.
"""

import logging
import os
import re
import time
from urllib.parse import unquote, urldefrag, urlsplit

logger = logging.getLogger('Sci-Hub')

# From the robot-check page: <div class="answer" onclick="check()">No</div>.
# Don't detect it by <altcha-widget>: the paper page has one of those too.
ANSWER_SELECTOR = '.question .answer'
CHALLENGE_SELECTOR = ANSWER_SELECTOR

# From the "no articles found" page: <... translate="en:notfound">I do not have any papers matching your request :(</...>
NOT_FOUND_SELECTOR = '[translate="en:notfound"]'

# Every attribute on the page that looks like a link to a PDF, resolved to an absolute URL.
FIND_PDF_LINKS_JS = """() => {
    const out = [];
    for (const el of document.querySelectorAll('[src], [href], [data]')) {
        for (const attr of ['src', 'data', 'href']) {
            const value = el.getAttribute(attr);
            if (value && value.toLowerCase().includes('.pdf')) {
                try { out.push(new URL(value, location.href).href); } catch (e) {}
            }
        }
    }
    return out;
}"""


class CaptchaNeedException(Exception):
    pass


class BrowserFetchError(Exception):
    pass


class ArticleNotFoundError(BrowserFetchError):
    """Sci-Hub says it has no article for the identifier."""
    pass


def _playwright_proxy(proxy):
    """Convert a proxy URL like socks5://user:pass@host:port to Playwright's proxy dict."""
    parts = urlsplit(proxy)
    server = '%s://%s' % (parts.scheme, parts.hostname)
    if parts.port:
        server += ':%d' % parts.port
    result = {'server': server}
    if parts.username:
        result['username'] = unquote(parts.username)
    if parts.password:
        result['password'] = unquote(parts.password)
    return result


def _safe_filename(text):
    """Make a string safe to use as a file name on Windows and Linux."""
    return re.sub(r'[^A-Za-z0-9._-]+', '_', text).strip('_')


class BrowserFetcher(object):
    """
    Lazily starts one Camoufox browser and reuses it for every fetch.
    Call close() (or use SciHub as a context manager) to shut it down.
    """

    def __init__(self, proxy=None, headless=True, debug_dir=None, timeout=90, captcha_attempts=3):
        self.proxy = proxy
        self.headless = headless
        self.debug_dir = debug_dir
        self.timeout_ms = timeout * 1000
        self.captcha_attempts = captcha_attempts
        self._camoufox = None
        self._browser = None
        self._context = None

    def _start(self):
        if self._context is not None:
            return
        from camoufox.sync_api import Camoufox

        options = {'headless': self.headless}
        if self.proxy:
            options['proxy'] = _playwright_proxy(self.proxy)

        logger.info('Starting Camoufox browser...')
        started = time.time()
        self._camoufox = Camoufox(**options)
        self._browser = self._camoufox.__enter__()
        self._context = self._browser.new_context()
        logger.info('Browser started in %.1fs', time.time() - started)

    def close(self):
        if self._camoufox is not None:
            self._camoufox.__exit__(None, None, None)
        self._camoufox = None
        self._browser = None
        self._context = None

    def _dump(self, page, reason):
        """Save the current page HTML so failures can be diagnosed from real data."""
        if not self.debug_dir:
            logger.info('No debug_dir set; not saving page HTML for %s', page.url)
            return None
        os.makedirs(self.debug_dir, exist_ok=True)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        name = '%s-%s-%s.html' % (stamp, reason, _safe_filename(page.url))
        path = os.path.join(self.debug_dir, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(page.content())
        logger.info('Saved page HTML (%s) to %s', reason, path)
        return path

    def _pass_robot_check(self, page):
        for attempt in range(1, self.captcha_attempts + 1):
            if page.query_selector(CHALLENGE_SELECTOR) is None:
                return
            logger.info('Robot check on %s, clicking "No" (attempt %d/%d, proof-of-work may take a while)...',
                        page.url, attempt, self.captcha_attempts)
            started = time.time()
            with page.expect_navigation(wait_until='load', timeout=self.timeout_ms):
                page.click(ANSWER_SELECTOR, timeout=self.timeout_ms)
            logger.info('Page reloaded after robot check in %.1fs', time.time() - started)

        if page.query_selector(CHALLENGE_SELECTOR) is not None:
            self._dump(page, 'captcha')
            raise CaptchaNeedException('Robot check still shown on %s after %d attempts'
                                       % (page.url, self.captcha_attempts))

    def fetch_pdf(self, page_url):
        """
        Load a Sci-Hub page, pass the robot check if shown, find the PDF and download it.
        Returns (pdf_bytes, pdf_url).
        """
        self._start()
        page = self._context.new_page()

        # PDFs the page itself loads (e.g. in an <embed>) show up here.
        pdf_responses = []

        def on_response(response):
            if 'application/pdf' in response.headers.get('content-type', ''):
                pdf_responses.append(response.url)

        page.on('response', on_response)

        try:
            logger.info('Loading %s', page_url)
            started = time.time()
            page.goto(page_url, wait_until='load', timeout=self.timeout_ms)
            logger.info('Loaded "%s" in %.1fs', page.title(), time.time() - started)

            self._pass_robot_check(page)

            if page.query_selector(NOT_FOUND_SELECTOR) is not None:
                raise ArticleNotFoundError('Sci-Hub has no article for %s' % page.url)

            candidates = []
            for url in pdf_responses + page.evaluate(FIND_PDF_LINKS_JS):
                url = urldefrag(url)[0]
                if url not in candidates:
                    candidates.append(url)
            logger.info('PDF candidates on %s: %s', page.url, candidates)

            if not candidates:
                self._dump(page, 'no-pdf-link')
                raise BrowserFetchError('No PDF link found on %s (title "%s")' % (page.url, page.title()))

            for url in candidates:
                logger.info('Downloading %s', url)
                started = time.time()
                response = self._context.request.get(url, timeout=self.timeout_ms)
                content_type = response.headers.get('content-type', '')
                body = response.body()
                logger.info('Got HTTP %d, %s, %d bytes in %.1fs',
                            response.status, content_type, len(body), time.time() - started)
                if response.ok and body.startswith(b'%PDF'):
                    return body, url

            self._dump(page, 'pdf-download-failed')
            raise BrowserFetchError('None of the PDF links on %s returned a PDF: %s' % (page.url, candidates))
        finally:
            page.close()
