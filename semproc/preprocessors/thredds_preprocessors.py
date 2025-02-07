from semproc.processor import Processor
from semproc.utils import extract_element_tag
from semproc.utils import generate_short_uuid
from semproc.utils import tidy_dict
from semproc.xml_utils import extract_elems, extract_attrib
from semproc.urlbuilders.thredds_links import ThreddsLink
from semproc.utils import generate_sha_urn, generate_uuid_urn


class ThreddsReader(Processor):
    def _manage_id(self, obj):
        if 'ID' not in obj:
            obj.update({"ID": generate_short_uuid()})
        return obj

    def _get_items(self, tag, elem, base_url, service_bases):
        '''
        return any structure not part of the
        current element's attributes
        '''

        def _normalize_key(key):
            '''
            standardize the url (or other) xml tags to the desired
            json key

            as source key: endpoint key
            '''
            remaps = {
                "serviceType": "type",
                "href": "url",
                "base": "url",
                "urlPath": "url"
            }

            if key in remaps:
                return remaps[key]
            return key

        def _run_element(elem, service_bases):
            '''
            for a given element, return any text() and any attribute value
            '''
            # run a generated xpath on the given element
            children = elem.xpath('./node()[local-name()!="metadata"' +
                                  'and local-name()!="dataset" and' +
                                  'local-name()!="catalogRef"]')

            element = {_normalize_key(extract_element_tag(k)): v for k, v
                       in elem.attrib.iteritems()}
            element = self._manage_id(element)

            for child in children:
                value = child.text
                # xp = generate_qualified_xpath(child, True)
                tag = _normalize_key(extract_element_tag(child.tag))

                if value:
                    element[tag] = value

                for k, v in child.attrib.iteritems():
                    if v:
                        element[tag + '_' + _normalize_key(extract_element_tag(k))] = v

            # get the service bases in case
            if [g for g in element.keys() if g.endswith('serviceName')]:
                sbs = [v for k, v in service_bases.iteritems() if k == element.get('serviceName')]
            else:
                sbs = service_bases.values()

            # send a unique list of base relative paths
            sbs = list(set(sbs))

            url_key = next(iter([g for g in element.keys() if g.endswith('url')]), '')
            if url_key:
                # for service urls, if catalog.xml isn't appended it will resolve to
                # the html endpoint (not desired). so if the path equals the/a path in
                # the service bases, append catalog.xml to the path

                # elem_url = element[url_key]
                # if elem_url in sbs or not sbs:
                #     elem_url += ('' if elem_url.endswith('/') else '/') + 'catalog.xml'
                # # element['url'] = intersect_url(base_url, elem_url, sbs)
                # # element['url'] = base_url

                # let's generate the link
                tl = ThreddsLink(elem, self.url, sbs)
                element['url'] = tl.urls

                element['actionable'] = 2

            return element

        children = extract_elems(elem, ['metadata']) + \
            extract_elems(elem, ['dataset']) + \
            extract_elems(elem, ['catalogRef'])

        # elem.xpath('./node()[local-name()="metadata" or ' +
        #                       'local-name()="dataset" or local-name()="catalogRef"]')

        element = _run_element(elem, service_bases)
        element_children = []
        for c in children:
            element_desc = _run_element(c, service_bases)
            element_children.append(element_desc)

        if element_children:
            element['children'] = element_children

        return element

    def _handle_elem(self, elem, child_tags, base_url, service_bases):
        description = self._get_items(
            extract_element_tag(elem.tag), elem, base_url, service_bases
        )
        description['source'] = extract_element_tag(elem.tag)

        endpoints = []

        for child_tag in child_tags:
            elems = extract_elems(elem, [child_tag])

            for e in elems:
                e_desc = self._get_items(
                    extract_element_tag(e.tag), e, base_url, service_bases
                )

                e_desc['childOf'] = description.get('ID', '')
                e_desc["source"] = extract_element_tag(child_tag)

                parents = description.get('parentOf', [])
                parents += [e['ID'] for e in endpoints if 'childOf' in e]
                description['parentOf'] = parents

                endpoints.append(e_desc)

        return description, endpoints

    def parse(self):
        output = {}
        urls = set()

        if 'service' in self.identify:
            service = {
                "object_id": generate_uuid_urn(),
                "dcterms:title": extract_attrib(self.parser.xml, ['@name']),
                "rdf:type": "UNIDATA:THREDDS {0}".format(
                    extract_attrib(self.parser.xml, ['@version'])),
                "bcube:dateCreated":
                    self.harvest_details.get('harvest_date', ''),
                "bcube:lastUpdated":
                    self.harvest_details.get('harvest_date', ''),
                "relationships": [],
                "urls": []
            }
            url_sha = generate_sha_urn(self.url)
            urls.add(url_sha)
            original_url = self._generate_harvest_manifest(**{
                "bcube:hasUrlSource": "Harvested",
                "bcube:hasConfidence": "Good",
                "vcard:hasURL": self.url,
                "object_id": url_sha
            })
            service['urls'].append(original_url)
            # NOTE: this is not the sha from the url
            service['relationships'].append(
                {
                    "relate": "bcube:originatedFrom",
                    "object_id": url_sha
                }
            )

        # deal with the "dataset"
        service_bases = self.parser.xml.xpath(
            '//*[local-name()="service" and @base != ""]'
        )
        self.service_bases = {
            s.attrib.get('name'): s.attrib.get('base') for s in service_bases
        }

        # if 'dataset' in self.identify:
        #     # TODO: this is really not right but it is not
        #     # a proper web service so meh
        #     datasets = self._parse_datasets()

        # # if 'metadata' in self.identify:
        # #     self.description['metadata'] = self._parse_metadata()
        output['services'] = [service]
        self.description = tidy_dict(output)

    def _parse_datasets(self):

        # get the level-one children (catalog->child)
        endpoints = []

        datasets = extract_elems(self.parser.xml, ['dataset'])
        # datasets = self.parser.find(dataset_xpath)
        for dataset in datasets:
            description, child_endpoints = self._handle_elem(
                dataset, ['dataset', 'metadata', 'catalogRef'],
                self.url,
                self.service_bases
            )
            endpoints += [description] + child_endpoints

        return {"endpoints": endpoints}

    def _parse_metadata(self):
        endpoints = []
        # metadatas = self.parser.find(metadata_xpath)
        metadatas = extract_elems(self.parser.xml, ['metadata'])
        for metadata in metadatas:
            description, child_endpoints = self._handle_elem(
                metadata,
                [],
                self.url,
                self.service_bases
            )
            endpoints += [description] + child_endpoints

        return {"endpoints": endpoints}

    def parse_endpoints(self):
        '''
        JUST THE SERVICE ENDPOINTS (service and catalogRef elements
            at the root level)
        if the catalog service contains service elements. or a dataset
        element or catalogRef elements, parse those as endpoints (relative paths
            and all of the tagging issues)
        '''
        endpoints = []

        services = extract_elems(self.parser.xml, ['service'])
        # ffs, services can be nested too
        for service in services:
            description, child_endpoints = self._handle_elem(
                service,
                ['service'],
                self.url,
                {}
            )
            endpoints += [description]
            if child_endpoints:
                endpoints += child_endpoints

        catrefs = extract_elems(self.parser.xml, ['catalogRef'])
        for catref in catrefs:
            description, child_endpoints = self._handle_elem(
                catref,
                ['catalogRef', 'metadata'],
                self.url,
                {}  # TODO: so dap or file base path only? (not the full set,
                    # that makes no sense)
            )
            endpoints += [description] + child_endpoints

        return endpoints


class NcmlReader(Processor):
    def parse(self):
        elem = self.parser.xml
        ncml = {'variables': []}

        ncml['identifier'] = elem.attrib.get('location', '')
        for variable in extract_elems(elem, ['variable']):
            v = {}
            v['name'] = variable.attrib.get('name', '')
            v['attributes'] = []
            for att in extract_elems(variable, ['attribute']):
                a = {}
                for key, value in att.attrib.iteritems():
                    tag = extract_element_tag(key)
                    if tag == 'values':
                        continue
                    
                    a[tag] = value.strip()
                    
                if a:
                    v['attributes'] += [a]

            v = tidy_dict(v)
            if v:
                ncml['variables'].append(v)

        return tidy_dict(ncml)
