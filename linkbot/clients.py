import requests
import re
import collections
from functools import partial
from urllib.parse import urlencode, quote
from . import saml, RequestLogger
from types import SimpleNamespace


class ServiceNowClient(RequestLogger, requests.Session):
    """ServiceNow REST client for looking up records."""
    api = '/api/now/table'
    table_map = {
        'ADVISORY': 'u_outage_communication',
        'CHG': 'change_request',
        'CTASK': 'change_task',
        'DMND': 'dmn_demand',
        'IDEA': 'idea',
        'INC': 'incident',
        'ITASK': 'u_incident_task',
        'PRB': 'problem',
        'PRJ': 'pm_project',
        'PTASK': 'problem_task',
        'REQ': 'u_simple_requests',
        'RTASK': 'u_request_task'
    }
    _digits_regex = re.compile('[0-9]')

    def __init__(self, host='', auth=()):
        """Initialize ServiceNowClient with a host and user/password tuple."""
        super(ServiceNowClient, self).__init__()
        self.headers.update({"Content-Type": "application/json",
                            "Accept": "application/json"})
        self.auth = auth
        self.host = host

    def get_number(self, number, full_payload=False):
        """Look up a service now record based on its number (eg REQ0000001).
        Return a ServiceNowRecord with, the attributes of which are controlled
        by ServiceNowRecord.fields, unless full_payload, in which case return
        all the attributes.
        """
        table = self._table_from_number(number)
        url = self.host + self.api
        fields = []
        if not full_payload:
            fields = ServiceNowRecord.fields
        query = {
            'sysparm_query': 'number={num}'.format(num=number),
            'sysparm_display_value': 'true',
            'sysparm_limit': '1',
            'sysparm_fields': ','.join(fields)
        }
        url += '/{table}?{query}'.format(table=table, query=urlencode(query))
        response = self.get(url)
        if response.status_code != 200:
            raise IOError('bad service now response ' + str(response))
        result = next(iter(response.json()['result']), None)
        if not result:
            raise KeyError(number + ' not found')
        return ServiceNowRecord(**result)

    def link(self, number):
        """Return a link to a record given its number."""
        table = self._table_from_number(number)
        # You're reading this right, it's triple-nested encoding
        sysparm_query = urlencode({'number': number})
        record_query = urlencode({'sysparm_table': table,
                                  'sysparm_query': sysparm_query})
        nav_query = urlencode({'uri': f'{table}.do?{record_query}'})
        return f'{self.host}/nav_to.do?{nav_query}'

    def _table_from_number(self, number):
        """Given a number, parse out the record type and return the matching
        table if there is one.
        """
        ticket_type = self._digits_regex.sub('', number)
        table = self.table_map.get(ticket_type)
        if not table:
            raise KeyError('unrecognized service now type ' + ticket_type)
        return table


class ServiceNowRecord:
    """A record returned from ServiceNowClient. The default fields are ones
    deemed interesting to summarize a record.
    """
    fields = {
        'short_description': 'Subject',
        'number': 'Number',
        'parent': 'Parent',
        'state': 'State',
        'priority': 'Priority',
        'assigned_to': 'Assigned To',
        'opened_by': 'Opened By',
        'sys_updated_on': 'Last Update'}

    def __init__(self, **kwargs):
        self.__dict__ = kwargs

    def __repr__(self):
        inner = ', '.join(map(partial(str.join, '='), self.items()))
        return 'ServiceNowRecord({inner})'.format(inner=inner)

    def items(self, pretty_names=False):
        """Yield the key/value tuples of the the record. If pretty_names,
        change the key to a user-facing value. If value is an object,
        check display_value for a more friendly value.
        """
        for field in self.fields:
            value = getattr(self, field)
            is_mapping = isinstance(value, collections.Mapping)
            if is_mapping and 'display_value' in value:
                value = value.get('display_value')
            if pretty_names:
                field = self.fields.get(field, field)
            yield field, value


class UwSamlJira:
    """A Jira client with a saml session to handle authn on an SSO redirect"""
    def __init__(self, host='', auth=(None, None)):
        """Initialize with the basic auth so we use our _session."""
        self._session = saml.UwSamlSession(credentials=auth)
        self.host = host

    def issue(self, issue_number):
        """
        Return a JIRA issue. Try to adhere to the same model as the
        jira package.
        """
        url = f'{self.host}/rest/api/latest/issue/{quote(issue_number)}'
        response = self._session.get(url)
        if response.status_code == 404:
            raise KeyError(f'{issue_number} not found')
        response.raise_for_status()
        data = response.json()
        fields = SimpleNamespace(**data['fields'])
        subobjects = ['status', 'reporter', 'assignee']
        for subobject in subobjects:
            objdict = getattr(fields, subobject, None)
            if objdict:
                setattr(fields, subobject, SimpleNamespace(**objdict))
        return SimpleNamespace(fields=fields)
