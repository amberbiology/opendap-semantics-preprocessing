from lxml import etree
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs
import urllib.request, urllib.error
from itertools import chain


class OpenSearchLinkBuilder(object):
    '''
    for an OSDD URL/@template url, create a generic
    search url, ie the link to return all results (if supported)
    '''

    def __init__(self, source_url, source_content):
        self.source_url = source_url
        self.source_content = source_content
        self._parse()

    def _parse(self):
        try:
            parser = etree.XMLParser(
                remove_blank_text=True,
                remove_comments=True,
                recover=True,
                remove_pis=True
            )
            self.xml = etree.fromstring(self.source_content, parser=parser)
        except:
            self.xml = None

    def _extract_urls(self, mimetype='atom+xml'):
        return self.xml.xpath(
            '//*[local-name()="Url" and ' +
            '(@*[local-name()="type"]="application/%(mimetype)s" or ' +
            '@*[local-name()="type"]="text/%(mimetype)s")]' % {'mimetype': mimetype})

    def generate_urls(self):
        template_urls = self._extract_urls('atom+xml') + self._extract_urls('rss+xml')
        template_urls = list(set(template_urls))

        urls = []

        if not template_urls:
            return urls

        for template_url in template_urls:
            osl = OpenSearchLink(template_url)
            if osl.url:
                urls.append(osl.url)

        return urls


class OpenSearchLink():
    def __init__(self, template_elem):
        self.url = '' # initialize empty
        self.elem = template_elem
        self._generate()

    def _generate(self):
        url_base, defaults, params = self._extract_template(self.elem.attrib.get('template'))
        if not url_base:
            return ''
        search_terms = self._extract_parameter_key('searchTerms', params)
        if search_terms:
            qps = dict(
                chain(
                    list(defaults.items()),
                    list({list(search_terms.keys())[0]: ''}.items())
                )
            )
        else:
            # make sure qps has a value
            qps = {} 

        self.url = url_base + '?' + urlencode(list(qps.items()))

    def _extract_parameter_key(self, value, params):
        # sort out the query parameter name for a parameter
        # and don't send curly bracketed things, please
        return {k: v.split(':')[-1].replace('?', '') for k, v
                in list(params.items())
                if value in v}

    def _extract_template(self, template_url, append_limit=True):
        parts = urlparse(template_url)
        if not parts.scheme:
            return '', '', {}

        base_url = urlunparse((
            parts.scheme,
            parts.netloc,
            parts.path,
            None,
            None,
            None
        ))

        qp = {k: v[0] for k, v in parse_qs(parts.query).items()}

        # get the hard-coded params
        defaults = {k: v for k, v in qp.items()
                    if not v.startswith('{')
                    and not v.endswith('}')}

        # get the rest (and ignore the optional/namespaces)
        parameters = {k: v[1:-1] for k, v in qp.items()
                      if v.startswith('{')
                      and v.endswith('}')}

        if append_limit:
            terms = self._extract_parameter_key('count', parameters)
            if terms:
                defaults = dict(
                    chain(list(defaults.items()), list({k: 5 for k in list(terms.keys())}.items()))
                )

        # note: not everyone manages url-encoded query parameter delimiters
        #       and not everyone manages non-url-encoded values so yeah. we are
        #       ignoring the non-url-encoded group.
        return base_url, defaults, parameters
