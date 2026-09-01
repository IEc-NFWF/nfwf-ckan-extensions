# -*- coding: utf-8 -*-
from setuptools import setup, find_packages  # Always prefer setuptools over distutils
from codecs import open  # To use a consistent encoding
from os import path

here = path.abspath(path.dirname(__file__))

with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='''ckanext-nfwf_permissions''',

    version='0.0.1',

    description='''NFWF user roles, permissions and account approval''',
    long_description=long_description,
    long_description_content_type='text/markdown',

    url='https://github.com/IEc-NFWF/nfwf-ckan-extensions',

    author='''Industrial Economics, Inc.''',
    author_email='''jstrzepek@indecon.com''',

    license='AGPL',

    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)',
        'Programming Language :: Python :: 3',
    ],

    keywords='''CKAN nfwf permissions roles''',

    packages=find_packages(exclude=['contrib', 'docs', 'tests*']),
    namespace_packages=['ckanext'],

    install_requires=[
      # CKAN extensions should not list dependencies here, but in a separate
      # ``requirements.txt`` file.
    ],

    include_package_data=True,
    package_data={
    },

    data_files=[],

    entry_points='''
        [ckan.plugins]
        nfwf_permissions=ckanext.nfwf_permissions.plugin:NfwfPermissionsPlugin

        [babel.extractors]
        ckan = ckan.lib.extract:extract_ckan
    ''',

    message_extractors={
        'ckanext': [
            ('**.py', 'python', None),
            ('**.js', 'javascript', None),
            ('**/templates/**.html', 'ckan', None),
        ],
    }
)
