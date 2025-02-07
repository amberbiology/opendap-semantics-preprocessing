from semproc.parser import Parser
from semproc.xml_utils import extract_elems
from semproc.utils import tidy_dict
from semproc.utils import generate_sha_urn


class Processor(object):
    '''
    where routes is the tag sets to run as namespace-free
    xpath. the service, metadata and dataset keys are the dicts of
    tag lists (in case we have different locations for y) and the
    resultset list is the tag list to the result children
    '''
    def __init__(self,
                 identify,
                 response,
                 url,
                 harvest_details):
        self.response = response
        self.url = url
        self.identify = identify
        self.harvest_details = harvest_details

        self._load_xml()
        self._init_reader()
        self.parse()

    def _init_reader(self):
        pass

    def parse(self):
        pass

    def parse_children(self, elem=None, tags=[]):
        '''
        where elem = the parent node for the set and
        tags is the un-namespaced list of explicit items
        to parse or, if not specified, run the children
        one level down
        '''
        elem = self.parser.xml if elem is None else elem
        children = []
        if tags:
            children = extract_elems(elem, tags)
        else:
            children = [child for child in elem.iterchildren()]

        for child in children:
            parsed = self._parse_child(child)
            if parsed:
                yield parsed

    def _load_xml(self):
        self.parser = Parser(self.response)

    def _parse_child(self, child):
        pass

    def _generate_harvest_manifest(self, **kwargs):
        harvest = {
            "vcard:hasURL": self.url,
            "bcube:atTime": self.harvest_details.get('harvest_date'),
            "bcube:HTTPStatusCodeValue": 200,
            "http:reasonPhrase": "OK",
            "bcube:HTTPStatusFamilyCode": 200,
            "bcube:HTTPStatusFamilyType": "Success message",
            "bcube:hasUrlSource": "",
            "bcube:hasConfidence": "",
            "bcube:validatedOn": self.harvest_details.get('harvest_date'),
            "dc:identifier": generate_sha_urn(self.url)
        }
        harvest.update(kwargs)
        return tidy_dict(harvest)
