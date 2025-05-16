from __future__ import annotations

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
import ckan.lib.helpers as helpers
import ckan.model as model
from flask import request
import geonamescache
from datetime import datetime
from ckan.types import Schema
from typing import cast

## Currently storing in code, switch to using configuration file
metric_class_vocab = [
'Avian',
'Beach Geomorphology',
'Dune Geomorphology',
'Coral Community',
'Elevation',
'Hydrology',
'Macroinvertebrates',
'Marsh Geomorphology',
'Nekton',
'Shoreline',
'Vegetation',
'Water Quality'
]
resilience_grant_vocab = [
'NFWF-41739',
'NFWF-41766',
'NFWF-41795',
'NFWF-41991',
'NFWF-42279',
'NFWF-42442',
'NFWF-42958',
'NFWF-42959',
'NFWF-43006',
'NFWF-43095',
'NFWF-43281',
'NFWF-43322',
'NFWF-43429',
'NFWF-43931',
'NFWF-43986',
'NFWF-44109',
'NFWF-44157',
'NFWF-44167',
'NFWF-44225',
'NPS-1A',
'USFWS-01',
'USFWS-06',
'USFWS-09',
'USFWS-15',
'USFWS-21',
'USFWS-31',
'USFWS-33',
'USFWS-37',
'USFWS-43',
'USFWS-50',
'USFWS-51',
'USFWS-53',
'USFWS-57',
'USFWS-65',
'USFWS-76',
'USFWS-77',
'USFWS-89',
'USFWS-94'
]
monitoring_grant_vocab = ['55013','55066','55032','55094','55097','55098','55110','55076']
nfwf_program_vocab = [
'Hurricane Sandy Coastal Resliency Competitive Grant Program',
'National Coastal Resilience Fund',
'Emergency Coastal Resilience Fund'
]
reporting_year_vocab = [
'Pre-2014','2014','2015','2016','2017','2018','2019','2020','2021'
,'2022','2023','2024','2025','2026','2027','2028','2029','2030'
]
gc = geonamescache.GeonamesCache()
state_abbr_vocab = [
'AK','AL','AS','CA','CT','DE','FL','GA','GU','HI','LA','MA','MD','ME',
'MP','MS','NC','NH','NJ','NY','OR','PR','RI','SC','TX','VA','VI','WA'
]
# # uncomment this to get all states:
# us_states = gc.get_us_states()
# state_abbr_vocab = list(us_states.keys())
us_counties = gc.get_us_counties()
county_vocab = [county['name'] for county in us_counties if county['state'] in state_abbr_vocab]
measurement_stage_vocab = [
'Reference',
'Baseline',
'Control',
'Monitoring'
]
restoration_activity_vocab = [
'Aquatic Connectivity',
'Beach',
'Dune',
'Living Shoreline',
'Marsh',
'Floodplain Connectivity',
'Coral',
'Mangrove'
]
metric_category_vocab = ['Ecological', 'Socioeconomic']
nature_based_solution_vocab = [
    "Aquatic Connectivity",
    "Beach Dune or Barrier Island Restoration",
    "Coastal Forest Restoration",
    "Community Resilience Planning",
    "Coral Reef Restoration",
    "Easements and Acquisitions",
    "Floodplain Restoration",
    "Green Stormwater Infrastructure",
    "Living Shoreline",
    "Mangrove Restoration",
    "Marine or Aquatic Habitat Restoration",
    "Marsh Restoration",
    "N/A",
    "Oyster Reef Restoration",
    "Stream Restoration",
    "Wildfire Prevention"
]
monitoring_parameter_vocab = [ # if you change this, make sure to update 'nbs_monitoring'
    "Acres Restored",
    "Avian Abundance",
    "Beach-Dune Geomorphology",
    "Coral Abundance",
    "Elevation",
    "Fish Abundance",
    "Rugosity or Reef Height",
    "Shoreline Position",
    "Survival",
    "Vegetation",
    "Water Level",
    "Water Quality"
]
grant_cycle_vocab = [str(year) for year in range(2015, 2031)]
pipeline_stage_vocab = [
    'Planning',
    'Preliminary Design',
    'Final Design',
    'Implementation',
    'Other'
]
grant_status_vocab = [
    'In Progress',
    'Closed'
]
doc_type_vocab = [
    'Monitoring Data',
    'Monitoring Plan',
    'GIS File',
    'As Built Drawing',
    'Eng and Design Plan',
    'Modeling Report',
    'Modeling Data',
    'Stakeholder Engagement Plan',
    'Resilience or Hazard Management Plan',
    'Plan (Other)'
]
nbs_monitoring = { # if you change this, make sure to update 'monitoring_parameter_vocab'
    "Aquatic Connectivity": [],
    "Beach Dune or Barrier Island Restoration": ["Shoreline Position", "Beach-Dune Geomorphology"],
    "Coastal Forest Restoration": [],
    "Community Resilience Planning": [],
    "Coral Reef Restoration": ["Acres Restored", "Coral Abundance", "Survival", "Rugosity or Reef Height", "Fish Abundance"],
    "Easements and Acquisitions": [],
    "Floodplain Restoration": ["Vegetation", "Elevation", "Water Level"],
    "Green Stormwater Infrastructure": [],
    "Living Shoreline": ["Vegetation", "Water Level", "Elevation", "Shoreline Position", "Acres Restored"],
    "Mangrove Restoration": [],
    "Marine or Aquatic Habitat Restoration": [],
    "Marsh Restoration": ["Vegetation", "Water Level", "Elevation", "Shoreline Position"],
    "N/A": [],
    "Oyster Reef Restoration": ["Water Level", "Elevation", "Acres Restored"],
    "Stream Restoration": [],
    "Wildfire Prevention": []
}
monitoring_stage_vocab = [
    'Baseline',
    'Immediate Post-Implementation',
    'One-Year Post-Implementation',
    'Long-term',
    'Other'
]
# from ckan.lib.helpers import unselected_facet_items

# def get_facets_unselected(facet, limit=None):
#     '''Return the list of unselected facet items for the given facet, sorted
#     by count.
#     Reads the complete list of facet items for the given facet from
#     c.search_facets, and filters out the facet items that the user has already
#     selected.
#     Arguments:
#     facet -- the name of the facet to filter.
#     limit -- the max. number of facet items to return.
#     exclude_active -- only return unselected facets.
#     '''
#     if not c.search_facets or \
#             not c.search_facets.get(facet) or \
#             not c.search_facets.get(facet).get('items'):
#         return []
#     facets = []
#     for facet_item in c.search_facets.get(facet)['items']:
#         if not len(facet_item['name'].strip()):
#             continue
#         if not (facet, facet_item['name']) in request.params.items():
#             facets.append(dict(active=False, **facet_item))
#     facets = sorted(facets, key=lambda item: item['count'], reverse=True)
#     return facets

# def get_facets_selected(facet):
#     '''
#     Returns the list of selected facet items for the given facet, sorted
#     by count.
#     '''
#     if not c.search_facets or \
#             not c.search_facets.get(facet) or \
#             not c.search_facets.get(facet).get('items'):
#         return []
#     facets = []
#     for facet_item in c.search_facets.get(facet)['items']:
#         if not len(facet_item['name'].strip()):
#             continue
#         if (facet, facet_item['name']) in request.params.items():
#             facets.append(dict(active=False, **facet_item))
#     facets = sorted(facets, key=lambda item: item['count'], reverse=True)
#     return facets

def groups():
    query = model.Group.all(group_type='group')
    
    def convert_to_dict(user):
        out = {}
        for k in ['id', 'name', 'title']:
            out[k] = getattr(user, k)
        return out

    out = map(convert_to_dict, query.all())

    return out

def default_group(group_id):
    query = model.Group.all(group_type='group')

    def convert_to_dict(user):
        out = {}
        for k in ['id', 'name', 'title']:
            out[k] = getattr(user, k)    
        return out

    default = group_id[0]['id']
    out = map(convert_to_dict, query.all())

    new_out = []
    for i in out:
        if i['id'] == default:
            new_out.append(i)
        else:
            continue
    return new_out

def groups_reload(available_groups,selected_groups):
    query = model.Group.all(group_type='group')

    def convert_to_dict(user):
        out = {}
        for k in ['id', 'name', 'title']:
            out[k] = getattr(user, k)    
        return out

    current_group = selected_groups[0]['id']
    out = map(convert_to_dict, query.all())

    user_groups = []
    for i in available_groups:
        user_groups.append(i['id'])

    selected_out = []
    for i in out:
        if i['id'] == current_group:
            continue
        else:
            selected_out.append(i)
    
    new_out = []
    for i in selected_out:
        if i['id'] in user_groups:
            new_out.append(i)
        else:
            continue
    
    return new_out

def add_tags(data,vocabulary_list,context):
    vocab = toolkit.get_action('vocabulary_show')(context,data)
    for tag in vocabulary_list:
        try:
            data = {'name': tag, 'vocabulary_id': vocab['id']}
            toolkit.get_action('tag_create')(context, data)
        except:
            continue

def create_tag_vocabulary(vocabulary_list,field_name):
    user = toolkit.get_action('get_site_user')({'ignore_auth': True}, {})
    context = {'user': user['name']}
    try:
        data = {'id': field_name}
        toolkit.get_action('vocabulary_show')(context, data)
        data = {'id': field_name}
        add_tags(data,vocabulary_list,context)
    except toolkit.ObjectNotFound:
        data = {'name': field_name}
        vocab = toolkit.get_action('vocabulary_create')(context, data)
        for tag in vocabulary_list:
            data = {'name': tag, 'vocabulary_id': vocab['id']}
            toolkit.get_action('tag_create')(context, data)

def metric_classes():
    create_tag_vocabulary(metric_class_vocab,'metric_classes')
    try:
        tag_list = toolkit.get_action('tag_list')
        metric_classes = tag_list(data_dict={'vocabulary_id': 'metric_classes'})
        return metric_classes
    except toolkit.ObjectNotFound:
        return None

def metric_categories():
    create_tag_vocabulary(metric_category_vocab,'metric_categories')
    try:
        tag_list = toolkit.get_action('tag_list')
        metric_categories = tag_list(data_dict={'vocabulary_id': 'metric_categories'})
        return metric_categories
    except toolkit.ObjectNotFound:
        return None

def resilience_grants():
    create_tag_vocabulary(resilience_grant_vocab,'resilience_grants')
    try:
        tag_list = toolkit.get_action('tag_list')
        resilience_grants = tag_list(data_dict={'vocabulary_id': 'resilience_grants'})
        return resilience_grants
    except toolkit.ObjectNotFound:
        return None

def monitoring_grants():
    create_tag_vocabulary(monitoring_grant_vocab,'monitoring_grants')
    try:
        tag_list = toolkit.get_action('tag_list')
        monitoring_grants = tag_list(data_dict={'vocabulary_id': 'monitoring_grants'})
        return monitoring_grants
    except toolkit.ObjectNotFound:
        return None

def nfwf_programs():
    create_tag_vocabulary(nfwf_program_vocab,'nfwf_programs')
    try:
        tag_list = toolkit.get_action('tag_list')
        nfwf_programs = tag_list(data_dict={'vocabulary_id': 'nfwf_programs'})
        return nfwf_programs
    except toolkit.ObjectNotFound:
        return None

def reporting_years():
    create_tag_vocabulary(reporting_year_vocab,'reporting_years')
    try:
        tag_list = toolkit.get_action('tag_list')
        reporting_years = tag_list(data_dict={'vocabulary_id': 'reporting_years'})
        return reporting_years
    except toolkit.ObjectNotFound:
        return None

def counties():
    create_tag_vocabulary(county_vocab,'counties')
    try:
        tag_list = toolkit.get_action('tag_list')
        counties = tag_list(data_dict={'vocabulary_id': 'counties'})
        return counties
    except toolkit.ObjectNotFound:
        return None

def state_abbreviations():
    create_tag_vocabulary(state_abbr_vocab,'state_abbreviations')
    try:
        tag_list = toolkit.get_action('tag_list')
        state_abbreviations = tag_list(data_dict={'vocabulary_id': 'state_abbreviations'})
        return state_abbreviations
    except toolkit.ObjectNotFound:
        return None

def measurement_stages():
    create_tag_vocabulary(measurement_stage_vocab,'measurement_stages')
    try:
        tag_list = toolkit.get_action('tag_list')
        measurement_stages = tag_list(data_dict={'vocabulary_id': 'measurement_stages'})
        return measurement_stages
    except toolkit.ObjectNotFound:
        return None
    
def grant_cycles():
    create_tag_vocabulary(grant_cycle_vocab, 'grant_cycles')
    try:
        tag_list = toolkit.get_action('tag_list')
        grant_cycles = tag_list(data_dict={'vocabulary_id': 'grant_cycles'})
        return grant_cycles
    except toolkit.ObjectNotFound:
        return None
    
def pipeline_stages():
    create_tag_vocabulary(pipeline_stage_vocab, 'pipeline_stages')
    try:
        tag_list = toolkit.get_action('tag_list')
        pipeline_stages = tag_list(data_dict={'vocabulary_id': 'pipeline_stages'})
        return pipeline_stages
    except toolkit.ObjectNotFound:
        return None

def nature_based_solutions():
    create_tag_vocabulary(nature_based_solution_vocab, 'nature_based_solutions')
    try:
        tag_list = toolkit.get_action('tag_list')
        nature_based_solutions = tag_list(data_dict={'vocabulary_id': 'nature_based_solutions'})
        return nature_based_solutions
    except toolkit.ObjectNotFound:
        return None

def grant_statuses():
    create_tag_vocabulary(grant_status_vocab, 'grant_statuses')
    try:
        tag_list = toolkit.get_action('tag_list')
        grant_statuses = tag_list(data_dict={'vocabulary_id': 'grant_statuses'})
        return grant_statuses
    except toolkit.ObjectNotFound:
        return None

def doc_types():
    create_tag_vocabulary(doc_type_vocab, 'doc_types')
    try:
        tag_list = toolkit.get_action('tag_list')
        doc_types = tag_list(data_dict={'vocabulary_id': 'doc_types'})
        return doc_types
    except toolkit.ObjectNotFound:
        return None
    
def monitoring_stages():
    create_tag_vocabulary(monitoring_stage_vocab, 'monitoring_stages')
    try:
        tag_list = toolkit.get_action('tag_list')
        monitoring_stages = tag_list(data_dict={'vocabulary_id': 'monitoring_stages'})
        return monitoring_stages
    except toolkit.ObjectNotFound:
        return None

def monitoring_parameters():
    create_tag_vocabulary(monitoring_parameter_vocab, 'monitoring_parameters')
    try:
        tag_list = toolkit.get_action('tag_list')
        monitoring_parameters = tag_list(data_dict={'vocabulary_id': 'monitoring_parameters'})
        return monitoring_parameters
    except toolkit.ObjectNotFound:
        return None

def get_grant_required_metrics_by_nbs(nbs_type_list):
    grant_required_metrics = []
    if nbs_type_list is not None:
        for nbs_type in nbs_type_list:
            metrics = nbs_monitoring.get(nbs_type)
            if metrics is not None:
                grant_required_metrics += metrics
    else:
        return []
    return list(set(grant_required_metrics))

def get_satisfied_metrics(package_id):
    package = toolkit.get_action('package_show')(data_dict={'id': package_id})
    org_id = package.get('owner_org')
    metrics = []
    if org_id:
        org_packages = toolkit.get_action('package_search')(data_dict={
            'q': f"owner_org:{org_id}",
            'rows': 1000,
            'include_private': True
            })
        if org_packages and org_packages.get('count') > 0:
            for package in org_packages.get('results'):
                if package.get('resources'):
                    for resource in package.get('resources'):
                        if (resource.get('doc_type') and resource.get('doc_type') == 'Monitoring Data'):
                            metric = resource.get('metric')
                            if metric:
                                metrics += metric
    return list(set(metrics))

def get_nbs_from_package_id(package_id):
    package = toolkit.get_action('package_show')(data_dict={'id': package_id})
    org_id = package.get('owner_org')
    if org_id:
        org = toolkit.get_action('organization_show')(data_dict={'id': org_id})
        if (org.get('extras')):
            return get_extra(org.get('extras'), 'nature_based')
    return []


def restoration_activities():
    create_tag_vocabulary(restoration_activity_vocab,'restoration_activities')
    try:
        tag_list = toolkit.get_action('tag_list')
        restoration_activities = tag_list(data_dict={'vocabulary_id': 'restoration_activities'})
        return restoration_activities
    except toolkit.ObjectNotFound:
        return None

def restoration_activities():
    create_tag_vocabulary(restoration_activity_vocab,'restoration_activities')
    try:
        tag_list = toolkit.get_action('tag_list')
        restoration_activities = tag_list(data_dict={'vocabulary_id': 'restoration_activities'})
        return restoration_activities
    except toolkit.ObjectNotFound:
        return None

def extras_has_value(extras_list, key, value):
    if extras_list:
        for extra in extras_list:
            parsed_key = extra.get('key')
            if extra.get('value'):
                parsed_value = parse_postgres_array(extra.get('value'))
                if parsed_key == key and ((parsed_value == value) or (value in parsed_value)):
                    return True
    return False

def parse_postgres_array(array_string):
    # Remove the outer curly braces
    content = array_string.strip('{}')
    
    # Use regex to properly split elements respecting quotes
    # This pattern finds either quoted strings or unquoted strings separated by commas
    pattern = r'"([^"\\]*(?:\\.[^"\\]*)*)"|\s*,\s*|\s*([^,\s][^,]*[^,\s]?)\s*'
    
    items = []
    current_index = 0
    
    while current_index < len(content):
        # Find the next comma or end of string
        next_comma = content.find(',', current_index)
        if next_comma == -1:
            next_comma = len(content)
        
        # Extract the item (trim quotes if present)
        item = content[current_index:next_comma].strip()
        if item.startswith('"') and item.endswith('"'):
            item = item[1:-1]
        
        items.append(item)
        
        # Move past the comma
        current_index = next_comma + 1
    
    return items

def get_extra(extras_list, key):
    if extras_list:
        for extra in extras_list:
            if extra.get('key') == key:
                try:
                    if extra.get('value'):
                        d = datetime.strptime(extra.get('value'), "%Y-%m-%d %H:%M:%S")
                        return d.strftime("%Y-%m-%d")
                except ValueError:
                    return parse_postgres_array(extra.get('value'))
    return None

def debug_helper_exists():
    return True

def debug_template_vars():
    context = {}
    for key in dir(toolkit.g):
        if not key.startswith('_'):
            context[key] = getattr(toolkit.g, key)
    return context

def dump(obj):
    import json
    try:
        return json.dumps(obj, indent=2)
    except:
        return str(obj)
    
def custom_get_facet_items_dict(facet, search_facets=None, limit=None, exclude_active=False):
    # Get search_facets from global g object if not provided
    if not search_facets and hasattr(toolkit.g, 'search_facets'):
        search_facets = toolkit.g.search_facets
    
    if not search_facets or not isinstance(search_facets, dict) or not search_facets.get(facet, {}).get('items'):
        return []
    
    facets = []
    for facet_item in search_facets[facet]['items']:
        if not len(facet_item['name'].strip()):
            continue
        
        # Check if this facet is in the request
        is_active = facet in request.args and facet_item['name'] in request.args.getlist(facet)
        
        if not is_active:
            facets.append(dict(active=False, **facet_item))
        elif not exclude_active:
            facets.append(dict(active=True, **facet_item))
    
    # Sort by count (descending) and display name (ascending)
    facets.sort(key=lambda it: (-it['count'], it['display_name'].lower()))
    
    # Apply limit if specified
    if limit is not None and limit > 0:
        return facets[:limit]
    
    return facets

class Nfwf_FieldsPlugin(plugins.SingletonPlugin, toolkit.DefaultDatasetForm, toolkit.DefaultOrganizationForm):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IDatasetForm)
    plugins.implements(plugins.IFacets)

    def dataset_facets(self, facets_dict, package_type):
        '''Add new search facet (filter) for datasets.
        This must be a field in the dataset (or organization or
        group if you're modifying those search facets, just change the function).
        '''
        # This changes the facet order and removes the license facet from the filter list.
        facets_dict['groups'] = facets_dict.pop('groups')
        facets_dict['groups'] = 'Programs'
        facets_dict['organization'] = facets_dict.pop('organization')
        facets_dict['organization'] = "Grants"
        facets_dict['vocab_metric_classes'] = plugins.toolkit._("Metric Classes")
        facets_dict['vocab_restoration_activities'] = plugins.toolkit._("Restoration Activities")
        facets_dict['vocab_monitoring_parameters'] = plugins.toolkit._("Monitoring Parameters")
        facets_dict['vocab_counties'] = plugins.toolkit._("Counties")
        facets_dict['vocab_state_abbreviations'] = plugins.toolkit._("States and Territories")
        facets_dict['grant_cycles'] = plugins.toolkit._("Grant Cycles")
        facets_dict['pipeline_stage'] = plugins.toolkit._("Pipeline Stages")
        facets_dict['res_format'] = facets_dict.pop('res_format')
        facets_dict['tags'] = facets_dict.pop('tags')
        facets_dict.pop('license_id')

        # Return the updated facet dict.
        return facets_dict

    def group_facets(self, facets_dict, group_type, package_type):
        # This changes the facet order and removes some facets from the filter list.
        facets_dict['organization'] = facets_dict.pop('organization')
        facets_dict['organization'] = "Grants"
        facets_dict['vocab_metric_classes'] = plugins.toolkit._("Metric Classes")
        facets_dict['vocab_restoration_activities'] = plugins.toolkit._("Restoration Activities")
        facets_dict['vocab_counties'] = plugins.toolkit._("Counties")
        facets_dict['vocab_state_abbreviations'] = plugins.toolkit._("States and Territories")
        facets_dict['grant_cycles'] = plugins.toolkit._("Grant Cycles")
        facets_dict['nature_based_solutions'] = plugins.toolkit._("Nature-based Solutions")
        facets_dict['grant_statuses'] = plugins.toolkit._("Grant Statuses")
        facets_dict['res_format'] = facets_dict.pop('res_format')
        facets_dict.pop('tags')
        facets_dict.pop('license_id')
        facets_dict.pop('groups')

        # Return the updated facet dict.

        return facets_dict

    def organization_facets(self, facets_dict, organization_type, package_type):
        # This changes the facet order and removes some facets from the filter list.
        facets_dict['vocab_metric_classes'] = plugins.toolkit._("Metric Classes")
        facets_dict['vocab_restoration_activities'] = plugins.toolkit._("Restoration Activities")
        facets_dict['vocab_counties'] = plugins.toolkit._("Counties")
        facets_dict['vocab_state_abbreviations'] = plugins.toolkit._("States and Territories")
        facets_dict['grant_cycles'] = plugins.toolkit._("Grant Cycles")
        facets_dict['nature_based_solutions'] = plugins.toolkit._("Nature-based Solutions")
        facets_dict['grant_statuses'] = plugins.toolkit._("Grant Statuses")
        facets_dict['res_format'] = facets_dict.pop('res_format')
        facets_dict.pop('organization')
        facets_dict.pop('tags')
        facets_dict.pop('license_id')
        facets_dict.pop('groups')
        
        # Return the updated facet dict.
        return facets_dict

    def create_package_schema(self):
        schema = super(Nfwf_FieldsPlugin, self).create_package_schema()
        schema = self._modify_package_schema(schema)
        return schema

    def update_package_schema(self):
        schema = super(Nfwf_FieldsPlugin, self).update_package_schema()
        schema = self._modify_package_schema(schema)
        return schema

    def _modify_package_schema(self, schema):
        schema.update({
            'principal_investigator': [toolkit.get_validator('not_empty'),
                            toolkit.get_converter('convert_to_extras')],

            'point_of_contact_email': [toolkit.get_validator('not_empty'),
                            toolkit.get_converter('convert_to_extras'),toolkit.get_validator('email_validator')],

            'point_of_contact_phone': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_extras')],

            'alt_point_of_contact_name': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_extras')],              
            
            'alt_point_of_contact_email': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_extras')],

            'alt_point_of_contact_phone': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_extras')],

            'private_rationale': [toolkit.get_validator('ignore_missing')],

            'metric_category': [toolkit.get_validator('ignore_missing'),
                                toolkit.get_converter('convert_to_tags')('metric_categories')],

            'metric_class': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_tags')('metric_classes')],

            'resilience_grant': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_tags')('resilience_grants')],

            'monitoring_grant': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_tags')('monitoring_grants')],

            'nfwf_program': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_tags')('nfwf_programs')],

            'reporting_year': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_tags')('reporting_years')],

            'county': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_tags')('counties'),
                            toolkit.get_converter('convert_to_list_if_string')],

            'state_abbr': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_tags')('state_abbreviations'),
                            toolkit.get_converter('convert_to_list_if_string')],
            
            'measurement_stage': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_tags')('measurement_stages')],
       
            'restoration_activity': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_tags')('restoration_activities')],

            'grant_cycle': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_tags')('grant_cycles')],

            'pipeline_stage': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_tags')('pipeline_stages'),
                            toolkit.get_converter('convert_to_list_if_string')],

            'nature_based_solution': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_tags')('nature_based_solution')],

            'grant_status': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_tags')('grant_status')]
        })
        # Custom resource schema:
        cast(Schema, schema['resources']).update({
                'metric': [toolkit.get_validator('ignore_missing'),
                        toolkit.get_converter('convert_to_list_if_string')],
                'doc_type': [toolkit.get_validator('ignore_missing')],
                'monitoring_stages': [toolkit.get_validator('ignore_missing'),
                        toolkit.get_converter('convert_to_list_if_string')],
                'reporting_years_resource': [toolkit.get_validator('ignore_missing'),
                        toolkit.get_converter('convert_to_list_if_string')],
                })
        return schema
    
    def show_package_schema(self):
        schema = super(Nfwf_FieldsPlugin, self).show_package_schema()
        schema['tags']['__extras'].append(toolkit.get_converter('free_tags_only'))
        schema.update({
            'principal_investigator': [toolkit.get_converter('convert_from_extras'),
                        toolkit.get_validator('not_empty')],

            'point_of_contact_email': [toolkit.get_converter('convert_from_extras'),
                        toolkit.get_validator('not_empty'),toolkit.get_validator('email_validator')],

            'point_of_contact_phone': [toolkit.get_converter('convert_from_extras'),
                        toolkit.get_validator('ignore_missing')],

            'alt_point_of_contact_name': [toolkit.get_converter('convert_from_extras'),
                        toolkit.get_validator('ignore_missing')],             
            
            'alt_point_of_contact_email': [toolkit.get_converter('convert_from_extras'),
                        toolkit.get_validator('ignore_missing')],

            'alt_point_of_contact_phone': [toolkit.get_converter('convert_from_extras'),
                        toolkit.get_validator('ignore_missing')],

            'private_rationale': [toolkit.get_validator('ignore_missing')],

            'metric_category': [toolkit.get_converter('convert_from_tags')('metric_categories'),
                toolkit.get_validator('ignore_missing')],
            'metric_class': [
                toolkit.get_converter('convert_from_tags')('metric_classes'),
                toolkit.get_validator('ignore_missing')],
            'resilience_grant': [
                toolkit.get_converter('convert_from_tags')('resilience_grants'),
                toolkit.get_validator('ignore_missing')],
            'monitoring_grant': [
                toolkit.get_converter('convert_from_tags')('monitoring_grants'),
                toolkit.get_validator('ignore_missing')],
            'nfwf_program': [
                toolkit.get_converter('convert_from_tags')('nfwf_programs'),
                toolkit.get_validator('ignore_missing')],
            'reporting_year': [
                toolkit.get_converter('convert_from_tags')('reporting_years'),
                toolkit.get_validator('ignore_missing')],
            'county': [
                toolkit.get_converter('convert_from_tags')('counties'),
                toolkit.get_converter('convert_to_list_if_string'),
                toolkit.get_validator('ignore_missing')],
            'state_abbr': [
                toolkit.get_converter('convert_from_tags')('state_abbreviations'),
                toolkit.get_converter('convert_to_list_if_string'),
                toolkit.get_validator('ignore_missing')],
            'measurement_stage': [
                toolkit.get_converter('convert_from_tags')('measurement_stages'),
                toolkit.get_validator('ignore_missing')],
            'restoration_activity': [
                toolkit.get_converter('convert_from_tags')('restoration_activities'),
                toolkit.get_validator('ignore_missing')],
            'grant_cycle': [
                toolkit.get_converter('convert_from_tags')('grant_cycles'),
                toolkit.get_validator('ignore_missing')],
            'pipeline_stage': [
                toolkit.get_converter('convert_from_tags')('pipeline_stages'),
                toolkit.get_converter('convert_to_list_if_string'),
                toolkit.get_validator('ignore_missing')],
            'nature_based_solution': [
                toolkit.get_converter('convert_from_tags')('nature_based_solutions'),
                toolkit.get_validator('ignore_missing')],
            'grant_status': [
                toolkit.get_converter('convert_from_tags')('grant_statuses'),
                toolkit.get_validator('ignore_missing')]
        })
        # Custom resource schema:
        cast(Schema, schema['resources']).update({
                'metric': [toolkit.get_validator('ignore_missing'),
                        toolkit.get_converter('convert_to_list_if_string')],
                'doc_type': [toolkit.get_validator('ignore_missing')],
                'monitoring_stages': [toolkit.get_validator('ignore_missing'),
                        toolkit.get_converter('convert_to_list_if_string')],
                'reporting_years_resource': [toolkit.get_validator('ignore_missing'),
                        toolkit.get_converter('convert_to_list_if_string')],
                })
        return schema

    def is_fallback(self):
        # Return True to register this plugin as the default handler for
        # package types not handled by any other IDatasetForm plugin.
        return True

    def package_types(self):
        # This plugin doesn't handle any special package types, it just
        # registers itself as the default (above).
        return []

    def get_helpers(self):
        return {
            'metric_categories': metric_categories, 
            'metric_classes': metric_classes, 
            'resilience_grants' : resilience_grants, 
            'monitoring_grants' : monitoring_grants, 
            'nfwf_programs' : nfwf_programs, 
            'reporting_years' : reporting_years, 
            'counties' : counties, 
            'state_abbreviations' : state_abbreviations, 
            'measurement_stages' : measurement_stages, 
            'restoration_activities' : restoration_activities,
            'groups_reload' : groups_reload,
            'default_group' : default_group,
            'groups': groups,
            'debug_helper_exists': debug_helper_exists,
            'debug_template_vars': debug_template_vars,
            'dump': dump,
            'custom_get_facet_items_dict': custom_get_facet_items_dict,
            'grant_cycles' : grant_cycles,
            'pipeline_stages' : pipeline_stages,
            'nature_based_solutions' : nature_based_solutions,
            'grant_statuses' : grant_statuses,
            'extras_has_value' : extras_has_value,
            'get_extra' : get_extra,
            'monitoring_parameters' : monitoring_parameters,
            'get_grant_required_metrics_by_nbs' : get_grant_required_metrics_by_nbs,
            'get_satisfied_metrics' : get_satisfied_metrics,
            'get_nbs_from_package_id': get_nbs_from_package_id,
            'doc_types': doc_types,
            'monitoring_stages': monitoring_stages
            }

    # IConfigurer

    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('fanstatic', 'nfwf_fields')

class Nfwf_Org_FieldsPlugin(plugins.SingletonPlugin, toolkit.DefaultOrganizationForm):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IGroupForm)

    # Add this property to specify it's for organizations
    is_organization = True
    
    # Add the following methods
    def group_types(self):
        return ['organization']
        
    def is_fallback(self):
        return True
        
    def create_group_schema(self):
        schema = super(Nfwf_Org_FieldsPlugin, self).create_group_schema()
        schema = self._modify_group_schema(schema)
        return schema
        
    def update_group_schema(self):
        schema = super(Nfwf_Org_FieldsPlugin, self).update_group_schema()
        schema = self._modify_group_schema(schema)
        return schema
        
    def show_group_schema(self):
        schema = super(Nfwf_Org_FieldsPlugin, self).show_group_schema()
        # schema['tags']['__extras'].append(toolkit.get_converter('free_tags_only'))
        schema.update({
            'grant_cycle': [toolkit.get_converter('convert_from_extras'),
                            toolkit.get_validator('not_empty')],
            'owner_group': [toolkit.get_converter('convert_from_extras'),
                              toolkit.get_validator('not_empty')],
            'pipeline_stage': [toolkit.get_converter('convert_from_extras'),
                                toolkit.get_converter('convert_to_list_if_string'),
                                toolkit.get_validator('not_empty')],
            'nature_based': [toolkit.get_converter('convert_from_extras'),
                            toolkit.get_converter('convert_to_list_if_string'),
                            toolkit.get_validator('not_empty')],
            'metric_category': [toolkit.get_converter('convert_from_extras'),
                               toolkit.get_validator('ignore_missing')],
            'grant_status': [toolkit.get_converter('convert_from_extras'),
                            toolkit.get_validator('ignore_missing')],
            'state_abbr_org': [toolkit.get_converter('convert_from_extras'),
                           toolkit.get_converter('convert_to_list_if_string'),
                          toolkit.get_validator('ignore_missing')],
            'county': [toolkit.get_converter('convert_from_extras'),
                       toolkit.get_converter('convert_to_list_if_string'),
                       toolkit.get_validator('ignore_missing')],
            'start_date': [toolkit.get_converter('convert_from_extras'),
                          toolkit.get_validator('isodate'),
                          toolkit.get_validator('ignore_missing')],
            'close_date': [toolkit.get_converter('convert_from_extras'),
                          toolkit.get_validator('isodate'),
                          toolkit.get_validator('ignore_missing')]
        })
        return schema
        
    def _modify_group_schema(self, schema):
        schema.update({
            'grant_cycle': [toolkit.get_validator('not_empty'),
                            toolkit.get_converter('convert_to_extras')],
            'owner_group': [toolkit.get_converter('convert_to_extras'),
                              toolkit.get_validator('not_empty')],
            'pipeline_stage': [toolkit.get_validator('not_empty'),
                               toolkit.get_converter('convert_to_list_if_string'),
                              toolkit.get_converter('convert_to_extras')],
            'nature_based': [toolkit.get_validator('not_empty'),
                            toolkit.get_converter('convert_to_list_if_string'),
                            toolkit.get_converter('convert_to_extras')],
            'metric_category': [toolkit.get_validator('ignore_missing'),
                               toolkit.get_converter('convert_to_extras')],
            'grant_status': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_extras')],
            'state_abbr_org': [toolkit.get_validator('ignore_missing'),
                           toolkit.get_converter('convert_to_list_if_string'),
                          toolkit.get_converter('convert_to_extras')],
            'county': [toolkit.get_validator('ignore_missing'),
                       toolkit.get_converter('convert_to_list_if_string'),
                       toolkit.get_converter('convert_to_extras')],
            'start_date': [toolkit.get_validator('ignore_missing'),
                          toolkit.get_validator('isodate'),
                          toolkit.get_converter('convert_to_extras')],
            'close_date': [toolkit.get_validator('ignore_missing'),
                          toolkit.get_validator('isodate'),
                          toolkit.get_converter('convert_to_extras')],
        })
        return schema

    def get_helpers(self):
        return {
            'metric_categories': metric_categories, 
            'metric_classes': metric_classes, 
            'resilience_grants' : resilience_grants, 
            'monitoring_grants' : monitoring_grants, 
            'nfwf_programs' : nfwf_programs, 
            'reporting_years' : reporting_years, 
            'counties' : counties, 
            'state_abbreviations' : state_abbreviations, 
            'measurement_stages' : measurement_stages, 
            'restoration_activities' : restoration_activities,
            'groups_reload' : groups_reload,
            'default_group' : default_group,
            'groups': groups,
            'debug_helper_exists': debug_helper_exists,
            'debug_template_vars': debug_template_vars,
            'dump': dump,
            'custom_get_facet_items_dict': custom_get_facet_items_dict,
            'grant_cycles' : grant_cycles,
            'pipeline_stages' : pipeline_stages,
            'nature_based_solutions' : nature_based_solutions,
            'grant_statuses' : grant_statuses,
            'extras_has_value' : extras_has_value,
            'get_extra' : get_extra
            }

    # IConfigurer
    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('fanstatic', 'nfwf_org_fields')