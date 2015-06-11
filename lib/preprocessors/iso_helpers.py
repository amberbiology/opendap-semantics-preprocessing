import dateutil as dateparser
from lib.xml_utils import extract_item, extract_items, generate_localname_xpath
from lib.xml_utils import extract_elem, extract_elems
from lib.utils import tidy_dict
from lib.geo_utils import bbox_to_geom, gml_to_geom, reproject, to_wkt


def parse_identifiers(elem):
    # note that this elem is the root iso
    identifiers = []

    xps = [
        ['fileIdentifier', 'CharacterString'],
        ['identificationInfo',
         'MD_DataIdentification',
         'citation',
         'CI_Citation',
         'identifier',
         'MD_Identifier',
         'code',
         'CharacterString'],
        ['dataSetURI', 'CharacterString']  # TODO: this can be multiple items
    ]

    for xp in xps:
        i = extract_item(elem, xp)
        if i:
            identifiers.append(i)

    return identifiers


def parse_identification_info(elem):
    title = extract_item(elem, ['citation', 'CI_Citation', 'title', 'CharacterString'])
    abstract = extract_item(elem, ['abstract', 'CharacterString'])
    keywords = parse_keywords(elem)

    # the rights information from MD_Constraints or MD_LegalConstraints
    rights = extract_item(elem, ['resourceConstraints', '*', 'useLimitation', 'CharacterString'])

    # deal with the extent
    extents = parse_extent(elem)

    return tidy_dict({
        "title": title,
        "abstract": abstract,
        "keywords": keywords,
        "rights": rights,
        "extents": extents
    })


def parse_keywords(elem):
    '''
    for each descriptiveKeywords block
    in an identification block
    '''
    keywords = []
    keywords += extract_items(
        elem, ['descriptiveKeywords', 'MD_Keywords', 'keyword', 'CharacterString'])

    # grab the iso topic categories as well
    keywords += extract_items(elem, ['topicCategory', 'MD_TopicCategoryCode'])

    # and the newer anchor style
    keywords += extract_items(elem, ['descriptiveKeywords', 'MD_Keywords', 'keyword', 'Anchor'])

    return keywords


def parse_responsibleparty(elem):
    '''
    parse any CI_ResponsibleParty
    '''
    individual_name = extract_item(elem, ['individualName', 'CharacterString'])
    organization_name = extract_item(elem, ['organisationName', 'CharacterString'])
    position_name = extract_item(elem, ['positionName', 'CharacterString'])

    e = extract_elem(elem, ['contactInfo', 'CI_Contact'])
    contact = parse_contact(e)

    return tidy_dict({
        "individual": individual_name,
        "organization": organization_name,
        "position": position_name,
        "contact": contact
    })


def parse_contact(elem):
    '''
    parse any CI_Contact
    '''
    contact = {}

    if elem is None:
        return contact

    contact['phone'] = extract_item(
        elem, ['phone', 'CI_Telephone', 'voice', 'CharacterString'])
    contact['addresses'] = extract_items(
        elem, ['address', 'CI_Address', 'deliveryPoint', 'CharacterString'])
    contact['city'] = extract_item(
        elem, ['address', 'CI_Address', 'city', 'CharacterString'])
    contact['state'] = extract_item(
        elem, ['address', 'CI_Address', 'administrativeArea', 'CharacterString'])
    contact['postal'] = extract_item(
        elem, ['address', 'CI_Address', 'postalCode', 'CharacterString'])
    contact['country'] = extract_item(
        elem, ['address', 'CI_Address', 'country', 'CharacterString'])
    contact['email'] = extract_item(
        elem, ['address', 'CI_Address', 'electronicMailAddress', 'CharacterString'])
    return tidy_dict(contact)


def parse_distribution(elem):
    ''' from the distributionInfo element '''
    distributions = []
    dist_elems = extract_elems(elem, ['MD_Distribution'])
    for dist_elem in dist_elems:
        # this is going to get ugly.
        # super ugly
        # get the transferoptions block
        # get the url, the name, the description, the size
        # get the format from a parent node
        # but where the transferoptions can be in some nested
        # distributor thing or at the root of the element (NOT
        # the root of the file)
        transfer_elems = extract_elems(dist_elem, ['//*', 'MD_DigitalTransferOptions'])
        for transfer_elem in transfer_elems:
            transfer = {}
            transfer['url'] = extract_item(
                transfer_elem, ['onLine', 'CI_OnlineResource', 'linkage', 'URL'])
            transfer['name'] = extract_item(
                transfer_elem, ['onLine', 'CI_OnlineResource', 'name', 'CharacterString'])
            transfer['description'] = extract_item(
                transfer_elem, ['onLine', 'CI_OnlineResource', 'description', 'CharacterString'])

            xp = generate_localname_xpath(['..', '..', 'distributorFormat', 'MD_Format'])
            format_elem = next(iter(transfer_elem.xpath(xp)), None)
            if format_elem is not None:
                transfer['format'] = {}
                transfer['format']['name'] = extract_item(
                    format_elem, ['name', 'CharacterString'])
                transfer['format']['specification'] = extract_item(
                    format_elem, ['specification', 'CharacterString'])
                transfer['format']['version'] = extract_item(
                    format_elem, ['version'])

                transfer['format'] = tidy_dict(transfer['format'])

            distributions.append(tidy_dict(transfer))

    return distributions


def handle_bbox(elem):
    west = extract_item(elem, ['westBoundLongitude', 'Decimal'])
    west = float(west) if west else 0

    east = extract_item(elem, ['eastBoundLongitude', 'Decimal'])
    east = float(east) if east else 0

    south = extract_item(elem, ['southBoundLatitude', 'Decimal'])
    south = float(south) if south else 0

    north = extract_item(elem, ['northBoundLatitude', 'Decimal'])
    north = float(north) if north else 0

    bbox = [west, south, east, north] if east and west and north and south else []

    geom = bbox_to_geom(bbox)
    return to_wkt(geom)


def handle_polygon(polygon_elem):
    elem = extract_elem(polygon_elem, ['polygon', 'Polygon'])
    srs_name = elem.attrib.get('srsName', 'EPSG:4326')

    geom = gml_to_geom(elem)
    if srs_name != '':
        geom = reproject(geom, srs_name, 'EPSG:4326')

    return to_wkt(geom)


def handle_points(point_elem):
    # this may not exist in the -2?
    pass


def parse_extent(elem):
    '''
    handle the spatial and/or temporal extent
    starting from the *:extent element
    '''
    extents = {}
    geo_elem = extract_elem(elem, ['EX_Extent', 'geographicElement'])
    if geo_elem is not None:
        # we need to sort out what kind of thing it is bbox, polygon, list of points
        bbox_elem = extract_elem(geo_elem, ['EX_GeographicBoundingBox'])
        if bbox_elem is not None:
            extents['geographic'] = handle_bbox(bbox_elem)

        poly_elem = extract_elem(geo_elem, ['EX_BoundingPolygon'])
        if poly_elem is not None:
            extents['polygon'] = handle_polygon(poly_elem)

    time_elem = extract_elem(elem, ['EX_Extent', 'temporalElement', 'extent', 'TimePeriod'])
    if time_elem is not None:
        begin_position = extract_elem(time_elem, ['beginPosition'])
        end_position = extract_elem(time_elem, ['endPosition'])

        if begin_position is not None and 'indeterminatePosition' not in begin_position.attrib:
            begin_position = parse_timestamp(begin_position.text)
        if end_position is not None and 'indeterminatePosition' not in end_position.attrib:
            end_position = parse_timestamp(end_position.text)

        extents['temporal'] = [begin_position, end_position]


def parse_timestamp(text):
    '''
    generic handler for any iso date/datetime/time/whatever element
    '''
    try:
        # TODO: deal with timezones if this doesn't
        return dateparser.parse(text)
    except ValueError:
        return None
