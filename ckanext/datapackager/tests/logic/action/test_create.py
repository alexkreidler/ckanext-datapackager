import json
import unittest
import mock
import tempfile
from io import StringIO

import pytest
import responses

import ckan.tests.helpers as helpers
import ckanext.datapackager.tests.helpers as custom_helpers
import ckantoolkit as toolkit
import ckan.tests.factories as factories

import re

responses.add_passthru(toolkit.config['solr_url'])


@pytest.mark.ckan_config('ckan.plugins', 'datapackager')
@pytest.mark.usefixtures('clean_db', 'with_plugins', 'with_request_context')
class TestPackageCreateFromDataPackage(unittest.TestCase):
    def test_it_requires_a_url_if_theres_no_upload_param(self):
        with self.assertRaises(toolkit.ValidationError):
            helpers.call_action('package_create_from_datapackage')


    def test_it_raises_if_datapackage_is_invalid(self):
        url = 'http://www.example.com/datapackage.json'
        datapackage = {}
        responses.add(responses.GET, url, json=datapackage)

        with self.assertRaises(toolkit.ValidationError):
            helpers.call_action('package_create_from_datapackage', url=url)
        

    def test_it_raises_if_datapackage_is_unsafe(self):
        datapackage = {
            'name': 'unsafe',
            'resources': [
                {
                    'name': 'unsafe-resource',
                    'path': '/etc/shadow',
                }
            ]
        }

        upload = mock.MagicMock()
        upload.file = StringIO(json.dumps(datapackage))

        
        with self.assertRaises(toolkit.ValidationError):
            helpers.call_action('package_create_from_datapackage', upload=upload)

    def test_it_creates_the_dataset(self):
        url = 'http://www.example.com/datapackage.json'
        datapackage = {
            'name': 'foo',
            'resources': [
                {
                    'name': 'the-resource',
                    'path': 'http://www.example.com/data.csv',
                }
            ],
            'some_extra_data': {'foo': 'bar'},
        }
        responses.add(responses.GET, url, json=datapackage)
        # FIXME: Remove this when
        # https://github.com/okfn/datapackage-py/issues/20 is done
        responses.add(responses.GET,
                                   datapackage['resources'][0]['path'])

        dataset = helpers.call_action('package_create_from_datapackage',
                                      url=url)
        assert dataset['state'] == 'active'

        extras = dataset['extras']

        extra_profile = None
        extra_data = None
        for extra in extras:
            if extra['key'] == 'profile':
                extra_profile = extra
            if extra['key'] == 'some_extra_data':
                extra_data = extra

        assert extra_profile is not None

        assert extra_data is not None

        assert extra_profile['value'] == 'data-package'
        assert json.loads(extra_data['value']) == datapackage['some_extra_data']

        resource = dataset.get('resources')[0]
        assert resource['name'] == datapackage['resources'][0]['name']
        assert resource['url'] == datapackage['resources'][0]['path']

    @responses.activate
    def test_it_creates_a_dataset_without_resources(self):
        url = 'http://www.example.com/datapackage.json'
        datapackage = {
            'name': 'foo',
            'resources': [
                {
                    'name': 'the-resource',
                    'data': 'inline data',
                }
            ]
        }
        responses.add(responses.GET, url, json=datapackage)

        helpers.call_action('package_create_from_datapackage', url=url)

        helpers.call_action('package_show', id=datapackage['name'])

    def test_it_deletes_dataset_on_error_when_creating_resources(self):
        datapkg_path = custom_helpers.fixture_path(
            'datetimes-datapackage-with-inexistent-resource.zip'
        )

        original_datasets = helpers.call_action('package_list')

        with open(datapkg_path, 'rb') as datapkg:
            
            with self.assertRaises(toolkit.ValidationError):
                helpers.call_action('package_create_from_datapackage',
                    upload=_UploadFile(datapkg))

        new_datasets = helpers.call_action('package_list')
        assert original_datasets == new_datasets

    def test_it_uploads_local_files(self):
        url = 'http://www.example.com/datapackage.zip'
        datapkg_path = custom_helpers.fixture_path('datetimes-datapackage.zip')
        with open(datapkg_path, 'rb') as f:
            responses.add(responses.GET, url, content=f.read())

        # FIXME: Remove this when
        # https://github.com/okfn/datapackage-py/issues/20 is done
        timezones_url = 'https://www.example.com/timezones.csv'
        responses.add(responses.GET, timezones_url, text='')

        helpers.call_action('package_create_from_datapackage', url=url)

        dataset = helpers.call_action('package_show', id='datetimes')
        resources = dataset.get('resources')

        assert resources[0]['url_type'] == 'upload'
        assert re.match('datetimes.csv$', resources[0]['url'])

    def test_it_uploads_resources_with_inline_strings_as_data(self):
        url = 'http://www.example.com/datapackage.json'
        datapackage = {
            'name': 'foo',
            'resources': [
                {
                    'name': 'the-resource',
                    'data': 'inline data',
                }
            ]
        }
        responses.add(responses.GET, url, json=datapackage)

        helpers.call_action('package_create_from_datapackage', url=url)

        dataset = helpers.call_action('package_show', id='foo')
        resources = dataset.get('resources')

        assert resources[0]['url_type'] == 'upload'
        assert resources[0]['name'] in resources[0]['url']

    def test_it_uploads_resources_with_inline_dicts_as_data(self):
        url = 'http://www.example.com/datapackage.json'
        datapackage = {
            'name': 'foo',
            'resources': [
                {
                    'name': 'the-resource',
                    'data': {'foo': 'bar'},
                }
            ]
        }
        responses.add(responses.GET, url, json=datapackage)

        helpers.call_action('package_create_from_datapackage', url=url)

        dataset = helpers.call_action('package_show', id='foo')
        resources = dataset.get('resources')

        assert resources[0]['url_type'] == 'upload'
        assert resources[0]['name'] in resources[0]['url']

    def test_it_allows_specifying_the_dataset_name(self):
        url = 'http://www.example.com/datapackage.json'
        datapackage = {
            'name': 'foo',
            'resources': [
                {'name': 'bar',
                 'path': 'http://example.com/some.csv'}
            ]
        }
        responses.add(responses.GET, url, json=datapackage)

        dataset = helpers.call_action('package_create_from_datapackage',
                                      url=url,
                                      name='bar')
        assert dataset['name'] == 'bar'

    def test_it_creates_unique_name_if_name_wasnt_specified(self):
        url = 'http://www.example.com/datapackage.json'
        datapackage = {
            'name': 'foo',
            'resources': [
                {'name': 'bar',
                 'path': 'http://example.com/some.csv'}
            ]
        }
        responses.add(responses.GET, url, json=datapackage)

        helpers.call_action('package_create', name=datapackage['name'])
        dataset = helpers.call_action('package_create_from_datapackage',
                                      url=url)
        assert dataset['name'].startswith('foo')

    def test_it_fails_if_specifying_name_that_already_exists(self):
        url = 'http://www.example.com/datapackage.json'
        datapackage = {
            'name': 'foo',
            'resources': [
                {'name': 'bar',
                 'path': 'http://example.com/some.csv'}
            ]
        }
        responses.add(responses.GET, url, json=datapackage)

        helpers.call_action('package_create', name=datapackage['name'])
        
        with self.assertRaises(toolkit.ValidationError):
            helpers.call_action('package_create_from_datapackage', url=url, name=datapackage['name'])

    def test_it_allows_changing_dataset_visibility(self):
        url = 'http://www.example.com/datapackage.json'
        datapackage = {
            'name': 'foo',
            'resources': [
                {'name': 'bar',
                 'path': 'http://example.com/some.csv'}
            ]
        }
        responses.add(responses.GET, url, json=datapackage)

        user = factories.Sysadmin()
        organization = factories.Organization()
        dataset = helpers.call_action('package_create_from_datapackage',
                                      context={'user': user['id']},
                                      url=url,
                                      owner_org=organization['id'],
                                      private='true')
        assert dataset['private']

    def test_it_allows_uploading_a_datapackage(self):
        datapackage = {
            'name': 'foo',
            'resources': [
                {'name': 'bar',
                 'path': 'http://example.com/some.csv'}
            ]

        }
        with tempfile.NamedTemporaryFile() as tmpfile:
            tmpfile.write(json.dumps(datapackage))
            tmpfile.flush()

            dataset = helpers.call_action('package_create_from_datapackage',
                                          upload=_UploadFile(tmpfile))
            assert dataset['name'] == 'foo'


class _UploadFile(object):
    '''Mock the parts from cgi.FileStorage we use.'''

    def __init__(self, fp):
        self.file = fp
