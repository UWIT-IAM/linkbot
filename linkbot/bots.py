import re
import random
from . import clients
from datetime import datetime


class LinkBot(object):
    """Implements Slack message matching and link response

    """
    QUIPS = [
        '%s',
        'linkbot noticed a link!  %s',
        'Oh, here it is... %s',
        'Maybe this, %s, will help?',
        'Click me!  %s',
        'Click my shiny metal link!  %s',
        'Here, let me link that for you... %s',
        'Couldn\'t help but notice %s was mentioned...',
        'Not that I was eavesdropping, but did you mention %s?',
        'hmmmm, did you mean %s?',
        '%s...  Mama said there\'d be days like this...',
        '%s?  An epic, yet approachable tale...',
        '%s?  Reminds me of a story...',
    ]
    default_match = r'_THIS_COULD_BE_OVERRIDDEN_'

    def __init__(self, conf):
        self._conf = conf
        match = conf.get('MATCH', self.default_match)
        self._regex = re.compile(r'(\A|\s)+(%s)' % match, flags=re.I)
        if 'QUIPS' in conf:
            self.QUIPS = conf.get('QUIPS')
        self._link = conf.get('LINK', '%s|%s')
        self._seen = []

    def match(self, text):
        """Return a set of unique matches for text."""
        return set(match[1] for match in self._regex.findall(text))

    def message(self, link_label):
        return self._message_text(self._link % (link_label, link_label))

    def reset(self):
        self._seen = []

    def _quip(self, link):
        if not self.QUIPS:
            return link
        quip = random.choice(self.QUIPS)
        return quip % link

    def _message_text(self, link):
        return self._quip(link)

    def _escape_html(self, text):
        escaped = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
        }

        return "".join(escaped.get(c, c) for c in text)


class JiraLinkBot(LinkBot):
    """Subclass LinkBot to customize response for JIRA links

    """
    default_match = r'[A-Z]{2,}\-[0-9]+'

    def __init__(self, conf):
        if 'LINK' not in conf:
            conf['LINK'] = '<{}/browse/%s|%s>'.format(conf['HOST'])
        super(JiraLinkBot, self).__init__(conf)
        self.jira = clients.UwSamlJira(host=conf.get('HOST'),
                                       auth=conf.get('AUTH'))

    @staticmethod
    def pretty_update_time(issue):
        updated = issue.fields.updated
        try:
            update_dt = datetime.strptime(updated, '%Y-%m-%dT%H:%M:%S.%f%z')
            updated = update_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
        return updated

    def message(self, link_label):
        msg = super(JiraLinkBot, self).message(link_label)
        issue = self.jira.issue(link_label)
        summary = issue.fields.summary
        def get_name(person): return person and person.displayName or 'None'
        reporter = '*Reporter* ' + get_name(issue.fields.reporter)
        assignee = '*Assignee* ' + get_name(issue.fields.assignee)
        status = '*Status* ' + issue.fields.status.name
        updated = '*Last Update* ' + self.pretty_update_time(issue)
        lines = list(map(self._escape_html,
                         [summary, reporter, assignee, status, updated]))
        return '\n> '.join([msg] + lines)


class ServiceNowBot(LinkBot):
    _ticket_regex = '|'.join(clients.ServiceNowClient.table_map)
    default_match = '(%s)[0-9]{7,}' % _ticket_regex

    def __init__(self, conf):
        super(ServiceNowBot, self).__init__(conf)
        self.client = clients.ServiceNowClient(
            host=conf.get('HOST'), auth=conf.get('AUTH'))

    def message(self, link_label):
        record = self.client.get_number(link_label)
        link = self._strlink(link_label)
        lines = [self._quip(link)]
        for key, value in record.items(pretty_names=True):
            if key == 'Subject':
                lines.append(value or 'No subject')
            elif key == 'Parent' and value:
                link = self._strlink(value)
                lines.append('*{key}* {link}'.format(key=key, link=link))
            elif value and key != 'Number':
                lines.append('*{key}* {value}'.format(key=key, value=value))
        return '\n> '.join(lines)

    def _strlink(self, link_label):
        link = self.client.link(link_label)
        return '<{link}|{label}>'.format(link=link, label=link_label)
