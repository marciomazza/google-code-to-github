import getpass
import itertools
import re
from datetime import datetime

import gdata.projecthosting.client
from gdata.projecthosting.client import Query
from lxml import html


class Bunch(object):
    "http://code.activestate.com/recipes/52308-the-simple-but-handy-collector-of-a-bunch-of-named"

    def __init__(self, **kwds):
        self.__dict__.update(kwds)

    def __repr__(self):
        return self.__dict__.__repr__()

class Attachment(object):

    def __init__(self, node):
        self.node = node
        self.url = next(a.attrib['href'] for a in node.cssselect('a')
                        if a.text == 'Download')
        parent = node.getparent()
        if 'issuedescription' in parent.attrib['class']:
            self.type, self.index = 'description', None
        elif 'issuecomment' in parent.attrib['class']:
            comment_id =int(re.search(r'\d+$',
                                      parent.attrib['id']).group())
            self.type, self.index = 'comment', comment_id
        else:
            raise AssertionError('Unrecognized attachment %s' % node)

    def __repr__(self):
        d = self.__dict__.copy()
        del d['node']
        return d.__repr__()

class Issue(Bunch):

    @property
    def scrap(self):
        if not hasattr(self, '_scrap') or not self._scrap:
            self._scrap = html.parse(self.url).getroot()
        return self._scrap

    @property
    def attachments(self):
        return map(Attachment, self.scrap.cssselect('.attachments'))

def step_queries(max_query_results):
    for start_index in itertools.count(start=1, step=max_query_results):
        yield Query(start_index = start_index,
                    max_results = max_query_results)

class GoogleCodeProject(object):

    max_query_results = 25

    def __init__(self, name, email=None, password=None):
        """
        Arguments:
        - `name`: Google Code project name
        """
        self.name = name
        self.client = gdata.projecthosting.client.ProjectHostingClient()
        if email:
            password = password or getpass.getpass("Type the google password for %s" % email)
            self.client.client_login(email, password, 'migration')

    def get_issues(self, query=None):
        queries = [query] if query else step_queries(self.max_query_results)
        for query in queries:
            feed = self.client.get_issues(self.name, query = query)
            if feed.entry:
                for issue in feed.entry:
                    url = issue.link[1].href
                    yield Issue(
                        id = int(issue.id.text.split('/')[-1]),
                        status = issue.status.text.lower() if issue.status else None,
                        title = issue.title.text,
                        url = url,
                        authors = [a.name.text for a in issue.author],
                        content = issue.content.text,
                        date = datetime.strptime(
                            issue.published.text, "%Y-%m-%dT%H:%M:%S.000Z"),
                        labels = [l.text for l in issue.label],
                        owner = issue.owner.username.text if issue.owner else None,
                        raw = issue,
                        )
            else:
                break

    def get_issue_by_id(self, issue_id):
        issues = list(self.get_issues(Query(issue_id=issue_id)))
        return issues[0] if issues else None
