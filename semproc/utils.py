import urllib.parse
import urllib.request, urllib.parse, urllib.error
import collections
from uuid import uuid4
import hashlib
from itertools import chain
from html.parser import HTMLParser
import re


'''
url handling:
    query parameter parsing
'''


def unquote(url):
    return urllib.parse.unquote(url)


def break_url(url):
    parts = urllib.parse.urlparse(url)

    url = urllib.parse.urlunparse((
        parts.scheme,
        parts.netloc,
        parts.path,
        None, None, None
    ))

    params = urllib.parse.parse_qs(parts.query)
    values = list(chain.from_iterable((list(params.values()))))

    return url, ' '.join(values)


def parse_url(url):
    '''
    strip out the query parameters
    '''
    if not url:
        return ''
    parsed_url = urllib.parse.urlparse(url)
    return urllib.parse.parse_qs(parsed_url.query)


'''
general utils
'''


def match(s, p):
    m = re.search(p, s)
    return m.group(0) if m else ''


def generate_short_uuid():
    '''
    this is not a proper uuid and should not be used as such
    it is the first chunk of the hash
    '''
    return str(uuid4()).split('-')[0]


def generate_uuid_urn():
    return uuid4().urn


def generate_sha(text):
    return hashlib.sha224(text.encode(encoding='UTF-8')).hexdigest()


def generate_sha_urn(text):
    return 'urn:sha:%s' % generate_sha(text)


def extract_element_tag(tag):
    '''
    drop the fully qualified namespace
    '''
    if not tag:
        return

    return tag.split('}')[-1]


def convert_header_list(headers):
    '''
    convert from the list of strings, one string
    per kvp, to a dict with keys normalized
    '''
    return dict(
        (k.strip().lower(), v.strip()) for k, v in (
            h.split(':', 1) for h in headers)
    )


def remap_http_method(original_method):
    '''
    return the "full" http method from some input
    '''
    definition = {
        "HTTP GET": ['get'],
        "HTTP POST": ['post']
    }
    for k, v in list(definition.items()):
        if original_method.lower() in v:
            return k
    return original_method


def generate_qualified_xpath(elem, do_join=True):
    '''
    from some element, iterate through the parents
    and generate the xpath back to it (without specific
        text values, ie no [text()= "thing"])
    '''
    tags = [elem.tag] + [e.tag for e in elem.iterancestors()]
    tags.reverse()
    return '/'.join(tags) if do_join else tags


def tidy_dict(items):
    # cleanup a dict (remove empty elements)
    # but only at the single depth
    to_remove = []
    for k, v in list(items.items()):
        if not v:
            to_remove.append(k)
    for k in to_remove:
        del items[k]

    return items


def flatten(items, excluded_keys=[]):
    '''
    flatten a list of irregular lists/singletons
    or some dict of singletons, lists, dicts

    basically just get a list of terminal strings
    '''

    def _flatten(item):
        if isinstance(item, dict):
            for k, v in list(item.items()):
                if k in excluded_keys:
                    continue
                # TODO: this introduces nested lists again!
                yield list(_flatten(v))
        elif isinstance(item, list):
            for i in item:
                if isinstance(i, collections.Iterable) \
                        and not isinstance(i, str):
                    for subitem in _flatten(i):
                        yield subitem
                else:
                    yield i
        elif isinstance(item, str):
            yield item

    arr = list(_flatten(items))
    if len([isinstance(a, collections.Iterable) and
            not isinstance(a, str) for a in arr]) > 0:
        # ick, flatten the dict issue again.
        return list(_flatten(arr))

    return arr


def strip_whitespace_from_xml(xml):
    ''' do not remember if this is necessary, but here it is '''
    for elem in xml.iter():
        t = elem.text.strip() if elem.text else ''
        if not t:
            continue
        elem.text = ' '.join(t.split())

    return xml


def strip_html(xml):
    # NOTE: this is deprecated by new parsers (10/1/2015)
    for elem in xml.iter():
        t = elem.text.strip() if elem.text else ''
        if not t:
            continue

        hparser = TextParser()
        hparser.feed(t)
        elem.text = hparser.get_data()

    return xml


class TextParser(HTMLParser):
    '''
    basic html parsing for text with html-encoded tags
    '''
    def __init__(self):
        self.reset()
        self.fed = []

    def handle_data(self, d):
        self.fed.append(d)

    def get_data(self):
        return ''.join(self.fed)
