# scihub.py

[![Python](https://img.shields.io/badge/Python-3%2B-blue.svg)](https://www.python.org)

scihub.py is an unofficial API for Sci-Hub. It can search for papers on Google Scholar and download papers from Sci-Hub. It can be imported as a library or used from the command line.

If you believe in open access to scientific papers, please donate to Sci-Hub.

## Features

* Download specific articles directly or via Sci-Hub
* Download a collection of articles by passing in a file of article identifiers
* Search for articles on Google Scholar and download them

**Note**: captchas show up every now and then, blocking searches or downloads. This is a known limitation.

**How Sci-Hub pages are loaded**: Sci-Hub shows an "Are you a robot?" page (an ALTCHA proof-of-work check) before the paper. scihub.py loads Sci-Hub pages in a [Camoufox](https://camoufox.com/) browser, clicks through that check, finds the PDF link on the paper page and downloads it with the browser's cookies. The browser starts on the first Sci-Hub fetch and is reused after that. Direct links to `.pdf` files are downloaded with `requests` and don't start the browser.

**Mirrors**: the default mirror is `https://sci-hub.ru`. Pass others with `-m` on the command line or `base_urls=[...]` in Python; they're tried in order when one fails.

## Setup

```
python3 -m pip install -r requirements.txt
```

The first run downloads the Camoufox browser (2.4 GB on disk for v158.0.1-beta.41, into `~/.cache/camoufox`). To do that ahead of time, run `python3 -m camoufox fetch`.

## Command-line usage

Run it as a module from the repository root:

```
python3 -m scihub -d <DOI|PMID|URL> -o papers
```

Quote DOIs that contain parentheses, e.g. `-d '10.1016/0266-1144(89)90022-8'`.

```
usage: scihub [-h] [-d (DOI|PMID|URL)] [-f path] [-s query] [-sd query]
              [-l N] [-o path] [-v] [-p PROXY] [-m URL] [--show-browser]
              [--debug-dir path]

SciHub - To remove all barriers in the way of science.

options:
  -h, --help            show this help message and exit
  -d (DOI|PMID|URL), --download (DOI|PMID|URL)
                        tries to find and download the paper
  -f path, --file path  pass file with list of identifiers and download each
  -s query, --search query
                        search Google Scholars
  -sd query, --search_download query
                        search Google Scholars and download if possible
  -l N, --limit N       the number of search results to limit to
  -o path, --output path
                        directory to store papers
  -v, --verbose         increase output verbosity
  -p PROXY, --proxy PROXY
                        via proxy format like socks5://user:pass@host:port
  -m URL, --mirror URL  sci-hub mirror to use; repeat to give fallbacks
                        (default: https://sci-hub.ru)
  --show-browser        show the browser window instead of running headless
  --debug-dir path      where to save page HTML when a download fails
                        (default: data/debug)
```

* `-f` expects a text file with one identifier (DOI, PMID or URL) per line; blank lines are skipped. A failed identifier doesn't stop the batch: it's logged, the batch carries on, and a summary of failures is printed at the end.
* `-o` defaults to the current directory.
* `-p` accepts `http://`, `https://` or `socks5://` proxy URLs and applies to both `requests` and the browser. SOCKS support in `requests` comes from `pysocks`; the browser (Playwright) doesn't support SOCKS proxies with a username and password.
* When a download fails for an unexpected reason (robot check not passed, no PDF link on the page), the page HTML is saved to `--debug-dir` so you can see what Sci-Hub actually returned.
* The exit status is 0 when everything succeeded and 1 when anything failed, including a DOI Sci-Hub doesn't have.
* `-v` currently has no effect: logging is already set to debug level by default.

## Library usage

Run Python from the repository root (or put the repository root on `PYTHONPATH`) so that the `scihub` package can be imported. The examples below demonstrate all the features.

`SciHub` takes optional `base_urls` (list of mirrors), `proxy`, `headless` (default `True`) and `debug_dir` (default `None`, meaning page HTML isn't saved on failure). Use it as a context manager, or call `sh.close()` when done, so the browser shuts down:

```python
from scihub import SciHub

with SciHub(base_urls=['https://sci-hub.ru'], debug_dir='data/debug') as sh:
    sh.download('10.1016/0266-1144(89)90022-8', destination='papers')
```

### fetch

```python
from scihub import SciHub

sh = SciHub()

# fetch a specific article without saving it to disk
result = sh.fetch('http://ieeexplore.ieee.org/xpl/login.jsp?tp=&arnumber=1648853')
```

On success, `fetch` returns a dictionary:

```python
{
    'pdf': PDF_DATA,      # bytes
    'url': SOURCE_URL,
    'name': UNIQUE_GENERATED_NAME
}
```

Other outcomes:

* If the robot check is still showing after 3 clicks, `fetch` switches to the next mirror (if there is one) and raises `CaptchaNeedException`.
* If the browser fails to load the page (mirror unreachable, timeout), it switches to the next mirror (if there is one) and re-raises the browser error.
* If Sci-Hub has no article for the identifier, it returns `{'err': 'Sci-Hub has no article for identifier ...'}`.
* If the paper page has no PDF link, or none of the links return a PDF, it returns `{'err': ERROR_MESSAGE}`.
* For a direct `.pdf` URL, a request error or a non-PDF response returns `{'err': ERROR_MESSAGE}`.

### download

```python
from scihub import SciHub

sh = SciHub()

# same as fetch, but saves the PDF to disk.
# destination is the directory (default: current directory);
# path is the file name (default: the generated unique name)
result = sh.download('http://ieeexplore.ieee.org/xpl/login.jsp?tp=&arnumber=1648853',
                     destination='papers', path='paper.pdf')
```

`download` makes up to 3 attempts when `fetch` raises, moving to the next mirror each time if there is one. If every attempt fails, the last exception is raised. It creates `destination` if it doesn't exist, and returns the same dictionary as `fetch`.

### search

```python
from scihub import SciHub

sh = SciHub()

# retrieve 5 articles on Google Scholar related to 'bittorrent'
results = sh.search('bittorrent', 5)

# download the papers, going through Sci-Hub when needed
for paper in results['papers']:
    sh.download(paper['url'])
```

`search` returns `{'papers': [{'name': ..., 'url': ...}, ...]}`. If the search fails (connection error or captcha), the dictionary also contains an `'err'` key.

## License

MIT
