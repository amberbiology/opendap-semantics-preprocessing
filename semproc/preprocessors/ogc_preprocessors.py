from owscapable.wms import WebMapService
from owscapable.wcs import WebCoverageService
from owscapable.coverage.wcsBase import DescribeCoverageReader
from owscapable.wfs import WebFeatureService
from owscapable.csw import CatalogueServiceWeb
from owscapable.sos import SensorObservationService
from semproc.processor import Processor
from semproc.preprocessors.csw_preprocessors import CswReader
from semproc.yaml_configs import import_yaml_configs
from semproc.geo_utils import bbox_to_geom, reproject, to_wkt
from semproc.utils import tidy_dict, remap_http_method, break_url
from semproc.xml_utils import extract_attrib
import dateutil.parser as dateparser
from semproc.utils import generate_sha_urn, generate_uuid_urn
import os
import urllib.request, urllib.parse, urllib.error


class OgcReader(Processor):
    '''
    base class to handle OWSLib responses

    support for: WMS 1.1.1
                 WMS 1.3.0
                 WFS 1.0.0
                 WFS 1.1.0
                 WCS 1.0.0
                 WCS 1.1.0
                 WCS 1.1.1
                 WCS 1.1.2
                 CSW 2.0.2
                 SOS 1.0.0
    '''
    def _init_reader(self):
        if 'service' in self.identify:
            # run the owslib getcapabilities parsers
            self.service_name = self.identify['service'].get('name', '')
            self.version = next(iter(
                self.identify['service'].get('version', [])), '')
            self.reader = self._get_service_reader(
                self.service_name, self.version)

    # TODO: there are far better ways of dealing with the cat-interop urns
    def _get_service_reader(self, service, version):
        if service == 'WMS' and version in ['1.1.1', '1.3.0']:
            reader = WebMapService('', xml=self.response, version=version)
            self.urn = 'OGC:WMS'
        elif service == 'WFS' and version in ['1.0.0', '1.1.0']:
            reader = WebFeatureService('', xml=self.response, version=version)
            self.urn = 'OGC:WFS'
        elif service == 'WCS' and version in ['1.0.0', '1.1.0', '1.1.1', '1.1.2']:
            reader = WebCoverageService(
                '', xml=self.response, version=version)
            self.urn = 'OGC:WCS'
        elif service == 'CSW' and version in ['2.0.2']:
            reader = CatalogueServiceWeb(
                '', xml=self.response, version=version)
            self.urn = 'OGC:CSW'
        elif service == 'SOS' and version in ['1.0.0']:
            reader = SensorObservationService(
                '', xml=self.response, version=version)
            self.urn = 'OGC:SOS'
        else:
            return None
        return reader

    def _get_service_config(self, service, version):
        # get the config file
        __location__ = os.path.join(
            '/'.join(os.path.abspath(
                os.path.dirname(__file__)).split('/')[:-1]),
            'configs',
            "ogc_parameters.yaml"
        )
        data = import_yaml_configs([__location__])
        self.config = next(d for d in data if d['name'] == service.upper() +
                           version.replace('.', ''))

    def _get_operations(self, reader, service, version):
        '''
        each operation can have more than one endpoint (get and post, ex)

        formatOptions = output format of the response method that can be some
                        controlled vocab value (XMLSCHEMA, etc)

                        this is incorrectly handled in wfs 1.1.0 (hardcoded value)

                        later versions can have an outputFormat parameter instead
                        BUT it comes down to whether that is a proper query parameter
                        or simply the delivered response (no choice in the spec)

        parameters = {name: {values: list}}
        '''
        _vocabs = {
            "XMLSCHEMA": "application/xml",
            "GML2": "text/xml; subtype=gml/2.1.2"
        }

        def _check_controlled_vocabs(term):
            if term in _vocabs:
                return _vocabs[term]
            return term

        def _replace_nones(to_check):
            return '' if to_check is None else to_check

        def _append_params(base_url, operation):
            if not base_url[-1] == '?':
                base_url += '?'
            return base_url + 'SERVICE=%s&VERSION=%s&REQUEST=%s' % (service,
                                                                    version,
                                                                    operation)

        def _merge_params(op_name, found_params):
            '''
            for some parameter structure:
                {'resultType': {'values': ['results', 'hits']}}
            integrate into the config params with the common elements

            '''
            # TODO: how to handle aliases (if necessary)
            req_methods = self.config.get('methods', [])
            req_params = next(
                iter(
                    [d for d in req_methods if d['name'] == op_name.upper()]
                ), {}
            ).get('params', [])
            req_params = [] if not req_params else req_params
            defaults = self.config.get('common', []) + req_params

            if not found_params:
                return defaults

            for k, v in found_params.items():
                param = next(
                    iter(d for d in defaults if d['name'] == k.lower()), [])
                if not param:
                    continue

                found_index = defaults.index(param)
                param['values'] = [
                    _check_controlled_vocabs(a) for a in v['values']
                ]
                defaults[found_index] = param

            return defaults

        def _return_parameter(param):
            # return a parameter dict without empty values
            parameter = {}
            for key in ['name', 'type', 'format', 'values']:
                if key in param and param[key]:
                    parameter[key] = param[key]
            return parameter

        operations = []
        for o in reader.operations:
            # TODO: handle the differing formatOptions

            # get the parameter values if supported by the service
            try:
                params = o.parameters
            except AttributeError:
                params = {}

            # merge with defaults (where it can be add the whole element
            #   OR parts of the element)
            params = _merge_params(o.name, params)

            # get the formatOptions
            try:
                formats = [
                    _check_controlled_vocabs(fo) for fo in o.formatOptions
                ]
            except AttributeError:
                formats = []

            endpoints = [
                tidy_dict({
                    "name": o.name,
                    "protocol": remap_http_method(m.get('type', '')),
                    "url": _append_params(m.get('url', ''), o.name),
                    "constraints": m.get('constraints', []),
                    "mimeType": formats,
                    "actionable": 1 if o.name == 'GetCapabilities' else 2,
                    "parameters": [_return_parameter(p) for p in params]
                }) for m in o.methods
            ]

            operations += endpoints

        return operations

    def _return_timerange(self, timepositions):
        '''
        from a set of timeposition or dimension/extent=temporal elements,
        try to parse the dates (iso 8601) from each element and return
        the min/max of the set

        structures:
            - an iso 8601 timestamp
            - a comma-delimited list of timestamps
            - a forward-slash delimited list of timestamps where the last
              item is the period (not a timestamp)
        '''
        timestamps = []
        for default_time, timeposition in timepositions:
            if ',' in timeposition:
                parts = timeposition.split(',')
            elif '/' in timeposition:
                parts = timeposition.split('/')[:-1]
            else:
                parts = [timeposition]

            for part in parts:
                try:
                    d = dateparser.parse(part)
                    timestamps.append(d)
                except:
                    continue

        return min(timestamps), max(timestamps)

    def _generate_url(self, url, layer_name, bbox, service, version):
        base_url, values = break_url(url)
        bbox = [
            str(bbox.get('esip:westBound')),
            str(bbox.get('esip:southBound')),
            str(bbox.get('esip:eastBound')),
            str(bbox.get('esip:northBound'))
        ]
        if service == 'WMS':
            params = {
                "service": service,
                "request": "GetMap",
                "version": version,
                "layers": layer_name,
                "width": 500,
                "height": 500,
                "styles": "",
                "format": "image/png"  # totes wrong
            }
            if version == '1.3.0':
                params['crs'] = 'CRS:84'
            else:
                params['srs'] = 'EPSG:4326'
            params['bbox'] = ','.join(bbox)
        elif service == 'WFS':
            params = {
                "service": service,
                "request": "GetFeature",
                "version": version,
                "featureid": layer_name,
                "typenames": "namespace:featuretype"
            }
        elif service == 'WCS':
            params = {
                "service": service,
                "request": "GetCoverage",
                "version": version,
                "coverage": layer_name,
                "width": 500,
                "height": 500,
                'crs': 'CRS:84',
                'bbox': ','.join(bbox),
                "format": "GTiff"  # this is so wrong
            }
        elif service == 'CSW':
            return ''
        elif service == 'SOS':
            return ''

        return base_url + '?' + urllib.parse.urlencode(params)

    def parse(self):
        # for ogc, a catalog record is the getcapabilities rsp
        output = {
            "layers": [],
            "catalog_records": []
        }

        urls = set()

        if not hasattr(self, 'reader') or not self.reader:
            self.description = {}
            return

        if 'service' in self.identify:
            service_id = generate_uuid_urn()
            service = {
                "object_id": service_id,
                "bcube:dateCreated": self.harvest_details.get(
                    'harvest_date', ''),
                "bcube:lastUpdated": self.harvest_details.get(
                    'harvest_date', ''),
                "relationships": [],
                "urls": [],
                "rdf:type": self.urn
            }

            url_sha = generate_sha_urn(self.url)
            urls.add(url_sha)
            url_id = generate_uuid_urn()
            service['urls'].append(
                self._generate_harvest_manifest(**{
                    "bcube:hasUrlSource": "Harvested",
                    "bcube:hasConfidence": "Good",
                    "vcard:hasURL": self.url,
                    "object_id": url_id,
                    "dc:identifier": url_sha
                })
            )
            service['relationships'].append({
                "relate": "bcube:originatedFrom",
                "object_id": url_id
            })

            # self._get_service_config(service_name, version)
            service_reader = self._parse_service(
                self.reader, self.service_name, self.version)

            # map to triples
            service.update({
                "dc:description": service_reader.get('abstract')
            })

            keywords = service_reader.get('subject', [])
            if keywords:
                output['keywords'] = [{
                    "object_id": generate_uuid_urn(),
                    "bcube:hasValue": keywords
                }]
                for k in output['keywords']:
                    service['relationships'].append(
                        {
                            "relate": "dc:conformsTo",
                            "object_id": k['object_id']
                        }
                    )
            if self.identify['service'].get('request', '') == 'GetCapabilities':
                # this is also awkward. meh. needs must.
                layers = []
                listed_layers = self._parse_getcap_datasets(self.reader)

                for ld in listed_layers:
                    layer = {
                        "object_id": generate_uuid_urn(),
                        "bcube:dateCreated":
                            self.harvest_details.get('harvest_date', ''),
                        "bcube:lastUpdated":
                            self.harvest_details.get('harvest_date', ''),
                        "dc:description": ld.get('abstract', ''),
                        "dc:title": ld.get('title', ''),
                        "relationships": []
                    }
                    service['relationships'].append({
                        "relate": "bcube:contains",
                        "object_id": layer['object_id']
                    })

                    # add the generated url for the service
                    generated_url = self._generate_url(
                        self.url,
                        ld.get('name'),
                        ld.get('bbox'),
                        self.service_name,
                        self.version
                    )
                    if generated_url:
                        url_sha = generate_sha_urn(generated_url)
                        if url_sha not in urls:
                            urls.add(url_sha)
                            url_id = generate_uuid_urn()
                            layer_url = self._generate_harvest_manifest(**{
                                "vcard:hasURL": generated_url,
                                "bcube:hasUrlSource": "Generated",
                                "bcube:hasConfidence": "Not Sure",
                                "object_id": url_id,
                                "dc:identifier": url_sha
                            })
                            service['urls'].append(layer_url)
                        # don't add to the larger set, but do
                        # include the reference within the layer
                        layer['relationships'].append({
                            "relate": "dcterms:references",
                            "object_id": url_id
                        })

                    # add each as a dataset with just a url for now
                    for mu in ld.get('metadata_urls', []):
                        url_link = generate_uuid_urn()
                        url_sha = generate_sha_urn(mu.get('url'))

                        if url_sha not in urls:
                            urls.add(url_sha)
                            url_id = generate_uuid_urn()
                            output['catalog_records'] += [
                                {
                                    "object_id": url_link,
                                    "urls": [
                                        self._generate_harvest_manifest(**{
                                            "vcard:hasURL": mu.get('url'),
                                            "bcube:hasUrlSource": "Harvested",
                                            "bcube:hasConfidence": "Good",
                                            "object_id": url_id,
                                            "dc:identifier": url_sha
                                        })
                                    ],
                                    "relationships": [
                                        {
                                            "relate": "dc:describes",
                                            "object_id": layer['object_id']
                                        },
                                        {
                                            "relate": "bcube:originatedFrom",
                                            "object_id": url_id
                                        }
                                    ]
                                }
                            ]

                    if 'temporal_extent' in ld:
                        temporal = tidy_dict(
                            {
                                "esip:startDate":
                                    ld['temporal_extent'].get('begin', ''),
                                "esip:endDate":
                                    ld['temporal_extent'].get('end', '')
                            }
                        )
                        if temporal:
                            layer.update(temporal)

                    if 'bbox' in ld:
                        layer.update(ld['bbox'])

                    layers.append(layer)

                service['layers'] = layers
                # if layers:
                #     service['layers'] = layers
                #     for layer in layers:
                #         service['relationships'].append({
                #             "relate": "bcube:contains",
                #             "object_id": layer['object_id']
                #         })

        output['services'] = [service]
        self.description = tidy_dict(output)

    def _parse_service(self, reader, service, version):
        rights = [reader.identification.accessconstraints]
        try:
            contact = [reader.provider.contact.name]
        except AttributeError:
            contact = []

        abstract = reader.identification.abstract
        keywords = reader.identification.keywords

        service = {
            "title": [reader.identification.title]
        }

        if rights:
            service['rights'] = rights

        if contact:
            service['contact'] = contact

        if abstract:
            service['abstract'] = abstract

        if keywords:
            service['subject'] = keywords

        return service

    def _parse_coverages(self, reader):
        def _return_timerange(start_range, end_range):
            try:
                start_date = dateparser.parse(start_range)
            except:
                start_date = None
            try:
                end_date = dateparser.parse(end_range)
            except:
                end_date = None

            return start_date, end_date

        datasets = []

        if reader.coverages is None:
            return []

        for coverage in reader.coverages:
            d = {}
            d['name'] = coverage.name
            if coverage.description:
                d['abstract'] = coverage.description

            if coverage.min_pos and coverage.max_pos:
                # TODO: translate this to a bbox
                min_pos = coverage.min_pos
                max_pos = coverage.max_pos
                crs_urn = coverage.srs_urn

                min_coord = list(map(float, min_pos.split()))
                max_coord = list(map(float, max_pos.split()))

                bbox = bbox_to_geom(min_coord + max_coord)
                # TODO: there's an issue with the gdal_data path
                #       where it is not finding the epsg registry
                # bbox = reproject(bbox, crs_urn, 'EPSG:4326')

                d['bbox'] = to_wkt(bbox)

            # TODO: what to do about the main envelope vs all the domainSet bboxes?
            try:
                if coverage.temporal_domain:
                    begin_range = coverage.temporal_domain.get('begin_position', '')
                    end_range = coverage.temporal_domain.get('end_position', '')
                    begin_time, end_time = _return_timerange(begin_range, end_range)
                    d['temporal_extent'] = {"begin": begin_time.isoformat(),
                                            "end": end_time.isoformat()}
            except AttributeError:
                pass

            try:
                if coverage.supported_formats:
                    d['formats'] = coverage.supported_formats
            except AttributeError:
                pass

            try:
                if coverage.supported_crs:
                    d['spatial_refs'] = coverage.supported_crs
            except AttributeError:
                pass

            datasets.append(d)

        return datasets

    def _parse_getcap_datasets(self, reader):
        '''
        from some content metadata object, get all of the
        layers/features/coverages

        output:
            name
            title
            srs
            bounding boxes
            wgs84 bbox

            style

            metadataurl (should be a relate)

            elevation
            time

        note: the values are lists to handle other service responses
              that may have multiple values for that element.
        '''
        datasets = []

        if reader.contents is None:
            return []

        for name, dataset in reader.contents.items():
            d = {}

            d['name'] = name
            if dataset.title:
                d['title'] = dataset.title

            if dataset.abstract:
                d['abstract'] = dataset.abstract

            if dataset.metadataUrls:
                d['metadata_urls'] = dataset.metadataUrls

            if dataset.boundingBoxes:
                d['bboxes'] = dataset.boundingBoxes

            # if dataset.boundingBoxWGS84:
            #     d['bbox'] = [dataset.boundingBoxWGS84]

            try:
                # convert to wkt (and there's something about sos - maybe not harmonized)
                if dataset.boundingBoxWGS84:
                    bbox = bbox_to_geom(dataset.boundingBoxWGS84)
                    d['bbox'] = {
                        'dc:spatial': to_wkt(bbox),
                        'esip:westBound': dataset.boundingBoxWGS84[0],
                        'esip:eastBound': dataset.boundingBoxWGS84[2],
                        'esip:northBound': dataset.boundingBoxWGS84[3],
                        'esip:southBound': dataset.boundingBoxWGS84[1]
                    }
            except AttributeError:
                pass

            if dataset.crsOptions:
                d['spatial_refs'] = dataset.crsOptions

            if dataset.attribution:
                d['rights'] = [dataset.attribution]

            if dataset.timepositions:
                d['temporal'] = dataset.timepositions

                begin_time, end_time = self._return_timerange(dataset.timepositions)
                d['temporal_extent'] = {"begin": begin_time.isoformat(),
                                        "end": end_time.isoformat()}

            # SOS 2.0.2 specific attributes
            if 'temporal_extent' not in d:
                d['temporal_extent'] = {}
            try:
                # because it has support for different time element names
                if dataset.begin_position:
                    d['temporal_extent']['begin'] = dataset.begin_position
            except AttributeError:
                pass

            try:
                # because it has support for different time element names
                if dataset.end_position:
                    d['temporal_extent']['end'] = dataset.end_position
            except AttributeError:
                pass

            try:
                if dataset.observed_properties:
                    d['observed_properties'] = dataset.observed_properties
            except AttributeError:
                pass

            try:
                if dataset.procedures:
                    d['procedures'] = dataset.procedures
            except AttributeError:
                pass

            try:
                if dataset.procedure_description_formats:
                    d['procedure_description_formats'] = dataset.procedure_description_formats
            except AttributeError:
                pass

            try:
                if dataset.features_of_interest:
                    d['features_of_interest'] = dataset.features_of_interest
            except AttributeError:
                pass

            try:
                if dataset.observation_models:
                    d['observation_models'] = dataset.observation_models
            except AttributeError:
                pass

            # and some of the WFS-specific bits
            try:
                if dataset.verbOptions:
                    d['verbs'] = dataset.verbOptions
            except AttributeError:
                pass

            # handling the sos vs wfs output formats (ows related)
            try:
                if dataset.outputFormats:
                    d['output_formats'] = dataset.outputFormats
            except AttributeError:
                pass
            try:
                if dataset.response_formats:
                    d['output_formats'] = dataset.response_formats
            except AttributeError:
                pass

            datasets.append(d)

        return datasets
