# -*- coding: utf-8 -*-

"""
Sci-API Unofficial API
[Search|Download] research papers from [scholar.google.com|sci-hub].

@author zaytoun
"""

import re
import argparse
import hashlib
import logging
import os

import requests
import urllib3
from bs4 import BeautifulSoup
from retrying import retry

try:
    from .browser import BrowserFetcher, BrowserFetchError, CaptchaNeedException
except ImportError:  # run as a script: python3 scihub/scihub.py
    from browser import BrowserFetcher, BrowserFetchError, CaptchaNeedException

# log config
logging.basicConfig()
logger = logging.getLogger('Sci-Hub')
logger.setLevel(logging.DEBUG)

#
urllib3.disable_warnings()

# constants
SCHOLARS_BASE_URL = 'https://scholar.google.com/scholar'
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:27.0) Gecko/20100101 Firefox/27.0'}
DEFAULT_MIRRORS = ['https://sci-hub.ru']


class OutOfMirrorsError(Exception):
    pass


class SciHub(object):
    """
    SciHub class can search for papers on Google Scholars
    and fetch/download papers from sci-hub.

    Pages on sci-hub are loaded in a Camoufox browser so its robot check can be
    passed. Call close() when done, or use SciHub as a context manager.
    """

    def __init__(self, base_urls=None, proxy=None, headless=True, debug_dir=None):
        self.sess = requests.Session()
        self.sess.headers = HEADERS
        self.available_base_url_list = [u.rstrip('/') for u in (base_urls or DEFAULT_MIRRORS)]
        self.base_url = self.available_base_url_list[0] + '/'
        self.browser = BrowserFetcher(headless=headless, debug_dir=debug_dir)
        self.set_proxy(proxy)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.browser.close()

    def set_proxy(self, proxy):
        '''
        set proxy for session and browser (must be called before the first fetch
        for the browser to pick it up)
        :param proxy: proxy URL like socks5://user:pass@host:port
        :return:
        '''
        if proxy:
            self.sess.proxies = {
                "http": proxy,
                "https": proxy, }
            self.browser.proxy = proxy

    def _change_base_url(self):
        if len(self.available_base_url_list) <= 1:
            raise OutOfMirrorsError('Ran out of valid sci-hub urls')
        del self.available_base_url_list[0]
        self.base_url = self.available_base_url_list[0] + '/'
        logger.info("I'm changing to {}".format(self.available_base_url_list[0]))

    def search(self, query, limit=10, download=False):
        """
        Performs a query on scholar.google.com, and returns a dictionary
        of results in the form {'papers': ...}. Unfortunately, as of now,
        captchas can potentially prevent searches after a certain limit.
        """
        start = 0
        results = {'papers': []}

        while True:
            try:
                res = self.sess.get(SCHOLARS_BASE_URL, params={'q': query, 'start': start})
            except requests.exceptions.RequestException:
                results['err'] = 'Failed to complete search with query %s (connection error)' % query
                return results

            s = self._get_soup(res.content)
            papers = s.find_all('div', class_="gs_r")

            if not papers:
                if 'CAPTCHA' in str(res.content):
                    results['err'] = 'Failed to complete search with query %s (captcha)' % query
                return results

            for paper in papers:
                if not paper.find('table'):
                    source = None
                    pdf = paper.find('div', class_='gs_ggs gs_fl')
                    link = paper.find('h3', class_='gs_rt')

                    if pdf:
                        source = pdf.find('a')['href']
                    elif link.find('a'):
                        source = link.find('a')['href']
                    else:
                        continue

                    results['papers'].append({
                        'name': link.text,
                        'url': source
                    })

                    if len(results['papers']) >= limit:
                        return results

            start += 10

    @retry(wait_random_min=100, wait_random_max=1000, stop_max_attempt_number=3,
           retry_on_exception=lambda e: not isinstance(e, OutOfMirrorsError))
    def download(self, identifier, destination='', path=None):
        """
        Downloads a paper from sci-hub given an indentifier (DOI, PMID, URL).
        Currently, this can potentially be blocked by a captcha if a certain
        limit has been reached.
        """
        data = self.fetch(identifier)

        if 'err' not in data:
            if destination:
                os.makedirs(destination, exist_ok=True)
            self._save(data['pdf'],
                       os.path.join(destination, path if path else data['name']))

        return data

    def fetch(self, identifier):
        """
        Fetches the paper. If the identifier is a direct link to a PDF, download it
        directly. Otherwise (DOI, PMID, or pay-walled URL) load it on sci-hub in the
        browser and download the PDF from there.
        """
        if self._classify(identifier) == 'url-direct':
            return self._fetch_direct(identifier)

        page_url = self.base_url + identifier
        try:
            pdf, url = self.browser.fetch_pdf(page_url)
        except CaptchaNeedException:
            logger.info('Failed to fetch pdf with identifier %s (page %s) due to captcha' % (identifier, page_url))
            self._try_next_mirror()
            raise
        except BrowserFetchError as e:
            logger.info('Failed to fetch pdf with identifier %s: %s' % (identifier, e))
            return {'err': 'Failed to fetch pdf with identifier %s: %s' % (identifier, e)}
        except Exception as e:  # browser/navigation errors, e.g. mirror unreachable
            logger.info('Browser error on %s (%s: %s)' % (page_url, type(e).__name__, e))
            self._try_next_mirror()
            raise

        return {
            'pdf': pdf,
            'url': url,
            'name': self._generate_name(url, pdf)
        }

    def _try_next_mirror(self):
        try:
            self._change_base_url()
        except OutOfMirrorsError:
            logger.info('No other sci-hub mirror to switch to; retrying %s' % self.base_url)

    def _fetch_direct(self, url):
        try:
            # verify=False is dangerous but some hosts serve incomplete
            # certificate chains that requests can't verify.
            res = self.sess.get(url, verify=False)
        except requests.exceptions.RequestException as e:
            logger.info('Failed to fetch pdf from %s due to request exception: %s' % (url, e))
            return {'err': 'Failed to fetch pdf from %s due to request exception: %s' % (url, e)}

        if not res.content.startswith(b'%PDF'):
            return {'err': 'Failed to fetch pdf from %s (got %s, HTTP %d)'
                           % (url, res.headers.get('Content-Type'), res.status_code)}
        return {
            'pdf': res.content,
            'url': url,
            'name': self._generate_name(res.url, res.content)
        }

    def _classify(self, identifier):
        """
        Classify the type of identifier:
        url-direct - openly accessible paper
        url-non-direct - pay-walled paper
        pmid - PubMed ID
        doi - digital object identifier
        """
        if (identifier.startswith('http') or identifier.startswith('https')):
            if identifier.endswith('pdf'):
                return 'url-direct'
            else:
                return 'url-non-direct'
        elif identifier.isdigit():
            return 'pmid'
        else:
            return 'doi'

    def _save(self, data, path):
        """
        Save a file give data and a path.
        """
        with open(path, 'wb') as f:
            f.write(data)

    def _get_soup(self, html):
        """
        Return html soup.
        """
        return BeautifulSoup(html, 'html.parser')

    def _generate_name(self, url, content):
        """
        Generate unique filename for paper. Returns a name by calcuating
        md5 hash of file contents, then appending the last 20 characters
        of the url which typically provides a good paper identifier.
        """
        name = url.split('/')[-1]
        name = re.sub('#view=(.+)', '', name)
        name = re.sub(r'[\\/:*?"<>|]', '_', name)
        pdf_hash = hashlib.md5(content).hexdigest()
        return '%s-%s' % (pdf_hash, name[-20:])


def main():
    parser = argparse.ArgumentParser(prog='scihub', description='SciHub - To remove all barriers in the way of science.')
    parser.add_argument('-d', '--download', metavar='(DOI|PMID|URL)', help='tries to find and download the paper',
                        type=str)
    parser.add_argument('-f', '--file', metavar='path', help='pass file with list of identifiers and download each',
                        type=str)
    parser.add_argument('-s', '--search', metavar='query', help='search Google Scholars', type=str)
    parser.add_argument('-sd', '--search_download', metavar='query',
                        help='search Google Scholars and download if possible', type=str)
    parser.add_argument('-l', '--limit', metavar='N', help='the number of search results to limit to', default=10,
                        type=int)
    parser.add_argument('-o', '--output', metavar='path', help='directory to store papers', default='', type=str)
    parser.add_argument('-v', '--verbose', help='increase output verbosity', action='store_true')
    parser.add_argument('-p', '--proxy', help='via proxy format like socks5://user:pass@host:port', action='store', type=str)
    parser.add_argument('-m', '--mirror', metavar='URL', action='append',
                        help='sci-hub mirror to use; repeat to give fallbacks (default: %s)' % DEFAULT_MIRRORS[0])
    parser.add_argument('--show-browser', action='store_true', help='show the browser window instead of running headless')
    parser.add_argument('--debug-dir', metavar='path', default=os.path.join('data', 'debug'),
                        help='where to save page HTML when a download fails (default: %(default)s)')

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    with SciHub(base_urls=args.mirror, proxy=args.proxy, headless=not args.show_browser,
                debug_dir=args.debug_dir) as sh:
        run(sh, args)


def run(sh, args):
    if args.download:
        result = sh.download(args.download, args.output)
        if 'err' in result:
            logger.debug('%s', result['err'])
        else:
            logger.debug('Successfully downloaded file with identifier %s', args.download)
    elif args.search:
        results = sh.search(args.search, args.limit)
        if 'err' in results:
            logger.debug('%s', results['err'])
        else:
            logger.debug('Successfully completed search with query %s', args.search)
        print(results)
    elif args.search_download:
        results = sh.search(args.search_download, args.limit)
        if 'err' in results:
            logger.debug('%s', results['err'])
        else:
            logger.debug('Successfully completed search with query %s', args.search_download)
            for paper in results['papers']:
                result = sh.download(paper['url'], args.output)
                if 'err' in result:
                    logger.debug('%s', result['err'])
                else:
                    logger.debug('Successfully downloaded file with identifier %s', paper['url'])
    elif args.file:
        with open(args.file, 'r') as f:
            identifiers = f.read().splitlines()
            for i, identifier in enumerate(identifiers, 1):
                logger.info('[%d/%d] %s', i, len(identifiers), identifier)
                result = sh.download(identifier, args.output)
                if 'err' in result:
                    logger.debug('%s', result['err'])
                else:
                    logger.debug('Successfully downloaded file with identifier %s', identifier)


if __name__ == '__main__':
    main()
