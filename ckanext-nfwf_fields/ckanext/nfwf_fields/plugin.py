from __future__ import annotations

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
import ckan.lib.helpers as helpers
from ckan.lib.navl.dictization_functions import Missing
import ckan.model as model
from flask import request
import geonamescache
from datetime import datetime
from ckan.types import Schema
from typing import cast
import logging
import json
from urllib.parse import urlencode
import re
import threading

_thread_state = threading.local()
log = logging.getLogger(__name__)

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
    "Nature-Based Stormwater Infrastructure",
    "Habitat Conservation Practices",
    "Kelp or Macroalgae Restoration",
    "Living Shoreline",
    "Mangrove Restoration",
    "Marine or Aquatic Habitat Restoration",
    "Marsh Restoration",
    "N/A",
    "Oyster Reef Restoration",
    "Riparian Restoration",
    "Seagrass Restoration",
    "Stream Restoration",
    "Wildfire Prevention"
]
monitoring_parameter_vocab = [ # if you change this, make sure to update 'nbs_monitoring'
    "Area",
    "Avian Abundance",
    "Beach-Dune Geomorphology",
    "Coral Abundance",
    "Density",
    "Elevation",
    "Fish Abundance",
    "NBSI Condition Assessment",
    "Rugosity or Reef Height",
    "Shoreline Position",
    "Survival",
    "Vegetation",
    "Water Level",
    "Water Quality",
    "Width"
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
    'Monitoring Report',
    'Image',
    'GIS File',
    'Implementation Report',
    'As Built Drawing',
    'Eng and Design Plan',
    'Env Compliance',
    'Modeling Report',
    'Modeling Data',
    'Stakeholder Engagement Plan',
    'Outreach Materials',
    'Resilience or Hazard Management Plan',
    'Other'
]
nbs_monitoring = { # if you change this, make sure to update 'monitoring_parameter_vocab'
    "Aquatic Connectivity": ["Width"],
    "Beach Dune or Barrier Island Restoration": ["Shoreline Position", "Beach-Dune Geomorphology", "Elevation"],
    "Coastal Forest Restoration": [],
    "Community Resilience Planning": [],
    "Coral Reef Restoration": ["Area", "Coral Abundance", "Survival", "Rugosity or Reef Height"],
    "Easements and Acquisitions": [],
    "Floodplain Restoration": ["Vegetation", "Elevation", "Water Level"],
    "Nature-Based Stormwater Infrastructure": ["NBSI Condition Assessment"],
    "Habitat Conservation Practices": [],
    "Kelp or Macroalgae Restoration": ["Density"],
    "Living Shoreline": ["Vegetation", "Water Level", "Elevation", "Shoreline Position", "Area"],
    "Mangrove Restoration": [],
    "Marine or Aquatic Habitat Restoration": [],
    "Marsh Restoration": ["Vegetation", "Water Level", "Elevation", "Shoreline Position"],
    "N/A": [],
    "Oyster Reef Restoration": ["Area", "Density", "Rugosity or Reef Height"],
    "Riparian Restoration": ["Elevation", "Vegetation"],
    "Seagrass Restoration": ["Vegetation"],
    "Stream Restoration": ["Elevation", "Vegetation", "Width"],
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
            try:
                toolkit.get_action('tag_create')(context, data)
            except toolkit.ValidationError:
                # Tag already exists, ignore
                pass

def metric_classes():
    create_tag_vocabulary(metric_class_vocab,'metric_classes')
    return metric_class_vocab

def metric_categories():
    create_tag_vocabulary(metric_category_vocab,'metric_categories')
    return metric_category_vocab

def resilience_grants():
    create_tag_vocabulary(resilience_grant_vocab,'resilience_grants')
    return resilience_grant_vocab

def monitoring_grants():
    create_tag_vocabulary(monitoring_grant_vocab,'monitoring_grants')
    return monitoring_grant_vocab

def nfwf_programs():
    create_tag_vocabulary(nfwf_program_vocab,'nfwf_programs')
    return nfwf_program_vocab

def reporting_years():
    create_tag_vocabulary(reporting_year_vocab,'reporting_years')
    return reporting_year_vocab

def counties():
    create_tag_vocabulary(county_vocab,'counties')
    return county_vocab

def state_abbreviations():
    create_tag_vocabulary(state_abbr_vocab,'state_abbreviations')
    return state_abbr_vocab

def measurement_stages():
    create_tag_vocabulary(measurement_stage_vocab,'measurement_stages')
    return measurement_stage_vocab

def grant_cycles():
    create_tag_vocabulary(grant_cycle_vocab, 'grant_cycles')
    return grant_cycle_vocab

def pipeline_stages():
    create_tag_vocabulary(pipeline_stage_vocab, 'pipeline_stages')
    return pipeline_stage_vocab

def nature_based_solutions():
    create_tag_vocabulary(nature_based_solution_vocab, 'nature_based_solutions')
    return nature_based_solution_vocab

def grant_statuses():
    create_tag_vocabulary(grant_status_vocab, 'grant_statuses')
    return grant_status_vocab

def doc_types():
    create_tag_vocabulary(doc_type_vocab, 'doc_types')
    return doc_type_vocab

def monitoring_stages():
    create_tag_vocabulary(monitoring_stage_vocab, 'monitoring_stages')
    return monitoring_stage_vocab

def monitoring_parameters():
    create_tag_vocabulary(monitoring_parameter_vocab, 'monitoring_parameters')
    return monitoring_parameter_vocab

def restoration_activities():
    create_tag_vocabulary(restoration_activity_vocab, 'restoration_activities')
    return restoration_activity_vocab

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

def private_rationale_validator(key, data, errors, context):
    private = data.get(('private',))
    if private:
        toolkit.get_validator('not_empty')(key, data, errors, context)
    else:
        toolkit.get_validator('ignore_missing')(key, data, errors, context)

def sysadmin_not_empty(key, data, errors, context):
    try:
        toolkit.check_access('sysadmin', context)
        toolkit.get_validator('not_empty')(key, data, errors, context)
    except toolkit.NotAuthorized:
        toolkit.get_validator('ignore_missing')(key, data, errors, context)

def extras_has_value(extras_list, key, value):
    if extras_list:
        for extra in extras_list:
            if extra.get('key') == key:
                if extra.get('value'):
                    parsed_value = parse_postgres_array(extra.get('value'))
                    try:
                        if value in parsed_value:
                            return True
                    except TypeError:
                        if value == parsed_value:
                            return True
    return False

def has_value(data_dict, key, value):
    if data_dict:
        if key in data_dict:
            data_value = data_dict.get(key)
            if not isinstance(data_value, Missing):
                try:
                    if value in data_value:
                        return True
                except TypeError:
                    if value == data_value:
                        return True
        if 'extras' in data_dict:
            return extras_has_value(data_dict.get('extras'), key, value)
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
                value = extra.get('value')
                if value:
                    try:
                        d = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                        return d.strftime("%Y-%m-%d")
                    except ValueError:
                        return parse_postgres_array(value)
    return None

def get_value_or_extra(data_dict, key):
    if data_dict:
        if key in data_dict:
            value = data_dict.get(key)
            if not isinstance(value, Missing):
                if isinstance(value, str):
                    try:
                        d = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                        return d.strftime("%Y-%m-%d")
                    except ValueError:
                        try:
                            datetime.strptime(value, "%Y-%m-%d")
                            return value
                        except ValueError:
                            return parse_postgres_array(value)
                return value
        if 'extras' in data_dict:
            return get_extra(data_dict.get('extras'), key)
    return None

def replace_keys(dict_old, dict_keys):
    if dict_old is None:
        return None
    if dict_keys is None:
        return dict_old
    
    dict_new = type(dict_old)()
    for old_key, new_key in dict_keys.items():
        if old_key in dict_old:
            dict_new[new_key] = dict_old[old_key]
    for key, value in dict_old.items():
        if key not in dict_keys:
            dict_new[key] = value
    
    return dict_new

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
    """
    Get facet items for display. For facets with active selections,
    runs a secondary search WITHOUT that facet's filter to show all
    available options (enabling multi-select OR within same facet).
    """
    managed_facets = [
        'groups', 'organization', 'nature_based', 'grant_cycle',
        'pipeline_stage', 'doc_type', 'metric', 'monitoring_stages',
        'res_format', 'state_abbr_org'
    ]

    # Get active values for this facet from request
    try:
        active_values = request.args.getlist(facet)
    except RuntimeError:
        active_values = []

    # If this facet has active selections AND it's a managed facet,
    # do a secondary search WITHOUT this facet's filter to get all options
    if active_values and facet in managed_facets:
        try:
            q = request.args.get('q', '') or ''

            # Build fq from OTHER active facets only (exclude current facet)
            fq_parts = []
            for other_facet in managed_facets:
                if other_facet == facet:
                    continue
                other_values = request.args.getlist(other_facet)
                if other_values:
                    if len(other_values) == 1:
                        fq_parts.append('%s:"%s"' % (other_facet, other_values[0]))
                    else:
                        or_clause = ' OR '.join('%s:"%s"' % (other_facet, v) for v in other_values)
                        fq_parts.append('(%s)' % or_clause)

            # If on a group page, scope to that group (not a URL param, applied implicitly)
            try:
                _group = toolkit.g.group_dict
                if _group and not _group.get('is_organization'):
                    fq_parts.append('groups:"%s"' % _group['name'])
            except (AttributeError, TypeError):
                pass

            fq = ' '.join(fq_parts)

             # Get current user for proper permission filtering
            try:
                user = toolkit.g.user
            except Exception:
                user = None

            # Use proper auth context so private datasets are only counted
            # for users who have permission to see them
            if user:
                context = {'user': user}
                include_private = True
            else:
                context = {}
                include_private = False

            # Set thread-local flag to prevent before_dataset_search from modifying this query
            _thread_state.skip_facet_or = True
            try:
                result = toolkit.get_action('package_search')(context, {
                    'q': q,
                    'fq': fq,
                    'rows': 0,
                    'facet.field': [facet],
                    'facet.limit': -1,
                    'facet.mincount': 0,
                    'include_private': include_private,
                })
            finally:
                _thread_state.skip_facet_or = False

            search_facets_result = result.get('search_facets', {})
            items_from_search = search_facets_result.get(facet, {}).get('items', [])

            facets = []
            found_active_names = set()

            for facet_item in items_from_search:
                if not facet_item.get('name', '').strip():
                    continue
                is_active = facet_item['name'] in active_values

                if is_active:
                    found_active_names.add(facet_item['name'])

                if is_active and exclude_active:
                    continue

                # Skip items with 0 count unless they are active
                if facet_item.get('count', 0) == 0 and not is_active:
                    continue

                facets.append(dict(active=is_active, **facet_item))

            # Ensure ALL active values appear even if secondary search didn't return them
            for active_val in active_values:
                if active_val not in found_active_names and not exclude_active:
                    facets.append({
                        'name': active_val,
                        'display_name': active_val,
                        'count': 0,
                        'active': True,
                    })

            facets.sort(key=lambda it: (-it['count'], it['display_name'].lower()))

            if limit is not None and limit > 0:
                return facets[:limit]

            return facets

        except Exception as e:
            log.warning('Secondary facet search failed for %s: %s', facet, e)
            # Fall through to normal behavior

    # --- Normal behavior: use search_facets from the main search ---
    if not search_facets and hasattr(toolkit.g, 'search_facets'):
        search_facets = toolkit.g.search_facets
    
    if not search_facets or not isinstance(search_facets, dict) or not search_facets.get(facet, {}).get('items'):
        return []
    
    facets = []
    for facet_item in search_facets[facet]['items']:
        if not facet_item.get('name', '').strip():
            continue
        
        # Check if this facet is in the request
        is_active = facet_item['name'] in active_values
        
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


def remove_grant_prefix(facet_item):
    name = facet_item.get('display_name')
    if name.startswith("Grant "):
        return name[6:]
    return name


def facet_url_add(facet_name, facet_value):
    """Build URL that adds a facet value, preserving existing multi-select values (OR within same facet)."""
    try:
        params = [(k, v) for k, v in request.args.items(multi=True) if k != 'page']
    except RuntimeError:
        return ''
    # Don't add duplicates
    if (facet_name, facet_value) not in params:
        params.append((facet_name, facet_value))
    base_url = request.path
    if params:
        return base_url + '?' + urlencode(params)
    return base_url


def facet_url_remove(facet_name, facet_value):
    """Build URL that removes a specific facet value, preserving other selections."""
    try:
        params = [(k, v) for k, v in request.args.items(multi=True) if k != 'page']
    except RuntimeError:
        return ''
    params = [(k, v) for k, v in params if not (k == facet_name and v == facet_value)]
    base_url = request.path
    if params:
        return base_url + '?' + urlencode(params)
    return base_url


def _auth_aware_package_count(context, fq_field, fq_value):
    """
    Return a dataset count respecting the current user's auth level.
    Sets skip_facet_or to prevent before_dataset_search from injecting
    facet OR clauses into this internal count query.
    """
    try:
        _thread_state.skip_facet_or = True
        try:
            result = toolkit.get_action('package_search')(
                dict(context),
                {
                    'fq': '%s:"%s"' % (fq_field, fq_value),
                    'rows': 0,
                    'include_private': True,
                }
            )
        finally:
            _thread_state.skip_facet_or = False

        return result.get('count', 0)

    except Exception as e:
        log.warning(
            'auth_aware_package_count failed for %s:"%s": %s',
            fq_field, fq_value, e
        )
        return 0


@toolkit.chained_action
def _chained_group_show(original_action, context, data_dict):
    """
    Wrap group_show to replace package_count with an auth-aware value.
    """
    result = original_action(context, data_dict)
    if context.get('__skip_package_count'):
        return result

    if isinstance(result, dict) and 'package_count' in result:
        is_org = result.get('is_organization', False)
        name = result.get('name') or result.get('id')
        if name:
            # Solr field 'groups' stores group names
            # Solr field 'organization' stores org names
            fq_field = 'organization' if is_org else 'groups'
            result['package_count'] = _auth_aware_package_count(
                context, fq_field, name
            )

    return result


@toolkit.chained_action
def _chained_group_list(original_action, context, data_dict):
    """
    Wrap group_list to replace package_count on every item with an
    auth-aware value. Uses a single batched Solr facet query instead
    of one query per group.
    """
    result = original_action(context, data_dict)

    all_fields = data_dict.get('all_fields', False)
    include_dataset_count = data_dict.get('include_dataset_count', True)

    if all_fields and include_dataset_count and isinstance(result, list) and result:
        try:
            _thread_state.skip_facet_or = True
            try:
                facet_result = toolkit.get_action('package_search')(
                    dict(context),
                    {
                        'q': '*:*',
                        'rows': 0,
                        'include_private': True,
                        'facet.field': ['groups'],
                        'facet.limit': -1,
                        'facet.mincount': 0,
                    }
                )
            finally:
                _thread_state.skip_facet_or = False

            counts = {
                item['name']: item['count']
                for item in facet_result
                    .get('search_facets', {})
                    .get('groups', {})
                    .get('items', [])
            }
            for group in result:
                if isinstance(group, dict):
                    name = group.get('name')
                    if name:
                        group['package_count'] = counts.get(name, 0)

        except Exception as e:
            log.warning('Batched group count failed, falling back: %s', e)
            for group in result:
                if isinstance(group, dict) and 'package_count' in group:
                    name = group.get('name') or group.get('id')
                    if name:
                        group['package_count'] = _auth_aware_package_count(
                            context, 'groups', name
                        )

    return result


@toolkit.chained_action
def _chained_organization_show(original_action, context, data_dict):
    """
    Wrap organization_show to replace package_count with an auth-aware value.
    """
    result = original_action(context, data_dict)

    if isinstance(result, dict) and 'package_count' in result:
        org_name = result.get('name')
        if org_name:
            # Solr's 'organization' field stores the org name/slug
            # Solr's 'owner_org' field stores the org UUID
            # Use 'organization' since we have the name
            result['package_count'] = _auth_aware_package_count(
                context, 'organization', org_name
            )

    return result


@toolkit.chained_action
def _chained_organization_list(original_action, context, data_dict):
    """
    Wrap organization_list to replace package_count with auth-aware values.
    Uses a single batched Solr facet query.
    """
    result = original_action(context, data_dict)

    all_fields = data_dict.get('all_fields', False)
    include_dataset_count = data_dict.get('include_dataset_count', True)

    if all_fields and include_dataset_count and isinstance(result, list) and result:
        try:
            _thread_state.skip_facet_or = True
            try:
                facet_result = toolkit.get_action('package_search')(
                    dict(context),
                    {
                        'q': '*:*',
                        'rows': 0,
                        'include_private': True,
                        'facet.field': ['organization'],
                        'facet.limit': -1,
                        'facet.mincount': 0,
                    }
                )
            finally:
                _thread_state.skip_facet_or = False

            counts = {
                item['name']: item['count']
                for item in facet_result
                    .get('search_facets', {})
                    .get('organization', {})
                    .get('items', [])
            }
            for org in result:
                if isinstance(org, dict):
                    name = org.get('name')
                    if name:
                        org['package_count'] = counts.get(name, 0)

        except Exception as e:
            log.warning('Batched org count failed, falling back: %s', e)
            for org in result:
                if isinstance(org, dict) and 'package_count' in org:
                    name = org.get('name') or org.get('id')
                    if name:
                        org['package_count'] = _auth_aware_package_count(
                            context, 'organization', name 
                        )

    return result


class Nfwf_FieldsPlugin(plugins.SingletonPlugin, toolkit.DefaultDatasetForm, toolkit.DefaultOrganizationForm):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IDatasetForm)
    plugins.implements(plugins.IFacets)
    plugins.implements(plugins.IPackageController, inherit=True)
    plugins.implements(plugins.IOrganizationController, inherit=True) 
    plugins.implements(plugins.IActions)
    plugins.implements(plugins.IGroupController, inherit=True)

    def before_dataset_index(self, pkg_dict):
        # From Grant (organization/group)
        owner_org = pkg_dict.get('owner_org')

        if owner_org:
            try:
                org = toolkit.get_action('organization_show')(
                    {'ignore_auth': True},
                    {'id': owner_org, 'include_extras': True}
                )
                extras = org.get('extras', [])

                # nature_based, pipeline_stage, grant_cycle, state_abbr_org
                for extra in extras:
                    if extra.get('state') == 'active':
                        value = extra.get('value')
                        key = extra.get('key')
                        # Multi-Valued facets
                        if key in ['nature_based', 'pipeline_stage', 'state_abbr_org']:
                            if value:
                                if isinstance(value, list):
                                    value_list = value
                                else:
                                    value_list = parse_postgres_array(value)
                                if value_list:
                                    pkg_dict[key] = value_list
                            continue
                        # Single-Valued facet
                        if key == 'grant_cycle':
                            if value and value.strip():
                                pkg_dict['grant_cycle'] = value.strip()
                            continue

                # groups
                owner_group_id = None
                for extra in extras:
                    if extra.get('key') == 'owner_group':
                        owner_group_id = extra.get('value')
                        break
                if owner_group_id:
                    try:
                        group = toolkit.get_action('group_show')(
                            {'ignore_auth': True, '__skip_package_count': True},
                            {'id': owner_group_id}
                        )
                        group_name = group.get('name')
                        if group_name:
                            # Override the groups field so the facet reflects
                            # the org→program relationship, not the member table
                            pkg_dict['groups'] = [group_name]
                    except Exception as e:
                        log.warning(
                            'Could not resolve owner_group "%s" for org "%s": %s',
                            owner_group_id, owner_org, e
                        )
                else:
                    # No owner_group on this org → dataset belongs to no program
                    pkg_dict['groups'] = []
                                    
            except Exception as e:
                log.error('before_dataset_index error: {}'.format(e))

        # From Resources (parse from validated_data_dict since resources aren't available as dicts)
        doc_types = set()
        metrics = set()
        monitoring_stages = set()
        validated = pkg_dict.get('validated_data_dict')
        if validated:
            try:
                full_dict = json.loads(validated)
                for resource in full_dict.get('resources', []):
                    dt = resource.get('doc_type')
                    if dt and dt.strip():
                        doc_types.add(dt.strip())
                    for m in resource.get('metric', []) or []:
                        if m and m.strip():
                            metrics.add(m.strip())
                    for ms in resource.get('monitoring_stages', []) or []:
                        if ms and ms.strip():
                            monitoring_stages.add(ms.strip())
            except Exception as e:
                log.warning('Could not parse validated_data_dict for resource fields: %s', e)
        if doc_types:
            pkg_dict['doc_type'] = list(doc_types)
        if metrics:
            pkg_dict['metric'] = list(metrics)
        if monitoring_stages:
            pkg_dict['monitoring_stages'] = list(monitoring_stages)

        return pkg_dict

    def before_dataset_search(self, search_params):
        """
        Convert same-facet multiple selections from AND to OR logic.
        Uses plain Solr OR syntax (no local params).
        Cross-facet remains AND.
        """
        # Skip if this is a secondary facet-count search
        if getattr(_thread_state, 'skip_facet_or', False):
            return search_params

        # Guard against non-request contexts (CLI reindex, tests, API)
        try:
            args = request.args
        except RuntimeError:
            return search_params

        # All facets we manage for multi-select OR behavior
        managed_facets = [
            'groups', 'organization', 'nature_based', 'grant_cycle',
            'pipeline_stage', 'doc_type', 'metric', 'monitoring_stages',
            'res_format', 'state_abbr_org'
        ]

        # Find which managed facets have any selected values
        active_facets = {}
        for param in managed_facets:
            values = args.getlist(param)
            if values:
                active_facets[param] = values

        if not active_facets:
            return search_params

        try:
            # --- Remove CKAN's default individual fq entries for managed facets ---
            fq = search_params.get('fq', '')

            for facet_name, values in active_facets.items():
                for value in values:
                    # Remove patterns like: facet_name:"value"
                    pattern = r'\s*' + re.escape(facet_name) + r':"' + re.escape(value) + r'"'
                    fq = re.sub(pattern, '', fq)

            # Also clean fq_list
            existing_fq_list = list(search_params.get('fq_list', []) or [])
            cleaned_fq_list = []
            for fq_item in existing_fq_list:
                keep = True
                for facet_name, values in active_facets.items():
                    for value in values:
                        if '%s:"%s"' % (facet_name, value) in fq_item:
                            keep = False
                            break
                    if not keep:
                        break
                if keep:
                    cleaned_fq_list.append(fq_item)

            # --- Add OR clauses (plain syntax, no local params) ---
            for facet_name, values in active_facets.items():
                if len(values) == 1:
                    fq += ' %s:"%s"' % (facet_name, values[0])
                else:
                    or_clause = ' OR '.join('%s:"%s"' % (facet_name, v) for v in values)
                    fq += ' (%s)' % or_clause

            search_params['fq'] = fq.strip()
            search_params['fq_list'] = cleaned_fq_list

        except Exception as e:
            log.error('before_dataset_search error: %s', e)

        return search_params

    def edit(self, entity):
        """Reindex all datasets belonging to this org after org is updated."""
        try:
            if not getattr(entity, 'is_organization', False):
                return
        except Exception:
            return

        try:
            org_id = entity.id

            # Force the session to flush so new data is readable
            model.Session.flush()

            # Small delay isn't needed if flush works, but invalidate any action cache
            # by passing fresh context
            packages = toolkit.get_action('package_search')(
                {'ignore_auth': True, 'use_cache': False},
                {
                    'fq': 'owner_org:%s' % org_id,
                    'rows': 1000,
                    'include_private': True,
                }
            )

            from ckan.lib.search import rebuild
            count = 0
            for pkg in packages.get('results', []):
                try:
                    rebuild(pkg['id'])
                    count += 1
                except Exception as e:
                    log.error('Error reindexing dataset %s: %s', pkg['id'], e)

            log.info('Reindexed %d datasets for org %s', count, org_id)

        except Exception as e:
            log.error('Error reindexing datasets for org "{}": {}'.format(entity.title, e))

    def read(self, entity):
        """Populate g.search_facets for the group page so facet_list snippets work."""
        # Skip if not in a web request context (e.g. CLI reindex)
        try:
            from flask import has_request_context
            if not has_request_context():
                return
        except Exception:
            return

        try:
            group_name = entity.name
            if not group_name:
                return

            try:
                user = toolkit.g.user
            except Exception:
                user = None

            context = {'user': user} if user else {}

            # Build fq from any active URL filters
            managed_facets = [
                'organization', 'nature_based', 'grant_cycle',
                'pipeline_stage', 'doc_type', 'metric', 'monitoring_stages',
                'res_format', 'state_abbr_org'
            ]

            fq_parts = ['groups:"%s"' % group_name]

            try:
                for facet in managed_facets:
                    values = request.args.getlist(facet)
                    if values:
                        if len(values) == 1:
                            fq_parts.append('%s:"%s"' % (facet, values[0]))
                        else:
                            or_clause = ' OR '.join('%s:"%s"' % (facet, v) for v in values)
                            fq_parts.append('(%s)' % or_clause)
            except RuntimeError:
                pass

            _thread_state.skip_facet_or = True
            try:
                result = toolkit.get_action('package_search')(context, {
                    'q': '',
                    'fq': ' '.join(fq_parts),
                    'rows': 0,
                    'facet.field': managed_facets,
                    'facet.limit': -1,
                    'facet.mincount': 1,
                    'include_private': bool(user),
                })
            finally:
                _thread_state.skip_facet_or = False

            toolkit.g.search_facets = result.get('search_facets', {})

        except Exception as e:
            log.warning('Failed to populate g.search_facets for group page: %s', e)

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

        facets_dict['grant_cycle'] = plugins.toolkit._("Grant Cycles")
        facets_dict['nature_based'] = plugins.toolkit._("Nature-based Solutions")
        facets_dict['pipeline_stage'] = plugins.toolkit._("Pipeline Stages")
        facets_dict['doc_type'] = plugins.toolkit._("File/Document Type")
        facets_dict['res_format'] = facets_dict.pop('res_format')
        facets_dict['metric'] = plugins.toolkit._("Monitoring Metrics")
        facets_dict['monitoring_stages'] = plugins.toolkit._("Monitoring Stages")
        facets_dict['state_abbr_org'] = plugins.toolkit._("States and Territories")
        facets_dict.pop('license_id')
        facets_dict.pop('tags')

        # Return the updated facet dict.
        return facets_dict

    def group_facets(self, facets_dict, group_type, package_type):
        # This changes the facet order and removes some facets from the filter list.
        # Mirror dataset_facets - 'groups' excluded since page
        facets_dict['organization'] = "Grants"
        facets_dict['grant_cycle'] = plugins.toolkit._("Grant Cycles")
        facets_dict['nature_based'] = plugins.toolkit._("Nature-based Solutions")
        facets_dict['pipeline_stage'] = plugins.toolkit._("Pipeline Stages")
        facets_dict['doc_type'] = plugins.toolkit._("File/Document Type")
        facets_dict['res_format'] = facets_dict.pop('res_format')
        facets_dict['metric'] = plugins.toolkit._("Monitoring Metrics")
        facets_dict['monitoring_stages'] = plugins.toolkit._("Monitoring Stages")
        facets_dict['state_abbr_org'] = plugins.toolkit._("States and Territories")
        facets_dict.pop('license_id', None)
        facets_dict.pop('tags', None)
        facets_dict.pop('groups', None)   # redundant - already on the group page

        # Return the updated facet dict.

        return facets_dict

    def organization_facets(self, facets_dict, organization_type, package_type):
        # This changes the facet order and removes some facets from the filter list.
        facets_dict['vocab_metric_classes'] = plugins.toolkit._("Metric Classes")
        facets_dict['vocab_restoration_activities'] = plugins.toolkit._("Restoration Activities")
        facets_dict['vocab_counties'] = plugins.toolkit._("Counties")
        facets_dict['vocab_state_abbreviations'] = plugins.toolkit._("States and Territories")
        facets_dict['grant_cycle'] = plugins.toolkit._("Grant Cycles")
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
            'title': [toolkit.get_validator('not_empty')],
            'notes': [toolkit.get_validator('not_empty')],
            'principal_investigator': [toolkit.get_validator('not_empty'),
                            toolkit.get_converter('convert_to_extras')],

            'point_of_contact_email': [toolkit.get_validator('not_empty'),
                            toolkit.get_converter('convert_to_extras'),
                            toolkit.get_validator('email_validator')],

            'point_of_contact_phone': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_extras')],

            'alt_point_of_contact_name': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_extras')],              
            
            'alt_point_of_contact_email': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_extras')],

            'alt_point_of_contact_phone': [toolkit.get_validator('ignore_missing'),
                            toolkit.get_converter('convert_to_extras')],

            'private_rationale': [private_rationale_validator,
                                  toolkit.get_converter('convert_to_extras')],

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
                'name': [toolkit.get_validator('not_empty')],
                'metric': [toolkit.get_validator('ignore_missing'),
                        toolkit.get_converter('convert_to_list_if_string')],
                'doc_type': [toolkit.get_validator('not_empty')],
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
            'title': [toolkit.get_validator('ignore_missing')],
            'notes': [toolkit.get_validator('ignore_missing')],
            'principal_investigator': [toolkit.get_converter('convert_from_extras'),
                        toolkit.get_validator('ignore_missing')],

            'point_of_contact_email': [toolkit.get_converter('convert_from_extras'),
                        toolkit.get_validator('ignore_missing'),toolkit.get_validator('email_validator')],

            'point_of_contact_phone': [toolkit.get_converter('convert_from_extras'),
                        toolkit.get_validator('ignore_missing')],

            'alt_point_of_contact_name': [toolkit.get_converter('convert_from_extras'),
                        toolkit.get_validator('ignore_missing')],             
            
            'alt_point_of_contact_email': [toolkit.get_converter('convert_from_extras'),
                        toolkit.get_validator('ignore_missing')],

            'alt_point_of_contact_phone': [toolkit.get_converter('convert_from_extras'),
                        toolkit.get_validator('ignore_missing')],

            'private_rationale': [toolkit.get_converter('convert_from_extras'),
                                  toolkit.get_validator('ignore_missing')],

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
            'has_value' : has_value,
            'parse_postgres_array' : parse_postgres_array,
            'get_extra' : get_extra,
            'get_value_or_extra' : get_value_or_extra,
            'replace_keys' : replace_keys,
            'monitoring_parameters' : monitoring_parameters,
            'get_grant_required_metrics_by_nbs' : get_grant_required_metrics_by_nbs,
            'get_satisfied_metrics' : get_satisfied_metrics,
            'get_nbs_from_package_id': get_nbs_from_package_id,
            'doc_types': doc_types,
            'monitoring_stages': monitoring_stages,
            'remove_grant_prefix': remove_grant_prefix,
            'facet_url_add': facet_url_add,
            'facet_url_remove': facet_url_remove,
            }
    
    def get_actions(self):
        return {
            'group_show':         _chained_group_show,
            'group_list':         _chained_group_list,
            'organization_show':  _chained_organization_show,
            'organization_list':  _chained_organization_list,
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
            'title': [toolkit.get_validator('ignore_missing')],
            'description': [toolkit.get_validator('ignore_missing')],
            'grant_cycle': [toolkit.get_converter('convert_from_extras'),
                            toolkit.get_validator('ignore_missing')],
            'funding_source': [toolkit.get_converter('convert_from_extras'),
                               toolkit.get_validator('ignore_missing')],
            'owner_group': [toolkit.get_converter('convert_from_extras'),
                              toolkit.get_validator('ignore_missing')],
            'pipeline_stage': [toolkit.get_converter('convert_from_extras'),
                                toolkit.get_converter('convert_to_list_if_string'),
                                toolkit.get_validator('ignore_missing')],
            'nature_based': [toolkit.get_converter('convert_from_extras'),
                            toolkit.get_converter('convert_to_list_if_string'),
                            toolkit.get_validator('ignore_missing')],
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
            'title': [toolkit.get_validator('not_empty')],
            'description': [toolkit.get_validator('not_empty')],
            'grant_cycle': [toolkit.get_validator('not_empty'),
                            toolkit.get_converter('convert_to_extras')],
            'funding_source': [sysadmin_not_empty,
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
            'has_value' : has_value,
            'get_extra' : get_extra,
            'get_value_or_extra' : get_value_or_extra,
            'replace_keys' : replace_keys,
            'remove_grant_prefix' : remove_grant_prefix,
            }

    # IConfigurer
    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('fanstatic', 'nfwf_org_fields')