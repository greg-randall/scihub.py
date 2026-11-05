# scihub.py

[![Python](https://img.shields.io/badge/Python-3%2B-blue.svg)](https://www.python.org)

scihub.py is an unofficial API for Sci-Hub. It can search for papers on Google Scholar and download papers from Sci-Hub. It can be imported as a library or used from the command line.

If you believe in open access to scientific papers, please donate to Sci-Hub.

## Features

* Download specific articles directly or via Sci-Hub
* Download a collection of articles by passing in a file of article identifiers
* Search for articles on Google Scholar and download them

**Note**: captchas show up every now and then, blocking searches or downloads. This is a known limitation.

**Note**: creating a `SciHub()` object makes a network request to `https://sci-hub.now.sh/` to find working Sci-Hub mirrors. If that request fails or returns no mirrors, `SciHub()` raises an exception. The command-line tool creates this object before parsing arguments, so even `--help` needs network access.

## Setup

```
python3 -m pip install -r requirements.txt
```

## Command-line usage

Run the script from the repository root:

```
python3 scihub/scihub.py -d <DOI|PMID|URL> -o papers
```

```
usage: scihub.py [-h] [-d (DOI|PMID|URL)] [-f path] [-s query] [-sd query]
                 [-l N] [-o path] [-v] [-p PROXY]

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
```

* `-f` expects a text file with one identifier (DOI, PMID or URL) per line.
* `-o` defaults to the current directory.
* `-p` accepts `http://`, `https://` or `socks5://` proxy URLs (SOCKS support comes from `pysocks`).
* `-v` currently has no effect: logging is already set to debug level by default.

## Library usage

Run Python from the repository root (or put the repository root on `PYTHONPATH`) so that the `scihub` package can be imported. The examples below demonstrate all the features.

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

* If the response is not a PDF (usually a captcha), `fetch` switches to the next Sci-Hub mirror and raises `CaptchaNeedException`.
* On a connection error, it switches to the next mirror and returns `None`.
* On any other request error, it returns `{'err': ERROR_MESSAGE}`.
* When there are no mirrors left, it raises `Exception('Ran out of valid sci-hub urls')`.

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

`download` retries up to 10 times when `fetch` fails, moving to the next mirror each time. If every attempt fails, the last exception is raised. It returns the same dictionary as `fetch`.

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
