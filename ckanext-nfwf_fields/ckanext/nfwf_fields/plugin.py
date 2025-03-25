import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
import ckan.lib.helpers as helpers
import ckan.model as model
from flask import request


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
state_abbr_vocab = [
'AK','AL','AS','CA','CT','DE','FL','GA','GU','HI','LA','MA','MD','ME',
'MP','MS','NC','NH','NJ','NY','OR','PR','RI','SC','TX','VA','VI','WA'
]
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

def restoration_activities():
    create_tag_vocabulary(restoration_activity_vocab,'restoration_activities')
    try:
        tag_list = toolkit.get_action('tag_list')
        restoration_activities = tag_list(data_dict={'vocabulary_id': 'restoration_activities'})
        return restoration_activities
    except toolkit.ObjectNotFound:
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
    """Modified version of get_facet_items_dict that works with CKAN 2.11"""
    
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

class Nfwf_FieldsPlugin(plugins.SingletonPlugin, toolkit.DefaultDatasetForm):
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
        facets_dict['vocab_state_abbreviations'] = plugins.toolkit._("States and Territories")
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
        facets_dict['vocab_state_abbreviations'] = plugins.toolkit._("States and Territories")
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
        facets_dict['vocab_state_abbreviations'] = plugins.toolkit._("States and Territories")
        facets_dict['res_format'] = facets_dict.pop('res_format')
        facets_dict.pop('organization')
        facets_dict.pop('tags')
        facets_dict.pop('license_id')
        facets_dict.pop('groups')
        
        # Return the updated facet dict.
        return facets_dict

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

            'metric_category': [toolkit.get_validator('not_empty'),
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


            'state_abbr': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_tags')('state_abbreviations')],
            
            'measurement_stage': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_tags')('measurement_stages')],
       
            'restoration_activity': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_tags')('restoration_activities')]
        })
 #       schema['resources'].update({
  #      'custom_resource_text' : [ toolkit.get_validator('ignore_missing') ]
  #      })
        return schema

    def create_package_schema(self):
        schema = super(Nfwf_FieldsPlugin, self).create_package_schema()
        schema = self._modify_package_schema(schema)
        return schema

    def update_package_schema(self):
        schema = super(Nfwf_FieldsPlugin, self).update_package_schema()
        schema = self._modify_package_schema(schema)
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

            'metric_category': [toolkit.get_converter('convert_from_tags')('metric_categories'),
                toolkit.get_validator('not_empty')],
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
            'state_abbr': [
                toolkit.get_converter('convert_from_tags')('state_abbreviations'),
                toolkit.get_validator('ignore_missing')],
            'measurement_stage': [
                toolkit.get_converter('convert_from_tags')('measurement_stages'),
                toolkit.get_validator('ignore_missing')],
            'restoration_activity': [
                toolkit.get_converter('convert_from_tags')('restoration_activities'),
                toolkit.get_validator('ignore_missing')]       
        })

 #       schema['resources'].update({
  #      'custom_resource_text' : [toolkit.get_validator('ignore_missing')]
  #          })
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
            'state_abbreviations' : state_abbreviations, 
            'measurement_stages' : measurement_stages, 
            'restoration_activities' : restoration_activities,
            'groups_reload' : groups_reload,
            'default_group' : default_group,
            'groups': groups,
            'debug_helper_exists': debug_helper_exists,
            'debug_template_vars': debug_template_vars,
            'dump': dump,
            'custom_get_facet_items_dict': custom_get_facet_items_dict
            }

    # IConfigurer

    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('fanstatic', 'nfwf_fields')