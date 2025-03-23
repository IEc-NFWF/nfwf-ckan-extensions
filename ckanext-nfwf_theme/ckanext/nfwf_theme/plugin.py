import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit


def most_popular_groups():
    '''Return a sorted list of the groups with the most datasets.'''

    # Get a list of all the site's groups from CKAN, sorted by number of
    # datasets.
    groups = toolkit.get_action('group_list')(
        data_dict={'sort': 'package_count desc', 'all_fields': True})

    # Truncate the list to the 3 most popular groups only.
    groups = groups[:9]
    return groups

def get_site_statistics():
    stats = {}
    stats['dataset_count'] = toolkit.get_action('package_search')(
        {}, {"rows": 1})['count']
    stats['group_count'] = len(toolkit.get_action('group_list')({}, {}))
    stats['organization_count'] = len(
        toolkit.get_action('organization_list')({}, {}))
    return stats


class Nfwf_ThemePlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.ITemplateHelpers)
    # IConfigurer

    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('assets', 'nfwf_theme')

    def get_helpers(self):
        '''Register the most_popular_groups() function above as a template
        helper function.

        '''
        # Template helper function names should begin with the name of the
        # extension they belong to, to avoid clashing with functions from
        # other extensions.
        return {
            'Nfwf_Theme_most_popular_groups': most_popular_groups,
            "Nfwf_Theme_get_site_statistics": get_site_statistics
            }